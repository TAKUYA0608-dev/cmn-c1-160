"""ScopeClassifyNode — main slot sub-node.

Classifies the governance **scope** (permitted-use / prohibited-use / data-handling
/ cross-border / disclosure), the **data sensitivity** tier, and **APPI applicability**
for the question. Heuristic keyword scoring is the auditable baseline; the LLM
disambiguates only when the heuristic is low-confidence. When confidence stays below
threshold (or context is insufficient) the node sets `clarification_needed` rather
than guessing a compliance verdict downstream.

Threshold: default 0.6, DI-overridable via the
`scope_confidence_threshold` constructor argument (config-free execute(): execute() takes no config).
"""

from __future__ import annotations

from typing import Any, Callable, cast

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus

from src.services.service import LLM_NOT_CONFIGURED, LLMClient
from src.utils.audit import emit_trace_event
from framework.schemas.trust_level import TrustLevel

_DEFAULT_THRESHOLD = 0.6

_SCOPE_KEYWORDS = {
    # Explicit prohibition INTENT only. Sensitivity indicators (medical /
    # criminal / 要配慮) are NOT prohibition indicators — a sensitivity label
    # alone must never route to a categorical prohibition; the Art.20(2)-aware
    # verdict handles sensitive data non-categorically.
    "prohibited-use": ("prohibited", "禁止", "banned", "shadow ai", "unapproved tool"),
    "cross-border": ("cross-border", "overseas", "outside japan", "abroad", "海外", "越境"),
    "disclosure": ("disclose", "data subject", "access right", "deletion right", "開示", "本人", "削除"),
    "data-handling": ("minimi", "pseudonymized", "anonymized", "retention", "取り扱い", "最小化"),
    "permitted-use": ("can i", "allowed", "permitted", "may i", "ok to", "使ってよい", "approved"),
}
_SENSITIVITY_KEYWORDS = {
    "sensitive-personal-data": ("sensitive-personal-data", "medical", "health", "criminal", "要配慮", "病歴"),
    "personal-data": ("customer", "email", "hr", "personal", "name", "顧客", "個人", "氏名"),
    "pseudonymized": ("pseudonymized", "仮名加工"),
    "anonymized": ("anonymized", "匿名加工"),
}


# The four meaningful scopes; "permitted-use" is the baseline/fallback (not keyword-competed).
_SPECIFIC_SCOPES = ("prohibited-use", "cross-border", "disclosure", "data-handling")


def _score_scope(text: str) -> tuple[str, float]:
    """Classify scope from keyword hits.

    A specific-scope match dominates: 1 hit → 0.75 confidence, 2+ → 1.0. With no
    specific match, fall back to permitted-use (0.7 when a permission-intent keyword
    is present, else 0.0 → clarification downstream).
    """
    low = text.lower()
    specific = {s: sum(1 for kw in _SCOPE_KEYWORDS[s] if kw in low) for s in _SPECIFIC_SCOPES}
    best = max(specific, key=cast(Callable[[str], int], specific.get))
    if specific[best] > 0:
        return best, round(min(1.0, 0.5 + 0.25 * specific[best]), 4)
    perm_hits = sum(1 for kw in _SCOPE_KEYWORDS["permitted-use"] if kw in low)
    return "permitted-use", (0.7 if perm_hits > 0 else 0.0)


def _detect_sensitivity(text: str) -> str:
    low = text.lower()
    for tier in ("sensitive-personal-data", "personal-data", "pseudonymized", "anonymized"):
        if any(kw in low for kw in _SENSITIVITY_KEYWORDS[tier]):
            return tier
    return "none"


class ScopeClassifyNode(FunctionNode):
    """Heuristic + LLM scope / sensitivity / APPI-applicability classification."""

    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def __init__(
        self, llm_client: LLMClient | None = None, scope_confidence_threshold: float = _DEFAULT_THRESHOLD
    ) -> None:
        super().__init__()
        # None = no LLM bound. Resolved by the graph (explicit kw > config["llm"]);
        # a bare node stays unbound and keeps the heuristic result (no stub).
        self._llm: LLMClient | None = llm_client
        self._threshold = scope_confidence_threshold

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("error_code"):
            return {}

        question = state.get("validated_question") or state.get("question") or ""
        # Threshold is dependency-injected via __init__ (config-free execute(): execute takes no config param).
        threshold = self._threshold

        scope, confidence = _score_scope(question)
        sensitivity = _detect_sensitivity(question)
        appi_applicable = sensitivity in ("personal-data", "sensitive-personal-data", "pseudonymized")

        rationale = f"heuristic scope={scope} (conf={confidence}); sensitivity={sensitivity}"
        # LLM disambiguation only when the heuristic is weak (auditable baseline first).
        if confidence < threshold and question and self._llm is None:
            # No LLM to disambiguate: keep the heuristic result (and its confidence,
            # so the clarification path still applies) and record why.
            emit_trace_event("llm_not_configured", {"reason_code": LLM_NOT_CONFIGURED, "scope": scope}, state)
            rationale += f"; llm_unavailable={LLM_NOT_CONFIGURED}"
        elif confidence < threshold and question:
            hint = (
                (
                    cast(LLMClient, self._llm).generate(
                        "Classify the governance scope of this personal-AI question into one of "
                        "[permitted-use, prohibited-use, data-handling, cross-border, disclosure]. "
                        f"Question: {question}\nReturn just the label."
                    )
                    or ""
                )
                .strip()
                .lower()
            )
            for cand in _SCOPE_KEYWORDS:
                if cand in hint:
                    scope = cand
                    confidence = max(confidence, threshold)  # LLM resolved the ambiguity
                    rationale += f"; llm_resolved={cand}"
                    break

        emit_trace_event(
            "scope_classified",
            {"scope": scope, "sensitivity": sensitivity, "appi_applicable": appi_applicable, "confidence": confidence},
            state,
        )

        out: dict[str, Any] = {
            "scope_label": scope,
            "data_sensitivity": sensitivity,
            "appi_applicable": appi_applicable,
            "scope_confidence": confidence,
            "classification_rationale": rationale,
            "status": AgentStatus.SUCCESS.value,
        }
        if confidence < threshold:
            out["clarification_needed"] = True
            out["clarification_prompt"] = (
                "To answer accurately, could you clarify: (1) which AI tool, (2) what data type "
                "(personal data / sensitive personal data / anonymized), and (3) the purpose? "
                "対象の AI ツール・データ種別・利用目的を教えてください。"
            )
        else:
            out["clarification_needed"] = False
        return out
