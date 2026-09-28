"""CMN-C1-160 Enterprise Personal AI Governance & APPI Compliance Q&A Agent — State.

Flat TypedDict per the platform's node and state-safety contracts:
every field is an Optional primitive or a JSON-serialized string (msgpack
round-trips cleanly). No Pydantic, no dataclass, no arbitrary Python objects,
and never JWT / API keys / credentials / raw personal or customer data values
(checkpoint DB leakage).

Pipeline (docs/02_design.md §Architecture Overview):
    QueryNormalize (S-1 input) → ScopeClassify → PolicyRetrieve
    → ComplianceAnswer → ResponseValidate (S-3 citation/APPI-disclaimer/redaction
    + S-4 audit)
"""

from __future__ import annotations

from typing import Optional

from framework.schemas.agent_state import AgentState


class PersonalAIGovernanceState(AgentState):
    """State for the personal-AI governance / APPI compliance Q&A pipeline.

    Shared fields (user_input, status, session_id, node_history, error_log,
    caller_trust_level, trace_id, correlation_id, …) are inherited from
    AgentState. Only domain fields are declared here; LangGraph drops keys not
    declared in the schema, so every field the pipeline writes MUST appear below.
    """

    # ─── Input (caller supplies via user_input + input_context) ───
    question: Optional[str]  # NL governance/compliance question
    business_context: Optional[str]  # JSON hint: {ai_tool, data_type, department}

    # ─── QueryNormalizeNode (pre_process, S-1 input boundary) ───
    validated_question: Optional[str]  # sanitized / normalized question
    extracted_context: Optional[str]  # JSON: {intent, tool_hints[], data_hints[]}

    # ─── ScopeClassifyNode ───
    scope_label: Optional[str]  # permitted-use | prohibited-use | data-handling | cross-border | disclosure
    data_sensitivity: Optional[str]  # personal-data | sensitive-personal-data | pseudonymized | anonymized | none
    appi_applicable: Optional[bool]  # whether APPI obligations are in scope
    scope_confidence: Optional[float]  # 0.0–1.0
    classification_rationale: Optional[str]
    clarification_needed: Optional[bool]  # True when confidence < threshold / context insufficient
    clarification_prompt: Optional[str]  # clarifying question to return (when clarification_needed)

    # ─── PolicyRetrieveNode (hybrid over governance KB) ───
    retrieved_clauses: Optional[str]  # JSON: [{clause_id, source, title, text, score, scope}]
    retrieval_hit_count: Optional[int]

    # ─── ComplianceAnswerNode (cited Markdown answer) ───
    answer: Optional[str]  # Markdown answer with inline [C#] citations
    verdict: Optional[
        str
    ]  # permitted | conditional | prior_consent_required_unless_verified_exception | prohibited | n/a
    citations: Optional[str]  # JSON: [{marker, clause_id, source, title}]
    remediation_steps: Optional[str]  # JSON: [{step, regulation, action}]

    # ─── ResponseValidateNode (S-3 citation/disclaimer/redaction gate + S-4 audit) ───
    validation_status: Optional[str]  # "passed" | "redacted" | "rejected"
    redaction_count: Optional[int]  # sensitive values redacted out of the answer
    disclaimer_applied: Optional[bool]  # mandatory APPI legal-disclaimer footer injected
    audit_logged: Optional[bool]  # True once the S-4 audit event is emitted

    # ─── Error propagation (any node; downstream nodes self-skip) ───
    error_code: Optional[str]
    error_message: Optional[str]


# Backward-compat alias: the scaffold (graph.py / server.py) references `State`.
State = PersonalAIGovernanceState
