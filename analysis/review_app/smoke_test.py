"""End-to-end smoke test for the HW4 review app. Never touches analysis/state.

Starts the server on a temporary state directory with --no-langfuse-writes,
drives every endpoint over HTTP, checks the files it writes, checks the
security rules, and optionally saves a headless-Chrome screenshot of the
Review view. All notes, suggestions, modes and labels it writes are
placeholders in the temporary directory, not review judgements.

    uv run python -m analysis.review_app.smoke_test
    uv run python -m analysis.review_app.smoke_test --screenshot analysis/review_app/cache/screenshot-review.png
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_STATE = REPO_ROOT / "analysis" / "state"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{' · ' + detail if detail else ''}")
    return bool(ok)


class Client:
    def __init__(self, port: int) -> None:
        self.port = port

    def req(self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None,
            raw: bytes | None = None) -> tuple[int, Any]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        hdrs = {"Host": f"127.0.0.1:{self.port}"}
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        conn.request(method, path, body=data, headers=hdrs)
        resp = conn.getresponse()
        payload = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(payload)
        except ValueError:
            return resp.status, payload.decode(errors="replace")

    def get(self, path: str, **kw: Any) -> tuple[int, Any]:
        return self.req("GET", path, **kw)

    def post(self, path: str, body: Any, **kw: Any) -> tuple[int, Any]:
        return self.req("POST", path, body=body, **kw)


def tree_digest(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(str(p.relative_to(root)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def wait_ready(client: Client, proc: subprocess.Popen, timeout: float = 120) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if proc.poll() is not None:
            return False
        try:
            status, _ = client.get("/api/version")
            if status == 200:
                return True
        except OSError:
            pass
        time.sleep(0.5)
    return False


def run(port: int, screenshot: Path | None) -> int:
    before = tree_digest(REAL_STATE)
    state = Path(tempfile.mkdtemp(prefix="review-app-state-"))
    if not port:
        import socket
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
    else:
        import socket
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"port {port} is already in use; refusing to test against a running app")
    cmd = [sys.executable, "-m", "analysis.review_app", "--port", str(port), "--state-dir", str(state), "--no-langfuse-writes"]
    proc = subprocess.Popen(cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    c = Client(port)
    try:
        if not check("server starts", wait_ready(c, proc), f"state dir {state}"):
            print(proc.stdout.read() if proc.stdout else "")
            return 1

        # -- listener --------------------------------------------------------
        lsof = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"], capture_output=True, text=True).stdout
        listen_lines = [ln for ln in lsof.splitlines()[1:] if ln.strip()]
        check("listener is 127.0.0.1 only", bool(listen_lines) and all(f"127.0.0.1:{port}" in ln for ln in listen_lines),
              "; ".join(" ".join(ln.split()[-2:]) for ln in listen_lines))

        # -- load from Langfuse if reachable ----------------------------------
        status, src = c.post("/api/reload", {"source": "langfuse"})
        if status == 200:
            check("reload from Langfuse", True, f"{src['source']['trace_count']} traces, cache written")
        else:
            check("reload from Langfuse (unreachable, kept fallback)", True, str(src.get("error"))[:120])
        _, st = c.get("/api/status")
        print(f"       source: {st['source']['kind']} · {st['source']['detail']}")

        # -- conversations ----------------------------------------------------
        _, lst = c.get("/api/conversations")
        convs = {x["id"]: x for x in lst["conversations"]}
        check("250 conversations", len(convs) == 250, f"{len(convs)} conversations from {st['source']['trace_count']} traces")
        for cid in ("support-0059", "support-0240"):
            _, conv = c.get(f"/api/conversation?id={cid}")
            ok = (len(conv["retried"]) == 1 and conv["retried"][0]["session_id"] != conv["session_id"]
                  and conv["trace_ids"] == [t["trace_id"] for t in conv["turns"]]
                  and not set(conv["trace_ids"]) & set(conv["retried"][0]["trace_ids"]))
            check(f"{cid} shows only its latest session, flagged retried", ok,
                  f"{len(conv['turns'])} turns in session {conv['session_id'][:8]}; earlier partial {conv['retried'][0]['session_id'][:8]} ({conv['retried'][0]['turn_count']} turns)")
        _, conv = c.get("/api/conversation?id=support-0238")
        results = {json.loads(ln)["scenario_id"]: json.loads(ln) for ln in (REPO_ROOT / "scenarios" / "final-results.jsonl").read_text().splitlines() if ln.strip()}
        turns = conv["turns"]
        stamps = [t["timestamp"] for t in turns]
        in_order = stamps == sorted(stamps) and [t["user"] for t in turns] == [t["user"] for t in results["support-0238"]["turns"]]
        tools_ok = all(all("result_text" in s for s in t["steps"] if s["kind"] == "tool") for t in turns)
        tool_turns = [t["number"] for t in turns if any(s["kind"] == "tool" for s in t["steps"])]
        check("support-0238: 4 turns in order, tool results inside the turn before its reply",
              len(turns) == 4 and in_order and tools_ok and conv["primary_trace_id"] == turns[0]["trace_id"],
              f"turns with tools: {tool_turns}; primary trace = turn 1 trace")
        _, c1 = c.get("/api/conversation?id=support-0001")
        ledger = c1["evidence"]["ledger"]
        check("ledger rows for support-0001", bool(ledger["refunds"]) and bool(ledger["orders"]) and ledger["label"].startswith("database state after the final run"),
              f"orders {[o['id'] for o in ledger['orders']]}, refunds {[(r['id'], r['status']) for r in ledger['refunds']]}")

        # -- annotations ------------------------------------------------------
        tool = next(st for st in turns[0]["steps"] if st["kind"] == "tool")
        rt = tool["result_text"]
        quote = next(ln.strip() for ln in rt.splitlines() if '"status"' in ln)
        start = rt.find(quote)
        note = {"conversation_id": "support-0238", "turn_index": 0, "trace_id": turns[0]["trace_id"], "target": f"t0.s{tool['index']}.result",
                "quote": quote, "start": start, "end": start + len(quote), "note": "[smoke test placeholder note, not a judgement]"}
        s403, _ = c.post("/api/annotations", {"annotation": note})
        s200, res = c.post("/api/annotations", {"by": "human", "annotation": note})
        ann = res["changed"][0] if s200 == 200 else {}
        s_edit, res2 = c.post("/api/annotations", {"by": "human", "annotation": {"id": ann.get("id"), "note": "[smoke test placeholder note, edited]"}})
        disk = json.loads((state / "annotations.json").read_text())["annotations"]
        rec = next((a for a in disk if a["id"] == ann.get("id")), {})
        fields = {"id", "conversation_id", "session_id", "trace_id", "turn_index", "quote", "start", "end", "note", "first_failure",
                  "no_failure", "source", "suggestion_id", "created_at", "updated_at", "history"}
        check("annotation: agent POST refused, reviewer POST saved with history", s403 == 403 and s200 == 200 and s_edit == 200
              and fields <= set(rec) and rec["first_failure"] and len(rec["history"]) == 2
              and rec["history"][0]["note"].endswith("not a judgement]") and rec["session_id"] == conv["session_id"],
              f"agent {s403}, reviewer {s200}, history {len(rec.get('history', []))} versions, first_failure {rec.get('first_failure')}")
        s_nf, _ = c.post("/api/annotations", {"by": "human", "action": "no_failure", "conversation_id": "support-0238"})
        s_nf2, _ = c.post("/api/annotations", {"by": "human", "action": "no_failure", "conversation_id": "support-0002"})
        check("'no failure observed' refused on a conversation with notes, saved on another", s_nf == 409 and s_nf2 == 200, f"{s_nf}, {s_nf2}")

        # -- suggestions ------------------------------------------------------
        t0_reply = turns[0]["reply"]
        sugg = [
            {"mode": "smoke_test_mode", "conversation_id": "support-0238", "quote": t0_reply[:30], "reason": "[smoke test placeholder suggestion A]"},
            {"mode": "smoke_test_mode", "conversation_id": "support-0001", "quote": c1["turns"][0]["reply"][:30], "reason": "[smoke test placeholder suggestion B]"},
            {"mode": "smoke_test_mode", "conversation_id": "support-0238", "quote": turns[0]["user"][:30], "reason": "[smoke test placeholder suggestion C, left pending]"},
        ]
        s_push, pushed = c.post("/api/suggestions", sugg)
        ids = [x["id"] for x in pushed.get("changed", [])]
        located = all(x.get("target") and x.get("start") is not None for x in pushed.get("changed", []))
        s_agent_accept, _ = c.post("/api/suggestions", {"action": "accept", "ids": ids[:1]})
        s_acc, acc = c.post("/api/suggestions", {"by": "human", "action": "accept", "ids": ids[:1], "reviewer_comment": "[smoke test] accepted"})
        s_rej, _ = c.post("/api/suggestions", {"by": "human", "action": "reject", "ids": ids[1:2], "reviewer_comment": "[smoke test] rejected: outside the boundary"})
        disk_s = {x["id"]: x for x in json.loads((state / "suggestions.json").read_text())}
        disk_a = json.loads((state / "annotations.json").read_text())["annotations"]
        linked = [a for a in disk_a if a.get("suggestion_id") == ids[0]] if ids else []
        check("suggestions: agent push pending + located; agent cannot decide; accept creates a linked note; rejection kept",
              s_push == 200 and len(ids) == 3 and located and s_agent_accept == 403 and s_acc == 200 and s_rej == 200
              and disk_s[ids[0]]["status"] == "accepted" and disk_s[ids[1]]["status"] == "rejected" and disk_s[ids[2]]["status"] == "pending"
              and disk_s[ids[1]]["reviewer_comment"] and len(linked) == 1 and linked[0]["source"] == "accepted_suggestion",
              f"statuses {[disk_s[i]['status'] for i in ids]}, linked annotation {linked[0]['id'] if linked else None}")

        # -- patterns ---------------------------------------------------------
        mode = {"name": "smoke_test_mode", "status": "accepted", "definition": "[placeholder definition for the smoke test]",
                "positive_conversation_ids": ["support-0238"], "source_annotation_ids": [ann.get("id")]}
        s_p, pres = c.post("/api/patterns", {"mode": mode})
        created = pres["changed"][0] if s_p == 200 else {}
        s_bad, _ = c.post("/api/patterns", {"mode": {"name": "Not Snake Case"}})
        s_agent_status, _ = c.post("/api/patterns", {"action": "set_status", "id": created.get("id"), "status": "accepted"})
        s_human_status, _ = c.post("/api/patterns", {"by": "human", "action": "set_status", "id": created.get("id"), "status": "accepted"})
        s_agent_edit, _ = c.post("/api/patterns", {"mode": {"id": created.get("id"), "definition": "agent edit after acceptance"}})
        s_human_edit, _ = c.post("/api/patterns", {"by": "human", "mode": {"id": created.get("id"), "boundary": "[placeholder boundary]", "evaluator_type": "llm_judge", "requirement_source": "RESP-2"}})
        disk_p = json.loads((state / "patterns.json").read_text())["modes"][0]
        check("pattern: agent proposal forced to 'proposed'; only the reviewer accepts or edits accepted modes; history kept",
              s_p == 200 and created.get("status") == "proposed" and created.get("proposed_by") == "agent" and s_bad == 400
              and s_agent_status == 403 and s_human_status == 200 and s_agent_edit == 409 and s_human_edit == 200
              and disk_p["status"] == "accepted" and len(disk_p["history"]) >= 5,
              f"status {disk_p['status']}, {len(disk_p['history'])} history entries, fields: {sorted(k for k in disk_p if k != 'history')}")

        # -- manifest ---------------------------------------------------------
        manifest = {"unit": "conversation", "dimension": "role", "batches": [
            {"name": "uniform_1", "method": "uniform random", "rationale": "[smoke test]", "conversation_ids": ["support-0001", "support-0238"]},
            {"name": "final_uniform", "method": "uniform random", "rationale": "[smoke test]", "final": True, "conversation_ids": ["support-0002"]},
        ]}
        s_m, _ = c.post("/api/samples", manifest)
        bad = json.loads(json.dumps(manifest))
        bad["batches"][1]["conversation_ids"].append("support-0001")
        s_dup, dup = c.post("/api/samples", bad)
        disk_m = json.loads((state / "sample_manifest.json").read_text())
        check("manifest saved; duplicate-batch manifest rejected and file unchanged",
              s_m == 200 and s_dup == 409 and disk_m["batches"][1]["conversation_ids"] == ["support-0002"] and all(b.get("created_at") for b in disk_m["batches"]),
              f"duplicate POST -> {s_dup}: {dup.get('error')} {dup.get('duplicates')}")

        # -- labels -----------------------------------------------------------
        s_noev, _ = c.post("/api/labels?mode=smoke_test_mode", {"by": "human", "conversation_id": "support-0238", "label": "present", "evidence": ""})
        s_l1, _ = c.post("/api/labels?mode=smoke_test_mode", {"by": "human", "conversation_id": "support-0238", "label": "present", "evidence": "[smoke test placeholder evidence]"})
        s_l2, _ = c.post("/api/labels?mode=smoke_test_mode", {"by": "human", "conversation_id": "support-0002", "label": "absent", "evidence": ""})
        s_agent_label, _ = c.post("/api/labels?mode=smoke_test_mode", {"conversation_id": "support-0001", "label": "absent"})
        rows = [json.loads(ln) for ln in (state / "labels" / "smoke_test_mode.jsonl").read_text().splitlines() if ln.strip()]
        want = {"conversation_id", "session_id", "primary_trace_id", "trace_ids", "mode", "decision", "label", "evidence", "decided_at", "langfuse_written"}
        check("labels: evidence required when present; one line per conversation; agent refused",
              s_noev == 400 and s_l1 == 200 and s_l2 == 200 and s_agent_label == 403 and len(rows) == 2 and all(want <= set(r) for r in rows)
              and {(r["conversation_id"], r["decision"], r["label"]) for r in rows} == {("support-0238", "present", 1), ("support-0002", "absent", 0)}
              and rows[0]["trace_id"] == rows[0]["primary_trace_id"],
              f"rows {[(r['conversation_id'], r['decision'], r['label'], r['langfuse_written']) for r in rows]}")
        s_dry, dry = c.post("/api/langfuse/write-labels", {"by": "human", "dry_run": True})
        s_w, w = c.post("/api/langfuse/write-labels", {"by": "human"})
        check("Langfuse write disabled by --no-langfuse-writes (dry run lists 2)", s_dry == 200 and len(dry["would_write"]) == 2 and s_w == 403,
              f"write -> {s_w}: {w.get('error')}")

        # -- progress ---------------------------------------------------------
        _, prog = c.get("/api/progress")
        check("progress view data", prog["reviewed"] == 2 and prog["suggestions"]["pending"] == 1 and prog["saturation"]["final_batch"] == "final_uniform",
              f"reviewed {prog['reviewed']}, pending {prog['suggestions']['pending']}, grid {prog['label_grid']['decided']}/{prog['label_grid']['cells']}, modes after final batch {prog['saturation']['modes_first_proposed_after']}")

        # -- security ---------------------------------------------------------
        g_host, _ = c.get("/api/conversations", headers={"Host": "evil.example:80"})
        p_origin, _ = c.post("/api/samples", manifest, headers={"Origin": "http://evil.example"})
        p_host, _ = c.post("/api/samples", manifest, headers={"Host": "attacker.test"})
        p_text, _ = c.req("POST", "/api/annotations", raw=b'{"by":"human"}', headers={"Content-Type": "text/plain"})
        p_form, _ = c.req("POST", "/api/samples", raw=b"a=b", headers={"Content-Type": "application/x-www-form-urlencoded"})
        g_local, _ = c.get("/api/version", headers={"Host": f"localhost:{port}", "Origin": f"http://localhost:{port}"})
        check("foreign Host/Origin and non-JSON POSTs get 403; own origin allowed",
              (g_host, p_origin, p_host, p_text, p_form, g_local) == (403, 403, 403, 403, 403, 200),
              f"host {g_host}, origin {p_origin}, post-host {p_host}, text/plain {p_text}, form {p_form}, localhost {g_local}")
        s_ui, page = c.get("/")
        import re as _re
        external = _re.findall(r'<(?:script|link|img)[^>]+(?:src|href)="(?:https?:)?//', str(page))
        check("UI served, no external resources", s_ui == 200 and "Cartwheel" in str(page) and not external, f"{len(str(page))} bytes")

        # -- demo detection (in-process, on a temporary copy) -----------------
        from analysis.review_app.store import ReviewStore

        demo_copy = Path(tempfile.mkdtemp(prefix="review-app-demo-"))
        shutil.copytree(REAL_STATE, demo_copy, dirs_exist_ok=True)
        store = ReviewStore(demo_copy, lambda: {})
        found = [f["path"] for f in store.demo_files()]
        moved = store.start_fresh()["moved"]
        check("course demo files detected and moved only on request (temp copy)", bool(found) and len(moved) == len(found)
              and (demo_copy / "_course_demo").exists() and not store.demo_files(), f"{len(found)} files: {', '.join(found)}")
        shutil.rmtree(demo_copy, ignore_errors=True)

        # -- screenshot -------------------------------------------------------
        if screenshot:
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            profile = tempfile.mkdtemp(prefix="review-app-chrome-")
            subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--user-data-dir={profile}",
                            "--window-size=1720,1080", "--virtual-time-budget=10000", f"--screenshot={screenshot}",
                            f"http://127.0.0.1:{port}/#review/support-0238"], capture_output=True, timeout=120)
            shutil.rmtree(profile, ignore_errors=True)
            check("screenshot of the Review view", screenshot.exists() and screenshot.stat().st_size > 20000, str(screenshot.relative_to(REPO_ROOT)) if screenshot.is_relative_to(REPO_ROOT) else str(screenshot))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        check("server stopped", proc.poll() is not None)
        check("analysis/state untouched", tree_digest(REAL_STATE) == before)
        shutil.rmtree(state, ignore_errors=True)
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    # Default 0 = pick a free port, so the test never talks to a review app already running on 8040.
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--screenshot", type=Path, default=None)
    args = parser.parse_args()
    shot = args.screenshot.resolve() if args.screenshot else None
    sys.exit(run(args.port, shot))


if __name__ == "__main__":
    main()
