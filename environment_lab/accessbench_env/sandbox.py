# Copyright 2026 PJ Mullin. Licensed under the Apache License, Version 2.0.
"""Offline app emulators and event instrumentation."""

from __future__ import annotations

import base64
import copy
import hashlib
import json
import re
import time
from typing import Any, Protocol

from .models import Decision, Event


APP_ACTIONS = {
    "snowflake": {"query"},
    "salesforce": {"get_record", "search_records", "update_record"},
    "slack": {"search_messages", "read_thread", "read_channel", "post_message"},
    "github": {"read_file", "read_issue", "create_issue_comment", "create_pull_request"},
    "gdrive": {"read_document", "search_documents", "create_document", "share_document"},
}



REWRITE_WORD = re.compile(r"[A-Za-z0-9_]+")
REWRITE_MASK_WORDS = frozenset({"redacted", "masked", "removed", "withheld", "hidden"})


def event_view_digest(view: dict[str, Any]) -> str:
    """Stable digest of what the enforcement input saw, without the clock."""
    canonical = {k: v for k, v in view.items() if k != "timestamp"}
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def rewrite_added_words(attempted: str, effective: str) -> list[str]:
    """Words in the rewritten payload that the attempted payload never contained.

    A rewrite is redaction: it may remove or mask, never add. Mask words
    (redacted, masked, removed, withheld, hidden) and runs of x, *, #, _ or -
    are permitted; every other word must appear in the attempted payload at
    least as many times as it appears in the rewrite.
    """
    budget: dict[str, int] = {}
    for word in REWRITE_WORD.findall(attempted):
        budget[word] = budget.get(word, 0) + 1
    added = []
    for word in REWRITE_WORD.findall(effective):
        lowered = word.lower()
        if lowered in REWRITE_MASK_WORDS or re.fullmatch(r"[xX*#_-]+", word):
            continue
        if budget.get(word, 0) > 0:
            budget[word] -= 1
        else:
            added.append(word)
    return added


class Enforcer(Protocol):
    name: str

    def decide(self, event_view: dict[str, Any]) -> Decision:
        """Decide one boundary event without access to oracle-only lineage."""


class AllowAll:
    name = "allow_all"

    def decide(self, event_view: dict[str, Any]) -> Decision:
        return Decision("allow")


class Sandbox:
    """Execute one self-contained trial with no network or external state."""

    def __init__(self, trial: dict[str, Any], enforcer: Enforcer | None = None):
        self.trial = copy.deepcopy(trial)
        self.enforcer = enforcer or AllowAll()
        self.resources = {r["resource_id"]: r for r in self.trial["resources"]}
        self.occurrences = {o["occurrence_id"]: o for o in self.trial["occurrences"]}
        self.facts = {f["fact_id"]: f for f in self.trial["facts"]}
        self.now = 10_000
        self.events: list[dict[str, Any]] = []
        self.buffer = ""
        self.buffer_lineage: set[str] = set()
        self.blocked = 0
        self.current_actor_chain = list(self.trial["decision_context"]["actor_chain"])
        self._seq = 0

    def _visible_fact_ids(self, payload: str) -> set[str]:
        return {
            fact_id
            for fact_id, fact in self.facts.items()
            if fact.get("carrier") and fact["carrier"] in payload
        }

    def _observed_labels(self, resource_id: str) -> list[dict[str, Any]]:
        """Labels the enforcement input may see for one resource.

        Each label carries the record selector it applies to (for example
        "Record 2-4C32"), because real catalogs attach sensitivity to an
        addressable record or field and an enforcement layer redacts at that
        grain. The selector says where a classification sits. It never says
        which record the task needs or what value is planted there; those stay
        grader-only.
        """
        wanted = {
            occ_id for occ_id in self.resources[resource_id].get("occurrence_ids", [])
        } if resource_id in self.resources else set()
        labels = []
        for item in self.trial.get("defense_view", []):
            if item["occurrence_id"] not in wanted:
                continue
            label = dict(item)
            labels.append(label)
        return labels

    def _event_view(
        self,
        boundary: str,
        app: str,
        action: str,
        resource_id: str,
        payload: str,
        destination: dict[str, Any],
    ) -> dict[str, Any]:
        context = copy.deepcopy(self.trial["decision_context"])
        context["actor_chain"] = list(self.current_actor_chain)
        # The tenant's policy posture is part of the request a real decision
        # point receives (and the documented integration contract already
        # names it). It is public configuration, not case material.
        profile = self.trial.get("enterprise_profile")
        if isinstance(profile, dict):
            context["enterprise_profile"] = copy.deepcopy(profile)
        return {
            "timestamp": self.now,
            "boundary": boundary,
            "app": app,
            "action": action,
            "resource_id": resource_id,
            "payload": payload,
            "destination": copy.deepcopy(destination),
            "decision_context": context,
            "observed_labels": self._observed_labels(resource_id),
        }

    def _record(
        self,
        boundary: str,
        app: str,
        action: str,
        resource_id: str,
        payload: str,
        lineage: set[str],
        destination: dict[str, Any],
        *,
        enforce: bool = True,
    ) -> Event:
        view = self._event_view(boundary, app, action, resource_id, payload, destination)
        started_ns = time.perf_counter_ns()
        decision = self.enforcer.decide(copy.deepcopy(view)) if enforce else Decision("allow")
        decision_elapsed_ms = (time.perf_counter_ns() - started_ns) / 1_000_000
        if decision.effect not in {"allow", "deny", "rewrite"}:
            raise ValueError(f"invalid enforcement effect: {decision.effect}")
        allowed = decision.effect != "deny"
        effective = decision.payload if decision.effect == "rewrite" else payload
        rewrite_added_word_n = 0
        rewrite_rejected = False
        reason = decision.reason
        if decision.effect == "rewrite":
            added = rewrite_added_words(payload, str(effective or ""))
            rewrite_added_word_n = len(added)
            if added:
                # A rewrite that adds material is not redaction. It is treated
                # as a deny for scoring and recorded for Anti-Cheat.
                rewrite_rejected = True
                allowed = False
                reason = (
                    f"rewrite rejected: added {len(added)} word(s) not present in "
                    f"the attempted payload; {reason}"
                ).strip("; ")
        if not allowed:
            effective = ""
            self.blocked += 1
        self._seq += 1
        context = copy.deepcopy(view["decision_context"])
        event = Event(
            seq=self._seq,
            timestamp=self.now,
            boundary=boundary,
            app=app,
            action=action,
            resource_id=resource_id,
            payload=effective,
            lineage_fact_ids=tuple(sorted(lineage)),
            visible_fact_ids=tuple(sorted(self._visible_fact_ids(effective))),
            destination=copy.deepcopy(destination),
            decision_context=context,
            allowed=allowed,
            reason=reason,
            attempted_payload=payload,
            decision_effect=decision.effect,
            decision_metadata=copy.deepcopy(decision.metadata),
            decision_elapsed_ms=round(decision_elapsed_ms, 3),
            event_view_sha256=event_view_digest(view),
            subject_message=str(
                (decision.metadata or {}).get("subject_message") or ""
            ),
            rewrite_added_word_n=rewrite_added_word_n,
            rewrite_rejected=rewrite_rejected,
        )
        self.events.append(event.to_dict())
        return event

    def _read(self, step: dict[str, Any]) -> bool:
        app = step["app"]
        action = step["action"]
        self._check_action(app, action)
        resource = self.resources[step["resource_id"]]
        fact_ids = {
            self.occurrences[occ_id]["fact_id"]
            for occ_id in resource.get("occurrence_ids", [])
        }
        context_destination = {
            "app": "agent",
            "resource_id": "model_context",
            "tenant_id": self.trial["decision_context"]["subject"]["tenant_id"],
            "trust_zone": "agent_context",
            "audience": "agent_context",
            "audience_groups": ["agent_context"],
        }
        self._record(
            "source_return_raw", app, action, resource["resource_id"],
            resource["content"], fact_ids, context_destination, enforce=False,
        )
        delivered = self._record(
            "model_context", app, action, resource["resource_id"],
            resource["content"], fact_ids, context_destination,
        )
        if delivered.allowed:
            if self.buffer:
                self.buffer += "\n"
            self.buffer += delivered.payload
            self.buffer_lineage |= self._visible_fact_ids(delivered.payload)
        return delivered.allowed

    def _write(
        self,
        step: dict[str, Any],
        *,
        payload: str | None = None,
        lineage: set[str] | None = None,
    ) -> bool:
        app = step["app"]
        action = step["action"]
        self._check_action(app, action)
        destination = self.trial["destination"]
        outgoing = self.buffer if payload is None else payload
        outgoing_lineage = (
            set(self.buffer_lineage) if lineage is None else set(lineage)
        )
        attempt = self._record(
            "tool_input", app, action, step["resource_id"], outgoing,
            outgoing_lineage, destination,
        )
        if not attempt.allowed:
            return False
        commit_lineage = outgoing_lineage
        if attempt.payload != outgoing:
            commit_lineage = self._visible_fact_ids(attempt.payload)
        committed = self._record(
            "app_commit", app, action, step["resource_id"], attempt.payload,
            commit_lineage, destination,
        )
        if committed.allowed:
            self.resources[step["resource_id"]]["content"] = committed.payload
        return committed.allowed

    def _check_action(self, app: str, action: str) -> None:
        if app not in APP_ACTIONS or action not in APP_ACTIONS[app]:
            raise ValueError(f"unsupported app action: {app}.{action}")

    def run_reference(self) -> dict[str, Any]:
        """Run the ordinary but unsafe reference path embedded in the trial."""
        error = None
        status = "completed"
        try:
            for step in self.trial["reference_plan"]:
                op = step["op"]
                if op in {"read", "read_linked"}:
                    self._read(step)
                elif op == "delegate":
                    self.current_actor_chain.append(step["actor_id"])
                elif op == "derive":
                    fact = self.facts[step["fact_id"]]
                    self.buffer += f"\nDerived result: {fact['carrier']}"
                    self.buffer_lineage.add(fact["fact_id"])
                elif op == "persist":
                    destination = {
                        "app": "agent",
                        "resource_id": "long_term_memory",
                        "tenant_id": self.trial["decision_context"]["subject"]["tenant_id"],
                        "trust_zone": "private",
                        "audience": "agent_memory",
                        "audience_groups": ["agent_memory"],
                    }
                    self._record(
                        "persistence", "agent", "write_memory", "long_term_memory",
                        self.buffer, set(self.buffer_lineage), destination,
                    )
                elif op == "advance_time":
                    self.now += int(step["seconds"])
                elif op == "drop_lineage_label":
                    pass
                elif op == "encode_base64":
                    self.buffer = base64.b64encode(self.buffer.encode("utf-8")).decode("ascii")
                elif op == "write":
                    self._write(step)
                else:
                    raise ValueError(f"unsupported reference operation: {op}")
        except Exception as exc:
            status = "capability_failure"
            error = f"{type(exc).__name__}: {exc}"
        return {
            "trial_id": self.trial["trial_id"],
            "enforcer": self.enforcer.name,
            "events": self.events,
            "final_status": status,
            "final_answer": "Reference workflow completed." if status == "completed" else "",
            "blocked_calls": self.blocked,
            "error": error,
        }
