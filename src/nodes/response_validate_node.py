"""ResponseValidateNode — post_process slot. **S-3 gate + S-4 audit.**

The terminal node. Three S-3 responsibilities (docs/02 Step):
  1. Citation presence check — a grounded answer MUST carry at least one [C#]
     citation; a substantive answer without one is rejected (replaced with a safe
     refusal). Out-of-scope refusals and clarification prompts are exempt.
  2. Sensitive-value redaction — マイナンバー (12-digit), internal IPv4 addresses, and
     obvious secret tokens are redacted out of the answer before it leaves the agent.
  3. Mandatory APPI legal-disclaimer footer — **fail-closed**: every non-empty answer
     MUST carry the not-legal-advice footer; it is injected unconditionally.
Then S-4: emit one redacted per-invocation audit event. Always fires (even on the
error path) — silent failure is prohibited.

This is domain validation in `execute()` — distinct from the framework `@final`
credential gate (`_security_gate_output`), which still runs automatically.
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import TrustLevel

from src.utils.audit import emit_trace_event

_CITATION = re.compile(r"\[C\d+\]")
# マイナンバー = a 12-digit Japanese national ID (optionally space/hyphen grouped).
# Over-redaction is the intended fail-safe direction: a false positive on another
# 12-digit run only redacts more, never leaks.
_MYNUMBER = re.compile(r"\b(?:\d[ \-]?){12}\b")
_INTERNAL_IP = re.compile(r"\b(?:10|172|192)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
_SECRET_TOKEN = re.compile(r"(?i)\b(?:api[_-]?key|secret|bearer|token)\s*[:=]\s*\S+")
_REDACTED = "[REDACTED:sensitive]"

_DISCLAIMER = (
    "\n\n---\n*This is an automated personal-AI governance / APPI compliance reference, not "
    "binding legal advice. Verify against the cited regulations (the APPI in force — "
    "平成15年法律第57号, PPC guidelines, etc.) "
    "and consult your privacy office or qualified counsel before acting.*"
)

_REJECTED = (
    "I can't ground this answer in a cited regulation/policy, so I'm withholding it to avoid "
    "unsupported compliance statements. Please rephrase toward a personal-AI governance or APPI "
    "topic covered by the knowledge base."
)

# Citation-gate substantive-answer threshold (characters). An answer shorter than this
# is treated as a short refusal / clarification — not a grounded compliance claim — so
# the [C#] citation requirement does not apply to it. Named module constant (not an
# inline literal) so the gate's boundary is explicit and tunable.
_MIN_SUBSTANTIVE = 40


def _redact(text: str) -> tuple[str, int]:
    count = 0

    def _sub(_m: "re.Match[str]") -> str:
        nonlocal count
        count += 1
        return _REDACTED

    text = _MYNUMBER.sub(_sub, text)
    text = _INTERNAL_IP.sub(_sub, text)
    text = _SECRET_TOKEN.sub(_sub, text)
    return text, count


class ResponseValidateNode(FunctionNode):
    """S-3 citation/redaction/disclaimer gate + S-4 audit (terminal node)."""

    # CoE CR-R1-01: declare the S-1 trust gate explicitly (agent requires VERIFIED_EXTERNAL).
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        answer = state.get("answer") or ""
        hit_count = state.get("retrieval_hit_count") or 0
        clarification = bool(state.get("clarification_needed"))

        # ── S-3 (1): citation presence ──────────────────────────────────────
        exempt = (
            state.get("error_code") or clarification or not answer or len(answer) < _MIN_SUBSTANTIVE or hit_count <= 0
        )
        if not exempt and not _CITATION.search(answer):
            emit_trace_event("citation_gate_reject", {"reason": "no_citation"}, state)
            answer = _REJECTED
            validation_status = "rejected"
        else:
            validation_status = "passed"

        # ── S-3 (2): sensitive-value redaction ──────────────────────────────
        answer, redaction_count = _redact(answer)
        if redaction_count and validation_status == "passed":
            validation_status = "redacted"

        # ── S-3 (3): mandatory legal-disclaimer footer (fail-closed) ────────
        disclaimer_applied = False
        if answer and "not binding legal advice" not in answer:
            answer = answer + _DISCLAIMER
            disclaimer_applied = True
        elif answer and "not binding legal advice" in answer:
            disclaimer_applied = True

        # ── S-4: redacted per-invocation audit event (always fires) ─────────
        def _count(field: str) -> int:
            try:
                v = json.loads(state.get(field) or "[]")
                return len(v) if isinstance(v, (list, dict)) else 0
            except (json.JSONDecodeError, TypeError):
                return 0

        payload: dict[str, Any] = {
            "scope": state.get("scope_label"),
            "verdict": state.get("verdict"),
            "data_sensitivity": state.get("data_sensitivity"),
            "appi_applicable": state.get("appi_applicable"),
            "question_length": len(state.get("validated_question") or state.get("question") or ""),
            "answer_length": len(answer),
            "citation_count": _count("citations"),
            "retrieval_hit_count": hit_count,
            "clarification_needed": clarification,
            "validation_status": validation_status,
            "redaction_count": redaction_count,
        }
        if state.get("error_code"):
            payload["error_code"] = state["error_code"]
        emit_trace_event("agent_invoke_complete", payload, state)

        return {
            "answer": answer,
            "validation_status": validation_status,
            "redaction_count": redaction_count,
            "disclaimer_applied": disclaimer_applied,
            "audit_logged": True,
            "status": AgentStatus.SUCCESS.value,
        }


# Backward-compat alias.
PostProcessNode = ResponseValidateNode
