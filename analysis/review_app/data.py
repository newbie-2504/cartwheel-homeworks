"""Trace loading and conversation building for the HW4 review app.

Sources, in order of preference:

1. Live Langfuse (public REST API), filtered to traces whose metadata
   attribute ``cartwheel.scenario_id`` starts with ``support-``. The raw
   traces are cached in ``analysis/review_app/cache/langfuse_traces.json``.
2. The cache written by an earlier Langfuse load.
3. The HW3 export ``traces/support_traces.json`` (offline source, shown with
   a banner in the UI).

Traces are grouped into conversations by session id. When a scenario has
more than one session (a partial run that was retried), the latest session
is the conversation and the earlier sessions are listed as ``retried``. The
course helper ``_merge_multi_turn`` merges by scenario id instead, which
would combine the partial and the retried session, so it is not used here.

The evidence panel is built from facts only: policies the agent fetched,
policy ids that appear in the agent's replies, and database rows for the
order, refund and ticket ids that appear in tool arguments or results. No
function in this module judges a trace.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from analysis.helpers.normalization import normalize_trace

REPO_ROOT = Path(__file__).resolve().parents[2]
EXPORT_PATH = REPO_ROOT / "traces" / "support_traces.json"
SCENARIOS_PATH = REPO_ROOT / "scenarios" / "support_scenarios.jsonl"
RESULTS_PATH = REPO_ROOT / "scenarios" / "final-results.jsonl"
DB_PATH = REPO_ROOT / "data" / "cartwheel.db"
POLICY_DIR = REPO_ROOT / "data" / "policies"
SPEC_PATH = REPO_ROOT / "SPEC.md"
SCENARIO_PREFIX = "support-"
CACHE_NAME = "langfuse_traces.json"
LEDGER_LABEL = "database state after the final run (23 Oct 2026)"

# Policy identifiers as they appear in this world: cw-* platform policies and
# store-*-policy store policies. Plain extraction, no validity check.
POLICY_ID_RE = re.compile(r"\b(cw-[a-z0-9]+(?:-[a-z0-9]+)*|store-[a-z0-9]+(?:-[a-z0-9]+)*-policy)\b")
LEDGER_KEYS = {"order_id": "order", "refund_id": "refund", "ticket_id": "ticket"}
LONG_RESULT_CHARS = 700
LONG_RESULT_LINES = 18


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_ts(value: Any) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] in ("{", "["):
            try:
                return json.loads(stripped)
            except ValueError:
                return value
    return value


def _pretty(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, indent=2, ensure_ascii=False)


def _parts_text(messages: Any) -> str:
    """Join the text parts of an OTel GenAI message list."""
    messages = _maybe_json(messages)
    if isinstance(messages, str):
        return messages
    out: list[str] = []
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        for part in message.get("parts") or []:
            if isinstance(part, dict) and part.get("type") == "text" and part.get("content"):
                out.append(str(part["content"]))
    return "\n".join(out)


def _attributes(raw: dict[str, Any]) -> dict[str, Any]:
    metadata = _maybe_json(raw.get("metadata"))
    if not isinstance(metadata, dict):
        return {}
    attrs = _maybe_json(metadata.get("attributes"))
    merged = dict(attrs) if isinstance(attrs, dict) else {}
    for key, value in metadata.items():
        if key != "attributes" and not isinstance(value, (dict, list)):
            merged.setdefault(key, value)
    return merged


def _scenario_id(raw: dict[str, Any]) -> str | None:
    sid = _attributes(raw).get("cartwheel.scenario_id") or raw.get("cartwheel_scenario_id")
    return str(sid) if sid else None


def _session_id(raw: dict[str, Any]) -> str:
    return str(_attributes(raw).get("cartwheel.session_id") or raw.get("sessionId") or "")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def spec_ids() -> list[str]:
    """Requirement identifiers in SPEC.md (read only), in document order."""
    if not SPEC_PATH.exists():
        return []
    found = re.findall(r"\b([A-Z]{2,}-\d+)\b", SPEC_PATH.read_text(encoding="utf-8"))
    return list(dict.fromkeys(found))


# ---------------------------------------------------------------------------
# Langfuse (read only)
# ---------------------------------------------------------------------------


class LangfuseReader:
    """Read-only client for the Langfuse public API. Keys never leave os.environ."""

    def __init__(self) -> None:
        self.host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000").rstrip("/")
        key = os.environ.get("LANGFUSE_PUBLIC_KEY")
        secret = os.environ.get("LANGFUSE_SECRET_KEY")
        self._auth = base64.b64encode(f"{key}:{secret}".encode()).decode() if key and secret else None

    @property
    def configured(self) -> bool:
        return self._auth is not None

    def _get(self, path: str) -> Any:
        req = urllib.request.Request(self.host + path, headers={"Authorization": "Basic " + str(self._auth)})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)

    def fetch_support_traces(self) -> list[dict[str, Any]]:
        """Every trace whose cartwheel.scenario_id starts with support-, with observations."""
        if not self.configured:
            raise RuntimeError("LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not set in .env")
        wanted: dict[str, dict[str, Any]] = {}
        page = 1
        while True:
            data = self._get(f"/api/public/traces?limit=100&page={page}")
            for summary in data.get("data") or []:
                sid = _scenario_id(summary)
                if sid and sid.startswith(SCENARIO_PREFIX):
                    wanted[summary["id"]] = summary
            total_pages = int((data.get("meta") or {}).get("totalPages") or 1)
            if page >= total_pages:
                break
            page += 1

        def full(trace_id: str) -> dict[str, Any]:
            return self._get("/api/public/traces/" + urllib.parse.quote(trace_id))

        with ThreadPoolExecutor(max_workers=8) as pool:
            traces = list(pool.map(full, sorted(wanted)))
        for trace in traces:
            trace.setdefault("cartwheel_scenario_id", _scenario_id(trace))
        return traces


# ---------------------------------------------------------------------------
# conversation building
# ---------------------------------------------------------------------------


def _result_summary(name: str, result: Any) -> str:
    if not isinstance(result, dict):
        text = _pretty(result).replace("\n", " ")
        return text[:120] + ("…" if len(text) > 120 else "")
    if result.get("ok") is False:
        return f"ok: false · {result.get('error', 'error')} · {result.get('reason', '')}".strip(" ·")
    bits = ["ok: true"] if result.get("ok") is True else []
    for key, value in result.items():
        if key == "ok":
            continue
        if isinstance(value, list):
            bits.append(f"{len(value)} {key}")
        elif isinstance(value, dict):
            inner = ", ".join(f"{k}: {v}" for k, v in list(value.items())[:4] if not isinstance(v, (dict, list)))
            bits.append(f"{key} {{{inner}…}}")
        elif len(bits) < 6:
            bits.append(f"{key}: {value}")
    return " · ".join(bits)


def _build_turn(raw: dict[str, Any], index: int) -> dict[str, Any]:
    user_text = _parts_text(raw.get("input"))
    reply = _parts_text(raw.get("output"))
    observations = sorted(
        [o for o in raw.get("observations") or [] if isinstance(o, dict)],
        key=lambda o: (str(o.get("startTime") or ""), str(o.get("id") or "")),
    )
    steps: list[dict[str, Any]] = []
    models: list[str] = []
    system_prompt = None
    for obs in observations:
        kind = obs.get("type")
        if kind == "GENERATION":
            if obs.get("model"):
                models.append(str(obs["model"]))
            gen_input = _maybe_json(obs.get("input"))
            if system_prompt is None and isinstance(gen_input, dict):
                for message in gen_input.get("messages") or []:
                    if isinstance(message, dict) and message.get("role") == "system":
                        system_prompt = _parts_text([message])
                        break
            outputs = _maybe_json(obs.get("output")) or []
            if not isinstance(outputs, list):
                continue
            has_tool_call = any(
                isinstance(p, dict) and p.get("type") == "tool_call"
                for m in outputs if isinstance(m, dict) for p in m.get("parts") or []
            )
            for message in outputs:
                if not isinstance(message, dict):
                    continue
                for part in message.get("parts") or []:
                    if not (isinstance(part, dict) and part.get("type") == "text"):
                        continue
                    text = str(part.get("content") or "")
                    if not text.strip():
                        continue
                    if not has_tool_call and text.strip() == reply.strip():
                        continue  # this is the reply, rendered after the steps
                    steps.append({
                        "kind": "model_text",
                        "text": text,
                        "with_tool_call": has_tool_call,
                        "observation_id": obs.get("id"),
                        "start_time": obs.get("startTime"),
                    })
        elif kind == "TOOL":
            args = _maybe_json(obs.get("input"))
            result = _maybe_json(obs.get("output"))
            result_text = _pretty(result)
            steps.append({
                "kind": "tool",
                "name": obs.get("name") or "tool",
                "arguments": args,
                "result": result,
                "args_text": _pretty(args),
                "result_text": result_text,
                "ok": result.get("ok") if isinstance(result, dict) else None,
                "error": result.get("error") if isinstance(result, dict) else None,
                "summary": _result_summary(str(obs.get("name")), result),
                "long": len(result_text) > LONG_RESULT_CHARS or result_text.count("\n") > LONG_RESULT_LINES,
                "observation_id": obs.get("id"),
                "start_time": obs.get("startTime"),
            })
    for i, step in enumerate(steps):
        step["index"] = i
    return {
        "index": index,
        "number": index + 1,
        "trace_id": str(raw["id"]),
        "timestamp": raw.get("timestamp"),
        "user": user_text,
        "steps": steps,
        "reply": reply,
        "models": list(dict.fromkeys(models)),
        "latency_s": raw.get("latency"),
        "html_path": raw.get("htmlPath"),
        "_system_prompt": system_prompt,
    }


def build_conversations(
    raw_traces: list[dict[str, Any]],
    scenarios: dict[str, dict[str, Any]],
    results: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    sessions: dict[str, dict[str, dict[str, dict[str, Any]]]] = defaultdict(lambda: defaultdict(dict))
    for raw in raw_traces:
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        sid = _scenario_id(raw)
        if not sid or not sid.startswith(SCENARIO_PREFIX):
            continue
        sessions[sid][_session_id(raw)][str(raw["id"])] = raw  # de-duplicates by trace id

    conversations: dict[str, dict[str, Any]] = {}
    for sid, by_session in sessions.items():
        ordered = sorted(
            by_session.items(),
            key=lambda kv: max(_parse_ts(t.get("timestamp")) for t in kv[1].values()),
        )
        session_id, traces_by_id = ordered[-1]
        traces = sorted(traces_by_id.values(), key=lambda t: _parse_ts(t.get("timestamp")))
        turns = [_build_turn(raw, i) for i, raw in enumerate(traces)]
        system_prompt = next((t.pop("_system_prompt") for t in turns if t.get("_system_prompt")), None)
        for t in turns:
            t.pop("_system_prompt", None)
        normalized = normalize_trace(traces[0])
        attrs = _attributes(traces[0])
        retried = []
        for earlier_session, earlier in ordered[:-1]:
            earlier_sorted = sorted(earlier.values(), key=lambda t: _parse_ts(t.get("timestamp")))
            retried.append({
                "session_id": earlier_session,
                "trace_ids": [str(t["id"]) for t in earlier_sorted],
                "turn_count": len(earlier_sorted),
                "started_at": earlier_sorted[0].get("timestamp"),
            })
        scenario = scenarios.get(sid)
        result = results.get(sid)
        warnings = []
        if result:
            result_turns = result.get("turns") or []
            if len(result_turns) != len(turns):
                warnings.append(f"final-results.jsonl records {len(result_turns)} turns; the session has {len(turns)} traces.")
            for i, (rt, turn) in enumerate(zip(result_turns, turns)):
                if (rt.get("agent") or "").strip() != turn["reply"].strip():
                    warnings.append(f"Turn {i + 1}: the reply in final-results.jsonl differs from the trace output.")
        else:
            warnings.append("No row in scenarios/final-results.jsonl for this scenario.")
        if not scenario:
            warnings.append("No row in scenarios/support_scenarios.jsonl for this scenario.")
        conversations[sid] = {
            "id": sid,
            "scenario_id": sid,
            "session_id": session_id,
            "trace_ids": [t["trace_id"] for t in turns],
            "primary_trace_id": turns[0]["trace_id"],
            "retried": retried,
            "started_at": turns[0]["timestamp"],
            "user_role": attrs.get("cartwheel.user_role") or normalized["meta"].get("role"),
            "user_id": attrs.get("cartwheel.user_id"),
            "prompt_version": attrs.get("cartwheel.prompt_version"),
            "models": list(dict.fromkeys(m for t in turns for m in t["models"])),
            "system_prompt": system_prompt,
            "turns": turns,
            "scenario": scenario,
            "result": {
                k: result.get(k) for k in ("status", "model", "error", "duration_s")
            } | {"turn_count": len(result.get("turns") or [])} if result else None,
            "warnings": warnings,
        }
    return dict(sorted(conversations.items()))


def annotatable_blocks(conv: dict[str, Any]) -> list[tuple[str, int, str]]:
    """(target key, turn index, text) for every block a note can attach to."""
    blocks: list[tuple[str, int, str]] = []
    for turn in conv["turns"]:
        t = turn["index"]
        blocks.append((f"t{t}.user", t, turn["user"]))
        for step in turn["steps"]:
            s = step["index"]
            if step["kind"] == "tool":
                blocks.append((f"t{t}.s{s}.args", t, step["args_text"]))
                blocks.append((f"t{t}.s{s}.result", t, step["result_text"]))
            else:
                blocks.append((f"t{t}.s{s}.text", t, step["text"]))
        blocks.append((f"t{t}.reply", t, turn["reply"]))
    return blocks


def locate_quote(conv: dict[str, Any], quote: str, turn_index: int | None = None) -> dict[str, Any] | None:
    """Find a quote in the conversation; prefer replies, then the given turn."""
    if not quote:
        return None
    blocks = annotatable_blocks(conv)
    if turn_index is not None:
        blocks = [b for b in blocks if b[1] == turn_index] + [b for b in blocks if b[1] != turn_index]
    blocks.sort(key=lambda b: 0 if b[0].endswith(".reply") else 1)
    for target, t, text in blocks:
        pos = text.find(quote)
        if pos >= 0:
            return {"target": target, "turn_index": t, "start": pos, "end": pos + len(quote)}
    return None


# ---------------------------------------------------------------------------
# evidence (facts only)
# ---------------------------------------------------------------------------


def _collect_ids(value: Any, found: list[tuple[str, int]]) -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            if key in LEDGER_KEYS and not isinstance(inner, bool):
                try:
                    found.append((LEDGER_KEYS[key], int(str(inner).strip().lstrip("#"))))
                except (TypeError, ValueError):
                    pass
            _collect_ids(inner, found)
    elif isinstance(value, list):
        for inner in value:
            _collect_ids(inner, found)


def _policy_file_text(policy_id: str) -> str | None:
    if not re.fullmatch(r"[a-z0-9-]+", policy_id or ""):
        return None
    path = POLICY_DIR / f"{policy_id}.md"
    return path.read_text(encoding="utf-8") if path.exists() else None


def _rows(con: sqlite3.Connection, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    cur = con.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def build_evidence(conv: dict[str, Any], db_path: Path = DB_PATH) -> dict[str, Any]:
    policies: list[dict[str, Any]] = []
    provenance: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for turn in conv["turns"]:
        for step in turn["steps"]:
            if step["kind"] != "tool":
                continue
            name, args, result = step["name"], step["arguments"], step["result"]
            for where, payload in (("arguments", args), ("result", result)):
                ids: list[tuple[str, int]] = []
                _collect_ids(payload, ids)
                for key in dict.fromkeys(ids):
                    provenance[key].append({"turn": turn["number"], "tool": name, "where": where})
            if name == "get_policy":
                res = result if isinstance(result, dict) else {}
                pid = res.get("policy_id") or (args.get("policy_id") if isinstance(args, dict) else None)
                policies.append({
                    "turn": turn["number"], "tool": name, "policy_id": pid,
                    "title": res.get("title"), "ok": res.get("ok"),
                    "error": res.get("error"), "reason": res.get("reason"),
                    "text": res.get("body"), "file_text": _policy_file_text(str(pid or "")),
                })
            elif name == "search_help_center":
                res = result if isinstance(result, dict) else {}
                query = (args or {}).get("query") if isinstance(args, dict) else None
                if res.get("ok") is False or not res.get("results"):
                    policies.append({
                        "turn": turn["number"], "tool": name, "query": query, "policy_id": None,
                        "ok": res.get("ok"), "error": res.get("error"), "reason": res.get("reason"),
                        "text": None, "note": "no results returned",
                    })
                for hit in res.get("results") or []:
                    policies.append({
                        "turn": turn["number"], "tool": name, "query": query,
                        "policy_id": hit.get("policy_id"), "title": hit.get("title"),
                        "score": hit.get("score"), "ok": res.get("ok"),
                        "text": hit.get("snippet"), "file_text": _policy_file_text(str(hit.get("policy_id") or "")),
                    })

    reply_ids = []
    for turn in conv["turns"]:
        counts: dict[str, int] = {}
        for match in POLICY_ID_RE.findall(turn["reply"] or ""):
            counts[match] = counts.get(match, 0) + 1
        for pid, n in counts.items():
            reply_ids.append({"turn": turn["number"], "policy_id": pid, "occurrences": n})

    def ids_of(kind: str) -> list[int]:
        return sorted(i for (k, i) in provenance if k == kind)

    def seen(kind: str, value: int) -> list[dict[str, Any]]:
        return provenance.get((kind, value), [])

    order_ids, refund_ids, ticket_ids = ids_of("order"), ids_of("refund"), ids_of("ticket")
    ledger: dict[str, Any] = {"label": LEDGER_LABEL, "orders": [], "refunds": [], "escalations": [], "error": None}
    if order_ids or refund_ids or ticket_ids:
        try:
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                if order_ids:
                    marks = ",".join("?" * len(order_ids))
                    for row in _rows(con, f"SELECT o.*, s.name AS store_name FROM orders o LEFT JOIN stores s ON s.id = o.store_id WHERE o.id IN ({marks}) ORDER BY o.id", order_ids):
                        row["seen_in"] = seen("order", row["id"])
                        ledger["orders"].append(row)
                    missing = sorted(set(order_ids) - {r["id"] for r in ledger["orders"]})
                    ledger["orders_not_in_db"] = missing
                clauses, params = [], []
                if refund_ids:
                    clauses.append(f"id IN ({','.join('?' * len(refund_ids))})")
                    params += refund_ids
                if order_ids:
                    clauses.append(f"order_id IN ({','.join('?' * len(order_ids))})")
                    params += order_ids
                for row in _rows(con, f"SELECT * FROM refunds WHERE {' OR '.join(clauses)} ORDER BY id", params):
                    row["seen_in"] = seen("refund", row["id"]) + [dict(s, via=f"order {row['order_id']}") for s in seen("order", row["order_id"])]
                    ledger["refunds"].append(row)
                clauses, params = [], []
                if ticket_ids:
                    clauses.append(f"id IN ({','.join('?' * len(ticket_ids))})")
                    params += ticket_ids
                if order_ids:
                    clauses.append(f"order_id IN ({','.join('?' * len(order_ids))})")
                    params += order_ids
                for row in _rows(con, f"SELECT * FROM escalations WHERE {' OR '.join(clauses)} ORDER BY id", params):
                    via_order = seen("order", row["order_id"]) if row.get("order_id") is not None else []
                    row["seen_in"] = seen("ticket", row["id"]) + [dict(s, via=f"order {row['order_id']}") for s in via_order]
                    ledger["escalations"].append(row)
            finally:
                con.close()
        except sqlite3.Error as exc:
            ledger["error"] = f"could not read {db_path.name}: {exc}"
    ledger["ids"] = {"order_id": order_ids, "refund_id": refund_ids, "ticket_id": ticket_ids}
    return {"policies_fetched": policies, "policy_ids_in_replies": reply_ids, "ledger": ledger}


# ---------------------------------------------------------------------------
# the data store the server holds in memory
# ---------------------------------------------------------------------------


class ConversationData:
    """Conversations plus where they came from. Swapped atomically on reload."""

    def __init__(self, cache_dir: Path, export_path: Path = EXPORT_PATH) -> None:
        self.cache_dir = cache_dir
        self.export_path = export_path
        self.lock = threading.Lock()
        self.conversations: dict[str, dict[str, Any]] = {}
        self.source: dict[str, Any] = {}
        self._evidence: dict[str, dict[str, Any]] = {}
        self.scenarios = {s["id"]: s for s in load_jsonl(SCENARIOS_PATH)}
        self.results = {r["scenario_id"]: r for r in load_jsonl(RESULTS_PATH)}

    @property
    def cache_path(self) -> Path:
        return self.cache_dir / CACHE_NAME

    def _install(self, traces: list[dict[str, Any]], source: dict[str, Any]) -> None:
        conversations = build_conversations(traces, self.scenarios, self.results)
        source = dict(source)
        source["trace_count"] = sum(1 for t in traces if (_scenario_id(t) or "").startswith(SCENARIO_PREFIX))
        source["conversation_count"] = len(conversations)
        source["traces_in_conversations"] = sum(len(c["trace_ids"]) for c in conversations.values())
        source["retried_scenarios"] = sorted(cid for cid, c in conversations.items() if c["retried"])
        source["missing_scenarios"] = sorted(set(self.scenarios) - set(conversations))
        with self.lock:
            self.conversations = conversations
            self.source = source
            self._evidence = {}

    def load_from_langfuse(self) -> None:
        reader = LangfuseReader()
        traces = reader.fetch_support_traces()
        if not traces:
            raise RuntimeError("Langfuse returned no traces with a support- scenario id")
        fetched_at = _utcnow()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"fetched_at": fetched_at, "trace_count": len(traces), "traces": traces}), encoding="utf-8")
        tmp.replace(self.cache_path)
        self._install(traces, {"kind": "langfuse", "offline": False, "fetched_at": fetched_at,
                               "detail": f"live Langfuse, cached to {self._rel(self.cache_path)}",
                               "langfuse_host": reader.host})

    def load_from_cache(self) -> bool:
        if not self.cache_path.exists():
            return False
        payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self._install(payload.get("traces") or [], {
            "kind": "langfuse_cache", "offline": False, "fetched_at": payload.get("fetched_at"),
            "detail": f"Langfuse cache {self._rel(self.cache_path)} fetched {payload.get('fetched_at')}",
            "langfuse_host": LangfuseReader().host,
        })
        return True

    def load_from_export(self, reason: str | None = None) -> None:
        payload = json.loads(self.export_path.read_text(encoding="utf-8"))
        traces = payload["traces"] if isinstance(payload, dict) else payload
        self._install(traces, {
            "kind": "export", "offline": True,
            "fetched_at": payload.get("exported_at") if isinstance(payload, dict) else None,
            "detail": f"offline source: {self._rel(self.export_path)} (HW3 export)",
            "offline_reason": reason,
            "langfuse_host": LangfuseReader().host,
        })

    def load(self, preference: str = "auto") -> None:
        """auto = cache, then live Langfuse, then the export."""
        if preference == "export":
            self.load_from_export("started with --source export")
            return
        if preference in ("auto", "cache") and self.load_from_cache():
            return
        try:
            self.load_from_langfuse()
        except (urllib.error.URLError, OSError, RuntimeError, ValueError, KeyError) as exc:
            if preference == "langfuse":
                raise
            self.load_from_export(f"Langfuse not reachable: {type(exc).__name__}: {str(exc)[:160]}")

    def evidence(self, conversation_id: str) -> dict[str, Any] | None:
        with self.lock:
            conv = self.conversations.get(conversation_id)
            cached = self._evidence.get(conversation_id)
        if conv is None:
            return None
        if cached is None:
            cached = build_evidence(conv)
            with self.lock:
                self._evidence[conversation_id] = cached
        return cached

    @staticmethod
    def _rel(path: Path) -> str:
        try:
            return str(path.resolve().relative_to(REPO_ROOT))
        except ValueError:
            return str(path)
