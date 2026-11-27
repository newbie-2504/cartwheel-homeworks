"""HW4 Part E label suggestions v2: code checks plus the scenario answer key.

Every row is a suggestion, never a label. confidence "high" can be bulk-confirmed after a
glance; "hint" must be decided by the reviewer. Writes analysis/state/label_suggestions.json.
"""
import json
import re
import urllib.request
from datetime import date

BASE = "http://127.0.0.1:8040"


def get(path):
    return json.load(urllib.request.urlopen(BASE + path))


manifest = json.load(open("analysis/state/sample_manifest.json"))
reviewed = list(dict.fromkeys(c for b in manifest["batches"] for c in b["conversation_ids"]))
modes = {m["name"]: m["id"] for m in get("/api/patterns")["modes"] if m["status"] == "accepted"}
keys = {r["id"]: r for r in (json.loads(l) for l in open("scenarios/support_scenarios.jsonl"))}
convs = {}
for cid in reviewed:
    d = get(f"/api/conversation?id={cid}")
    convs[cid] = d.get("conversation", d)

FLAG = ["missing", "not available", "no delivery date", "isn't recorded", "not recorded", "unavailable", "inconsistent",
        "doesn't show", "does not show", "unclear", "can't confirm", "cannot confirm", "no record of", "not listed",
        "appears to be an error", "looks incorrect", "seems incorrect", "data issue", "isn't available", "not provided",
        "doesn't have a delivery date", "no recorded delivery"]
POLICY_WORDS = re.compile(r"\b(\d+\s*-?\s*(day|days|hour|hours|%)|percent|restocking|return window|window|fee|threshold|eligible|eligibility|policy|refund within|processing time|dispute)\b", re.I)
INELIGIBLE = re.compile(r"(not eligible|isn't eligible|ineligible|can(no|')t be (returned|refunded)|cannot be (returned|refunded)|no longer eligible|outside (the|your) (return )?window|window (has )?(closed|passed|expired))", re.I)
ASK = re.compile(r"(provide|share|confirm|tell me|what is|what's|could you|can you|please (send|give)).{0,70}(order (number|id|#)|the reason|refund amount|amount to refund|which order|store name)", re.I)
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]


def turns(c):
    return c.get("turns", [])


def steps(t):
    return [s for s in t.get("steps", []) if s.get("name")]


def replies(c):
    return [t.get("reply") or "" for t in turns(c)]


def d(s):
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None


def row(decision, confidence, evidence):
    return {"decision": decision, "confidence": confidence, "evidence": evidence}


# ---------------------------------------------------------------- escalation (ESC-5), code
def escalation(cid, c, k):
    hits, ok = [], []
    for i, t in enumerate(turns(c), 1):
        for s in steps(t):
            r = s.get("result") or {}
            if s["name"] == "escalate_to_human" and r.get("ok") and r.get("ticket_id") is not None:
                rep = t.get("reply") or ""
                sla = r.get("sla_hours")
                has_t = str(r["ticket_id"]) in rep
                has_s = sla is not None and (f"{sla} hour" in rep or f"{sla}-hour" in rep or (sla == 24 and ("24 hours" in rep or "one day" in rep or "a day" in rep)))
                miss = [x for x, y in ((f"ticket id {r['ticket_id']}", has_t), (f"response time ({sla} h)", has_s)) if not y]
                (hits if miss else ok).append(f"turn {i}: ticket {r['ticket_id']}, sla {sla} h; reply " + ("omits " + " and ".join(miss) if miss else "states both"))
    if hits:
        return row("present", "high", "Code check: " + "; ".join(hits))
    return row("absent", "high", "Code check: " + ("; ".join(ok) if ok else "no escalate_to_human call in the conversation"))


# ---------------------------------------------------------------- policy citation / unsupported (policy part)
def fetched_policies(c):
    ids = []
    for t in turns(c):
        for s in steps(t):
            r = s.get("result") or {}
            if s["name"] in ("get_policy", "get_store_info", "search_help_center") and isinstance(r, dict):
                if r.get("policy_id"):
                    ids.append(str(r["policy_id"]))
                for x in r.get("results") or []:
                    for f in ("policy_id", "id"):
                        if isinstance(x, dict) and x.get(f):
                            ids.append(str(x[f]))
    return list(dict.fromkeys(ids))


def policy_modes(cid, c, k):
    tup = (k or {}).get("tuple") or {}
    app = tup.get("applicable_policy")
    app = None if app in (None, "", "none") else str(app)
    text = " ".join(replies(c))
    fetched = fetched_policies(c)
    cited = [p for p in fetched + ([app] if app else []) if p and p in text]
    states_policy = bool(POLICY_WORDS.search(text))
    if cited:
        cit = row("absent", "high", f"Answer key + trace: reply cites {', '.join(dict.fromkeys(cited))}")
    elif fetched and states_policy:
        cit = row("present", "high", f"Answer key + trace: policy fetched ({', '.join(fetched[:3])}); applicable policy {app or 'n/a'}; reply states policy content without citing it")
    elif fetched:
        cit = row("absent", "hint", f"Policy fetched ({', '.join(fetched[:3])}) but the reply shows no policy-style content; check")
    else:
        cit = row("absent", "high", "No policy source fetched, so an uncited policy claim belongs to unsupported_claim")
    tool_text = json.dumps([s.get("result") for t in turns(c) for s in steps(t)])
    claims = re.findall(r"(\d+(?:\.\d+)?)\s*(?:-|\s)?(business days|days?|hours?|%|percent)\b", text, re.I)
    unbacked = [f"{n} {u}" for n, u in claims if not re.search(rf"(?<![\d.]){re.escape(n)}(?![\d])", tool_text)]
    if not fetched and unbacked:
        uns = row("present", "high", f"No policy or tool source fetched, yet the reply states {', '.join(dict.fromkeys(unbacked))} (no tool result contains these numbers); applicable policy {app or 'n/a'}")
    elif not fetched and re.search(r"restocking|return window|threshold|dispute window|processing time|policy (says|states|allows)", text, re.I):
        uns = row("present", "hint", f"No policy source fetched, but the reply describes policy (applicable policy {app or 'n/a'}); check whether a tool result supports it")
    elif fetched and unbacked:
        uns = row("absent", "hint", f"Policy fetched ({', '.join(fetched[:2])}); the reply also states {', '.join(dict.fromkeys(unbacked))}, which no tool result contains. Check them against the policy text")
    else:
        uns = row("absent", "hint", "No unbacked policy number found; still check non-policy claims (invented processes, timings, promises)")
    return cit, uns


# ---------------------------------------------------------------- damaged record, answer key + code
def broken_in_tools(c):
    for t in turns(c):
        for s in steps(t):
            r = s.get("result") or {}
            orders = [r["order"]] if isinstance(r.get("order"), dict) else [o for o in (r.get("orders") or []) if isinstance(o, dict)]
            for o in orders:
                od, sd, dd = d(o.get("ordered_at")), d(o.get("shipped_at")), d(o.get("delivered_at"))
                if o.get("status") == "delivered" and not dd:
                    return f"order {o.get('order_id')}: delivered but delivered_at null"
                if isinstance(o.get("total_usd"), (int, float)) and o["total_usd"] < 0:
                    return f"order {o.get('order_id')}: negative total"
                if od and sd and (sd < od or (sd - od).days > 180):
                    return f"order {o.get('order_id')}: impossible ship date"
            if s["name"] == "search_products":
                for p in r.get("products") or []:
                    if isinstance(p.get("price"), (int, float)) and p["price"] < 0:
                        return f"product {p.get('product_id')}: negative price"
                    if not (p.get("title") or "").strip():
                        return f"product {p.get('product_id')}: missing title"
    return None


def damaged(cid, c, k):
    k = k or {}
    dq = k.get("data_quality_case_id")
    src = ((k.get("expected") or {}).get("source") or {})
    state = (k.get("tuple") or {}).get("record_state") or ""
    key_broken = dq or src.get("type") == "data_quality_table"
    tool_broken = broken_in_tools(c)
    if not key_broken and not tool_broken:
        return row("absent", "high", f"Answer key: valid record (record_state {state or 'none'}); no broken value in tool output")
    flagged = any(w in r.lower() for r in replies(c) for w in FLAG)
    what = f"data-quality case {dq or src.get('reference')}" if key_broken else tool_broken
    exp = (k.get("expected") or {}).get("outcome")
    if flagged:
        return row("absent", "hint", f"Answer key: {what}; expected '{exp}'. Reply appears to flag it; check the wording")
    ref = str(dq or src.get("reference") or "")
    fits = (not key_broken) or any(w in ref for w in ("missing", "invalid", "negative", "inconsistent", "date"))
    if not fits:
        return row("present", "hint", f"Answer key: {what} (record_state {state}); expected '{exp}'. This data-quality case is not a missing or inconsistent value; decide whether it fits the mode")
    return row("present", "high", f"Answer key: {what} (record_state {state}); expected '{exp}'. No reply tells the user the record is incomplete or inconsistent")


# ---------------------------------------------------------------- misreport, code (presents are hints)
def misreport(cid, c, k):
    hits, seen = [], 0
    for i, t in enumerate(turns(c), 1):
        rep = t.get("reply") or ""
        low = rep.lower()
        for s in steps(t):
            if s["name"] != "get_order":
                continue
            o = (s.get("result") or {}).get("order")
            if not isinstance(o, dict):
                continue
            seen += 1
            st = o.get("status")
            if st == "delivered" and o.get("delivered_at") and re.search(r"(not (yet )?(been )?(marked as )?delivered|hasn't been delivered|in transit|on its way)", low):
                hits.append(f"turn {i}: status delivered but the reply says not delivered")
            if st == "delivered" and not o.get("delivered_at") and re.search(r"(not (yet )?(been )?(marked as )?delivered|hasn't been delivered)", low):
                hits.append(f"turn {i}: status field says delivered but the reply says not delivered (delivered_at null: also check damaged_record)")
            if st == "shipped" and re.search(r"\b(has been|was) delivered", low):
                hits.append(f"turn {i}: status shipped but the reply says delivered")
            if st == "placed" and re.search(r"\b(has|was) (been )?(shipped|delivered)", low) and " not " not in f" {low} ":
                hits.append(f"turn {i}: status placed but the reply says shipped or delivered")
            tot = o.get("total_usd")
            if tot is not None:
                for m in re.finditer(r"order total[^.$]{0,20}\$\s?(\d+(?:\.\d{1,2})?)", low):
                    if abs(float(m.group(1)) - float(tot)) > 0.005:
                        hits.append(f"turn {i}: reply states an order total of ${m.group(1)}; record ${tot}")
    if hits:
        return row("present", "hint", "Code check: " + "; ".join(hits) + ". Confirm the field is valid (else it is damaged_record)")
    if seen:
        return row("absent", "hint", f"Code check: status and stated totals match the {seen} order record(s); dates not checked, so scan them")
    return row("absent", "high", "No single order record was looked up, so there is nothing to misreport")


# ---------------------------------------------------------------- ineligibility, answer key (hint)
def ineligibility(cid, c, k):
    text = " ".join(replies(c))
    m = INELIGIBLE.search(text)
    if not m:
        return row("absent", "high", "The reply never says the order is ineligible or cannot be returned or refunded")
    reason = ((k or {}).get("expected") or {}).get("reason") or ""
    dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", reason)
    windows = re.findall(r"(\d+)-day", reason)
    has_date = any(x in text for x in dates) or any(MONTHS[int(x[5:7]) - 1].capitalize() + " " + str(int(x[8:10])) in text for x in dates)
    has_window = any(re.search(rf"\b{w}[- ]day", text) for w in windows) or bool(re.search(r"\b\d+[- ]day", text))
    if has_date or has_window:
        return row("absent", "hint", f"Reply says ineligible and gives a window or date ({'date' if has_date else 'window'}); answer key reason: {reason[:140]}")
    return row("present", "hint", f"Reply says '{m.group(0)}' but gives no window or date; answer key reason: {reason[:160]}")


# ---------------------------------------------------------------- re-asks, answer key (hint)
def reasks(cid, c, k):
    ts = turns(c)
    asks = [(i, t.get("reply") or "") for i, t in enumerate(ts, 1) if ASK.search(t.get("reply") or "")]
    if not asks:
        return row("absent", "high", "No reply asks the user for an order number, reason, amount or store")
    tup = (k or {}).get("tuple") or {}
    given_text = " ".join((t.get("user") or "") for t in ts[: asks[0][0]])
    oid = tup.get("order_id")
    gave_order = (oid is not None and str(oid) in given_text) or bool(re.search(r"\b\d{4}\b", given_text))
    i, rep = asks[0]
    asked = ASK.search(rep).group(0)
    if gave_order and re.search(r"order (number|id|#)|which order", asked, re.I):
        return row("present", "hint", f"Turn {i} asks '{asked[:80]}', but an earlier user message already contains an order number")
    if tup.get("difficulty") == "missing_information":
        return row("absent", "hint", f"Turn {i} asks '{asked[:80]}'; the scenario is missing_information, so the ask may be legitimate. Check")
    return row("absent", "hint", f"Turn {i} asks '{asked[:80]}'; check whether the user already gave it (reason, amount)")


# ---------------------------------------------------------------- question not answered, answer key (hint)
def not_answered(cid, c, k):
    exp = (k or {}).get("expected") or {}
    outcome, reason = exp.get("outcome") or "", exp.get("reason") or ""
    text = " ".join(replies(c))
    if not outcome.startswith(("states_", "answers_", "gives_", "explains_")):
        return row("absent", "hint", f"Expected outcome '{outcome or exp.get('criterion', '')[:60]}' is an action or handling, not an informational answer; check")
    facts = re.findall(r"\b\d+(?:\.\d+)?%|\$\d+(?:\.\d{2})?|\b\d{4}-\d{2}-\d{2}\b|\b\d+-day\b|\b\d+ days\b", reason)
    found = [f for f in facts if f.replace("-day", " day") in text.replace("-day", " day") or f in text]
    if facts and not found:
        return row("present", "hint", f"Expected '{outcome}'; none of the key facts {facts[:4]} appear in any reply. Could also be unsupported or misreported")
    if facts:
        return row("absent", "hint", f"Expected '{outcome}'; reply contains {found[:3]}")
    return row("absent", "hint", f"Expected '{outcome}'; no checkable key fact; read the reply")


plan = {
    "escalation_reply_missing_ticket_or_sla": escalation,
    "damaged_record_not_flagged": damaged,
    "misreported_order_data": misreport,
    "ineligibility_without_reason": ineligibility,
    "reasks_provided_information": reasks,
    "question_not_answered": not_answered,
}
out = {"generated_at": date.today().isoformat(),
       "method": "code checks over the trace plus the scenario answer key (applicable_policy, record_state, data_quality_case_id, expected outcome and reason). Suggestions, not labels: 'high' rows may be bulk-confirmed after a glance; 'hint' rows need the reviewer's decision.",
       "modes": {}}
rows = {m: {} for m in modes}
for cid, c in convs.items():
    k = keys.get(cid)
    for name, fn in plan.items():
        if name in modes:
            rows[name][cid] = fn(cid, c, k)
    if "policy_claim_without_citation" in modes or "unsupported_claim" in modes:
        cit, uns = policy_modes(cid, c, k)
        if "policy_claim_without_citation" in modes:
            rows["policy_claim_without_citation"][cid] = cit
        if "unsupported_claim" in modes:
            rows["unsupported_claim"][cid] = uns
for name, r in rows.items():
    out["modes"][modes[name]] = {"check": name, "rows": r}
    p_hi = sum(1 for x in r.values() if x["decision"] == "present" and x["confidence"] == "high")
    p_hint = sum(1 for x in r.values() if x["decision"] == "present" and x["confidence"] == "hint")
    a_hi = sum(1 for x in r.values() if x["decision"] == "absent" and x["confidence"] == "high")
    a_hint = sum(1 for x in r.values() if x["decision"] == "absent" and x["confidence"] == "hint")
    print(f"{name:40} P high {p_hi:3} | P hint {p_hint:3} | A high {a_hi:3} | A hint {a_hint:3}")
json.dump(out, open("analysis/state/label_suggestions.json", "w"), indent=1)
