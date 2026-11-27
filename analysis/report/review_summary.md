# Homework 4 review summary

This summary reports the reviewed sample, the final taxonomy of 7 binary failure modes, and the labels behind each mode. It also covers the taxonomy revisions, including the 27 Nov rejection of `misreported_order_data`, both search rounds, the `SPEC.md` revisions and the saturation check.

Sources: `analysis/state/sample_manifest.json`, `patterns.json`, `annotations.json`, `suggestions.json`, `label_suggestions.json`, `labels/`, and the review app API (`/api/progress`, `/api/conversations`, `/api/conversation`), as they stood on 27 Nov 2026 after the reviewer's final recheck decisions. Quoted notes have their typos corrected. Reviewer comments in Section 8 are verbatim.

## 1. Sample size and composition

I reviewed **104 distinct conversations**. **100** sit in the four handout batches and form the review set. The other **4** form a convenience batch, `exploration_0` (support-0001 to support-0004). I report it separately and did not label it. No conversation appears in two batches.

The unit of review is the conversation. Cartwheel writes one Langfuse trace per user turn. The review app therefore groups traces by `cartwheel.session_id` in time order. The app loaded 419 support traces from Langfuse (cache of 28 Oct) and built 250 conversations.

Review outcome: 95 conversations carry at least one failure note, and 9 carry "no failure observed". The 116 failure notes split into 104 I wrote and 12 from accepted search suggestions.

### Batch summary

| Batch | Handout batch | Method | Seed and draw | Drawn | Size |
|---|---|---|---|---|---|
| `uniform_1` | 1a | Uniform random | `random.Random(20261028).sample` over all 250 conversations | 28 Oct | 15 |
| `cluster_1` | 1b | Cluster representatives | k-means, k=15, seed 20261028, on structure only; the conversation nearest each centre; `uniform_1` excluded | 28 Oct | 15 |
| `difficulty_2` | 2 | Dimension-targeted, stratified random | 6 per `difficulty` value, `random.Random(20261030).sample` within each value; batch 1 and `exploration_0` excluded | 30 Oct | 30 |
| `depth_3` | 3 | Depth search with deterministic signals, plus close negatives | `random.Random(20261031)` within each search's result list; all earlier batches excluded | 31 Oct | 25 |
| `uniform_4` | 4 (final 15) | Uniform random, saturation check | `random.Random(20261031).sample` of 15 from conversations outside every earlier batch | 31 Oct | 15 |
| `exploration_0` | none | Convenience | The first four conversations in the list; reviewed 28 Oct, recorded 30 Oct | 30 Oct | 4 |

The `cluster_1` features are turn count, total tool calls, calls per tool (10 tools), log reply words and role. No outcome entered the clustering. I chose `difficulty` as the batch 2 dimension on 28 Oct, before any review.

### Composition by role and difficulty

| Batch | Size | shopper | merchant | support | well_specified | ambiguous | missing_information | boundary | false_premise |
|---|---|---|---|---|---|---|---|---|---|
| `uniform_1` | 15 | 8 | 3 | 4 | 11 | 1 | 3 | 0 | 0 |
| `cluster_1` | 15 | 9 | 3 | 3 | 7 | 1 | 2 | 3 | 2 |
| `difficulty_2` | 30 | 17 | 3 | 10 | 6 | 6 | 6 | 6 | 6 |
| `depth_3` | 25 | 16 | 2 | 7 | 17 | 3 | 3 | 2 | 0 |
| `uniform_4` | 15 | 12 | 2 | 1 | 10 | 3 | 1 | 1 | 0 |
| **Review set** | **100** | **62** | **13** | **25** | **51** | **14** | **15** | **12** | **8** |
| `exploration_0` | 4 | 4 | 0 | 0 | 4 | 0 | 0 | 0 | 0 |
| All conversations | 250 | 143 | 57 | 50 | 163 | 37 | 17 | 19 | 14 |

The sample does not mirror the store. It covers 15 of 17 `missing_information` conversations but only 13 of 57 merchant conversations. Batch 2 gave each difficulty value 6 conversations, which over-samples the rare values. No batch stratified by role.

### Per-conversation detail

The last column lists the final modes labelled present in Part E. Codes: CIT `policy_claim_without_citation`, INEL `ineligibility_without_reason`, UNS `unsupported_claim`, ESC `escalation_reply_missing_ticket_or_sla`, DMG `damaged_record_not_flagged`, REASK `reasks_provided_information`, NOANS `question_not_answered`.

#### `uniform_1`

| Conversation | Role | Difficulty | Intent | Notes | Modes present |
|---|---|---|---|---|---|
| support-0010 | shopper | well_specified | refund | 4 notes | UNS |
| support-0012 | shopper | well_specified | refund | 4 notes | INEL, UNS, ESC |
| support-0037 | shopper | well_specified | order_status | 2 notes | not labelled |
| support-0055 | shopper | well_specified | product_search | 1 note | none |
| support-0128 | merchant | well_specified | policy_question | 1 note | CIT |
| support-0139 | merchant | well_specified | product_search | 2 notes | none |
| support-0143 | merchant | missing_information | human_handoff | 2 notes | UNS, ESC |
| support-0149 | support | well_specified | order_status | 1 note | INEL |
| support-0150 | support | well_specified | order_status | 1 note | none |
| support-0159 | support | well_specified | policy_question | 1 note | none |
| support-0176 | shopper | missing_information | return_deadline | 5 notes | UNS, DMG, NOANS |
| support-0177 | shopper | missing_information | refund | 2 notes | INEL, DMG |
| support-0186 | shopper | well_specified | refund | 1 note | INEL, UNS, DMG |
| support-0240 | shopper | ambiguous | order_status | 2 notes; retried session, latest shown | none |
| support-0249 | support | well_specified | refund | 1 note | INEL |

#### `cluster_1`

| Conversation | Role | Difficulty | Intent | Notes | Modes present |
|---|---|---|---|---|---|
| support-0053 | shopper | ambiguous | product_search | 1 note | none |
| support-0225 | shopper | boundary | refund | 1 note | UNS |
| support-0227 | support | boundary | refund | 1 note | none |
| support-0199 | merchant | well_specified | product_search | 1 note | DMG |
| support-0236 | support | false_premise | dispute | 1 note | UNS, NOANS |
| support-0111 | merchant | well_specified | refund | 1 note | INEL, UNS, ESC, NOANS |
| support-0032 | shopper | well_specified | policy_question | 1 note | CIT |
| support-0210 | merchant | false_premise | order_status | 1 note | none |
| support-0057 | shopper | well_specified | cancellation | 1 note | UNS |
| support-0219 | shopper | boundary | return_deadline | 1 note | CIT, INEL |
| support-0025 | shopper | well_specified | policy_question | 1 note | none |
| support-0165 | support | well_specified | dispute | 1 note | INEL, UNS |
| support-0027 | shopper | well_specified | policy_question | 1 note | UNS |
| support-0102 | shopper | missing_information | human_handoff | 1 note | ESC |
| support-0244 | shopper | missing_information | order_status | 1 note | UNS |

#### `difficulty_2`

| Conversation | Role | Difficulty | Intent | Notes | Modes present |
|---|---|---|---|---|---|
| support-0026 | shopper | well_specified | policy_question | 1 note | UNS |
| support-0038 | shopper | well_specified | order_status | 1 note | UNS |
| support-0126 | merchant | well_specified | policy_question | 1 note | UNS, NOANS |
| support-0142 | merchant | well_specified | account_change | 1 note | UNS, ESC |
| support-0171 | support | well_specified | account_change | 1 note | ESC |
| support-0175 | support | well_specified | store_info | 1 note | CIT |
| support-0016 | shopper | ambiguous | refund | 2 notes | REASK |
| support-0084 | shopper | ambiguous | return_deadline | 1 note | none |
| support-0191 | shopper | ambiguous | product_search | no failure observed | DMG |
| support-0193 | shopper | ambiguous | product_search | 1 note | DMG |
| support-0201 | shopper | ambiguous | product_search | 1 note | DMG |
| support-0242 | support | ambiguous | return_deadline | 1 note | none |
| support-0100 | shopper | missing_information | human_handoff | 1 note | none |
| support-0103 | shopper | missing_information | human_handoff | 1 note | ESC |
| support-0174 | support | missing_information | human_handoff | 1 note | UNS, ESC |
| support-0178 | shopper | missing_information | order_status | 1 note | UNS, DMG |
| support-0179 | merchant | missing_information | return_deadline | 1 note | INEL, DMG |
| support-0245 | support | missing_information | store_info | no failure observed | none |
| support-0066 | shopper | boundary | order_history | 1 note | UNS, NOANS |
| support-0216 | shopper | boundary | refund | 1 note | UNS |
| support-0217 | shopper | boundary | return_deadline | 1 note | INEL, UNS, NOANS |
| support-0221 | support | boundary | return_deadline | 1 note | CIT |
| support-0223 | support | boundary | return_deadline | 1 note | CIT, INEL |
| support-0228 | support | boundary | refund | 1 note | REASK |
| support-0196 | shopper | false_premise | product_search | 1 note | DMG |
| support-0200 | support | false_premise | product_search | 1 note | DMG |
| support-0214 | shopper | false_premise | refund | 1 note | none |
| support-0234 | shopper | false_premise | policy_question | 1 note | CIT |
| support-0247 | shopper | false_premise | refund | 1 note | INEL, ESC |
| support-0248 | support | false_premise | refund | 1 note | none |

#### `depth_3`

Each search over a draft mode returned positives (the signal fires) and close negatives (same situation, no signal). The signals are retrieval hints, not labels. The 15 signal positives became agent suggestions (Section 8).

| Conversation | Role | Difficulty | Intent | Search: draft mode, role | Notes | Modes present |
|---|---|---|---|---|---|---|
| support-0093 | shopper | well_specified | account_change | `escalation_reply_missing_ticket_or_sla`, positive | 1 note | ESC |
| support-0014 | shopper | well_specified | refund | `escalation_reply_missing_ticket_or_sla`, positive | 1 note | INEL, UNS, ESC |
| support-0224 | shopper | boundary | refund | `escalation_reply_missing_ticket_or_sla`, close negative | 2 notes | REASK |
| support-0073 | shopper | ambiguous | return_deadline | `policy_claim_without_citation`, positive | 1 note | CIT |
| support-0088 | shopper | well_specified | store_info | `policy_claim_without_citation`, positive | 1 note | CIT |
| support-0031 | shopper | well_specified | policy_question | `policy_claim_without_citation`, close negative | no failure observed | none |
| support-0180 | support | missing_information | return_deadline | `damaged_record_not_flagged`, positive | 1 note | INEL, DMG |
| support-0147 | support | well_specified | refund | `support_caller_treated_as_customer`, positive | 1 note | none |
| support-0156 | support | well_specified | policy_question | `support_caller_treated_as_customer`, positive | 1 note | none |
| support-0157 | support | well_specified | policy_question | `support_caller_treated_as_customer`, close negative | no failure observed | none |
| support-0173 | support | well_specified | out_of_scope | `support_caller_treated_as_customer`, close negative | no failure observed | none |
| support-0022 | shopper | well_specified | policy_question | `reasks_provided_information`, close negative | 2 notes | UNS |
| support-0013 | shopper | well_specified | refund | `unneeded_or_duplicate_escalation`, close negative | 2 notes | INEL, ESC |
| support-0243 | shopper | missing_information | refund | `refund_without_request_or_return_check`, close negative | 1 note | not labelled |
| support-0023 | shopper | well_specified | policy_question | `unsupported_claim`, positive | 1 note | UNS |
| support-0024 | shopper | well_specified | policy_question | `unsupported_claim`, positive | 1 note | UNS |
| support-0029 | shopper | well_specified | policy_question | `unsupported_claim`, close negative | 1 note | CIT |
| support-0239 | shopper | ambiguous | return_deadline | `ineligibility_without_reason`, positive | 1 note | UNS |
| support-0183 | shopper | ambiguous | return_deadline | `ineligibility_without_reason`, positive | 1 note | INEL, DMG |
| support-0112 | merchant | well_specified | refund | `ineligibility_without_reason`, close negative | 1 note | INEL, UNS, ESC |
| support-0160 | support | well_specified | cancellation | `misreported_order_data`, positive | 1 note | UNS |
| support-0246 | merchant | missing_information | cancellation | `misreported_order_data`, positive | 1 note | none |
| support-0161 | support | well_specified | cancellation | `misreported_order_data`, close negative | no failure observed | none (4 of 7 modes labelled) |
| support-0220 | shopper | boundary | refund | `escalation_reply_missing_ticket_or_sla`, positive | 1 note | INEL, UNS, ESC |
| support-0083 | shopper | well_specified | return_deadline | `policy_claim_without_citation`, positive | 1 note | CIT |

The searches ran under the draft name `next_steps_missing_after_action`, now `escalation_reply_missing_ticket_or_sla`. The `misreported_order_data` search targeted a mode I rejected on 27 Nov (Section 7.2).

#### `uniform_4` (the final 15)

| Conversation | Role | Difficulty | Intent | Notes | Modes present |
|---|---|---|---|---|---|
| support-0018 | shopper | missing_information | refund | 1 note | REASK |
| support-0020 | shopper | well_specified | policy_question | 1 note | UNS |
| support-0039 | shopper | well_specified | order_status | 1 note | UNS |
| support-0048 | shopper | well_specified | product_search | no failure observed | none |
| support-0064 | shopper | ambiguous | cancellation | 1 note | UNS |
| support-0079 | shopper | ambiguous | return_deadline | 1 note | UNS, NOANS |
| support-0082 | shopper | well_specified | return_deadline | 1 note | UNS |
| support-0090 | shopper | well_specified | store_info | 1 note | none |
| support-0092 | shopper | well_specified | account_change | 1 note | UNS |
| support-0113 | merchant | well_specified | order_status | 1 note | INEL |
| support-0133 | merchant | well_specified | payout_question | no failure observed | none |
| support-0170 | support | well_specified | product_search | no failure observed | none |
| support-0192 | shopper | ambiguous | product_search | 1 note | none |
| support-0213 | shopper | well_specified | order_status | 1 note | NOANS |
| support-0226 | shopper | boundary | return_deadline | 1 note | INEL, UNS |

#### `exploration_0` (reported separately, not labelled)

| Conversation | Role | Difficulty | Intent | Notes |
|---|---|---|---|---|
| support-0001 | shopper | well_specified | refund | 1 note |
| support-0002 | shopper | well_specified | refund | 3 notes |
| support-0003 | shopper | well_specified | refund | 1 note |
| support-0004 | shopper | well_specified | refund | 1 note |

## 2. Labelling coverage

I labelled **98 of the 100** review-set conversations. **97** carry a judgement for all 7 final modes.

- **support-0037** (`uniform_1`) and **support-0243** (`depth_3`) were reviewed and carry notes, but have no labels.
- **support-0161** (`depth_3`) is labelled for 4 of 7 modes: `policy_claim_without_citation`, `ineligibility_without_reason`, `escalation_reply_missing_ticket_or_sla` and `damaged_record_not_flagged`. All four are absent. `unsupported_claim`, `reasks_provided_information` and `question_not_answered` are blank.
- `exploration_0` carries no labels.

The 7 final modes hold **683 judgements**: 98 rows for 4 modes and 97 rows for the other 3. The review set needs 700 (100 × 7), so 17 cells are blank. The app's progress view counts 728 cells, because it includes `exploration_0` (104 × 7). The label file for the rejected `misreported_order_data` holds 97 more rows, 780 in all. Those rows stay as a record and sit outside the final taxonomy.

Labelling ran on two days, and rechecks followed on 4 Nov and 27 Nov. In the 7 final modes, 23 judgements carry a 31 Oct timestamp, on support-0010, 0012, 0013 and 0014. 642 carry a 3 Nov timestamp, between 19:57 and 21:53 GMT. 6 carry a 4 Nov timestamp: 5 changed decisions and 1 rewritten evidence. 12 carry a 27 Nov timestamp, all changed decisions (Section 8.2). The app keeps the old timestamp when I confirm a label unchanged.

**Langfuse.** Langfuse holds **780 label scores**, one per labelled conversation and mode across all 8 label files. Score IDs are deterministic, `hw4-label-<mode>-<conversation>`, so a rewrite updates the same score. The app wrote all 780 on 3 Nov at 22:16 GMT. It rewrote the 8 scores the first recheck touched on 4 Nov at 07:30 GMT. It rewrote 12 more on 27 Nov, at 11:24 and 11:41 GMT, one per changed label in the 7 final modes. Each score sits on the conversation's primary trace. Its name is the mode, its value is 1 (present) or 0 (absent), and its comment is the evidence. The 683 scores for the 7 final modes are current, and every one of their label rows records `langfuse_written: true`.

The 97 `misreported_order_data` scores stay from before the rejection, with their values as of 4 Nov. Three of them, support-0179, 0180 and 0216, still read 1. Their local labels now read absent and record `langfuse_written: false`. Homework 5 uses the 7 accepted modes only. Langfuse's `meta.totalItems` also counts unmerged versions of upserted scores, so it reads above 780. The score list is the authority: 780 unique IDs.

The local copy sits in `analysis/state/labels/`, one file per mode. `labels/unsupported_policy_claim.jsonl` is course demo data and belongs to no mode here.

## 3. Final taxonomy: the 7 modes

`patterns.json` holds 13 modes: 7 accepted and 6 rejected. The coding agent proposed all 13. I accepted or rejected each one in the Taxonomy tab. The sixth rejection, `misreported_order_data`, came on 27 Nov (Section 7.2).

`patterns.json` stores the positive and close-negative conversation IDs for each accepted mode. On 27 Nov I refreshed the positive lists from the labels, so `positive_conversation_ids` matches the conversations I labelled present. `close_negative_conversation_ids` holds 3 conversations per mode, 21 in total, and each one is labelled absent. The coding agent proposed them after reading each trace in the app. I confirmed all 21 on 4 Nov. On 27 Nov I confirmed 20 unchanged and replaced 1: support-0242 took the place of support-0220 in the ineligibility list, because support-0220 became positive.

Definitions and boundaries are quoted from `patterns.json` as stored on 27 Nov. No accepted mode carries a "Draft" boundary. On 4 Nov I finalised the three that did: `ineligibility_without_reason`, `reasks_provided_information` and `question_not_answered`. On 27 Nov I revised four boundaries to send contradicted values to `unsupported_claim`, and I tightened the ineligibility boundary to require both the window and the dates.

### 3.1 `policy_claim_without_citation`

- **Definition:** "The reply states a policy fact (return window, fee, refund threshold, dispute window, refund timing, eligibility rule) without naming the policy id it comes from."
- **Boundary:** "Present only when a policy was fetched in the conversation (get_policy, get_store_info with a policy_id, or search_help_center results) and the reply states a fact from it without its policy id. If no policy source was fetched at all, the claim is unsupported_claim, not this mode."
- **Nearest mode:** `unsupported_claim`. **Evaluator:** code check. **Requirement source:** RESP-1.
- **Originating annotations:** 9 notes in 9 conversations. Examples: ann-9b24df533c (support-0128, "cite policy id") and ann-ee0290d599 (support-0032, "policy not cited"). Two of the six review-set origins are positive: support-0032 and 0128. support-0010, 0025, 0176 and 0225 are absent. support-0010 fetched no policy, so its claim is `unsupported_claim` (Section 8.2). support-0176 fetched none either: its `get_store_info` call returned `policy_id: null`. support-0001 to 0003 sit in `exploration_0`.
- **Confirmed positives (11):** support-0029, 0032, 0073, 0083, 0088, 0128, 0175, 0219, 0221, 0223, 0234.
- **Close negatives (confirmed 4 Nov and 27 Nov):** support-0031 (`get_store_info` returned the store policy id; the reply cites it). support-0157 (`get_policy` fetched `cw-refunds`, and the reply cites it). support-0159 (`search_help_center` returned `cw-cancellations`, and the reply cites it).

### 3.2 `ineligibility_without_reason`

- **Definition:** "The reply says an order cannot be refunded or returned without stating why: which window applies and which dates put the order outside it."
- **Boundary:** "Present when the reply says the order cannot be refunded or returned without stating both the window that applies and the dates that put the order outside it. Restating the record flag ('marked as not eligible', 'non-refundable') is not a reason. A reason given without a policy id is policy_claim_without_citation when the policy was fetched, otherwise unsupported_claim. A reason that contradicts the tool results is unsupported_claim."
- **Nearest mode:** `policy_claim_without_citation`. **Evaluator:** LLM judge. **Requirement source:** RESP-5.
- **Originating annotations:** 6 notes in 6 conversations. Examples: ann-ddfb80c4ee (support-0012, "explain to the user in one turn why it is not eligible") and ann-2eccbc8d33 (support-0219, "explain based on policy why it is not eligible"). All 6 are positive.
- **Confirmed positives (20):** support-0012, 0013, 0014, 0111, 0112, 0113, 0149, 0165, 0177, 0179, 0180, 0183, 0186, 0217, 0219, 0220, 0223, 0226, 0247, 0249.
- **Close negatives (revised 27 Nov):** support-0239 (rejected suggestion; window and dates come before "not eligible"). support-0082 (window and dates given; the wrong conclusion is an unsupported claim). support-0242 (turn 3 says order 9884 "is marked as not eligible for a refund", after turn 1 stated the 30-day window, the April 1 delivery date and the May 1 last day for the same order). support-0220 left the list on 27 Nov, when it became positive.
- **Reason given earlier in the conversation:** a reason stated earlier in the conversation, for the same order, counts. support-0242 follows the same logic as the rejected support-0239 suggestion: the reply had already given the reason. support-0220 fails the rule: turn 1 says "longer than the typical return window" and never states the 21-day window.

### 3.3 `unsupported_claim`

- **Definition:** "The reply states a fact, rule, process or promise that no tool result or fetched policy in the conversation supports."
- **Boundary:** "Present when no tool result or fetched policy in the conversation supports the stated fact, rule, process or promise. If the supporting policy was fetched but its id is not cited, use policy_claim_without_citation instead. This includes a value that contradicts a valid order record. If the record itself is broken and the reply does not flag it, use damaged_record_not_flagged."
- **Nearest mode:** `damaged_record_not_flagged`. **Evaluator:** LLM judge. **Requirement source:** RESP-3.
- **Originating annotations:** 6 notes in 6 conversations. Examples: ann-14c5ed78b3 (support-0010, "completely made up fact?") and ann-aa2385bd78 (support-0244, "not grounded response"). Four of the five labelled origins are positive: support-0010, 0012, 0176 and 0244. support-0240 is absent, and support-0037 is not labelled.
- **Confirmed positives (36):** support-0010, 0012, 0014, 0020, 0022, 0023, 0024, 0026, 0027, 0038, 0039, 0057, 0064, 0066, 0079, 0082, 0092, 0111, 0112, 0126, 0142, 0143, 0160, 0165, 0174, 0176, 0178, 0186, 0216, 0217, 0220, 0225, 0226, 0236, 0239, 0244.
- **Close negatives (confirmed 4 Nov and 27 Nov):** support-0234 (window and fee match the fetched store policy). support-0088 (the 21-day window matches `get_store_info`). support-0133 (payout facts match the fetched `cw-payouts`).

### 3.4 `escalation_reply_missing_ticket_or_sla`

- **Definition:** "After escalate_to_human succeeds, the reply omits the ticket_id or the response time from sla_hours."
- **Boundary:** "Fails when the reply after a successful escalation leaves out the ticket id or the sla_hours response time. A stated response time or channel that differs from the tool result is unsupported_claim. No escalation in the conversation means absent."
- **Nearest mode:** `unsupported_claim`. **Evaluator:** code check. **Requirement source:** ESC-5 (SPEC revision, 30 Oct).
- **Originating annotations:** 7 notes in 7 conversations. Examples: ann-6859f5d4be (support-0012, "no ticket id") and ann-9ef1e4db5e (support-0027, "response SLA missing"). support-0012, 0102 and 0143 are positive. support-0010, 0027, 0057 and 0225 are absent, because none of them calls `escalate_to_human`.
- **Confirmed positives (14):** support-0012, 0013, 0014, 0093, 0102, 0103, 0111, 0112, 0142, 0143, 0171, 0174, 0220, 0247.
- **Close negatives (confirmed 4 Nov and 27 Nov):** support-0100 (ticket 157 and 24 hours stated). support-0224 (ticket 170 and 24 hours stated). Only these two conversations escalate and state both values. The third close negative is a look-alike: support-0010 queues a refund for human review but never calls `escalate_to_human`.

### 3.5 `damaged_record_not_flagged`

- **Definition:** "The reply repeats, reasons from, or substitutes another field for an order or product record that is missing a required value or is internally inconsistent (for example a null delivery date on a delivered order, a negative price, or a ship date long after the order date), without telling the user the record is incomplete or inconsistent."
- **Boundary:** "The record itself is broken and the reply does not flag it. If the reply contradicts a valid field, that is unsupported_claim; a conversation can carry both when both happen. A reply that flags the missing or inconsistent value passes."
- **Nearest mode:** `unsupported_claim`. **Evaluator:** code check. **Requirement source:** RESP-3.
- **Originating annotations:** 4 notes in 4 conversations. Examples: ann-2144db2df5 (support-0199, "negative price should not be shown") and ann-54dcc8222e (support-0179, "delivery date is missing"). All 4 are positive.
- **Confirmed positives (13):** support-0176, 0177, 0178, 0179, 0180, 0183, 0186, 0191, 0193, 0196, 0199, 0200, 0201. All 13 are answer-key data-quality cases.
- **Close negatives (confirmed 4 Nov and 27 Nov):** support-0192 (duplicate titles; the reply lists all five and asks which). support-0150 and support-0038 (look-alikes: a null delivery date on a shipped order is valid, and neither reply invents one). Only support-0192 is a data-quality case labelled absent.

### 3.6 `reasks_provided_information`

- **Definition:** "The reply asks the user for information the user already gave earlier in the conversation, or that a tool result in the trace already contains."
- **Boundary:** "Present when the reply asks for information the user already gave or a tool result already holds. Asking for information that is genuinely missing passes, and so does confirming an ambiguous match (for example, several orders fit the description)."
- **Nearest mode:** `question_not_answered`. **Evaluator:** LLM judge. **Requirement source:** RESP-5.
- **Originating annotations:** 3 notes in 2 conversations. Examples: ann-a5f3f39304 (support-0016, the amount and reason were already given) and ann-04446fc6ab (support-0228, "reason already there in the first turn"). The third note, ann-a47852c1d6 on support-0016, concerns tone. Both conversations are positive.
- **Confirmed positives (4):** support-0016, 0018, 0224, 0228.
- **Close negatives (confirmed 4 Nov and 27 Nov):** support-0246 (asks for the order ID the user never gave). support-0100 (asks once for the issue, then escalates). support-0248 (asks for the refund reason the user never gave).

### 3.7 `question_not_answered`

- **Definition:** "The reply does not answer the question the user asked: it answers a different question, or gives related information without the answer."
- **Boundary:** "Present when the reply leaves the user's question unanswered: it answers a different question, or gives related information without the answer. A partial answer that addresses the core question passes. An answer that is given but wrong is unsupported_claim."
- **Nearest mode:** `reasks_provided_information`. **Evaluator:** LLM judge. **Requirement source:** RESP-5.
- **Originating annotations:** 3 notes in 3 conversations. Examples: ann-0d7e1d2399 (support-0126, "intent not fulfilled") and ann-a49908212f (support-0242, "user did not get the answer first"). support-0126 is positive. support-0179 and 0242 are absent. The support-0179 note also supports `damaged_record_not_flagged`. support-0242 answers each return-date question with a date (May 1, then April 21).
- **Confirmed positives (8):** support-0066, 0079, 0111, 0126, 0176, 0213, 0217, 0236.
- **Close negatives (confirmed 4 Nov and 27 Nov):** support-0083 (exact return deadline given). support-0090 (restocking fee question answered). support-0149 (status and all three dates given).

## 4. Sample fractions per mode

These are **sample fractions**, not prevalence estimates. The full-sample column covers every labelled review-set conversation. The random column covers `uniform_1` plus `uniform_4` only: 29 labelled conversations, because support-0037 is not labelled.

| Mode | Present | Absent | n | Sample fraction | Random batches: present / n | Random-batch sample fraction |
|---|---|---|---|---|---|---|
| `policy_claim_without_citation` | 11 | 87 | 98 | 11.2% | 1 / 29 | 3.4% |
| `ineligibility_without_reason` | 20 | 78 | 98 | 20.4% | 7 / 29 | 24.1% |
| `unsupported_claim` | 36 | 61 | 97 | 37.1% | 12 / 29 | 41.4% |
| `escalation_reply_missing_ticket_or_sla` | 14 | 84 | 98 | 14.3% | 2 / 29 | 6.9% |
| `damaged_record_not_flagged` | 13 | 85 | 98 | 13.3% | 3 / 29 | 10.3% |
| `reasks_provided_information` | 4 | 93 | 97 | 4.1% | 1 / 29 | 3.4% |
| `question_not_answered` | 8 | 89 | 97 | 8.2% | 3 / 29 | 10.3% |

**Why the full sample is skewed.** Three batches changed its composition on purpose. Difficulty stratification in `difficulty_2` gave each difficulty value 6 conversations, so the rare values weigh far more than in the store. The review set ends up holding 15 of the store's 17 `missing_information` conversations. `difficulty_2` alone supplies 7 of the 13 damaged-record positives. Depth searches in `depth_3` drew conversations where a signal fired. They supply 5 of the 14 escalation positives and 4 of the 11 citation positives. In the random batches, the escalation fraction drops from 14.3% to 6.9%, and the citation fraction from 11.2% to 3.4%. Cluster representatives in `cluster_1` take one conversation per structural cluster, so rare tool patterns weigh as much as common ones.

The random column is small. One conversation moves it by 3.4 points, so it is no estimate either. The 27 Nov recheck cut the random citation count from 3 to 1 (support-0020 and 0176) and the random non-answer count from 5 to 3 (support-0039 and 0113). Prevalence estimates come in Homework 5, on the complete Module 1 trace store, and in Homework 7.

## 5. Readiness for Homework 5

Homework 5 needs at least 30 Pass (absent) and 30 Fail (present) labels per mode. It uses the 7 accepted modes only.

| Mode | Pass (absent) | Fail (present) | Fail labels short of 30 | Synthetic scenarios needed |
|---|---|---|---|---|
| `policy_claim_without_citation` | 87 | 11 | 19 | yes |
| `ineligibility_without_reason` | 78 | 20 | 10 | yes |
| `unsupported_claim` | 61 | 36 | 0 | no |
| `escalation_reply_missing_ticket_or_sla` | 84 | 14 | 16 | yes |
| `damaged_record_not_flagged` | 85 | 13 | 17 | yes |
| `reasks_provided_information` | 93 | 4 | 26 | yes |
| `question_not_answered` | 89 | 8 | 22 | yes |

Every mode clears 30 Pass labels. Only `unsupported_claim` clears 30 Fail labels. The other 6 modes need synthetic scenarios that target the failure, 110 Fail labels in total. On 4 Nov, 7 of the then 8 modes needed 131 Fail labels. Rejecting `misreported_order_data` removed its 26. The 27 Nov recheck added 5 net: 2 for citation, 1 for re-asks and 4 for non-answers, less 2 for ineligibility. The largest gaps are `reasks_provided_information` (26) and `question_not_answered` (22).

## 6. New modes in the final 15 (`uniform_4`): 1

One of the final 15 conversations showed a consequential failure that no final mode covers. The count records what I saw, not what I kept. It holds under the 7-mode taxonomy. No final-15 conversation carried the rejected misreport. Each 27 Nov change there (support-0020, 0039 and 0113) left the conversation with another final mode.

**support-0092** (shopper, `account_change`, well_specified). The user asks to change the account email. In both turns the agent offers a ticket but never calls `escalate_to_human`. ESC-2 sends account changes of any kind to a human. My note reads "no human escalation here?".

I recorded it as the parked candidate **`required_escalation_not_made`**: a required account-change escalation (ESC-2) was never made. I did not add it, because one trace supports it and each final mode needs 3 positives. Workshop run 8 (support-0164) is a second hint. There the agent only offered to escalate a dispute (ESC-3). That run sits outside the reviewed sample, and Workshop findings are hypotheses, not labels. The final labels mark support-0092 present only for `unsupported_claim`, for the missing `cw-account-security` source.

The app's saturation check reports 0 modes created after `uniform_4` began. That agrees with the count of 1, because I parked the candidate instead of adding it.

The other 14 conversations in the final 15:

| Conversation | My note (shortened) | Modes present |
|---|---|---|
| support-0018 | "reason was provided in the first part, no need to ask again" | REASK |
| support-0020 | "policy not cited, not looked up policy" | UNS |
| support-0039 | "user can be told also how much time it takes for the order to deliver" | UNS |
| support-0048 | no failure observed | none |
| support-0064 | "policy not cited" | UNS |
| support-0079 | "why do you need to assume? agent has tools to see when the order was delivered" | UNS, NOANS |
| support-0082 | "did not look up the policy for the particular store" | UNS |
| support-0090 | "additional information - user asked only for the restocking fees" | none |
| support-0113 | "no reason given for the refund" | INEL |
| support-0133 | no failure observed | none |
| support-0170 | no failure observed | none |
| support-0192 | "give product name here as well" | none |
| support-0213 | "incorrect - it can look up recent orders, product by store name as well" | NOANS |
| support-0226 | "why guessing - can look up store return policy" | INEL, UNS |

Nine of these 14 carry a final mode. Three show no failure. support-0090 and support-0192 carry a note but no final mode.

## 7. Taxonomy revisions

The revision I report for the handout runs in two steps. On 3 Nov I split `misreported_order_data` from `damaged_record_not_flagged` (Section 7.1). On 27 Nov the split's effect left the misreport mode too thin to keep, and I rejected it (Section 7.2).

### 7.1 The 3 Nov split of misreport and damaged record

On 3 Nov I fixed the boundary between `misreported_order_data` and `damaged_record_not_flagged`. The two definitions overlapped on one case: the reply substitutes another field when one is missing.

| | Before (31 Oct) | After (3 Nov, 20:25 GMT) |
|---|---|---|
| `misreported_order_data` definition | "…does not match the order record, including substituting another field when one is missing." | "…contradicts a valid field in the order record." |
| `misreported_order_data` boundary | "Draft: a specific record value is wrong. Claims with no record behind them are unsupported_claim." | The field is present and valid, and the reply contradicts it. A broken field that the reply does not flag is `damaged_record_not_flagged`. One conversation can carry both. |
| `damaged_record_not_flagged` definition | "The reply repeats or reasons from" a broken record without flagging it. | "The reply repeats, reasons from, or substitutes another field for" a broken record without flagging it. |
| `damaged_record_not_flagged` boundary | "Draft. A value that differs from a valid record is misreported_order_data." | The record is broken and the reply does not flag it. A reply that flags the value passes. One conversation can carry both. |

My decision log records the basis: split by product fix. Copying a valid record faithfully is one fix. Detecting and flagging broken data is another.

**Example.** My decision log names support-0178 as the case that carries both. Its turn 1 reply says order 8002 "has not yet been marked as delivered", while the status field says delivered. The record's delivery date is also null, and the reply does not flag it. On 4 Nov I labelled support-0178 present for both modes, as the decision log intended. support-0179 and 0180 also carried both on 4 Nov, and all three concern order 8002. support-0177 concerns the same order and carries the damaged record only.

**Effect on the originating notes.** All three notes that seeded the misreport mode concern the null delivery date. The two support-0176 notes say the agent made up the return date and did not handle the null delivery date. support-0176 is absent for the misreport and present for the damaged record. The support-0177 note says the agent used the shipped date as the delivery date. That substitution is a damaged-record failure under the split. Since 4 Nov, support-0177 is absent for the misreport and present for the damaged record. The split therefore left the misreport mode with no originating note.

The two failures need different fixes: copying a valid field versus flagging broken data. Applying the split showed most misreports were broken-record cases.

### 7.2 The 27 Nov rejection of `misreported_order_data`

On 27 Nov at 11:24 GMT I rejected `misreported_order_data`. The 27 Nov recheck cut its confirmed positives from 4 to 1, support-0178. Each final mode needs 3. No valid field is contradicted in the other three:

- support-0179 and 0180 reason from the null `delivered_at`, which is a damaged record. Their stated status and eligibility match the record.
- support-0216 says the item is "not listed" among the user's orders. `list_my_orders` returns no product names, so no record backs the claim. That is `unsupported_claim`, not a contradicted field.

The split explains the outcome. All 3 notes that seeded the mode concerned the null delivery date, and the split moved that failure into `damaged_record_not_flagged`. What remained, a reply that contradicts a valid field, had one trace behind it.

**Example.** support-0178 now carries the damaged record plus an unsupported claim. Its turn 1 reply says order 8002 "has not yet been marked as delivered", against status delivered. That contradicted status moved to `unsupported_claim` on 27 Nov. The null delivery date that the reply does not flag stays `damaged_record_not_flagged`. The conversation still shows two failures with two fixes, now under two final modes.

Four boundaries changed with the rejection. `unsupported_claim`, `damaged_record_not_flagged`, `ineligibility_without_reason` and `question_not_answered` now send a contradicted value to `unsupported_claim`. The nearest mode of `unsupported_claim` changed from the misreport to `damaged_record_not_flagged`. The nearest mode of `damaged_record_not_flagged` changed from the misreport to `unsupported_claim`.

The 97 misreport labels and their Langfuse scores stay as a record (Section 2). Its stored positive list now holds only support-0178, which matches its labels. Homework 5 uses the 7 accepted modes only.

### 7.3 Citation versus unsupported claim (3 Nov, 20:18 GMT)

Before, the citation boundary read: "Draft: the fact is stated but uncited. If no reason is given at all, it is ineligibility_without_reason." Its nearest mode was `ineligibility_without_reason`. The rule did not say what happens when no policy was fetched. Both modes could therefore claim the same uncited sentence.

After, the deciding question is whether a policy was fetched. Fetched but uncited is `policy_claim_without_citation`. Nothing fetched is `unsupported_claim`. The citation mode's nearest mode is now `unsupported_claim`.

**support-0023** shows the boundary. The reply explains restocking fees with zero tool calls, so it is `unsupported_claim` only. support-0239 follows the same rule. `get_store_info` returned no policy id, so its uncited 30-day window is labelled `unsupported_claim`, not a citation failure. The 27 Nov recheck applied the same rule to support-0020 (zero tool calls) and support-0176 (`policy_id: null`).

### 7.4 The escalation mode: rename, then narrowing to ESC-5

1. **31 Oct, 16:40.** I renamed `next_steps_missing_after_action` to `escalation_reply_missing_ticket_or_sla`. The new name matches ESC-5, which requires the ticket id and the response time.
2. **3 Nov, 19:57.** I narrowed the definition to match the name. Before, it read: "After escalating or completing an action, the reply omits what happens next: a ticket or reference id, the response time, the channel, or the charge outcome." After, it reads: "After escalate_to_human succeeds, the reply omits the ticket_id or the response time from sla_hours."
3. The nearest mode changed from `unneeded_or_duplicate_escalation`, already rejected, to `unsupported_claim`. The evaluator changed from an LLM judge to a code check.
4. Cancellations and queued refunds no longer count. support-0057 (a cancellation) and support-0010 (a queued refund) are now absent. My four labels from 31 Oct on this mode already matched the narrowed rule.

### 7.5 Mode 9: narrowed, then rejected

1. **28 Oct.** The coding agent proposed `confusing_or_contradictory_reply` from 6 of my notes. Its definition: "The reply contradicts itself, misframes what the user asked, or cannot be understood without re-reading."
2. **30 Oct, 15:20.** I narrowed it to `contradicts_earlier_statement`: "The reply contradicts something the agent itself stated earlier: in a previous turn of the same conversation, or earlier in the same reply."
3. The narrowing dropped 5 of the 6 notes. Only support-0055 fit: "saying no laptop and then saying tell me the brand?". The other five sit on support-0176 (2 notes), support-0236 and support-0002 (2 notes).
4. **30 Oct, 17:16.** I accepted the narrowed mode. Two boundary questions stayed open: an explicit self-correction, and a reversal under wrong user pushback.
5. **31 Oct, 16:40.** I rejected it with 2 positives, below the 3 the handout requires. The two notes that fit are support-0055 and support-0066 ("contradicting its own sentence").

### 7.6 Modes removed

I rejected four more modes on 31 Oct at 16:40, and `misreported_order_data` on 27 Nov at 11:24. Three of the 31 Oct rejections rested on spec gaps. For two of them I recorded the gap, decided the behaviour and revised `SPEC.md` on 30 Oct. The third never received a revision.

| Mode | Rejected | Requirement source in the file | Supporting notes | Recorded basis |
|---|---|---|---|---|
| `refund_without_request_or_return_check` | 31 Oct | REF-1 and REF-3 (SPEC revision, 30 Oct); REF-2 needs a return tool first | 5 notes: support-0001, 0003, 0010, 0227, 0249 | Spec gap. REF-2 cannot be checked from a trace until a return tool and a return status exist. Two of the five notes sit in `exploration_0`. |
| `support_caller_treated_as_customer` | 31 Oct | "Spec gap: role-specific replies for support staff (revision needed)" | 4 notes: support-0010, 0171, 0200, 0214; 2 accepted suggestions: support-0147, 0156 | Spec gap with no revision behind it. The handout requires a SPEC identifier or a recorded revision. In support-0214 the user is a shopper who claims to be staff. |
| `over_formatted_or_verbose_reply` | 31 Oct | RESP-6 (SPEC revision, 30 Oct) | 7 notes in support-0037, 0053, 0139, 0149, 0150, 0240 | Spec gap. Its open question was whether the chat client renders Markdown. RESP-6 records that it does, so `**` is not visible to the user. |
| `unneeded_or_duplicate_escalation` | 31 Oct | ESC-3, ESC-4 (boundary unclear) | 2 notes: support-0012, 0143 | Two supporting conversations, below the 3 positives each mode needs. Its boundary still reads "needs more examples". |
| `misreported_order_data` | 27 Nov | RESP-3 | 3 notes in 2 conversations: support-0176 (2), 0177 | 1 confirmed positive, support-0178, below the 3 each mode needs. All 3 notes concern the null delivery date, which the 3 Nov split moved to `damaged_record_not_flagged`. A contradicted value is now `unsupported_claim` (Section 7.2). |

## 8. Search suggestions and the repeated search

### 8.1 First search: depth-search suggestions (31 Oct)

The coding agent pushed **15** suggestions on 31 Oct from the depth-search signals in `depth_3`. I reviewed each one: **12 accepted, 3 rejected**, 0 pending. Each accepted suggestion became a note with `source: accepted_suggestion`.

| Mode (current name) | Suggested | Accepted | Rejected |
|---|---|---|---|
| `escalation_reply_missing_ticket_or_sla` | 3 | 3 | 0 |
| `policy_claim_without_citation` | 3 | 3 | 0 |
| `unsupported_claim` | 2 | 2 | 0 |
| `support_caller_treated_as_customer` (mode rejected 31 Oct) | 2 | 2 | 0 |
| `ineligibility_without_reason` | 2 | 1 | 1 |
| `misreported_order_data` (mode rejected 27 Nov) | 2 | 0 | 2 |
| `damaged_record_not_flagged` | 1 | 1 | 0 |
| **Total** | **15** | **12** | **3** |

The three rejected suggestions and the boundaries they set:

| Conversation | Mode | Signal | My reviewer comment (verbatim) | Boundary |
|---|---|---|---|---|
| support-0239 | `ineligibility_without_reason` | The reply says "not eligible", and that sentence gives no reason | "reason is given in the earlier aprt of the reply - just the policy is not cited" | A reason anywhere in the reply passes this mode. A missing citation is another mode's failure. |
| support-0160 | `misreported_order_data` | A keyword check flags a conflict with status `placed` | "yes the reply should have been since order is not shipped it is eligible for cancellation.and policy should be cited, But this is not misreported data" | A status reported correctly is not a misreport, even when the reply has another weakness. |
| support-0246 | `misreported_order_data` | Same keyword check, status `placed` | "again incorrect - since order not shipped, it can be cancelled. no need to say it is in the placed status" | Same boundary as support-0160. |

The traces confirm both cancellation comments. In support-0160 the reply says the order "hasn't shipped yet and is eligible for cancellation". In support-0246 it says the order "hasn't shipped yet and can be canceled". support-0239 and support-0246 are confirmed close negatives of final modes in Section 3. support-0160 was a close negative of the rejected misreport mode, and it is positive for `unsupported_claim`.

### 8.2 Repeated search and recheck after the 3 Nov revisions

After the 3 Nov revisions, the label-suggestion pass re-ran over every reviewed conversation. `analysis/review_app/suggest_labels.py` (v2) combines code checks over each trace with the scenario answer key. The answer key supplies the applicable policy, the record state, the data-quality case and the expected outcome. Each row is a suggestion with a confidence of "high" or "hint". The pass wrote `label_suggestions.json` on 3 Nov at 20:41 GMT: 104 rows per mode, `exploration_0` included.

I then went through the reviewed traces again, one conversation at a time, and confirmed or overrode each suggestion. This pass rechecked the earlier traces against the revised definitions. The table compares my 683 labels in the 7 final modes, as they stand after the 27 Nov decisions, with the suggestions. The suggestions date from 3 Nov and did not change. The "4 Nov" column applies the same method to the same 7 modes as they stood on 4 Nov.

| Mode | n | Agree | Agreement | 4 Nov | Suggested present, I said absent | Suggested absent, I said present | High rows (agree) | Hint rows (agree) |
|---|---|---|---|---|---|---|---|---|
| `policy_claim_without_citation` | 98 | 97 | 99.0% | 96.9% | 0 | 1 | 98 (97) | 0 |
| `ineligibility_without_reason` | 98 | 87 | 88.8% | 88.8% | 0 | 11 | 75 (75) | 23 (12) |
| `unsupported_claim` | 97 | 76 | 78.4% | 79.4% | 2 | 19 | 2 (2) | 95 (74) |
| `escalation_reply_missing_ticket_or_sla` | 98 | 98 | 100.0% | 100.0% | 0 | 0 | 98 (98) | 0 |
| `damaged_record_not_flagged` | 98 | 97 | 99.0% | 99.0% | 1 | 0 | 94 (94) | 4 (3) |
| `reasks_provided_information` | 97 | 93 | 95.9% | 94.8% | 0 | 4 | 88 (87) | 9 (6) |
| `question_not_answered` | 97 | 88 | 90.7% | 86.6% | 3 | 6 | 0 | 97 (88) |
| **Total** | **683** | **636** | **93.1%** | **92.2%** | **6** | **41** | **455 (453)** | **228 (183)** |

On 4 Nov this table covered 8 modes, and 724 of 780 labels agreed (92.8%). The misreport row then read 94 of 97 (96.9%). Without it, 4 Nov agreement is 630 of 683 (92.2%). The 27 Nov recheck raised it to 636 of 683 (93.1%).

**How to read the agreement.** It is not an independent check. The suggestions sat beside each cell while I labelled, so they could anchor me. Agreement is highest for the code-check modes, where the rule is mechanical: 100.0% for escalation, and 99.0% each for citation and damaged record. It is lowest for three LLM-judge modes that need judgement: `unsupported_claim` (78.4%), `ineligibility_without_reason` (88.8%) and `question_not_answered` (90.7%). In 41 of my 47 overrides I found a failure the suggestion missed.

**What the revised definitions decided.** Under the narrowed escalation rule, four originating conversations are absent: support-0010, 0027, 0057 and 0225. Under the split, the misreport notes on support-0176 and support-0177 fall under the damaged-record mode. Under the citation boundary, support-0010, 0012, 0014, 0020, 0023, 0176 and 0239 count as `unsupported_claim` only.

**Conflicts resolved on 4 Nov.** The 3 Nov recheck left labels that differed from the stored boundaries. On 4 Nov I decided each one. Each changed label keeps its old value in `history`.

- **support-0178, misreport: absent → present.** Turn 1 says the order "has not yet been marked as delivered", but the status field says delivered. The conversation then carried both the misreport and the damaged record. The 27 Nov rejection moved the contradicted status to `unsupported_claim`.
- **support-0225, escalation: present → absent.** It has no `escalate_to_human` call. The boundary says no escalation means absent, as for support-0010.
- **support-0010, 0012, 0013 and 0014, citation: present → absent.** None of them fetched a policy, so the claim falls to `unsupported_claim`. support-0010, 0012 and 0014 were already present there. support-0013 stays absent there, because its reply only relays the `refund_eligible` flag and states no policy rule.
- **support-0177, misreport: present → absent.** Using `shipped_at` as the delivery date is a damaged-record failure under the split. Its status, total and refund eligibility match the record.
- **support-0010, unsupported claim: stays present.** Its evidence now names the turn 2 promise "your case will be prioritized". The `issue_refund` note backs the $100 threshold.
- **support-0112, ineligibility: stays present.** Its reason, "marked as non-refundable", is not wrong, but it is circular. support-0012, 0013, 0014 and 0177 show the same pattern. The rule: restating the record flag is not a reason. The stored boundary now says so.

The 4 Nov decisions moved 7 labels toward the suggestions. Across the 8 modes of that date, agreement rose from 717 to 724 of 780 (91.9% to 92.8%).

**27 Nov recheck.** On 27 Nov I rechecked the labels against the stored boundaries once more and changed 15 labels: 12 in the final modes and 3 in the rejected misreport. I also tightened the ineligibility boundary: the mode is present unless the reply states both the window and the dates. Each changed label keeps its old value in `history`.

- **support-0179, 0180 and 0216, misreport: present → absent.** No valid field is contradicted. support-0179 and 0180 reason from the null `delivered_at`, which is damaged. support-0216's "not listed" has no record behind it, which is unsupported.
- **support-0180 and 0149, ineligibility: absent → present.** The reply restates "not eligible for a refund" with no window or dates.
- **support-0220, ineligibility: absent → present.** Turn 1 says "longer than the typical return window" and never states the 21-day window that applies. It is no longer a close negative.
- **support-0176, ineligibility: present → absent.** No reply says the order is ineligible.
- **support-0020 and 0176, citation: present → absent.** Neither fetched a policy: support-0020 makes no tool calls, and support-0176 received `policy_id: null`.
- **support-0113, 0039, 0084 and 0242, question not answered: present → absent.** Each reply addresses the core question.
- **support-0022, re-ask: present → absent.** The user never gave the order ID, and no tool returned it.
- **support-0178, unsupported claim: absent → present.** Its contradicted status, "has not yet been marked as delivered" against status delivered, moves here because the misreport is rejected.

The 12 changes in the final modes moved 9 labels toward the suggestions and 3 away: support-0149, 0178 and 0220. Agreement on the 7 modes therefore rose from 630 to 636 of 683 (92.2% to 93.1%). All 3 misreport changes moved toward the suggestions.

Two timing gaps remain in the 7 final modes. 23 labels carry a 31 Oct timestamp, and 33 more, on support-0016, 0018, 0020, 0022 and 0023, predate the 3 Nov split at 20:25. Agreement on these 56 labels is 85.7%, compared to 93.8% on the 627 labels from 20:25 onward.

## 9. `SPEC.md` revisions

I added five requirements on 30 Oct, during error analysis. `SPEC.md` marks each one as a Homework 4 addition.

| Revision | What it requires | Motivating annotations | Final mode that uses it |
|---|---|---|---|
| **ESC-5** | After `escalate_to_human` succeeds, the reply gives the `ticket_id` and the response time from `sla_hours`. The `summary` argument states the issue, the order and the request. | support-0012 (ann-6859f5d4be), support-0143 (ann-a7e6c1151c), support-0102 (ann-dd980faa08), support-0225 (ann-a1c97571e8), support-0027 (ann-9ef1e4db5e), support-0010 (ann-ec42f055d6) | `escalation_reply_missing_ticket_or_sla` |
| **REF-1** | Refund only when the user asked for one in this conversation. | support-0227 (ann-5944c5d699), support-0249 (ann-f1272364d4) | none; `refund_without_request_or_return_check` was rejected |
| **REF-2** | Start a return before refunding a shopper. This needs a new return tool and a return status, so traces cannot show it yet. | support-0010 (ann-65be49e2ba), support-0001 (ann-3d3463d544), support-0003 (ann-30694f3cad) | none |
| **REF-3** | A support caller's refund `reason` references the customer request, such as a ticket or email reference. Without one, the agent asks and does not refund. | support-0227 (ann-5944c5d699), support-0249 (ann-f1272364d4) | none |
| **RESP-6** | The chat client renders Markdown. Simple answers use plain sentences; lists or headings only for several steps or items. | support-0037 (ann-2dd5dfc537), support-0139 (ann-5ff56eb3cf, ann-c493a24728), support-0149 (ann-d538100736), support-0150 (ann-f44c5cf72d), support-0053 (ann-c7906ee910) | none; `over_formatted_or_verbose_reply` was rejected |

RESP-6 and REF-1 to REF-3 stay in `SPEC.md`, although their modes were removed. They record the decided behaviour, so a later mode or evaluator can use them.

## 10. Comparison with the AgentDebug taxonomy

| Final mode | AgentDebug category |
|---|---|
| `unsupported_claim` | Hallucination |
| `reasks_provided_information` | Memory: Retrieval Failure |
| `escalation_reply_missing_ticket_or_sla` | Reflection: Progress Misassessment (loose fit) |
| `policy_claim_without_citation` | No equivalent |
| `damaged_record_not_flagged` | No equivalent |
| `question_not_answered` | No equivalent |
| `ineligibility_without_reason` | No direct equivalent (an explanation omission) |

The rejected `misreported_order_data` mapped to Reflection: Outcome Misinterpretation. A contradicted value now falls under `unsupported_claim`, so that category has no final mode of its own.

Policy citation, the broken record, the unanswered question and the missing reason have no close AgentDebug equivalent. They depend on Cartwheel's product and on `SPEC.md`, not on a general agent module.

**Possible omission: Action Parameter Error.** Workshop run 7 (support-0194) passed a store id as a store name to `search_products`. I did not add a mode, because no human annotation supports it. support-0194 is not in the reviewed sample.

**Unclear name fixed:** `next_steps_missing_after_action` became `escalation_reply_missing_ticket_or_sla` (Section 7.4).

## 11. Part C: Raindrop Workshop

`analysis/report/workshop_notes.md` records 10 fresh Cartwheel conversations inspected in Raindrop Workshop 0.1.23, on a local daemon at `127.0.0.1:5899`. The runs used a fresh seed database and scenarios outside the reviewed sample. The notes list every Workshop run id, the candidate failures per run, and one uncertain case (run 5, support-0110).

Three candidates bear on the final taxonomy. Runs 3 and 6 omit the ticket id after an escalation (ESC-5). Run 7 (support-0194) passes a wrong tool argument. Run 8 (support-0164) misses a mandatory dispute escalation, a second hint for the parked `required_escalation_not_made`.

My decisions on every Workshop suggestion are in the decisions table of `workshop_notes.md` (27 Nov). I accepted the ESC-5 omissions and the invented timings, revised the run 1 citation claim, kept run 8 as evidence for the parked escalation mode, and rejected the other four.

## 12. Batch 2 hypothesis outcome

On 28 Oct, before any review, I chose `difficulty` as the batch 2 dimension. The hypothesis: the agent fails differently by how hard the request is. After axial coding on 31 Oct, I recorded that the hypothesis held.

| Difficulty | Predicted pattern | Batch 2 conversations whose notes support it |
|---|---|---|
| missing_information | broken records left unflagged (`damaged_record_not_flagged`) | support-0178, support-0179 (2 of 6) |
| false_premise | support callers treated as customers (`support_caller_treated_as_customer`) | support-0200, support-0214 (2 of 6) |
| ambiguous | re-asks and non-answers (`reasks_provided_information`, `question_not_answered`) | support-0016 (re-ask), support-0242 and support-0084 (non-answers) (3 of 6) |

The final labels of 27 Nov give a second view. Each cell shows positives out of 6 batch 2 conversations.

| Mode | well_specified | ambiguous | missing_information | boundary | false_premise |
|---|---|---|---|---|---|
| `damaged_record_not_flagged` | 0 | 3 | 2 | 0 | 2 |
| `reasks_provided_information` | 0 | 1 | 0 | 1 | 0 |
| `question_not_answered` | 1 | 0 | 0 | 2 | 0 |
| `unsupported_claim` | 4 | 0 | 2 | 3 | 0 |
| `escalation_reply_missing_ticket_or_sla` | 2 | 0 | 2 | 0 | 1 |

Data that argues against a strong reading:

- In the notes, each predicted pattern rests on 2 or 3 conversations out of 6.
- In the final labels, the ambiguous prediction keeps 1 positive, the re-ask in support-0016. The 27 Nov recheck set the two ambiguous non-answers, support-0084 and 0242, absent.
- Damaged records appear more in `ambiguous` (3 of 6) than in `missing_information` (2 of 6). All three ambiguous cases are product-search data-quality cases.
- Three other `missing_information` conversations concern escalation replies (support-0100, 0103, 0174), not broken records.
- In support-0214 the user is a shopper who claims to be on the support team. The role claim is the false premise.
- I rejected `support_caller_treated_as_customer` on 31 Oct, so the false-premise prediction has no final mode.
- Re-asks and non-answers also appear in `boundary` (support-0228, 0066, 0217) and `well_specified` (support-0126).

**Verdict.** It held only weakly. After the recheck, each surviving prediction rests on 1 or 2 of 6 conversations. Damaged records appeared more in ambiguous requests than in missing-information ones, and the false-premise prediction lost its mode.
