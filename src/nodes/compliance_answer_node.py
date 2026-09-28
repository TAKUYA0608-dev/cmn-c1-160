"""ComplianceAnswerNode — main slot sub-node.

Synthesizes the cited Markdown answer: a structured verdict
(permitted / conditional / prior_consent_required_unless_verified_exception / prohibited), the required handling, remediation steps,
and an "Applicable Clauses" section with inline [C#] citations. Citations are built
deterministically from the retrieved clause set so every [C#] marker resolves to a
real clause — ResponseValidate's S-3 gate then verifies citation presence. The LLM
supplies only a short rationale narrative (it cannot introduce uncited claims); with
no LLM bound the rationale slot carries a named `LLM_NOT_CONFIGURED` notice instead
(S-4 `llm_not_configured`) and the deterministic answer is delivered in full.

Branches:
  - clarification_needed → return the clarification prompt as the answer (no citation).
  - zero-hit retrieval    → safe out-of-scope answer (no fabricated clauses).
"""

from __future__ import annotations

from typing import Any

import json

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus

from src.services.service import (
    ART20_SENSITIVE_REF,
    ART28_CROSS_BORDER_REF,
    LLM_NOT_CONFIGURED,
    PPC_GUIDELINES_REF,
    LLMClient,
)
from framework.schemas.trust_level import TrustLevel
from src.utils.audit import emit_trace_event

_OUT_OF_SCOPE = (
    "This question falls outside the indexed governance / APPI knowledge base (the APPI in "
    "force — 平成15年法律第57号, PPC guidelines, cross-border transfer rules, corporate AI-use "
    "policy). I'm withholding an answer rather than cite sources I can't ground. Please "
    "rephrase toward a personal-AI governance or APPI compliance topic."
)


def _verdict_for(scope: str | None, sensitivity: str | None) -> str:
    """Deterministic verdict baseline from scope + sensitivity (auditable).

    A sensitivity label alone never yields a categorical prohibition: APPI
    Art.20(2) carries its own exception set, so the conservative default for
    sensitive personal data is a NON-categorical consent-required outcome —
    prior consent stands unless a separately trusted evidence-verification
    boundary confirms an exception (none ships by default). Only an explicit
    prohibited-use scope (corporate policy prohibition) is categorical.
    """
    if scope == "prohibited-use":
        return "prohibited"
    if sensitivity == "sensitive-personal-data":
        return "prior_consent_required_unless_verified_exception"
    if scope in ("cross-border", "data-handling", "disclosure") or sensitivity in ("personal-data", "pseudonymized"):
        return "conditional"
    return "permitted"


class ComplianceAnswerNode(FunctionNode):
    """Build the cited Markdown compliance answer + verdict + remediation steps."""

    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        super().__init__()
        # None = no LLM bound. Resolved by the graph (explicit kw > config["llm"]);
        # a bare node stays unbound and names the gap rather than using a stub.
        self._llm: LLMClient | None = llm_client

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("error_code"):
            return {}

        # Clarification short-circuit: surface the clarifying question, no citations.
        if state.get("clarification_needed"):
            return {
                "answer": state.get("clarification_prompt") or "Could you clarify the AI tool, data type, and purpose?",
                "verdict": "n/a",
                "citations": json.dumps([], ensure_ascii=False),
                "remediation_steps": json.dumps([], ensure_ascii=False),
                "status": AgentStatus.SUCCESS.value,
            }

        try:
            clauses = json.loads(state.get("retrieved_clauses") or "[]")
        except (json.JSONDecodeError, TypeError):
            clauses = []

        if not clauses:
            return {
                "answer": _OUT_OF_SCOPE,
                "verdict": "n/a",
                "citations": json.dumps([], ensure_ascii=False),
                "remediation_steps": json.dumps([], ensure_ascii=False),
                "status": AgentStatus.SUCCESS.value,
            }

        scope = state.get("scope_label")
        sensitivity = state.get("data_sensitivity")
        verdict = _verdict_for(scope, sensitivity)

        # Citations [C1..Cn] from the retrieved clause set (deterministic).
        # official_ref / effective_date are propagated verbatim so the caller
        # receives the verifiable legal identifier, not just a display label.
        citations = []
        clause_lines = []
        for i, c in enumerate(clauses, start=1):
            marker = f"[C{i}]"
            citations.append(
                {
                    "marker": marker,
                    "clause_id": c.get("clause_id"),
                    "source": c.get("source"),
                    "title": c.get("title"),
                    "official_ref": c.get("official_ref"),
                    "effective_date": c.get("effective_date"),
                }
            )
            ref = c.get("official_ref")
            clause_lines.append(f"- {c.get('source')} — {c.get('title')} {marker}" + (f" — {ref}" if ref else ""))

        # Remediation steps derived from verdict + scope + clause sources.
        remediation = []
        if verdict == "prohibited":
            remediation.append(
                {
                    "step": "Do not input this data into a personal AI tool without a lawful basis",
                    "regulation": clauses[0].get("source"),
                    "action": "obtain explicit prior consent or use an approved, contracted enterprise AI",
                }
            )
        elif verdict == "prior_consent_required_unless_verified_exception":
            # Non-categorical: consent is the default for 要配慮
            # data, an Art.20(2) exception applies only when verified — the
            # advice states the fact-dependence instead of asserting PROHIBITED.
            remediation.append(
                {
                    "step": "Obtain the principal's prior consent before inputting sensitive personal data (要配慮個人情報)",
                    "regulation": ART20_SENSITIVE_REF,
                    "action": "prior consent is the default under APPI Art.20(2) — an exception "
                    "(statutory basis / already public / protection of life) applies only if "
                    "verified; applicability is fact-dependent and requires legal review",
                }
            )
        elif verdict == "conditional":
            remediation.append(
                {
                    "step": "Proceed only with the required safeguards",
                    "regulation": clauses[0].get("source"),
                    "action": "specify purpose, minimise/pseudonymise data, and confirm an approved tool",
                }
            )
        if scope == "cross-border":
            # 越境移転は必ず第28条 (外国にある第三者への提供の制限)。
            remediation.append(
                {
                    "step": "Confirm a lawful cross-border transfer basis before using an overseas AI",
                    "regulation": ART28_CROSS_BORDER_REF,
                    "action": "prior consent — unless (i) the destination is a country designated "
                    "by the PPC as having an equivalent protection regime (指定国), or (ii) the "
                    "recipient maintains a standards-compliant system (基準適合体制); either route "
                    "is fact-dependent and requires verification / legal review (APPI Art.28)",
                }
            )
        remediation.append(
            {
                "step": "Record what personal data was processed and why (audit trail)",
                "regulation": PPC_GUIDELINES_REF,
                "action": "retain a processing record for data-subject rights handling",
            }
        )

        if self._llm is None:
            # Named degradation: the reader sees why there is no rationale; verdict,
            # remediation and citations below do not depend on the LLM.
            emit_trace_event(
                "llm_not_configured",
                {"reason_code": LLM_NOT_CONFIGURED, "citation_count": len(citations)},
                state,
            )
            rationale = (
                f"Rationale narrative omitted ({LLM_NOT_CONFIGURED}): no language model is "
                "bound to this deployment; the verdict, remediation steps and clauses below "
                "are derived deterministically from the retrieved governance clauses."
            )
        else:
            rationale = (
                self._llm.generate(
                    "In one sentence, summarise the compliance reasoning for this verdict.\n"
                    f"Verdict: {verdict}; scope: {scope}; sensitivity: {sensitivity}\nClauses: "
                    + "; ".join(str(c.get("title")) for c in clauses)
                )
                or ""
            ).strip()

        answer = (
            f"## Verdict: {verdict.upper()} [C1]\n"
            + (f"_{rationale}_\n\n" if rationale else "\n")
            + f"**Scope:** {scope} · **Data sensitivity:** {sensitivity} · "
            + f"**APPI applicable:** {'yes' if state.get('appi_applicable') else 'no'}\n\n"
            + "## Required handling / Remediation\n"
            + "\n".join(f"- {r['step']} ({r['regulation']}) — {r['action']}" for r in remediation)
            + "\n\n## Applicable Clauses\n"
            + "\n".join(clause_lines)
        )

        emit_trace_event("compliance_answer_built", {"verdict": str(verdict)}, state)
        return {
            "answer": answer,
            "verdict": verdict,
            "citations": json.dumps(citations, ensure_ascii=False),
            "remediation_steps": json.dumps(remediation, ensure_ascii=False),
            "status": AgentStatus.SUCCESS.value,
        }
