"""Scenario review app for Homework 3. Built with Claude Code.

One screen per scenario: the tuple, then each turn's user message, tool calls
(collapsed; click for the full arguments and result) and agent reply, with the
answer key pinned beside the four review fields from the handout. Every change
is saved to the review JSONL, so there is no export step.

Usage:
    uv run python -m scenarios.review_app                          # Part B pilot review
    uv run python -m scenarios.review_app --mode decision \
        --scenarios scenarios/support_scenarios.jsonl \
        --review scenarios/support_review.jsonl --ids support-0001,...      # Part C review before the run

Run mode records scenario_valid / confirmed_failure / evidence / scenario_change (pilot_review.jsonl).
Decision mode records decision (accept, revise, reject) / reason / change (support_review.jsonl) and shows
the scripted user turns when the scenarios have not been run yet.

Tool calls come from Langfuse (LANGFUSE_* in .env), matched on
``cartwheel.scenario_id``. When a scenario ran more than once, the latest
session is shown. The server listens on 127.0.0.1 only and rejects requests
whose Host or Origin is not this app, so another page in the browser cannot
write the review file.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from observability.instrument import load_env
from scenarios.validate import load_jsonl

REPO_ROOT = Path(__file__).resolve().parents[1]
HOST = "127.0.0.1"
REVIEW_FIELDS = {
    "run": ("scenario_id", "scenario_valid", "confirmed_failure", "evidence", "scenario_change"),
    "decision": ("scenario_id", "decision", "reason", "change"),
}
DECISIONS = {"accept", "revise", "reject"}


class Langfuse:
    """Read-only Langfuse public API client: scenario id -> tool calls per turn."""

    def __init__(self) -> None:
        self.host = os.environ.get("LANGFUSE_HOST", "http://localhost:3000").rstrip("/")
        key, secret = os.environ.get("LANGFUSE_PUBLIC_KEY"), os.environ.get("LANGFUSE_SECRET_KEY")
        self.auth = base64.b64encode(f"{key}:{secret}".encode()).decode() if key and secret else None
        self.index: dict[str, list[str]] | None = None
        self.observations: dict[str, list[dict[str, Any]]] = {}
        self.lock = threading.Lock()

    def _get(self, path: str) -> Any:
        req = urllib.request.Request(self.host + path, headers={"Authorization": "Basic " + str(self.auth)})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)

    def _build_index(self, wanted: set[str]) -> dict[str, list[str]]:
        # Group each scenario's message traces by session and keep the latest
        # session, so a rerun replaces the earlier run instead of mixing with it.
        sessions: dict[tuple[str, str], list[dict[str, Any]]] = {}
        page = 1
        while True:
            data = self._get(f"/api/public/traces?name=cartwheel.session_message&limit=100&page={page}")
            for trace in data["data"]:
                attrs = (trace.get("metadata") or {}).get("attributes") or {}
                sid = attrs.get("cartwheel.scenario_id")
                if sid in wanted:
                    sessions.setdefault((sid, attrs.get("cartwheel.session_id", "")), []).append(trace)
            if page >= data["meta"]["totalPages"]:
                break
            page += 1
        latest: dict[str, list[dict[str, Any]]] = {}
        for (sid, _), traces in sessions.items():
            newest = max(t["timestamp"] for t in traces)
            if sid not in latest or newest > max(t["timestamp"] for t in latest[sid]):
                latest[sid] = traces
        return {sid: [t["id"] for t in sorted(ts, key=lambda t: t["timestamp"])] for sid, ts in latest.items()}

    def tools_for(self, scenario_id: str, wanted: set[str], refresh: bool = False) -> dict[str, Any]:
        if not self.auth:
            return {"error": "LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not set in .env"}
        try:
            with self.lock:
                if self.index is None or refresh:
                    self.index = self._build_index(wanted)
            trace_ids = self.index.get(scenario_id, [])
            turns = []
            for trace_id in trace_ids:
                if trace_id not in self.observations:
                    obs = sorted(self._get(f"/api/public/traces/{trace_id}")["observations"], key=lambda o: o["startTime"])
                    self.observations[trace_id] = [
                        {"name": o["name"], "input": o.get("input"), "output": o.get("output")}
                        for o in obs
                        if o["type"] == "TOOL"
                    ]
                turns.append(self.observations[trace_id])
            return {"trace_ids": trace_ids, "turns": turns, "langfuse_url": self.host}
        except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
            return {"error": f"Langfuse not reachable at {self.host}: {exc}"}


class ReviewStore:
    """The review JSONL, rewritten in scenario order on every change."""

    def __init__(self, path: Path, order: list[str], mode: str) -> None:
        self.path, self.order, self.mode = path, order, mode
        self.lock = threading.Lock()
        self.records: dict[str, dict[str, Any]] = {}
        if path.exists():
            for record in load_jsonl(path):
                self.records[record["scenario_id"]] = record

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        sid = record.get("scenario_id")
        if sid not in self.order:
            raise ValueError(f"unknown scenario_id {sid!r}")
        with self.lock:
            if self.mode == "decision":
                return self._save_decision(sid, record)
            if record.get("scenario_valid") is None:
                self.records.pop(sid, None)  # "clear" in the UI
            else:
                valid = bool(record["scenario_valid"])
                change = (record.get("scenario_change") or "").strip()
                self.records[sid] = {
                    "scenario_id": sid,
                    "scenario_valid": valid,
                    # The handout counts a failure only when the scenario is valid.
                    "confirmed_failure": bool(record.get("confirmed_failure")) and valid,
                    "evidence": (record.get("evidence") or "").strip(),
                    "scenario_change": change or None,
                }
            rows = self._write()
            return {"reviewed": len(rows), "failures": sum(r["confirmed_failure"] for r in rows)}

    def _save_decision(self, sid: str, record: dict[str, Any]) -> dict[str, Any]:
        decision = record.get("decision")
        if decision is None:
            self.records.pop(sid, None)
        elif decision not in DECISIONS:
            raise ValueError(f"decision must be one of {sorted(DECISIONS)}")
        else:
            change = (record.get("change") or "").strip()
            self.records[sid] = {"scenario_id": sid, "decision": decision,
                                 "reason": (record.get("reason") or "").strip(), "change": change or None}
        rows = self._write()
        return {"reviewed": len(rows), "failures": sum(r["decision"] != "accept" for r in rows)}

    def _write(self) -> list[dict[str, Any]]:
        fields = REVIEW_FIELDS[self.mode]
        rows = [self.records[s] for s in self.order if s in self.records]
        tmp = self.path.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(json.dumps({k: r.get(k) for k in fields}) + "\n" for r in rows))
        tmp.replace(self.path)
        return rows


def build_handler(scenarios: list[dict[str, Any]], results: dict[str, dict[str, Any]], store: ReviewStore,
                  langfuse: Langfuse, config: dict[str, Any], port: int) -> type[BaseHTTPRequestHandler]:
    allowed_hosts = {f"{HOST}:{port}", f"localhost:{port}"}
    wanted = {s["id"] for s in scenarios}
    payload = [
        {
            "id": s["id"],
            "group": s.get("scenario_group"),
            "dq": s.get("data_quality_case_id"),
            "tuple": s.get("tuple", {}),
            "expected": s.get("expected", {}),
            "result": results.get(s["id"]),
            "script": [s.get("opening_message", "")] + list(s.get("followups", [])),
        }
        for s in scenarios
    ]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002
            pass

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data: Any, status: int = 200) -> None:
            self._send(status, json.dumps(data).encode(), "application/json")

        def _trusted(self) -> bool:
            # Host check blocks DNS rebinding; Origin check blocks other pages posting here.
            if self.headers.get("Host") not in allowed_hosts:
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin in {f"http://{h}" for h in allowed_hosts}

        def do_GET(self) -> None:  # noqa: N802
            if not self._trusted():
                return self._json({"error": "forbidden"}, 403)
            path, _, query = self.path.partition("?")
            params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
            if path == "/":
                return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            if path == "/api/data":
                return self._json({"scenarios": payload, "review": store.records, "config": config})
            if path == "/api/tools":
                sid = urllib.parse.unquote(params.get("id", ""))
                return self._json(langfuse.tools_for(sid, wanted, refresh=params.get("refresh") == "1"))
            return self._json({"error": "not found"}, 404)

        def do_POST(self) -> None:  # noqa: N802
            if not self._trusted() or self.headers.get("Content-Type") != "application/json":
                return self._json({"error": "forbidden"}, 403)
            if self.path != "/api/review":
                return self._json({"error": "not found"}, 404)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                return self._json(store.save(body))
            except (ValueError, KeyError) as exc:
                return self._json({"error": str(exc)}, 400)

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Review scenario runs and save the review JSONL.")
    parser.add_argument("--scenarios", default="scenarios/pilot_scenarios.jsonl")
    parser.add_argument("--results", default="scenarios/pilot-results.jsonl")
    parser.add_argument("--review", default="scenarios/pilot_review.jsonl")
    parser.add_argument("--need-reviewed", type=int, default=10)
    parser.add_argument("--need-failures", type=int, default=5)
    parser.add_argument("--port", type=int, default=8030)
    parser.add_argument("--mode", choices=["run", "decision"], default="run")
    parser.add_argument("--ids", help="comma separated scenario ids to review (default: all)")
    args = parser.parse_args()

    load_env(REPO_ROOT / ".env")
    scenarios = load_jsonl(REPO_ROOT / args.scenarios)
    if args.ids:
        keep = set(args.ids.split(","))
        scenarios = [s for s in scenarios if s["id"] in keep]
    results_path = REPO_ROOT / args.results
    results = {r["scenario_id"]: r for r in load_jsonl(results_path)} if results_path.exists() else {}
    store = ReviewStore(REPO_ROOT / args.review, [s["id"] for s in scenarios], args.mode)
    config = {"review_file": args.review, "scenario_file": args.scenarios, "mode": args.mode,
              "need_reviewed": args.need_reviewed, "need_failures": args.need_failures}
    handler = build_handler(scenarios, results, store, Langfuse(), config, args.port)
    server = ThreadingHTTPServer((HOST, args.port), handler)
    print(f"Reviewing {len(scenarios)} scenarios -> {args.review}")
    print(f"Open http://{HOST}:{args.port}/   (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>Scenario review</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--line:#e3e3df;--ink:#1f2328;--mute:#6b7075;--user:#eef4ff;--agent:#f4f1ea;
--ok:#1a7f37;--bad:#cf222e;--warn:#9a6700;--accent:#0969da}
*{box-sizing:border-box}body{margin:0;font:14px/1.45 -apple-system,system-ui,sans-serif;color:var(--ink);background:var(--bg)}
header{display:flex;gap:16px;align-items:center;padding:10px 16px;border-bottom:1px solid var(--line);background:var(--card);position:sticky;top:0;z-index:2}
header h1{font-size:15px;margin:0}.pill{padding:2px 8px;border-radius:10px;background:#eaeef2;font-size:12px}
.met{background:#dafbe1;color:var(--ok)}.unmet{background:#fff8c5;color:var(--warn)}#saved{margin-left:auto;color:var(--mute);font-size:12px}
main{display:grid;grid-template-columns:200px 1fr 380px;height:calc(100vh - 45px)}
nav{border-right:1px solid var(--line);overflow:auto;background:var(--card)}
nav .filters{display:flex;gap:4px;padding:8px;position:sticky;top:0;background:var(--card);border-bottom:1px solid var(--line)}
nav .filters button{flex:1;font-size:11px;padding:3px;border:1px solid var(--line);background:#fff;border-radius:4px;cursor:pointer}
nav .filters button.on{background:var(--ink);color:#fff}
nav a{display:flex;justify-content:space-between;padding:6px 10px;color:var(--ink);text-decoration:none;border-bottom:1px solid #f0f0ec;font-size:13px}
nav a.cur{background:#ddf4ff}nav a small{color:var(--mute)}
#conv{overflow:auto;padding:16px 24px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 16px}.chip{font-size:12px;padding:2px 8px;border-radius:4px;background:#eaeef2}
.chip b{font-weight:600}.chip.g-challenge{background:#ffebe9}.chip.g-coverage{background:#dafbe1}
.turn{margin-bottom:18px}.lbl{font-size:11px;color:var(--mute);text-transform:uppercase;letter-spacing:.04em;margin-bottom:3px}
.msg{padding:10px 12px;border-radius:8px;white-space:pre-wrap;border:1px solid var(--line)}.user{background:var(--user)}.agent{background:var(--agent)}
details.tool{margin:6px 0 6px 18px;border-left:3px solid #d0d7de;padding-left:8px;font-size:12.5px}
details.tool summary{cursor:pointer;font-family:ui-monospace,Menlo,monospace}.tok{color:var(--ok)}.terr{color:var(--bad)}
details.tool pre{background:#f6f8fa;padding:8px;border-radius:6px;overflow:auto;max-height:340px;white-space:pre-wrap;font-size:12px}
.notool{margin:6px 0 6px 18px;color:var(--mute);font-size:12px;font-style:italic}
.warnbox{background:#fff8c5;border:1px solid #d4a72c;padding:8px 10px;border-radius:6px;margin:8px 0;font-size:13px}
aside{border-left:1px solid var(--line);overflow:auto;padding:14px;background:var(--card)}
.key{background:#f6f8fa;border:1px solid var(--line);border-radius:8px;padding:10px 12px;margin-bottom:16px}
.key code{font-size:12px;word-break:break-all}.key p{margin:6px 0}.src{color:var(--mute);font-size:12px}
.field{margin-bottom:14px}.field>label{display:block;font-weight:600;margin-bottom:4px}.field>label kbd{font-weight:400}
.seg{display:flex;gap:6px}.seg button{flex:1;padding:7px;border:1px solid var(--line);background:#fff;border-radius:6px;cursor:pointer;font-size:13px}
.seg button.yes{background:var(--ok);color:#fff;border-color:var(--ok)}.seg button.no{background:var(--bad);color:#fff;border-color:var(--bad)}
.seg button:disabled{opacity:.4;cursor:not-allowed}
textarea{width:100%;min-height:90px;font:13px/1.4 inherit;padding:8px;border:1px solid var(--line);border-radius:6px;resize:vertical}
textarea.need{border-color:var(--bad);background:#fff5f5}.hint{font-size:12px;color:var(--mute)}.err{color:var(--bad);font-size:12px}
kbd{font:11px ui-monospace,monospace;padding:1px 4px;border:1px solid #d0d7de;border-radius:3px;background:#f6f8fa}
.navbtns{display:flex;gap:6px;margin-top:10px}.navbtns button{flex:1;padding:6px;border:1px solid var(--line);background:#fff;border-radius:6px;cursor:pointer}
.keys{font-size:12px;color:var(--mute);margin-top:14px;line-height:1.9}
</style></head><body>
<header><h1>Scenario review</h1><span id="file" class="pill"></span><span id="prog" class="pill"></span><span id="fail" class="pill"></span><span id="saved"></span></header>
<main>
<nav><div class="filters"><button data-f="all" class="on">All</button><button data-f="todo">To do</button><button data-f="fail">Failures</button><button data-f="invalid">Invalid</button></div><div id="list"></div></nav>
<section id="conv"></section>
<aside id="side"></aside>
</main>
<script>
let S=[],R={},D={},C={},cur=0,filter='all',toolCache={};const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const md=s=>esc(s).replace(/\*\*(.+?)\*\*/g,'<b>$1</b>');
const DEC=()=>C.mode==='decision';
function rec(id){return R[id]||(D[id]=D[id]||(DEC()?{scenario_id:id,decision:null,reason:'',change:''}:{scenario_id:id,scenario_valid:null,confirmed_failure:false,evidence:'',scenario_change:''}))}
function status(id){const r=R[id];if(!r)return['○','todo'];
  if(DEC())return r.decision==='accept'?['✓','pass']:r.decision==='revise'?['✎','fail']:['✗','invalid'];
  if(!r.scenario_valid)return['⚠','invalid'];
  if(r.confirmed_failure)return[r.evidence?'✗':'!','fail'];return['✓','pass']}
function counts(){const v=Object.values(R);return{rev:v.length,fail:v.filter(r=>DEC()?r.decision!=='accept':r.confirmed_failure).length}}
function coverage(){const ids=new Set(Object.keys(R)),seen=k=>new Set(S.filter(s=>ids.has(s.id)).map(k)),all=k=>new Set(S.map(k));
  const f=(k,l)=>`${l} ${seen(k).size}/${all(k).size}`;return [f(s=>s.group,'groups'),f(s=>s.tuple.role,'roles'),f(s=>s.tuple.intent,'intents')].join(' · ')}
function header(){const c=counts();$('file').textContent='→ '+C.review_file;
  if(DEC()){$('prog').textContent=`${c.rev}/${S.length} reviewed`;$('prog').className='pill '+(c.rev>=S.length?'met':'unmet');
    $('fail').textContent=`${c.fail} to revise or reject · ${coverage()}`;$('fail').className='pill';return}
  $('prog').textContent=`${c.rev}/${S.length} reviewed (need ${C.need_reviewed})`;$('prog').className='pill '+(c.rev>=C.need_reviewed?'met':'unmet');
  $('fail').textContent=`${c.fail} confirmed failures (need ${C.need_failures})`;$('fail').className='pill '+(c.fail>=C.need_failures?'met':'unmet')}
function list(){$('list').innerHTML=S.map((s,i)=>{const[ic,st]=status(s.id);
  if(filter!=='all'&&filter!==st)return'';
  return `<a href="#" data-i="${i}" class="${i===cur?'cur':''}"><span>${ic} ${esc(s.id)}</span><small>${s.group==='challenge'?'chal':'cov'}${s.dq?' · DQ':''}</small></a>`}).join('');
  document.querySelectorAll('#list a').forEach(a=>a.onclick=e=>{e.preventDefault();go(+a.dataset.i)})}
function summarize(v){const t=JSON.stringify(v);return t&&t.length>90?t.slice(0,90)+'…':t}
function toolLine(t){let out=t.output;try{if(typeof out==='string')out=JSON.parse(out)}catch(e){}
  const ok=out&&typeof out==='object'&&'ok'in out?(out.ok?'<span class="tok">ok</span>':`<span class="terr">${esc(out.error||'error')}</span>`):'';
  return `<details class="tool"><summary>🔧 ${esc(t.name)}(${esc(summarize(t.input))}) → ${ok}</summary><div class="lbl">arguments</div><pre>${esc(JSON.stringify(t.input,null,2))}</pre><div class="lbl">result</div><pre>${esc(JSON.stringify(out,null,2))}</pre></details>`}
function conv(){const s=S[cur],t=s.tuple,res=s.result;
  const chips=Object.entries(t).map(([k,v])=>`<span class="chip"><b>${esc(k)}</b> ${esc(v)}</span>`).join('');
  let h=`<h2 style="margin:0">${esc(s.id)}</h2><div class="chips"><span class="chip g-${s.group}"><b>${esc(s.group)}</b></span>${s.dq?`<span class="chip"><b>DQ</b> ${esc(s.dq)}</span>`:''}${chips}</div>`;
  if(!res){h+='<div class="warnbox">Not run yet: these are the scripted user turns. The answer key is on the right.</div>';
    s.script.forEach((m,i)=>{h+=`<div class="turn"><div class="lbl">T${i+1} user</div><div class="msg user">${esc(m)}</div></div>`});
    $('conv').innerHTML=h;return}
  if(res.status!=='completed')h+=`<div class="warnbox">Run status: ${esc(res.status)} ${esc(res.error||'')}</div>`;
  const tc=toolCache[s.id];
  if(tc&&tc.error)h+=`<div class="warnbox">Tool calls unavailable: ${esc(tc.error)}</div>`;
  else if(tc&&tc.turns.length!==res.turns.length)h+=`<div class="warnbox">Found ${tc.turns.length} traces for ${res.turns.length} turns. Tool calls may not line up with turns.</div>`;
  res.turns.forEach((u,i)=>{h+=`<div class="turn"><div class="lbl">T${i+1} user</div><div class="msg user">${esc(u.user)}</div>`;
    if(!tc)h+='<div class="notool">loading tool calls…</div>';
    else if(tc.turns&&tc.turns[i])h+=tc.turns[i].length?tc.turns[i].map(toolLine).join(''):'<div class="notool">no tool calls</div>';
    h+=`<div class="lbl" style="margin-top:6px">T${i+1} agent</div><div class="msg agent">${md(u.agent)}</div></div>`});
  if(tc&&tc.trace_ids)h+=`<div class="hint">Traces (search in Langfuse at ${esc(tc.langfuse_url)}): ${tc.trace_ids.map(esc).join(', ')} · <a href="#" id="refresh">reload tool calls</a></div>`;
  $('conv').innerHTML=h;const rf=$('refresh');if(rf)rf.onclick=e=>{e.preventDefault();loadTools(s.id,true)}}
function side(){const s=S[cur],e=s.expected||{},r=rec(s.id);
  const key=e.evaluation==='human_judgment'
    ?`<div class="lbl">Answer key · human judgement</div><p>${esc(e.criterion)}</p>`
    :`<div class="lbl">Answer key · objective</div><p><code>${esc(e.outcome)}</code></p><p>${esc(e.reason)}</p>`;
  const src=e.source?`<div class="src">source: ${esc(e.source.type)} · ${esc(e.source.reference)}</div>`:'';
  if(DEC())return sideDecision(key,src,r);
  const needEv=r.confirmed_failure&&!r.evidence.trim();
  $('side').innerHTML=`<div class="key">${key}${src}</div>
  <div class="field"><label>Scenario valid? <kbd>V</kbd></label><div class="seg">
    <button id="v1" class="${r.scenario_valid===true?'yes':''}">Valid</button><button id="v0" class="${r.scenario_valid===false?'no':''}">Invalid</button></div>
    <div class="hint">Does this conversation test what its tuple and answer key say?</div></div>
  <div class="field"><label>Confirmed failure? <kbd>F</kbd></label><div class="seg">
    <button id="f0" ${r.scenario_valid!==true?'disabled':''} class="${r.scenario_valid===true&&!r.confirmed_failure?'yes':''}">No failure</button>
    <button id="f1" ${r.scenario_valid!==true?'disabled':''} class="${r.confirmed_failure?'no':''}">Failure</button></div>
    <div class="hint">Only for a valid scenario whose behaviour conflicts with the answer key or SPEC.md.</div></div>
  <div class="field"><label>Evidence <kbd>E</kbd></label><textarea id="ev" class="${needEv?'need':''}" placeholder="The database value, policy, tool result or requirement behind your decision">${esc(r.evidence)}</textarea>
    ${needEv?'<div class="err">Evidence is required for a failure.</div>':''}</div>
  <div class="field"><label>Scenario change <kbd>C</kbd></label><textarea id="ch" placeholder="Leave empty for null">${esc(r.scenario_change||'')}</textarea>
    ${r.scenario_valid===false&&!(r.scenario_change||'').trim()?'<div class="hint" style="color:var(--warn)">An invalid scenario usually needs a change.</div>':''}</div>
  <div class="navbtns"><button id="prev">← Prev <kbd>K</kbd></button><button id="clr">Clear</button><button id="next">Next <kbd>J</kbd> →</button></div>
  <div class="keys"><kbd>J</kbd>/<kbd>K</kbd> next/prev · <kbd>V</kbd> valid · <kbd>F</kbd> failure · <kbd>E</kbd>/<kbd>C</kbd> type · <kbd>Esc</kbd> leave a text box</div>`;
  $('v1').onclick=()=>set({scenario_valid:true});$('v0').onclick=()=>set({scenario_valid:false,confirmed_failure:false});
  $('f0').onclick=()=>set({confirmed_failure:false});$('f1').onclick=()=>set({confirmed_failure:true});
  $('ev').oninput=ev=>typed('evidence',ev.target.value);$('ch').oninput=ev=>typed('scenario_change',ev.target.value);
  $('prev').onclick=()=>go(cur-1);$('next').onclick=()=>go(cur+1);$('clr').onclick=()=>{if(confirm('Clear this review?'))set({scenario_valid:null},true)}}
function sideDecision(key,src,r){const needWhy=r.decision&&!r.reason.trim(),needCh=(r.decision==='revise'||r.decision==='reject')&&!(r.change||'').trim();
  $('side').innerHTML=`<div class="key">${key}${src}</div>
  <div class="field"><label>Decision <kbd>A</kbd> <kbd>R</kbd> <kbd>X</kbd></label><div class="seg">
    <button id="da" class="${r.decision==='accept'?'yes':''}">Accept</button><button id="dr" class="${r.decision==='revise'?'no':''}">Revise</button><button id="dx" class="${r.decision==='reject'?'no':''}">Reject</button></div>
    <div class="hint">Is this a realistic, correctly keyed test of its tuple? Revise fixes it; reject replaces it.</div></div>
  <div class="field"><label>Reason <kbd>E</kbd></label><textarea id="ev" class="${needWhy?'need':''}" placeholder="Why: the message, tuple or answer key fact behind your decision">${esc(r.reason)}</textarea>
    ${needWhy?'<div class="err">A reason is required.</div>':''}</div>
  <div class="field"><label>Change <kbd>C</kbd></label><textarea id="ch" class="${needCh?'need':''}" placeholder="Leave empty for accept">${esc(r.change||'')}</textarea>
    ${needCh?'<div class="err">Say what to change or what replaces it.</div>':''}</div>
  <div class="navbtns"><button id="prev">← Prev <kbd>K</kbd></button><button id="clr">Clear</button><button id="next">Next <kbd>J</kbd> →</button></div>
  <div class="keys"><kbd>J</kbd>/<kbd>K</kbd> next/prev · <kbd>A</kbd> accept · <kbd>R</kbd> revise · <kbd>X</kbd> reject · <kbd>E</kbd>/<kbd>C</kbd> type · <kbd>Esc</kbd> leave a text box</div>`;
  $('da').onclick=()=>set({decision:'accept'});$('dr').onclick=()=>set({decision:'revise'});$('dx').onclick=()=>set({decision:'reject'});
  $('ev').oninput=ev=>typed('reason',ev.target.value);$('ch').oninput=ev=>typed('change',ev.target.value);
  $('prev').onclick=()=>go(cur-1);$('next').onclick=()=>go(cur+1);$('clr').onclick=()=>{if(confirm('Clear this review?'))set({decision:null},true)}}
let timer=null;
function typed(field,val){const r=rec(S[cur].id);r[field]=val;if(DEC()?r.decision===null:r.scenario_valid===null){$('saved').textContent=DEC()?'Choose a decision to save':'Choose Valid or Invalid to save';return}
  R[S[cur].id]=r;clearTimeout(timer);timer=setTimeout(()=>save(r,false),400)}
function set(patch,clear){const id=S[cur].id,r=Object.assign(rec(id),patch);if(clear){delete R[id];delete D[id]}else{R[id]=r;delete D[id]}save(clear?Object.assign({scenario_id:id},DEC()?{decision:null}:{scenario_valid:null}):r,true)}
async function save(r,redraw){$('saved').textContent='Saving…';
  try{const res=await fetch('/api/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(r)});
    const j=await res.json();if(!res.ok)throw new Error(j.error);$('saved').textContent='Saved ✓ '+new Date().toLocaleTimeString()}
  catch(e){$('saved').textContent='Save failed: '+e.message}
  header();list();if(redraw)side();else{const ev=$('ev'),r2=rec(S[cur].id);if(ev)ev.classList.toggle('need',DEC()?!!r2.decision&&!r2.reason.trim():r2.confirmed_failure&&!r2.evidence.trim())}}
async function loadTools(id,refresh){if(refresh)delete toolCache[id];if(!toolCache[id]){
  const res=await fetch('/api/tools?id='+encodeURIComponent(id)+(refresh?'&refresh=1':''));toolCache[id]=await res.json()}
  if(S[cur].id===id)conv()}
function needsTools(s){return !!s.result}
function go(i){if(i<0||i>=S.length)return;cur=i;location.hash=S[i].id;list();conv();side();$('conv').scrollTop=0;if(needsTools(S[i]))loadTools(S[i].id)}
document.querySelectorAll('.filters button').forEach(b=>b.onclick=()=>{filter=b.dataset.f;
  document.querySelectorAll('.filters button').forEach(x=>x.classList.toggle('on',x===b));list()});
document.addEventListener('keydown',e=>{const typing=/TEXTAREA|INPUT/.test(document.activeElement.tagName);
  if(e.key==='Escape'&&typing){document.activeElement.blur();return}if(typing||e.metaKey||e.ctrlKey)return;
  const r=rec(S[cur].id),k=e.key.toLowerCase();
  if(k==='j')go(cur+1);else if(k==='k')go(cur-1);
  else if(DEC()){if(k==='a')set({decision:'accept'});else if(k==='r')set({decision:'revise'});else if(k==='x')set({decision:'reject'});
    else if(k==='e'){e.preventDefault();$('ev').focus()}else if(k==='c'){e.preventDefault();$('ch').focus()}}
  else if(k==='v')set(r.scenario_valid===true?{scenario_valid:false,confirmed_failure:false}:{scenario_valid:true});
  else if(k==='f'&&r.scenario_valid===true)set({confirmed_failure:!r.confirmed_failure});
  else if(k==='e'){e.preventDefault();$('ev').focus()}else if(k==='c'){e.preventDefault();$('ch').focus()}});
fetch('/api/data').then(r=>r.json()).then(d=>{S=d.scenarios;R=d.review;C=d.config;
  if(DEC()){const b=document.querySelectorAll('.filters button');b[2].textContent='Revise';b[3].textContent='Reject'}
  const h=location.hash.slice(1),i=S.findIndex(s=>s.id===h);header();go(i>=0?i:0)});
</script></body></html>
"""


if __name__ == "__main__":
    main()
