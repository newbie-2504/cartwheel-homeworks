"""HW4 review app: conversation-level error analysis for Cartwheel. Built with Claude Code.

A Python standard-library HTTP server and a single-file UI (``ui/index.html``).
It groups the HW3 support traces into conversations by session, shows each
conversation turn by turn with tool calls beside the replies, and saves the
reviewer's free-text notes, taxonomy, suggestion decisions, sample batches
and binary labels under the state directory (default ``analysis/state``).

Run:

    uv run python -m analysis.review_app --port 8040
    python analysis/review_app/server.py --port 8040 --state-dir /tmp/scratch-state

Security (same pattern as ``scenarios/review_app.py``): the server binds
127.0.0.1 only, rejects any request whose Host or Origin is not this app,
and rejects a POST whose Content-Type is not ``application/json``.

Langfuse scores are written only when the reviewer presses "Write accepted
labels to Langfuse" (POST /api/langfuse/write-labels), never on page load.
``--no-langfuse-writes`` disables that endpoint entirely (use it in tests).

The API is documented in ``analysis/review_app/README.md``.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # run as a script: make the repo importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from analysis.review_app.data import REPO_ROOT, ConversationData, locate_quote, spec_ids  # noqa: E402
from analysis.review_app.store import ReviewStore, StoreError, now  # noqa: E402
from observability.instrument import load_env  # noqa: E402

HERE = Path(__file__).resolve().parent
HOST = "127.0.0.1"
UI_PATH = HERE / "ui" / "index.html"
MAX_BODY = 10 * 1024 * 1024
HUMAN_ONLY = {"/api/annotations", "/api/labels", "/api/langfuse/write-labels", "/api/demo/start-fresh"}


class App:
    """Everything a request handler needs, shared across threads."""

    def __init__(self, data: ConversationData, store: ReviewStore, no_langfuse_writes: bool, port: int) -> None:
        self.data = data
        self.store = store
        self.no_langfuse_writes = no_langfuse_writes
        self.port = port
        self.data_version = 1
        self.reload_lock = threading.Lock()
        self.write_lock = threading.Lock()
        self.last_reload_error: str | None = None

    # -- derived views ------------------------------------------------------

    def review_status(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for a in self.store.annotations(include_deleted=False)["annotations"]:
            entry = out.setdefault(a["conversation_id"], {"notes": 0, "no_failure": False})
            if a.get("no_failure"):
                entry["no_failure"] = True
            else:
                entry["notes"] += 1
        for entry in out.values():
            entry["status"] = "has_notes" if entry["notes"] else ("no_failure" if entry["no_failure"] else "not_reviewed")
        return out

    def batch_of(self) -> dict[str, str]:
        return {c: b["name"] for b in self.store.manifest().get("batches", []) for c in b.get("conversation_ids", [])}

    def conversation_list(self) -> list[dict[str, Any]]:
        status, batch = self.review_status(), self.batch_of()
        out = []
        for cid, c in self.data.conversations.items():
            sc = c.get("scenario") or {}
            tup = sc.get("tuple") or {}
            ids = {k: v for k, v in tup.items() if k.endswith("_id") and k != "user_id"}
            st = status.get(cid, {"status": "not_reviewed", "notes": 0})
            out.append({
                "id": cid, "session_id": c["session_id"], "primary_trace_id": c["primary_trace_id"],
                "trace_ids": c["trace_ids"], "turn_count": len(c["turns"]), "started_at": c["started_at"],
                "role": tup.get("role") or c.get("user_role"), "user_id": tup.get("user_id") or c.get("user_id"),
                "intent": tup.get("intent"), "record_state": tup.get("record_state"),
                "difficulty": tup.get("difficulty"), "user_style": tup.get("user_style"),
                "group": sc.get("scenario_group"), "dq": sc.get("data_quality_case_id"), "ids": ids,
                "retried_sessions": [r["session_id"] for r in c["retried"]],
                "review_status": st["status"], "note_count": st.get("notes", 0), "batch": batch.get(cid),
                "warnings": len(c["warnings"]),
            })
        return out

    def status(self) -> dict[str, Any]:
        manifest_path = self.store.path("sample_manifest.json")
        manifest_foreign = False
        if manifest_path.exists():
            try:
                raw = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest_foreign = not (isinstance(raw, dict) and "batches" in raw)
            except ValueError:
                manifest_foreign = True
        try:
            state_dir = str(self.store.dir.resolve().relative_to(REPO_ROOT))
        except ValueError:
            state_dir = str(self.store.dir)
        return {
            "source": self.data.source,
            "last_reload_error": self.last_reload_error,
            "state_dir": state_dir,
            "no_langfuse_writes": self.no_langfuse_writes,
            "demo_files": self.store.demo_files(),
            "manifest_foreign_shape": manifest_foreign,
            "spec_ids": spec_ids(),
            "version": self.version(),
        }

    def version(self) -> str:
        return f"{self.data_version}#{self.store.version()}"

    def conversation(self, cid: str) -> dict[str, Any] | None:
        conv = self.data.conversations.get(cid)
        if conv is None:
            return None
        out = dict(conv)
        out["evidence"] = self.data.evidence(cid)
        out["batch"] = self.batch_of().get(cid)
        host = (self.data.source or {}).get("langfuse_host")
        out["langfuse_trace_urls"] = {t["trace_id"]: host + t["html_path"] for t in conv["turns"] if host and t.get("html_path")}
        return out

    def progress(self) -> dict[str, Any]:
        convs = self.data.conversations
        status = self.review_status()
        reviewed = {c for c, s in status.items() if s["status"] != "not_reviewed" and c in convs}
        manifest = self.store.manifest()
        batches = []
        in_batches: set[str] = set()
        for b in manifest.get("batches", []):
            ids = b.get("conversation_ids", [])
            in_batches |= set(ids)
            batches.append({
                "name": b["name"], "method": b.get("method"), "created_at": b.get("created_at"), "final": bool(b.get("final")),
                "size": len(ids), "reviewed": sum(1 for c in ids if c in reviewed),
                "with_notes": sum(1 for c in ids if status.get(c, {}).get("status") == "has_notes"),
                "no_failure": sum(1 for c in ids if status.get(c, {}).get("status") == "no_failure"),
                "not_reviewed_ids": [c for c in ids if c not in reviewed],
            })
        modes = self.store.patterns()["modes"]
        accepted = [m for m in modes if m.get("status") == "accepted"]
        grid = []
        for m in accepted:
            rows = {r["conversation_id"]: r for r in self.store.labels(m["name"])["labels"]}
            decided = [c for c in reviewed if c in rows]
            present = [c for c in decided if rows[c].get("decision") == "present"]
            grid.append({
                "mode": m["name"], "reviewed": len(reviewed), "decided": len(decided),
                "missing": sorted(reviewed - set(decided)), "present": len(present), "absent": len(decided) - len(present),
                "sample_fraction_present": round(len(present) / len(decided), 3) if decided else None,
                "present_without_evidence": [c for c in present if not rows[c].get("evidence")],
                "not_written_to_langfuse": sum(1 for r in rows.values() if not r.get("langfuse_written")),
            })
        suggestions = self.store.suggestions()
        final = next((b for b in reversed(manifest.get("batches", [])) if b.get("final")), None) or (manifest.get("batches") or [None])[-1]
        saturation: dict[str, Any] = {"final_batch": None}
        if final:
            started = final.get("created_at") or ""
            later = [m for m in modes if (m.get("created_at") or "") > started]
            saturation = {
                "final_batch": final["name"], "final_batch_started_at": started,
                "modes_first_proposed_after": len(later),
                "modes": [{"name": m["name"], "status": m["status"], "created_at": m.get("created_at"), "proposed_by": m.get("proposed_by")} for m in later],
                "rule": "the final batch is the batch marked final: true, else the last batch in sample_manifest.json",
            }
        total_cells = len(reviewed) * len(accepted)
        return {
            "conversations": len(convs),
            "reviewed": len(reviewed),
            "with_notes": sum(1 for c in reviewed if status[c]["status"] == "has_notes"),
            "no_failure": sum(1 for c in reviewed if status[c]["status"] == "no_failure"),
            "reviewed_not_in_any_batch": sorted(reviewed - in_batches),
            "batches": batches,
            "batch_conversations_without_judgement": sorted(in_batches - reviewed),
            "label_grid": {"cells": total_cells, "decided": sum(g["decided"] for g in grid), "modes": grid},
            "suggestions": {s: sum(1 for x in suggestions if x.get("status") == s) for s in ("pending", "accepted", "rejected")},
            "saturation": saturation,
        }

    # -- Langfuse writes ----------------------------------------------------

    def write_labels(self, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        wanted = set(body.get("modes") or [])
        plan = []
        for m in self.store.accepted_modes():
            if wanted and m["name"] not in wanted:
                continue
            for r in self.store.labels(m["name"])["labels"]:
                if not r.get("langfuse_written"):
                    plan.append((m["name"], r))
        summary = [{"mode": mode, "conversation_id": r["conversation_id"], "trace_id": r["primary_trace_id"], "value": r["label"]} for mode, r in plan]
        if body.get("dry_run"):
            return 200, {"ok": True, "dry_run": True, "would_write": summary}
        if self.no_langfuse_writes:
            return 403, {"error": "Langfuse writes are disabled (--no-langfuse-writes)", "would_write": summary}
        if not plan:
            return 200, {"ok": True, "written": 0, "errors": []}
        from analysis.helpers import langfuse_io  # imported lazily: needs the langfuse SDK

        if not langfuse_io.is_configured():
            return 409, {"error": "LANGFUSE_HOST / LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not set in .env"}
        # One write at a time: a second click while a batch is running would duplicate scores.
        if not self.write_lock.acquire(blocking=False):
            return 409, {"error": "a Langfuse write is already running; wait for it to finish"}
        try:
            client = langfuse_io._client()
            stamp = now()
            written: dict[str, set[str]] = {}
            errors = []
            for mode, r in plan:
                try:
                    # Deterministic score id per (conversation, mode): re-writing updates the same
                    # score instead of adding a duplicate.
                    client.create_score(
                        score_id=f"hw4-label-{mode}-{r['conversation_id']}",
                        name=mode,
                        value=int(r["label"]),
                        trace_id=langfuse_io.logical_to_langfuse_id(r["primary_trace_id"], client),
                        data_type="NUMERIC",
                        comment=r.get("evidence") or None,
                    )
                    written.setdefault(mode, set()).add(r["conversation_id"])
                except Exception as exc:  # report per row, keep going
                    errors.append({"mode": mode, "conversation_id": r["conversation_id"], "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
            client.flush()  # one flush for the batch instead of one per score
            for mode, ids in written.items():
                self.store.mark_written(mode, ids, stamp)
            return (200 if not errors else 502), {"ok": not errors, "written": sum(len(v) for v in written.values()), "errors": errors}
        finally:
            self.write_lock.release()


def build_handler(app: App) -> type[BaseHTTPRequestHandler]:
    allowed_hosts = {f"{HOST}:{app.port}", f"localhost:{app.port}"}
    allowed_origins = {f"http://{h}" for h in allowed_hosts}

    class Handler(BaseHTTPRequestHandler):
        server_version = "cartwheel-review"

        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data: Any, status: int = 200) -> None:
            self._send(status, json.dumps(data, default=str).encode(), "application/json")

        def _trusted(self) -> bool:
            # Host check blocks DNS rebinding; Origin check blocks other pages posting here.
            if self.headers.get("Host") not in allowed_hosts:
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin in allowed_origins

        def do_GET(self) -> None:  # noqa: N802
            if not self._trusted():
                return self._json({"error": "forbidden"}, 403)
            parsed = urllib.parse.urlsplit(self.path)
            path, params = parsed.path, dict(urllib.parse.parse_qsl(parsed.query))
            try:
                if path in ("/", "/index.html"):
                    return self._send(200, UI_PATH.read_bytes(), "text/html; charset=utf-8")
                if path == "/api/status":
                    return self._json(app.status())
                if path == "/api/version":
                    return self._json({"version": app.version()})
                if path == "/api/conversations":
                    return self._json({"source": app.data.source, "conversations": app.conversation_list()})
                if path == "/api/conversation":
                    conv = app.conversation(params.get("id", ""))
                    return self._json(conv) if conv else self._json({"error": "unknown conversation id"}, 404)
                if path == "/api/annotations":
                    return self._json(app.store.annotations())
                if path == "/api/patterns":
                    return self._json(app.store.patterns())
                if path == "/api/suggestions":
                    return self._json(app.store.suggestions())
                if path == "/api/samples":
                    return self._json(app.store.manifest())
                if path == "/api/labels":
                    if params.get("mode"):
                        return self._json(app.store.labels(params["mode"]))
                    return self._json({"modes": {m["name"]: app.store.labels(m["name"])["labels"] for m in app.store.accepted_modes()}})
                if path == "/api/progress":
                    return self._json(app.progress())
                if path == "/api/label-suggestions":
                    # Read-only: code-check suggestions written by a script. The reviewer
                    # confirms each one in the UI; nothing here writes a label.
                    raw = app.store._read("label_suggestions.json", {})
                    names = {m["id"]: m["name"] for m in app.store.patterns()["modes"]}
                    modes = raw.get("modes", {}) if isinstance(raw, dict) else {}
                    return self._json({"method": raw.get("method") if isinstance(raw, dict) else None,
                                       "modes": {names[mid]: v.get("rows", {}) for mid, v in modes.items() if mid in names}})
            except StoreError as exc:
                return self._json({"error": str(exc), **exc.extra}, exc.status)
            return self._json({"error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            if not self._trusted() or self.headers.get("Content-Type") != "application/json":
                return self._json({"error": "forbidden"}, 403)
            parsed = urllib.parse.urlsplit(self.path)
            path, params = parsed.path, dict(urllib.parse.parse_qsl(parsed.query))
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                return self._json({"error": "body too large"}, 413)
            try:
                body = json.loads(self.rfile.read(length) or b"null")
            except ValueError:
                return self._json({"error": "expected a JSON body"}, 400)
            if body is None:
                return self._json({"error": "expected a JSON body"}, 400)
            actor = (body.get("by") if isinstance(body, dict) else None) or self.headers.get("X-Review-Actor") or "agent"
            actor = "human" if actor == "human" else "agent"
            if path in HUMAN_ONLY and actor != "human":
                return self._json({"error": "only the reviewer UI writes this (send by: human from the UI); agents propose through /api/patterns and /api/suggestions"}, 403)
            try:
                if path == "/api/annotations":
                    return self._json(app.store.save_annotations(body))
                if path == "/api/patterns":
                    return self._json(app.store.save_patterns(body, actor))
                if path == "/api/suggestions":
                    return self._json(app.store.save_suggestions(body, actor, locate_quote))
                if path == "/api/samples":
                    return self._json(app.store.save_manifest(body))
                if path == "/api/labels":
                    mode = params.get("mode") or (body.get("mode") if isinstance(body, dict) else None)
                    if not mode:
                        return self._json({"error": "pass ?mode=<mode name>"}, 400)
                    return self._json(app.store.save_labels(mode, body))
                if path == "/api/langfuse/write-labels":
                    status, payload = app.write_labels(body if isinstance(body, dict) else {})
                    return self._json(payload, status)
                if path == "/api/reload":
                    return self._reload(body if isinstance(body, dict) else {})
                if path == "/api/demo/start-fresh":
                    if not (isinstance(body, dict) and body.get("confirm") is True):
                        return self._json({"error": "send confirm: true"}, 400)
                    return self._json(app.store.start_fresh())
            except StoreError as exc:
                return self._json({"error": str(exc), **exc.extra}, exc.status)
            except Exception as exc:  # pragma: no cover - surfaced to the UI
                return self._json({"error": f"internal error: {type(exc).__name__}: {str(exc)[:300]}"}, 500)
            return self._json({"error": "not found"}, 404)

        def _reload(self, body: dict[str, Any]) -> None:
            if not app.reload_lock.acquire(blocking=False):
                return self._json({"error": "a reload is already running"}, 409)
            try:
                if body.get("source") == "export":
                    app.data.load_from_export("reloaded from the export on request")
                else:
                    try:
                        app.data.load_from_langfuse()
                    except Exception as exc:
                        app.last_reload_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                        return self._json({"error": f"Langfuse reload failed; kept the current source. {app.last_reload_error}",
                                           "source": app.data.source}, 502)
                app.last_reload_error = None
                app.data_version += 1
                return self._json({"ok": True, "source": app.data.source})
            finally:
                app.reload_lock.release()

    return Handler


def make_server(port: int, state_dir: Path, cache_dir: Path, source: str, no_langfuse_writes: bool) -> tuple[ThreadingHTTPServer, App]:
    load_env(REPO_ROOT / ".env")
    data = ConversationData(cache_dir)
    data.load(source)
    store = ReviewStore(state_dir, lambda: data.conversations)
    app = App(data, store, no_langfuse_writes, port)
    server = ThreadingHTTPServer((HOST, port), build_handler(app))
    return server, app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="HW4 conversation review app (binds 127.0.0.1 only).")
    parser.add_argument("--port", type=int, default=8040)
    parser.add_argument("--state-dir", type=Path, default=REPO_ROOT / "analysis" / "state",
                        help="where annotations, patterns, suggestions, the manifest and labels live (default analysis/state)")
    parser.add_argument("--cache-dir", type=Path, default=HERE / "cache", help="Langfuse trace cache (default analysis/review_app/cache)")
    parser.add_argument("--source", choices=("auto", "cache", "langfuse", "export"), default="auto",
                        help="auto: cache, then live Langfuse, then the HW3 export (offline)")
    parser.add_argument("--no-langfuse-writes", action="store_true", help="disable POST /api/langfuse/write-labels")
    args = parser.parse_args(argv)
    server, app = make_server(args.port, args.state_dir.resolve(), args.cache_dir.resolve(), args.source, args.no_langfuse_writes)
    src = app.data.source
    print(f"Review app on http://{HOST}:{args.port}/   (Ctrl+C to stop)")
    print(f"  source: {src.get('detail')} · {src.get('conversation_count')} conversations from {src.get('trace_count')} traces")
    print(f"  state:  {args.state_dir}")
    if args.no_langfuse_writes:
        print("  Langfuse score writes are disabled (--no-langfuse-writes)")
    demo = app.store.demo_files()
    if demo:
        print(f"  note: {len(demo)} course demo file(s) in the state dir are ignored (see the banner in the app)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
