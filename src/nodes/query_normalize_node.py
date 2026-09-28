"""QueryNormalizeNode — pre_process slot / S-1 input boundary.

Entity extraction ONLY: pull intent + context
tokens (AI tool, data type) out of the NL question, normalize terminology
synonyms, and reject prompt-injection before any LLM sees the input. Scope
*classification* is the next node's responsibility (ScopeClassify).

Node contract: extend FunctionNode; override
`execute(self, state) -> dict`; return ONLY changed fields + an
AgentStatus enum value.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import TrustLevel
from src.utils.audit import emit_trace_event

_MAX_LEN = 2000

_INJECTION = re.compile(
    r"(?i)(ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions"
    r"|disregard\s+(?:the\s+)?(?:system|previous)\s+(?:prompt|instructions)"
    r"|reveal\s+(?:your\s+)?system\s+prompt"
    r"|you\s+are\s+now\s+(?:a|an|in)\b"
    r"|<\s*script\b|</\s*script\s*>)"
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Terminology synonym normalization (right-hand canonical form).
_SYNONYMS = {
    "個人情報保護法": "appi",
    "個情法": "appi",
    "要配慮個人情報": "sensitive-personal-data",
    "越境": "cross-border",
    "越境移転": "cross-border",
    "仮名加工": "pseudonymized",
    "匿名加工": "anonymized",
    "生成AI": "generative-ai",
}

# Intent hints (entity extraction only — no decision made here).
_INTENT_HINTS = {
    "permitted-use": ("can i", "allowed", "permitted", "may i", "ok to", "使ってよい", "使っていい"),
    "data-handling": ("how should", "handle", "minimi", "pseudonym", "anonym", "取り扱い", "扱い"),
    "cross-border": ("overseas", "outside japan", "cross-border", "transfer abroad", "越境", "海外"),
    "disclosure": ("disclose", "data subject", "access right", "deletion", "開示", "本人"),
}
_TOOL_HINTS = ("openhuman", "chatgpt", "copilot", "gemini", "claude", "personal ai", "個人ai", "アシスタント")
_DATA_HINTS = ("customer", "email", "source code", "hr", "medical", "personal", "顧客", "メール", "人事", "個人")


def _extract_context(text: str) -> dict[str, Any]:
    low = text.lower()
    intent = next((i for i, hints in _INTENT_HINTS.items() if any(h in low for h in hints)), "permitted-use")
    tool_hints = sorted({t for t in _TOOL_HINTS if t in low})
    data_hints = sorted({d for d in _DATA_HINTS if d in low})
    return {"intent": intent, "tool_hints": tool_hints, "data_hints": data_hints}


class QueryNormalizeNode(FunctionNode):
    """S-1: validate + normalize the question; extract context; reject injection."""

    # CoE CR-R1-01: declare the S-1 trust gate explicitly (agent requires VERIFIED_EXTERNAL).
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("error_code"):
            return {}

        ic = state.get("input_context") or {}
        raw = state.get("question") or state.get("user_input") or ""

        if not raw or not str(raw).strip():
            return {
                "error_code": "INPUT_EMPTY",
                "error_message": "QueryNormalizeNode: question is empty or missing",
                "status": AgentStatus.ERROR.value,
            }
        if len(str(raw)) > _MAX_LEN:
            return {
                "error_code": "INPUT_TOO_LONG",
                "error_message": f"QueryNormalizeNode: question exceeds {_MAX_LEN} chars",
                "status": AgentStatus.ERROR.value,
            }
        if _INJECTION.search(str(raw)):
            return {
                "error_code": "INJECTION_DETECTED",
                "error_message": "QueryNormalizeNode: prompt-injection pattern rejected",
                "status": AgentStatus.ERROR.value,
            }

        validated = unicodedata.normalize("NFKC", str(raw))
        validated = _CONTROL.sub("", validated).strip()
        validated = re.sub(r"\s+", " ", validated)
        for jp, canon in _SYNONYMS.items():
            if jp in validated:
                validated = validated.replace(jp, canon)

        out: dict[str, Any] = {
            "question": validated,
            "validated_question": validated,
            "extracted_context": json.dumps(_extract_context(validated), ensure_ascii=False),
            "status": AgentStatus.SUCCESS.value,
        }
        ctx_hint = state.get("business_context") or ic.get("business_context")
        if ctx_hint:
            out["business_context"] = str(ctx_hint)
        emit_trace_event("query_normalized", {"length": len(str(out.get("validated_question") or ""))}, state)
        return out
