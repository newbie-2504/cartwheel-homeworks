"""File-backed review state for the HW4 review app.

Every write goes through this module, under one lock, and every file is
written atomically (temp file, then replace) with the course helper
``analysis.helpers._state``. The files are re-read on every request, so the
disk is the source of truth and a crash loses at most the request in flight.

Files under the state directory (default ``analysis/state``):

    annotations.json        {"annotations": [...]}
    patterns.json           {"modes": [...]}
    suggestions.json        [...]
    sample_manifest.json    {"unit": "conversation", "batches": [...], "dimension": ...}
    labels/<mode>.jsonl     one JSON line per conversation

Rules the server enforces, so the human stays the only judge:

    - annotations and labels are written only by the reviewer UI (``by: human``);
    - agent-proposed modes always arrive with status ``proposed``, and only the
      reviewer changes a mode's status or edits a non-proposed mode;
    - agent suggestions always arrive ``pending``; only the reviewer accepts or
      rejects them, and rejections are kept;
    - a conversation may appear in only one sample batch.

Records the app did not write (the course demo shapes, which lack a
``conversation_id``) are never shown, never merged and never deleted. The
"start fresh" action moves the demo files to ``_course_demo/`` on request.
"""

from __future__ import annotations

import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from analysis.helpers import _state

SNAKE_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
MODE_STATUSES = ("proposed", "accepted", "rejected", "merged")
EVALUATOR_TYPES = ("code_check", "llm_judge")
MODE_TEXT_FIELDS = ("name", "definition", "boundary", "nearest_mode", "requirement_source", "evaluator_type")
MODE_LIST_FIELDS = ("positive_conversation_ids", "close_negative_conversation_ids", "source_annotation_ids")
DEMO_FILES = ("demo_annotations.json", "store_traces.json", "splits.json", "samples.json", "graph.json")


class StoreError(Exception):
    """A request the store refuses; carries the HTTP status to return."""

    def __init__(self, message: str, status: int = 400, **extra: Any) -> None:
        super().__init__(message)
        self.status = status
        self.extra = extra


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = re.split(r"[\s,]+", value)
    return list(dict.fromkeys(str(v).strip() for v in value if str(v).strip()))


class ReviewStore:
    def __init__(self, state_dir: Path, conversations: Callable[[], dict[str, dict[str, Any]]]) -> None:
        self.dir = state_dir
        self.dir.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._conversations = conversations

    # -- paths and raw io ---------------------------------------------------

    def path(self, *parts: str) -> Path:
        return self.dir.joinpath(*parts)

    def _read(self, name: str, default: Any) -> Any:
        try:
            data = _state.read_json(self.path(name), default=default)
        except ValueError:
            raise StoreError(f"{name} is not valid JSON; fix or move it before saving", 500)
        return default if data is None else data

    def _write(self, name: str, data: Any) -> None:
        _state.write_json(self.path(name), data)

    def version(self) -> str:
        """Changes whenever any state file changes (the UI polls this)."""
        parts = []
        for name in ("annotations.json", "patterns.json", "suggestions.json", "sample_manifest.json"):
            p = self.path(name)
            parts.append(f"{p.stat().st_mtime_ns}:{p.stat().st_size}" if p.exists() else "-")
        labels = self.path("labels")
        if labels.exists():
            for p in sorted(labels.glob("*.jsonl")):
                parts.append(f"{p.name}:{p.stat().st_mtime_ns}:{p.stat().st_size}")
        return "|".join(parts)

    def _conv(self, conversation_id: Any) -> dict[str, Any]:
        conv = self._conversations().get(str(conversation_id or ""))
        if conv is None:
            raise StoreError(f"unknown conversation_id {conversation_id!r}", 404)
        return conv

    # -- annotations --------------------------------------------------------

    def _annotation_doc(self) -> dict[str, Any]:
        doc = self._read("annotations.json", {"annotations": []})
        if isinstance(doc, list):  # the reference server writes a bare list
            doc = {"annotations": doc}
        if not isinstance(doc.get("annotations"), list):
            doc["annotations"] = []
        return doc

    @staticmethod
    def _is_ours(record: Any) -> bool:
        return isinstance(record, dict) and bool(record.get("conversation_id")) and bool(record.get("id"))

    def annotations(self, include_deleted: bool = True) -> dict[str, Any]:
        with self.lock:
            doc = self._annotation_doc()
        ours = [a for a in doc["annotations"] if self._is_ours(a)]
        if not include_deleted:
            ours = [a for a in ours if not a.get("deleted_at")]
        return {"annotations": ours, "foreign_records_ignored": len(doc["annotations"]) - len([a for a in doc["annotations"] if self._is_ours(a)])}

    def _active(self, records: list[dict[str, Any]], conversation_id: str) -> list[dict[str, Any]]:
        return [a for a in records if self._is_ours(a) and a["conversation_id"] == conversation_id and not a.get("deleted_at")]

    @staticmethod
    def _soft_delete(record: dict[str, Any], why: str) -> None:
        record["deleted_at"] = now()
        record["deleted_reason"] = why
        record["updated_at"] = record["deleted_at"]

    def _ensure_first_failure(self, records: list[dict[str, Any]], conversation_id: str) -> None:
        notes = [a for a in self._active(records, conversation_id) if not a.get("no_failure")]
        if notes and not any(a.get("first_failure") for a in notes):
            earliest = min(notes, key=lambda a: a.get("created_at") or "")
            earliest["first_failure"] = True

    def _new_annotation(self, records: list[dict[str, Any]], payload: dict[str, Any], source: str = "human",
                        suggestion_id: str | None = None) -> dict[str, Any]:
        conv = self._conv(payload.get("conversation_id"))
        note = str(payload.get("note") or "").strip()
        if not note:
            raise StoreError("a note needs text")
        turn_index = payload.get("turn_index")
        if turn_index is not None:
            turn_index = int(turn_index)
            if not 0 <= turn_index < len(conv["turns"]):
                raise StoreError(f"turn_index {turn_index} is outside the conversation")
        trace_id = payload.get("trace_id") or (conv["turns"][turn_index]["trace_id"] if turn_index is not None else conv["primary_trace_id"])
        if trace_id not in conv["trace_ids"]:
            raise StoreError(f"trace_id {trace_id} is not part of {conv['id']}'s session")
        active = self._active(records, conv["id"])
        no_failure = [a for a in active if a.get("no_failure")]
        if no_failure:
            if not payload.get("replace_no_failure"):
                raise StoreError(f"{conv['id']} is marked 'no failure observed'. Send replace_no_failure: true to replace that mark with this note.", 409)
            for rec in no_failure:
                self._soft_delete(rec, "replaced by a note")
        has_notes = any(not a.get("no_failure") for a in active)
        stamp = now()
        record = {
            "id": new_id("ann"),
            "conversation_id": conv["id"],
            "session_id": conv["session_id"],
            "trace_id": trace_id,
            "turn_index": turn_index,
            "target": payload.get("target"),
            "quote": str(payload.get("quote") or ""),
            "start": payload.get("start"),
            "end": payload.get("end"),
            "note": note,
            "first_failure": not has_notes,
            "no_failure": False,
            "source": source,
            # Course schema: analysis/helpers/reporting.py and the tests read author == "human".
            "author": "human",
            "suggestion_id": suggestion_id,
            "created_at": stamp,
            "updated_at": stamp,
            "deleted_at": None,
            "history": [{"at": stamp, "note": note}],
        }
        records.append(record)
        return record

    def save_annotations(self, body: Any) -> dict[str, Any]:
        """Create, edit, delete or mark annotations. See README for body shapes."""
        with self.lock:
            doc = self._annotation_doc()
            records = doc["annotations"]
            by_id = {a["id"]: a for a in records if self._is_ours(a)}
            changed: list[dict[str, Any]] = []
            action = body.get("action") if isinstance(body, dict) else None

            if action == "delete":
                rec = by_id.get(str(body.get("id")))
                if rec is None:
                    raise StoreError("unknown annotation id", 404)
                self._soft_delete(rec, str(body.get("reason") or "deleted by reviewer"))
                if rec.get("first_failure"):
                    rec["first_failure"] = False
                    self._ensure_first_failure(records, rec["conversation_id"])
                changed.append(rec)
            elif action == "set_first_failure":
                rec = by_id.get(str(body.get("id")))
                if rec is None or rec.get("deleted_at") or rec.get("no_failure"):
                    raise StoreError("unknown or inactive annotation id", 404)
                for other in self._active(records, rec["conversation_id"]):
                    other["first_failure"] = other is rec
                rec["updated_at"] = now()
                changed.append(rec)
            elif action == "no_failure":
                conv = self._conv(body.get("conversation_id"))
                active = self._active(records, conv["id"])
                if body.get("value", True):
                    if any(not a.get("no_failure") for a in active):
                        raise StoreError(f"{conv['id']} already has notes; delete them before marking 'no failure observed'", 409)
                    if not any(a.get("no_failure") for a in active):
                        stamp = now()
                        rec = {
                            "id": new_id("ann"), "conversation_id": conv["id"], "session_id": conv["session_id"],
                            "trace_id": conv["primary_trace_id"], "turn_index": None, "target": None,
                            "quote": "", "start": None, "end": None, "note": "no failure observed",
                            "first_failure": False, "no_failure": True, "source": "human", "suggestion_id": None,
                            "created_at": stamp, "updated_at": stamp, "deleted_at": None,
                            "history": [{"at": stamp, "note": "no failure observed"}],
                        }
                        records.append(rec)
                        changed.append(rec)
                else:
                    for rec in active:
                        if rec.get("no_failure"):
                            self._soft_delete(rec, "reviewer cleared 'no failure observed'")
                            changed.append(rec)
            elif action is None:
                if isinstance(body, dict) and "annotation" in body:
                    items = [body["annotation"]]
                elif isinstance(body, dict) and isinstance(body.get("annotations"), list):
                    items = body["annotations"]
                elif isinstance(body, list):
                    items = body
                else:
                    raise StoreError("expected {annotation: {...}}, {annotations: [...]} or an action")
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    item = dict(item)
                    if isinstance(body, dict) and body.get("replace_no_failure"):
                        item.setdefault("replace_no_failure", True)
                    rec = by_id.get(str(item.get("id"))) if item.get("id") else None
                    if rec is None:
                        rec = self._new_annotation(records, item)
                        by_id[rec["id"]] = rec
                        changed.append(rec)
                        continue
                    note = item.get("note")
                    if note is not None and str(note).strip() and str(note).strip() != rec["note"]:
                        stamp = now()
                        rec["note"] = str(note).strip()
                        rec.setdefault("history", []).append({"at": stamp, "note": rec["note"]})
                        rec["updated_at"] = stamp
                        changed.append(rec)
            else:
                raise StoreError(f"unknown action {action!r}")
            self._write("annotations.json", doc)
        return {"ok": True, "changed": changed, "annotations": self.annotations()["annotations"]}

    # -- patterns (taxonomy) ------------------------------------------------

    def _pattern_doc(self) -> dict[str, Any]:
        doc = self._read("patterns.json", {"modes": []})
        if not isinstance(doc, dict):
            doc = {"modes": []}
        if not isinstance(doc.get("modes"), list):
            doc["modes"] = []
        for mode in doc["modes"]:
            if isinstance(mode, dict):
                self._fill_mode(mode)
        return doc

    @staticmethod
    def _fill_mode(mode: dict[str, Any]) -> dict[str, Any]:
        # A stable id for modes written by other tools without one.
        mode.setdefault("id", f"mode-{mode.get('name')}" if mode.get("name") else new_id("mode"))
        for f in ("definition", "boundary", "nearest_mode", "requirement_source"):
            mode.setdefault(f, "")
        mode.setdefault("evaluator_type", None)
        for f in MODE_LIST_FIELDS:
            mode[f] = _as_list(mode.get(f))
        mode.setdefault("status", "proposed")
        mode.setdefault("merged_into", None)
        mode.setdefault("proposed_by", "agent")
        mode.setdefault("created_at", None)
        mode.setdefault("updated_at", mode.get("created_at"))
        mode.setdefault("history", [])
        return mode

    def _sync_created_from(self, doc: dict[str, Any]) -> None:
        """Course schema: each mode lists the trace ids of the human annotations it came from."""
        anns = {a["id"]: a for a in self._read("annotations.json", {"annotations": []}).get("annotations", [])}
        for mode in doc.get("modes", []):
            ids = [anns[i]["trace_id"] for i in mode.get("source_annotation_ids", []) if i in anns and anns[i].get("trace_id")]
            mode["created_from"] = list(dict.fromkeys(ids))

    def patterns(self) -> dict[str, Any]:
        with self.lock:
            return self._pattern_doc()

    def _validate_mode(self, mode: dict[str, Any], modes: list[dict[str, Any]]) -> None:
        name = mode.get("name") or ""
        if not SNAKE_RE.match(name):
            raise StoreError(f"mode name {name!r} must be snake_case (lowercase letters, digits, underscores)")
        if any(m is not mode and m.get("name") == name for m in modes):
            raise StoreError(f"a mode named {name!r} already exists", 409)
        if mode.get("evaluator_type") not in (None, "", *EVALUATOR_TYPES):
            raise StoreError(f"evaluator_type must be one of {EVALUATOR_TYPES}")
        if mode.get("status") not in MODE_STATUSES:
            raise StoreError(f"status must be one of {MODE_STATUSES}")
        convs = self._conversations()
        for f in ("positive_conversation_ids", "close_negative_conversation_ids"):
            unknown = [c for c in mode[f] if c not in convs]
            if unknown:
                raise StoreError(f"{f} contains unknown conversation ids: {unknown}")
        overlap = set(mode["positive_conversation_ids"]) & set(mode["close_negative_conversation_ids"])
        if overlap:
            raise StoreError(f"conversations cannot be both positive and close negative: {sorted(overlap)}")

    def _rename_side_effects(self, old: str, new: str) -> None:
        old_path, new_path = self.path("labels", f"{old}.jsonl"), self.path("labels", f"{new}.jsonl")
        if old_path.exists():
            rows = _state.read_jsonl(old_path)
            if any(r.get("langfuse_written") for r in rows):
                raise StoreError(f"labels for {old!r} were already written to Langfuse under that score name; create a new mode instead of renaming", 409)
            if new_path.exists():
                raise StoreError(f"labels/{new}.jsonl already exists", 409)
            for r in rows:
                r["mode"] = new
            _state.write_jsonl(new_path, rows)
            old_path.unlink()
        sugg = self._read("suggestions.json", [])
        touched = False
        for s in sugg if isinstance(sugg, list) else []:
            if isinstance(s, dict) and s.get("mode") == old:
                s["mode"] = new
                touched = True
        if touched:
            self._write("suggestions.json", sugg)

    def _apply_mode_edit(self, mode: dict[str, Any], incoming: dict[str, Any], actor: str, modes: list[dict[str, Any]]) -> bool:
        stamp, changed = now(), False
        allowed = MODE_TEXT_FIELDS + MODE_LIST_FIELDS + (("status", "merged_into") if actor == "human" else ())
        if actor != "human" and "status" in incoming and incoming["status"] != mode["status"]:
            raise StoreError("only the reviewer changes a mode's status", 403)
        pending: dict[str, Any] = {}
        for field in allowed:
            if field not in incoming:
                continue
            value = _as_list(incoming[field]) if field in MODE_LIST_FIELDS else incoming[field]
            if isinstance(value, str):
                value = value.strip()
            if field == "evaluator_type" and value == "":
                value = None
            if value != mode.get(field):
                pending[field] = value
        if not pending:
            return False
        if actor != "human" and mode["status"] != "proposed":
            raise StoreError(f"mode {mode['name']!r} is {mode['status']}; only the reviewer can edit it", 409)
        candidate = dict(mode, **pending)
        self._validate_mode(candidate, [m for m in modes if m is not mode])
        if "name" in pending and mode.get("name"):
            self._rename_side_effects(mode["name"], pending["name"])
        for field, value in pending.items():
            mode["history"].append({"at": stamp, "by": actor, "field": field, "previous": mode.get(field), "value": value})
            mode[field] = value
            changed = True
        mode["updated_at"] = stamp
        return changed

    @staticmethod
    def _mode_items(body: Any) -> list[dict[str, Any]]:
        if isinstance(body, list):
            return [m for m in body if isinstance(m, dict)]
        if not isinstance(body, dict):
            raise StoreError("expected a mode, a list of modes, or {modes: [...]}")
        if isinstance(body.get("mode"), dict):
            return [body["mode"]]
        if isinstance(body.get("modes"), list):
            return [m for m in body["modes"] if isinstance(m, dict)]
        if "name" in body:
            return [body]
        # the reference server's live shape: {mode_name: {...}}
        flat = [dict(v, name=k) for k, v in body.items() if isinstance(v, dict) and k not in ("by",)]
        if flat:
            return flat
        raise StoreError("expected a mode, a list of modes, or {modes: [...]}")

    def save_patterns(self, body: Any, actor: str) -> dict[str, Any]:
        with self.lock:
            doc = self._pattern_doc()
            modes = doc["modes"]
            by_id = {m["id"]: m for m in modes}
            by_name = {m.get("name"): m for m in modes}
            action = body.get("action") if isinstance(body, dict) else None
            changed: list[dict[str, Any]] = []
            stamp = now()

            if action in ("set_status", "merge"):
                if actor != "human":
                    raise StoreError("only the reviewer accepts, rejects or merges modes", 403)
                mode = by_id.get(str(body.get("id"))) or by_name.get(body.get("name"))
                if mode is None:
                    raise StoreError("unknown mode", 404)
                if action == "set_status":
                    status = body.get("status")
                    if status not in ("proposed", "accepted", "rejected"):
                        raise StoreError("status must be proposed, accepted or rejected (use action merge to merge)")
                    if status == "accepted" and not (mode.get("definition") or "").strip():
                        raise StoreError("write a binary definition before accepting the mode")
                    self._apply_mode_edit(mode, {"status": status, "merged_into": None}, actor, modes)
                    changed.append(mode)
                else:
                    target = by_id.get(str(body.get("into"))) or by_name.get(body.get("into"))
                    if target is None or target is mode:
                        raise StoreError("merge needs a different target mode in 'into'", 400)
                    if target["status"] in ("rejected", "merged"):
                        raise StoreError(f"cannot merge into a {target['status']} mode", 409)
                    union = {f: list(dict.fromkeys(target[f] + mode[f])) for f in MODE_LIST_FIELDS}
                    overlap = set(union["positive_conversation_ids"]) & set(union["close_negative_conversation_ids"])
                    union["close_negative_conversation_ids"] = [c for c in union["close_negative_conversation_ids"] if c not in overlap]
                    self._apply_mode_edit(target, union, actor, modes)
                    self._apply_mode_edit(mode, {"status": "merged", "merged_into": target["name"]}, actor, modes)
                    changed += [mode, target]
            elif action is None:
                for item in self._mode_items(body):
                    mode = by_id.get(str(item.get("id"))) if item.get("id") else None
                    if mode is None and item.get("name") in by_name:
                        mode = by_name[item.get("name")]
                    if mode is None:
                        status = item.get("status", "proposed") if actor == "human" else "proposed"
                        if status not in ("proposed", "accepted"):
                            status = "proposed"
                        mode = self._fill_mode({
                            "id": new_id("mode"), "name": str(item.get("name") or "").strip(),
                            "status": status, "proposed_by": "human" if actor == "human" else "agent",
                            "created_at": stamp, "updated_at": stamp,
                        })
                        for field in MODE_TEXT_FIELDS[1:] + MODE_LIST_FIELDS:
                            if field in item:
                                mode[field] = _as_list(item[field]) if field in MODE_LIST_FIELDS else (item[field].strip() if isinstance(item[field], str) else item[field])
                        if mode["evaluator_type"] == "":
                            mode["evaluator_type"] = None
                        if mode["status"] == "accepted" and not mode["definition"]:
                            raise StoreError("write a binary definition before accepting the mode")
                        self._validate_mode(mode, modes + [mode])
                        mode["history"].append({"at": stamp, "by": actor, "field": "created", "previous": None,
                                                "value": {k: mode[k] for k in MODE_TEXT_FIELDS + MODE_LIST_FIELDS + ("status",)}})
                        modes.append(mode)
                        by_id[mode["id"]] = mode
                        by_name[mode["name"]] = mode
                        changed.append(mode)
                    elif self._apply_mode_edit(mode, item, actor, modes):
                        changed.append(mode)
            else:
                raise StoreError(f"unknown action {action!r}")
            self._sync_created_from(doc)
            self._write("patterns.json", doc)
            return {"ok": True, "changed": changed, "modes": modes}

    def accepted_modes(self) -> list[dict[str, Any]]:
        return [m for m in self.patterns()["modes"] if m.get("status") == "accepted"]

    # -- suggestions --------------------------------------------------------

    def suggestions(self) -> list[dict[str, Any]]:
        with self.lock:
            data = self._read("suggestions.json", [])
        if isinstance(data, dict):
            data = data.get("suggestions", [])
        return [s for s in data if isinstance(s, dict) and s.get("id") and s.get("conversation_id")] if isinstance(data, list) else []

    def save_suggestions(self, body: Any, actor: str, locate: Callable[[dict[str, Any], str, int | None], dict[str, Any] | None]) -> dict[str, Any]:
        with self.lock:
            raw = self._read("suggestions.json", [])
            if isinstance(raw, dict):
                raw = raw.get("suggestions", [])
            if not isinstance(raw, list):
                raw = []
            by_id = {s["id"]: s for s in raw if isinstance(s, dict) and s.get("id")}
            action = body.get("action") if isinstance(body, dict) else None
            changed: list[dict[str, Any]] = []
            created_annotations: list[dict[str, Any]] = []
            stamp = now()

            if action in ("accept", "reject", "reopen", "comment"):
                if actor != "human":
                    raise StoreError("only the reviewer accepts or rejects suggestions", 403)
                decisions = body.get("decisions")
                if not isinstance(decisions, list):
                    ids = body.get("ids") or ([body["id"]] if body.get("id") else [])
                    decisions = [{"id": i, "reviewer_comment": body.get("reviewer_comment")} for i in ids]
                if not decisions:
                    raise StoreError("no suggestion ids given")
                ann_doc = self._annotation_doc()
                records = ann_doc["annotations"]
                for d in decisions:
                    s = by_id.get(str(d.get("id")))
                    if s is None:
                        raise StoreError(f"unknown suggestion id {d.get('id')!r}", 404)
                    comment = d.get("reviewer_comment")
                    if comment is not None:
                        s["reviewer_comment"] = str(comment).strip()
                    previous = s.get("status")
                    if action == "accept" and previous != "accepted":
                        note = s.get("reviewer_comment") or f"[accepted suggestion: {s.get('mode')}] {s.get('reason') or ''}".strip()
                        rec = self._new_annotation(records, {
                            "conversation_id": s["conversation_id"], "trace_id": s.get("trace_id"),
                            "turn_index": s.get("turn_index"), "target": s.get("target"), "quote": s.get("quote"),
                            "start": s.get("start"), "end": s.get("end"), "note": note, "replace_no_failure": True,
                        }, source="accepted_suggestion", suggestion_id=s["id"])
                        created_annotations.append(rec)
                        s["annotation_id"] = rec["id"]
                    if action in ("reject", "reopen") and previous == "accepted":
                        for rec in records:
                            if self._is_ours(rec) and rec.get("suggestion_id") == s["id"] and not rec.get("deleted_at"):
                                self._soft_delete(rec, f"suggestion {action}ed by reviewer")
                                if rec.get("first_failure"):
                                    rec["first_failure"] = False
                                    self._ensure_first_failure(records, rec["conversation_id"])
                    if action != "comment":
                        s["status"] = {"accept": "accepted", "reject": "rejected", "reopen": "pending"}[action]
                        s["decided_at"] = None if action == "reopen" else stamp
                        s.setdefault("history", []).append({"at": stamp, "status": s["status"], "previous": previous, "reviewer_comment": s.get("reviewer_comment")})
                    changed.append(s)
                self._write("annotations.json", ann_doc)
            elif action is None:
                if isinstance(body, list):
                    items = body
                elif isinstance(body, dict) and isinstance(body.get("suggestions"), list):
                    items = body["suggestions"]
                elif isinstance(body, dict) and isinstance(body.get("suggestion"), dict):
                    items = [body["suggestion"]]
                else:
                    raise StoreError("expected a list of suggestions, {suggestions: [...]} or an action")
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    existing = by_id.get(str(item.get("id"))) if item.get("id") else None
                    if existing is None:
                        existing = next((s for s in raw if isinstance(s, dict) and s.get("mode") == item.get("mode")
                                         and s.get("conversation_id") == item.get("conversation_id")
                                         and s.get("quote") == item.get("quote")), None)
                    if existing is not None:
                        if existing.get("status") != "pending":
                            continue  # decided suggestions are never changed by a push
                        for f in ("reason", "quote", "start", "end", "turn_index", "target", "trace_id"):
                            if f in item and item[f] != existing.get(f):
                                existing[f] = item[f]
                        changed.append(existing)
                        continue
                    conv = self._conv(item.get("conversation_id"))
                    if not item.get("mode") or not str(item.get("quote") or "").strip():
                        raise StoreError("a suggestion needs mode, conversation_id and quote")
                    turn_index = item.get("turn_index")
                    if turn_index is not None:
                        turn_index = int(turn_index)
                        if not 0 <= turn_index < len(conv["turns"]):
                            raise StoreError(f"turn_index {turn_index} is outside {conv['id']}")
                    item = dict(item, turn_index=turn_index)
                    rec = {
                        "id": str(item.get("id") or new_id("sug")),
                        "mode": str(item["mode"]),
                        "conversation_id": conv["id"],
                        "trace_id": item.get("trace_id"),
                        "turn_index": item.get("turn_index"),
                        "target": item.get("target"),
                        "quote": str(item["quote"]),
                        "start": item.get("start"),
                        "end": item.get("end"),
                        "reason": str(item.get("reason") or ""),
                        "source": "agent",
                        "status": "pending",
                        "reviewer_comment": "",
                        "created_at": stamp,
                        "decided_at": None,
                        "history": [],
                    }
                    if rec["target"] is None or rec["start"] is None:
                        spot = locate(conv, rec["quote"], rec["turn_index"])
                        if spot:
                            rec.update({k: spot[k] for k in ("target", "turn_index", "start", "end")})
                    if rec["trace_id"] is None:
                        rec["trace_id"] = conv["turns"][rec["turn_index"]]["trace_id"] if rec["turn_index"] is not None else conv["primary_trace_id"]
                    if rec["trace_id"] not in conv["trace_ids"]:
                        raise StoreError(f"trace_id {rec['trace_id']} is not part of {conv['id']}'s session")
                    raw.append(rec)
                    by_id[rec["id"]] = rec
                    changed.append(rec)
            else:
                raise StoreError(f"unknown action {action!r}")
            self._write("suggestions.json", raw)
        return {"ok": True, "changed": changed, "created_annotations": created_annotations, "suggestions": self.suggestions()}

    # -- sample manifest ----------------------------------------------------

    def manifest(self) -> dict[str, Any]:
        with self.lock:
            data = self._read("sample_manifest.json", None)
        if not isinstance(data, dict) or "batches" not in data:
            return {"unit": "conversation", "batches": [], "dimension": None}
        return data

    def save_manifest(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise StoreError("expected a manifest object")
        with self.lock:
            current = self.manifest()
            existing = {b.get("name"): b for b in current.get("batches", []) if isinstance(b, dict)}
            if body.get("action") == "delete_batch":
                manifest = dict(current, batches=[b for b in current["batches"] if b.get("name") != body.get("name")])
            elif isinstance(body.get("batch"), dict):
                batches = list(current["batches"])
                names = [b.get("name") for b in batches]
                name = body["batch"].get("name")
                if name in names:
                    batches[names.index(name)] = body["batch"]
                else:
                    batches.append(body["batch"])
                manifest = dict(current, batches=batches)
                if "dimension" in body:
                    manifest["dimension"] = body["dimension"]
            else:
                manifest = {k: v for k, v in body.items() if k not in ("by",)}
            manifest.setdefault("unit", "conversation")
            manifest.setdefault("dimension", None)
            if manifest["unit"] != "conversation":
                raise StoreError("unit must be 'conversation'")
            if not isinstance(manifest.get("batches"), list):
                raise StoreError("batches must be a list")
            convs = self._conversations()
            seen: dict[str, str] = {}
            duplicates: list[dict[str, Any]] = []
            names: set[str] = set()
            clean = []
            for b in manifest["batches"]:
                if not isinstance(b, dict) or not str(b.get("name") or "").strip():
                    raise StoreError("every batch needs a name")
                name = str(b["name"]).strip()
                if name in names:
                    raise StoreError(f"two batches are named {name!r}")
                names.add(name)
                ids = [str(c) for c in b.get("conversation_ids") or []]
                unknown = [c for c in ids if c not in convs]
                if unknown:
                    raise StoreError(f"batch {name!r} has unknown conversation ids: {unknown[:10]}")
                for c in ids:
                    if c in seen:
                        duplicates.append({"conversation_id": c, "batches": [seen[c], name]})
                    else:
                        seen[c] = name
                prior = existing.get(name) or {}
                clean.append({
                    **{k: v for k, v in b.items() if k not in ("name", "conversation_ids")},
                    "name": name,
                    "method": b.get("method") or prior.get("method") or "",
                    "rationale": b.get("rationale") or prior.get("rationale") or "",
                    "created_at": b.get("created_at") or prior.get("created_at") or now(),
                    "conversation_ids": ids,
                })
            if duplicates:
                raise StoreError("a conversation may appear in only one batch", 409, duplicates=duplicates)
            manifest["batches"] = clean
            self._write("sample_manifest.json", manifest)
            return {"ok": True, "manifest": manifest}

    # -- labels -------------------------------------------------------------

    def _label_path(self, mode: str) -> Path:
        if not SNAKE_RE.match(mode or ""):
            raise StoreError("mode must be a snake_case name")
        return self.path("labels", f"{mode}.jsonl")

    def labels(self, mode: str) -> dict[str, Any]:
        with self.lock:
            rows = _state.read_jsonl(self._label_path(mode))
        ours = [r for r in rows if r.get("conversation_id")]
        return {"mode": mode, "labels": ours, "foreign_rows_ignored": len(rows) - len(ours)}

    def save_labels(self, mode_name: str, body: Any) -> dict[str, Any]:
        with self.lock:
            mode = next((m for m in self.patterns()["modes"] if m.get("name") == mode_name), None)
            if mode is None:
                raise StoreError(f"unknown mode {mode_name!r}", 404)
            if mode.get("status") != "accepted":
                raise StoreError(f"mode {mode_name!r} is {mode.get('status')}; accept it before labelling", 409)
            path = self._label_path(mode_name)
            rows = _state.read_jsonl(path)
            foreign = [r for r in rows if not r.get("conversation_id")]
            if foreign:
                raise StoreError(f"labels/{mode_name}.jsonl holds {len(foreign)} rows this app did not write (course demo?). Move them before labelling this mode.", 409)
            by_conv = {r["conversation_id"]: r for r in rows}
            if isinstance(body, dict) and isinstance(body.get("labels"), list):
                items = body["labels"]
            elif isinstance(body, dict):
                items = [body]
            else:
                raise StoreError("expected a label object or {labels: [...]}")
            changed = []
            for item in items:
                conv = self._conv(item.get("conversation_id"))
                if item.get("action") == "clear":
                    if conv["id"] in by_conv:
                        changed.append(by_conv.pop(conv["id"]))
                    continue
                raw_label = item.get("label")
                decision = {"present": "present", "absent": "absent", 1: "present", 0: "absent", "1": "present", "0": "absent", True: "present", False: "absent"}.get(raw_label)
                if decision is None:
                    raise StoreError("label must be present|absent (or 1|0)")
                evidence = str(item.get("evidence") or "").strip()
                if decision == "present" and not evidence:
                    raise StoreError(f"{conv['id']}: an evidence note is required when the mode is present")
                stamp = now()
                row = by_conv.get(conv["id"])
                if row is None:
                    row = {"history": [], "langfuse_written": False, "langfuse_writes": []}
                elif row.get("decision") == decision and row.get("evidence") == evidence:
                    continue
                else:
                    row.setdefault("history", []).append({"at": row.get("decided_at"), "decision": row.get("decision"), "evidence": row.get("evidence")})
                row.update({
                    "conversation_id": conv["id"],
                    "session_id": conv["session_id"],
                    "trace_id": conv["primary_trace_id"],
                    "primary_trace_id": conv["primary_trace_id"],
                    "trace_ids": conv["trace_ids"],
                    "mode": mode_name,
                    "decision": decision,
                    "label": 1 if decision == "present" else 0,
                    "evidence": evidence,
                    "source": "human",
                    "decided_at": stamp,
                    "langfuse_written": False,
                })
                by_conv[conv["id"]] = row
                changed.append(row)
            order = {cid: i for i, cid in enumerate(self._conversations())}
            _state.write_jsonl(path, sorted(by_conv.values(), key=lambda r: order.get(r["conversation_id"], 10**6)))
        return {"ok": True, "changed": changed, **self.labels(mode_name)}

    def mark_written(self, mode_name: str, conversation_ids: set[str], stamp: str) -> None:
        with self.lock:
            path = self._label_path(mode_name)
            rows = _state.read_jsonl(path)
            for r in rows:
                if r.get("conversation_id") in conversation_ids:
                    r["langfuse_written"] = True
                    r["langfuse_written_at"] = stamp
                    r.setdefault("langfuse_writes", []).append({"at": stamp, "value": r.get("label")})
            _state.write_jsonl(path, rows)

    # -- course demo detection ----------------------------------------------

    def demo_files(self) -> list[dict[str, Any]]:
        """Files in the state dir that hold course demo content, not this app's."""
        found = []
        for name in DEMO_FILES:
            if self.path(name).exists():
                found.append({"path": name, "why": "course demo or reference-UI file"})
        doc = _state.read_json(self.path("annotations.json"), default=None) if self.path("annotations.json").exists() else None
        records = doc if isinstance(doc, list) else (doc or {}).get("annotations", []) if isinstance(doc, dict) else []
        foreign = [a for a in records if not self._is_ours(a)]
        if foreign:
            found.append({"path": "annotations.json", "why": f"{len(foreign)} annotations without a conversation_id"})
        sugg = _state.read_json(self.path("suggestions.json"), default=None) if self.path("suggestions.json").exists() else None
        if isinstance(sugg, list) and any(isinstance(s, dict) and not s.get("conversation_id") for s in sugg):
            found.append({"path": "suggestions.json", "why": "suggestions without a conversation_id"})
        labels = self.path("labels")
        if labels.exists():
            for p in sorted(labels.glob("*.jsonl")):
                rows = _state.read_jsonl(p)
                if rows and any(not r.get("conversation_id") for r in rows):
                    found.append({"path": f"labels/{p.name}", "why": f"{sum(1 for r in rows if not r.get('conversation_id'))} label rows without a conversation_id"})
        judges = self.path("judges")
        if judges.exists():
            ours = {m.get("name") for m in self.patterns()["modes"]}
            for p in sorted(judges.glob("*.json")):
                stem = p.stem.removeprefix("_history_").rsplit("-v", 1)[0]
                if stem not in ours:
                    found.append({"path": f"judges/{p.name}", "why": "judge for a mode not in patterns.json"})
        return found

    def start_fresh(self) -> dict[str, Any]:
        """Move the course demo files to _course_demo/ (only on explicit request)."""
        with self.lock:
            files = self.demo_files()
            dest_root = self.path("_course_demo")
            moved = []
            for f in files:
                src = self.path(f["path"])
                if not src.exists():
                    continue
                dest = dest_root / f["path"]
                if dest.exists():
                    dest = dest.with_name(f"{dest.stem}.{datetime.now().strftime('%Y%m%d%H%M%S')}{dest.suffix}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                if f["path"] == "annotations.json":
                    doc = _state.read_json(src, default={})
                    records = doc if isinstance(doc, list) else doc.get("annotations", [])
                    shutil.copy2(src, dest)
                    _state.write_json(src, {"annotations": [a for a in records if self._is_ours(a)]})
                elif f["path"] == "suggestions.json":
                    data = _state.read_json(src, default=[])
                    shutil.copy2(src, dest)
                    _state.write_json(src, [s for s in data if isinstance(s, dict) and s.get("conversation_id")])
                else:
                    shutil.move(str(src), str(dest))
                moved.append({"from": f["path"], "to": str(dest.relative_to(self.dir))})
            return {"ok": True, "moved": moved}
