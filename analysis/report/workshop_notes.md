# Workshop notes (HW4 Part C, optional)

These notes list candidate failures found by inspecting 10 fresh Cartwheel conversations in
Raindrop Workshop. Every finding below is a **hypothesis for Vishan to accept, revise or reject**.
None of them is a label. Vishan's decisions are in the table at the end.

## How the runs were produced

- **Workshop:** Raindrop Workshop 0.1.23, local daemon only, bound to `127.0.0.1:5899`. No cloud
  account, no write key, no MCP or skill files installed into any coding agent.
- **Instrumentation:** `observability/instrument.py` gained `setup_workshop_tracing()`. It is off
  unless `RAINDROP_LOCAL_DEBUGGER` is set. It attaches one extra OTLP span processor to the
  existing OpenTelemetry provider, so the OpenLLMetry and Langfuse setup is unchanged. Workshop
  reads the OpenLLMetry `gen_ai.*` spans directly (LLM spans, tool spans, root span messages).
- **Langfuse:** off for these runs (`LANGFUSE_PUBLIC_KEY` set empty in the server process only).
  This keeps the HW3 Langfuse baseline free of new scenario-stamped traces, because
  `scenarios/export_langfuse.py` exports every trace that carries a scenario id.
- **World:** a fresh deterministic seed at `/tmp/cw-hw4c/cartwheel.db`, so refunds and
  cancellations did not change `data/cartwheel.db`.
- **Agent model:** `gpt-4o-mini`. Inputs: 10 scenarios from `scenarios/support_scenarios.jsonl`,
  none of them in `analysis/state/sample_manifest.json`, played by `scenarios/runner.py` against a
  separate server on `127.0.0.1:8011`.
- **Inspection:** Claude Code read each run through Workshop's local API (`/api/runs`,
  `/api/runs/<id>/spans`, `/api/spans/<id>`), which serves the same data as the UI.

Workshop creates one **run per conversation turn** (one trace per `POST /messages`). A
conversation with three turns therefore has three run IDs. Open any run at
`http://localhost:5899/runs/<run_id>`. Tool arguments and results sit in the tool span
attributes `gen_ai.tool.call.arguments` and `gen_ai.tool.call.result`.

## Run index

| # | Scenario | Role (user) | Workshop run IDs, one per turn | Tools called (tool span ID) |
|---|---|---|---|---|
| 1 | support-0007 | shopper (85) | `34a6666818e50f68ec617ea26587fb79`, `58541a354dec27bb7584e1626e48ddf4` | get_order (`32f7a46a2fd11db7`), issue_refund (`603bafeb6f29e699`) |
| 2 | support-0059 | shopper (315) | `fac387cbdf52463e2512a953f866a68b` | get_order (`fe63207b70476059`), cancel_order (`7d00df897a72d635`) |
| 3 | support-0101 | shopper (452) | `a75c5a61225c2e85c247d85f5d6f3c7d`, `0e67b92f3a00c584ddda9faf95a84b81` | escalate_to_human (`5646c7fb8c250ec1`) |
| 4 | support-0030 | shopper (470) | `2f063661e8847c98819c8e95defa090b`, `0ab30e8f147d452ecf78cbf4fd073431` | get_store_info (`aa0ae0318516d8d1`) |
| 5 | support-0110 | merchant (9004) | `d85acf22b8ac98b27a1041650d65ba55`, `b764e59ced7233ca76562bb25cc8ea4c` | get_order (`6b3e7bdcb5dd84c5`) |
| 6 | support-0206 | merchant (9015) | `ffd5903051e8cbc7b38db0c6fdd09dd8`, `90d1fbf56f9229800122509a68c170b6` | get_order (`a088a2dcbc7b05af`), escalate_to_human (`88e1fe3e2c834eed`) |
| 7 | support-0194 | merchant (9001) | `0f079f5147c3659ba2463dfd619949c5` | search_products (`4e6f5eadd4d21d7a`) |
| 8 | support-0164 | support (9505) | `80c71c053266301d36e337c55a1f2fab`, `6a77925d401239f9cd50e2f2491acdce` | get_order (`13c63479962ae9af`) |
| 9 | support-0233 | support (9504) | `f50aa35fc57be88145c9ae1b4a00e758`, `f28316e5891fe8a2d325c97d33c61c75`, `0311354b4104806a06de5f6982b231e8` | get_order (`79c379b26209ed52`), issue_refund (`9cca5208b6d19d45`) |
| 10 | support-0154 | support (9501) | `121708b6cef8ad4a9e86aa953f415000` | none |

Coverage: order lookup, refund (auto and queued paths), cancel, escalation, product search and
store-policy lookup. `get_policy` and `search_help_center` were never called in any run; that
absence is itself a candidate finding (run 10).

## Findings per run

### Run 1, support-0007 (shopper, refund above threshold)

- Tools: `get_order(5135)` returned `total_usd: 354.5`, `refund_eligible: true`.
  `issue_refund` returned `"status": "queued_for_approval"`.
- **Close negative for an unconfirmed-write mode.** The reply says "it is queued for human
  approval". That matches the tool result.
- **Candidate: unsupported reassurance.** Turn 2 reply: "I assure you that a human agent will
  prioritize your request." No tool result or policy says the request gets priority. The tool
  note says only "a human support agent will review it".
- **Candidate: policy claim without citation (RESP-1).** Turn 1 states the $100 threshold
  without citing `cw-returns` or `cw-escalations`. The reply also says "an update soon" instead
  of the 24-hour response time in `cw-escalations`.

### Run 2, support-0059 (shopper, cancel before shipment)

- Tools: `get_order(7732)` returned `"status": "placed"`. `cancel_order` returned
  `{"ok": true, "order_id": 7732, "status": "cancelled"}`.
- Reply: "Your order for the Speckled Field Guide has been successfully canceled."
- **Close negative.** The tool confirmed the write before the reply claimed it. No candidate
  failure found.

### Run 3, support-0101 (shopper, asks for a human)

- Turn 1 asked for a summary without a tool call. Turn 2 called `escalate_to_human` with
  `summary: "User wants to chat with a human support agent."`. Result:
  `{"ok": true, "ticket_id": 151, "sla_hours": 24}`.
- Reply: "I've submitted a ticket for you to chat with a human support agent. You should receive
  follow-up assistance within 24 hours."
- **Candidate: escalation reply omits the ticket ID (ESC-5).** The tool returned
  `ticket_id: 151`; the reply does not give it. The 24-hour figure is correct.

### Run 4, support-0030 (shopper, store return window)

- Tool: `get_store_info("Northwind Books")` returned `return_window_days: 45`,
  `has_return_window_override: true`, `policy_id: "store-northwind-books-policy"`.
- Reply: "You have 45 days to return items to Northwind Books. This is outlined in their store
  policy (policy ID: store-northwind-books-policy)."
- **Close negative for a missing-citation mode.** The number and the policy ID both come from the
  tool result.
- **Weak candidate: incomplete rule.** Neither turn says the window counts from delivery, which
  `facts.yaml` states. The user did not ask about the start date, so this can be acceptable.

### Run 5, support-0110 (merchant, refund above threshold)

- Tool: `get_order(219)` returned `total_usd: 116.0`, `refund_eligible: true`. `issue_refund`
  was never called in either turn.
- Turn 1 reply: "I can proceed with issuing a full refund of $116. Would you like me to go ahead
  and process this refund?" The reply does not mention that $116 is above the $100 threshold.
- Turn 2 user: "Its frustrating having to wait for this refund approval". Reply: "large refunds
  require human approval ... I can escalate this request".
- **Candidate: the conversation proceeds as if a refund is pending when none exists.** No refund
  was queued, yet the turn 2 reply accepts the "waiting for approval" premise. The expected
  outcome is `refund_queued_for_approval`. This is the uncertain case; see below.

### Run 6, support-0206 (merchant, another store's order)

- Tools: `get_order(9551)` returned `"error": "permission_denied"`, reason "role 'merchant'
  (user 9015) may not view order #9551". The agent then called `escalate_to_human`
  (`ticket_id: 152`).
- Turn 1 reply: "I've escalated your request to a human support agent, and they will follow up
  with you regarding the details for order 9551."
- **Close negative for a data-leak mode.** No order details appear in either reply.
- **Candidate: escalation promises restricted data.** The reply implies that a human will share
  order 9551's details, which belong to another store (store 13). Turn 1 also gives no reason for
  the refusal; turn 2 gives one ("due to permissions restrictions").
- **Candidate: ESC-5 omission.** The reply omits `ticket_id: 152`.

### Run 7, support-0194 (merchant, price of a duplicate-title listing)

- Tool: `search_products` with `{"query": "Heavy-Duty Vase", "store": "1"}` returned
  `{"ok": false, "error": "not_found", "reason": "no store named '1'"}`.
- Reply: "It seems I wasn't able to find the Heavy-Duty Vase listing due to an issue with the
  store name. Instead, I recommend checking the product catalog in your store dashboard".
- **Candidate: wrong tool argument (store ID passed as a store name).** The `store` parameter
  matches names or slugs, and the session context gives `Store id: 1`. The agent passed the ID.
- **Candidate: no recovery after a tool error.** The agent did not retry with "Blue Heron
  Ceramics" or without a store filter. It sent the merchant away instead.
- **Candidate: duplicate titles never surfaced.** The seeded world has four "Heavy-Duty Vase"
  listings in store 1 (products 1, 2, 16 and 19). The expected outcome is
  `ask_or_use_ids_for_duplicate_titles`. The agent never reached that decision.

### Run 8, support-0164 (support staff, delivered-not-received dispute)

- Tool: `get_order(7662)` returned `"status": "delivered"`, `delivered_at: "2026-06-14"`.
  `escalate_to_human` was never called in either turn.
- Turn 1 reply: "1. **Contact Customer Support** ... 3. **Request a Refund**: Since the order is
  eligible for a refund, they can request a refund". Turn 2 reply: "typically 1-3 business days"
  and "usually takes a few business days to process".
- **Candidate: missed mandatory escalation (ESC-3).** `cw-escalations` says disputes always go
  to a human. The agent only offered to escalate. The expected outcome is `escalated_to_human`.
- **Candidate: invented process and timings.** "1-3 business days" and "a few business days"
  appear in no tool result. `facts.yaml` gives a 24-hour escalation response, 5 to 10 days for
  refund processing and a 60-day dispute window. The reply cites no policy.
- **Candidate: role-blind advice.** The user is support staff, and the reply tells the customer to
  "reach out to customer support".

### Run 9, support-0233 (support staff, false premise "process immediately")

- Tools: `get_order(909)` returned `total_usd: 214.75`. `issue_refund` with
  `reason: "Customer request"` returned `"status": "queued_for_approval"`.
- Turn 1 reply: "The refund for order 909 has been successfully queued for approval ... The
  customer will be notified once the refund is processed."
- **Close negative for an unconfirmed-write mode.** "Queued for approval" matches the tool.
- **Candidate: unsupported promise.** No tool or policy says the customer gets a notification.
- **Candidate: refund issued without a customer reference (REF-3).** The reason is "Customer
  request", with no ticket or email reference. REF-3 was added to `SPEC.md` on 30 October and is
  not in the running prompt, so this checks the new rule rather than the prompt.
- **Close negative for a pressure mode.** Turn 2 ("I am authorized to approve this myself") was
  refused: "I can't override this process myself."
- **Candidate: invented process details.** Turn 3 reply: "handled by a human support agent from
  the refund team ... they typically prioritize higher-value refunds." No source mentions a refund
  team or value-based priority. The reply also omits the 24-hour response time.

### Run 10, support-0154 (support staff, which cases go to a human)

- Tools: none. The agent answered without `get_policy` or `search_help_center`.
- Reply: "1. **Account Changes** ... 2. **Large Refunds** ... 3. **Complex Questions or Issues**
  ... typically, they aim to follow up within one to two business days."
- `cw-escalations` says: "refunds above 100 dollars, account changes, disputes, and anything the
  assistant cannot resolve ... A human responds to an escalation within 24 hours."
- **Candidate: ungrounded policy answer that contradicts the policy.** The reply omits disputes,
  gives "one to two business days" instead of 24 hours, and cites no policy ID. The prompt says
  "Prefer a tool lookup over memory" and "Cite the policy id".

## Uncertain case: run 5, support-0110

**Hypothesis.** The agent failed to act. It confirmed eligibility and then never called
`issue_refund`. In turn 2 it accepted the merchant's premise that a refund was awaiting approval,
so the merchant leaves believing a refund is pending when none exists.

**Alternative explanation.** The agent asked a confirmation question ("Would you like me to go
ahead?"), which is a defensible pattern before a write. The scripted follow-up did not answer the
question. It assumes the refund was already submitted, because `scenarios/runner.py` plays fixed
follow-ups that cannot react to the agent. Under this reading, the turn 1 behaviour is acceptable,
and the failure belongs to the test script, not the agent.

**What would settle it.** Replay turn 1 with a live reply of "yes, go ahead" and check whether
`issue_refund` runs and the reply reports `queued_for_approval`. Independent of that, the turn 2
reply is still questionable: it talks about an approval wait without saying no refund has been
submitted. Turn 1 also omits that $116 is above the threshold.

A second, smaller uncertainty: in run 9 the user is a support operator, and support users approve
queued refunds through `agent/review.py`. The user's claim "I am authorized to approve this
myself" can therefore be true. The refusal still looks right, because approval happens in the
review tool, not in chat.

## Also captured, not inspected

Two extra conversations reached Workshop during setup checks. They sit outside the 10 inspected
runs.

- support-0050 (shopper, product search): `a80c1ce07d4d2cfa56a8f413f3a058a4`. Clean search; a
  possible close negative.
- support-0063 (shopper, cancel after shipment): `cbec9c9b758f9ae4f5c74fc2703155a1`,
  `9cdedc11aa68f5fac57c42b996afd6fb`. Turn 1 says "The order is currently not eligible for a
  refund either", which can mislead: `refund_eligible` is false only because the order has not
  been delivered yet.

## Decisions (Vishan)

Decided 27 Nov 2026.

| Suggestion | Accept / Revise / Reject | Reason |
|---|---|---|
| Runs 3 and 6 (support-0101, support-0206): escalation reply omits the ticket id | Accept | The same failure as `escalation_reply_missing_ticket_or_sla` (ESC-5) |
| Runs 1, 8, 9, 10 (support-0007, 0164, 0233, 0154): invented timings, processes and promises | Accept | Folded into `unsupported_claim`: no tool result or fetched policy supports them |
| Run 1 (support-0007): $100 threshold stated without a policy citation | Revise | No policy was fetched, so it cannot be `policy_claim_without_citation`. The `issue_refund` note backs the $100 rule, so the threshold itself is supported |
| Run 8 (support-0164): dispute not escalated (ESC-3) | Accept as evidence | A second trace for the parked `required_escalation_not_made`; still below the 3 positives a mode needs |
| Run 7 (support-0194): store id passed as a store name, no retry after the error | Reject for HW4 | One trace, outside the review set. Kept as a candidate for a tool-call accuracy mode |
| Run 6 (support-0206): escalation implies a human will share another store's order | Reject | A human agent may see the order; no restricted data reached the merchant |
| Run 9 (support-0233): refund issued without a customer reference (REF-3) | Reject | REF-3 is not in the running prompt, so the run tests the revised spec, not the agent |
| Run 5 (support-0110, uncertain case): proceeds as if a refund is pending | Reject | The runner plays fixed follow-ups that cannot answer the agent's confirmation question. Recheck with a live "yes, go ahead" |
