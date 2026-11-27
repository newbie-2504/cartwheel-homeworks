# HW4 review app

A conversation-level review interface for Homework 4. The reviewer reads each conversation turn by turn and does all of the following in the app: writes free-text notes, owns the taxonomy, decides on agent suggestions, and records binary labels. The coding agent proposes modes, suggestions and sample batches through the API. Only the reviewer makes a judgement.

## Run

```bash
uv run python -m analysis.review_app --port 8040            # state in analysis/state
python analysis/review_app/server.py --port 8040 --state-dir /tmp/scratch-state
uv run python -m analysis.review_app.smoke_test --screenshot analysis/review_app/cache/screenshot-review.png
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--port` | 8040 | The server always binds to 127.0.0.1. There is no host option. |
| `--state-dir` | `analysis/state` | The directory for annotations, patterns, suggestions, the manifest and labels. |
| `--cache-dir` | `analysis/review_app/cache` | The Langfuse trace cache. The directory is gitignored. |
| `--source` | `auto` | `auto` tries the cache, then live Langfuse, then the HW3 export. You can also pass `cache`, `langfuse` or `export`. |
| `--no-langfuse-writes` | off | Disables `POST /api/langfuse/write-labels`. The smoke test uses this flag. |

Langfuse credentials come from `.env` through `observability.instrument.load_env`. The app never prints or stores the keys. The cache holds only trace data.

## Data

- **Traces.** The app loads every trace whose `cartwheel.scenario_id` starts with `support-`. It lists them through `/api/public/traces` and fetches each one through `/api/public/traces/{id}`. The offline fallback is `traces/support_traces.json`, which the app marks with an "offline source" banner. On 27 Oct 2026, live Langfuse held 419 support traces and the export held 418. The extra trace belongs to the earlier, retried session of support-0240, so the conversations shown are the same.
- **Conversations.** A conversation groups traces by session id, in chronological order. When a scenario ran in more than one session, the latest session is the conversation and the header says `retried: earlier partial session <id>`. This affects support-0059 and support-0240. The conversation id is the scenario id. The primary trace is the first trace of the session, which is where Langfuse scores attach.
- **Model text.** Text the model emitted alongside a tool call appears as its own block, "not part of the reply sent to the user". The reason: `server/app.py` replies with `result.final_output` only, and the trace outputs match the `agent` turns in `final-results.jsonl`.
- **Joined data.** The app joins `scenarios/support_scenarios.jsonl` and `scenarios/final-results.jsonl`. The answer key stays hidden until you click "Reveal answer key". The answer-key panel also holds `applicable_policy` and `tools_needed`, because they hint at the expected behaviour.
- **Evidence.** The evidence panel shows facts only:
  - (a) every `get_policy` result and `search_help_center` hit, with its turn and text;
  - (b) policy ids that appear in replies, found by regex, with no claim about whether they are correct;
  - (c) rows from `orders`, `refunds` and `escalations` for every `order_id`, `refund_id` and `ticket_id` in tool arguments or results. The app opens `data/cartwheel.db` read-only (`mode=ro`) and labels the rows "database state after the final run (23 Oct 2026)".

## Who may write what

Every POST needs `Content-Type: application/json`, and its Host and Origin must be this app. The actor is `by` in the JSON body, or the `X-Review-Actor` header. The default actor is `agent`.

| Endpoint | Agent | Reviewer (`by: "human"`, sent by the UI) |
| --- | --- | --- |
| `/api/annotations` | refused (403) | create, edit, delete, first failure, no failure |
| `/api/labels` | refused (403) | save or clear |
| `/api/langfuse/write-labels`, `/api/demo/start-fresh` | refused (403) | allowed |
| `/api/patterns` | creates modes as `proposed`; edits only `proposed` modes; cannot change status | everything, including accept, reject and merge |
| `/api/suggestions` | pushes `pending` suggestions; cannot change decided ones | accept, reject, reopen, comment |
| `/api/samples` | allowed | allowed |
| `/api/reload` | allowed | allowed |

## Endpoints

| Method and path | Body or query | Returns |
| --- | --- | --- |
| `GET /` | | the UI |
| `GET /api/status` | | the source and its banners, the state dir, demo files, SPEC ids and the version |
| `GET /api/version` | | `{version}`, which changes on any state write or reload (the UI polls it every 3 s) |
| `GET /api/conversations` | | `{source, conversations: [{id, session_id, primary_trace_id, trace_ids, turn_count, role, user_id, intent, record_state, difficulty, user_style, group, dq, ids, retried_sessions, review_status, note_count, batch}]}` |
| `GET /api/conversation?id=support-0238` | | the full conversation: `turns[{index, number, trace_id, timestamp, user, steps[], reply}]`, `retried`, `scenario` (including `expected`), `result`, `warnings`, `evidence` |
| `GET/POST /api/annotations` | see below | `{annotations: [...]}` |
| `GET/POST /api/patterns` | see below | `{modes: [...]}` |
| `GET/POST /api/suggestions` | see below | `[...]` |
| `GET/POST /api/samples` | the manifest | the manifest |
| `GET/POST /api/labels?mode=<name>` | see below | `{mode, labels: [...]}`. Without `mode`, returns `{modes: {name: [...]}}` for the accepted modes. |
| `GET /api/progress` | | per-batch counts, label grid completeness, suggestion counts and the saturation check |
| `POST /api/langfuse/write-labels` | `{by, modes?: [...], dry_run?: true}` | writes one score per unwritten label of the accepted modes |
| `POST /api/reload` | `{source: "langfuse" or "export"}` | the new source. A failed Langfuse reload keeps the current data. |
| `POST /api/demo/start-fresh` | `{by: "human", confirm: true}` | `{moved: [...]}` |

A step in `turns[].steps` is one of these two shapes:

- `{kind: "tool", index, name, arguments, result, args_text, result_text, ok, error, summary, long}`
- `{kind: "model_text", index, text, with_tool_call}`

A note attaches to a block through `target`:

- `t<turn>.user`
- `t<turn>.reply`
- `t<turn>.s<step>.args`
- `t<turn>.s<step>.result`
- `t<turn>.s<step>.text`

`start` and `end` are character offsets into that block's text (`args_text` and `result_text` for tool blocks).

## State files and JSON shapes

### annotations.json

```json
{"annotations": [{"id": "ann-…", "conversation_id": "support-0238", "session_id": "…", "trace_id": "<the turn's trace>",
  "turn_index": 0, "target": "t0.s1.result", "quote": "…", "start": 120, "end": 143, "note": "free text",
  "first_failure": true, "no_failure": false, "source": "human | accepted_suggestion", "suggestion_id": null,
  "created_at": "…", "updated_at": "…", "deleted_at": null, "history": [{"at": "…", "note": "original text"}, {"at": "…", "note": "edited text"}]}]}
```

- `history` lists every version of the note. The first entry is the original note.
- A delete is soft. It sets `deleted_at` and `deleted_reason`, so the record stays inspectable.
- The first note in a conversation gets `first_failure: true` by default. Use `{"action": "set_first_failure", "id": …}` to move the marker.
- "No failure observed" is a record with `no_failure: true` and the note `"no failure observed"`.

POST bodies:

- `{by, annotation: {...}}` or `{by, annotations: [...]}` creates a note, or edits it when the id exists.
- Add `replace_no_failure: true` to replace a "no failure observed" mark with a note.
- `{by, action: "delete", id}` deletes a note.
- `{by, action: "set_first_failure", id}` moves the first-failure marker.
- `{by, action: "no_failure", conversation_id, value: true|false}` sets or clears the mark. The server refuses `true` when the conversation already has notes.

### patterns.json

```json
{"modes": [{"id": "mode-…", "name": "snake_case", "definition": "", "positive_conversation_ids": [], "close_negative_conversation_ids": [],
  "source_annotation_ids": [], "nearest_mode": "", "boundary": "", "evaluator_type": "code_check | llm_judge | null",
  "requirement_source": "RESP-2 or spec revision: …", "status": "proposed | accepted | rejected | merged", "merged_into": null,
  "proposed_by": "agent | human", "created_at": "…", "updated_at": "…",
  "history": [{"at": "…", "by": "agent | human", "field": "definition", "previous": "…", "value": "…"}]}]}
```

POST bodies:

- `{mode: {...}}`, `{modes: [...]}`, a bare list, or the reference shape `{name: {...}}`. The server upserts each mode by `id`, else by `name`.
- `{by: "human", action: "set_status", id, status}` sets the status to `proposed`, `accepted` or `rejected`. Accepting needs a definition.
- `{by: "human", action: "merge", id, into}` merges a mode. The target receives the union of the notes, positives and close negatives, and the source becomes `merged`.

Validation rules:

- Names must be snake_case and unique.
- A conversation cannot be both a positive and a close negative.
- Renaming a mode moves `labels/<name>.jsonl`. The server refuses a rename once any of the mode's labels were written to Langfuse.
- The server records every changed field in `history` with its previous value.

### suggestions.json

```json
[{"id": "sug-…", "mode": "…", "conversation_id": "support-0001", "trace_id": "…", "turn_index": 0, "target": "t0.reply",
  "quote": "…", "start": 0, "end": 30, "reason": "…", "source": "agent", "status": "pending | accepted | rejected",
  "reviewer_comment": "", "created_at": "…", "decided_at": null, "annotation_id": null, "history": []}]
```

- An agent push needs `mode`, `conversation_id`, `quote` and `reason`. When `target` or `start` is missing, the server finds the quote in the conversation, trying replies first.
- The server ignores a re-pushed suggestion with the same (mode, conversation, quote).
- Decision body: `{by: "human", action: "accept" | "reject" | "reopen" | "comment", ids: [...], reviewer_comment?}`.
- Accepting creates an annotation with `source: "accepted_suggestion"` and `suggestion_id` set. The note text is the reviewer's comment, else `[accepted suggestion: <mode>] <reason>`.
- Rejected suggestions stay in the file.

### sample_manifest.json

```json
{"unit": "conversation", "dimension": null, "batches": [{"name": "uniform_1", "method": "uniform random", "rationale": "…",
  "created_at": "…", "final": false, "conversation_ids": ["support-0001"]}]}
```

- POST a whole manifest, or `{batch: {...}}` to add or replace one batch by name, or `{action: "delete_batch", name}`.
- The server answers 409 and lists the duplicates when one conversation appears in two batches.
- The saturation check uses the batch marked `final: true`, else the last batch in the list. It counts the modes whose `created_at` is later than that batch's `created_at`.
- Do not call the course helper `select_traces` against this state directory. It overwrites `sample_manifest.json` with a different shape.

### labels/&lt;mode&gt;.jsonl

The file holds one line per conversation. The server rewrites it in conversation order.

```json
{"conversation_id": "support-0238", "session_id": "…", "trace_id": "<primary>", "primary_trace_id": "<primary>", "trace_ids": ["…"],
 "mode": "…", "decision": "present | absent", "label": 1, "evidence": "…", "source": "human", "decided_at": "…",
 "langfuse_written": false, "langfuse_written_at": null, "langfuse_writes": [{"at": "…", "value": 1}],
 "history": [{"at": "…", "decision": "absent", "evidence": ""}]}
```

- `label` is 1 (present) or 0 (absent). `trace_id` equals the primary trace. With these two fields, the course helpers (`tools._load_labels`, HW5 `split_labels`) read the file unchanged.
- POST body: `{by, conversation_id, label: "present" | "absent" | 1 | 0, evidence}` or `{by, labels: [...]}`.
- `{by, conversation_id, action: "clear"}` removes a decision.
- A present label needs evidence.
- You can label only accepted modes.
- Changing a label resets `langfuse_written` to false.
- "Write accepted labels to Langfuse" calls `analysis.helpers.langfuse_io.write_label_score`. It writes one score per unwritten (conversation, mode) pair on the primary trace: the score name is the mode, the value is 1 for present and 0 for absent, and the comment is the evidence.

## Course demo files

The state directory ships with course demo files: `demo_annotations.json`, `store_traces.json`, `splits.json`, `labels/unsupported_policy_claim.jsonl` and `judges/*`. The app never shows or merges records without a `conversation_id`. A banner offers "Start fresh", which moves those files to `<state-dir>/_course_demo/` only after you click it and confirm. `tests/test_hw_holes.py` reads the demo files from `analysis/state`, so those course tests fail while the files are moved.

## Known limitations

- Margin notes stack in a column. On long conversations, a note can sit lower than its highlight. Hover links the two.
- Notes attach to one block. A selection that spans two blocks is refused.
