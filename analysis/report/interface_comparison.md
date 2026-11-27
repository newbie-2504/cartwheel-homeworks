# Interface comparison: the Langfuse view and the HW4 review app

The review app in `analysis/review_app/` replaced the Langfuse annotation view for open coding. Each of my 6 Langfuse friction notes has a matching feature. Langfuse stays the canonical store.

**Data source.** The app loaded 419 support traces from live Langfuse, cached on 28 Oct, and built 250 conversations. I did not need the offline HW3 export.

## Friction in the Langfuse view, and the response

I reviewed 6 traces in the standard Langfuse view on 26 Oct and wrote these notes.

| # | Langfuse friction | Review app response |
|---|---|---|
| 1 | Tool calls are not beside the reply; each trace must be opened. | Each turn shows the user message, its tool calls and the reply in one column, with progressive disclosure (below). |
| 2 | Comments attach to a whole trace; no phrase highlighting. | Quote-anchored notes. I select text in any block, including tool arguments and results, and type a note. The note stores the block, quote and offsets. |
| 3 | The answer key is not visible. | An answer-key panel, hidden until I click "Reveal answer key", so I judge before I see the expected outcome. |
| 4 | Role and dimensions are not visible. | Chips show role, intent, record state, difficulty and user style. The list filters by batch, role and intent. |
| 5 | Multi-turn conversations need clicking trace by trace. | Traces are grouped by `cartwheel.session_id`, in time order. Retried support-0059 and support-0240 show the latest session, flagged. |
| 6 | No way to see whether a policy claim was fetched or invented. | The evidence panel lists every policy fetched, by turn, and the policy ids in replies. A read-only ledger shows the matching `orders`, `refunds` and `escalations` rows. |

## Features beyond the friction notes

- **Taxonomy, Suggestions and Labels tabs.** Taxonomy shows each mode with its notes and revision history. Labels holds one present or absent decision per conversation and mode.
- **Agent suggestions kept apart.** Suggestions carry a lavender tint and a tag. I accept or reject each one with a comment.
- **Code-check label suggestions.** Code checks plus the scenario answer key suggest a label for each cell in the 7 final modes. High-confidence suggestions show as dashed chips and hints as dotted chips. One becomes a label only when I confirm it.
- **Langfuse score write-back.** One score per conversation and mode on the primary trace: name = mode, value 1 or 0, comment = evidence.

## Design retained from the reference interface

I kept the reference interface's quote-anchored highlight with a margin note. I also kept the tool-call-and-result box and the file-backed API.

## Design changed after inspecting the traces: progressive disclosure

On 28 Oct, after I saw every tool call expanded, I chose progressive disclosure. Each tool call is now one summary line: name, arguments, ok or error, and a result summary. Intermediate model text is one preview line. Both open on click, all at once with `t`, and automatically when they carry a note or suggestion.

Nothing is dimmed by role, unlike the reference, which fades system and boilerplate blocks. The error-discovery skill says to collapse, never mute. Source: Shreya, Lecture 2 [57:46].

Collapsed tool calls kept a whole conversation on one screen. Notes still opened their evidence automatically.

## Limitation remaining

The app README lists two: a margin note can sit below its highlight, and a note cannot span two blocks. A third, a changed label adding a second Langfuse score, was fixed on 3 Nov with deterministic score ids.

The limitation that matters most: a note cannot span two blocks, so a failure that runs across a tool result and its reply needs two notes.

## My assessment

Tool calls inline with replies made the first-failure call fast, and code-check suggestions shortened the labelling pass. Next I would add a blind second-rater view.
