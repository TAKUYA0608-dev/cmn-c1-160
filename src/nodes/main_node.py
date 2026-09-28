"""PersonalAIGovernanceMainNode (main slot) — composes the 3 core reasoning steps.

The framework exposes three writable slots; the personal-AI governance reasoning
core is three steps composed into this single `main` node in fixed order:

    ScopeClassify → PolicyRetrieve → ComplianceAnswer

Sub-node composition: sub-nodes are instantiated in `__init__()`
(`self._seq`) and called via `sub_node.execute(state)` **directly — not
`__call__()`**. The composite therefore owns the single S-2/S-3/S-4 boundary and the
framework hooks are not re-invoked per sub-node (same pattern as its sibling templates
`NotebookKBMainNode` / a sibling template `APPIMainNode`). Each sub-node returns only its
changed fields and self-skips on `error_code` / `clarification_needed`. The LLM
backend is dependency-injected into the sub-nodes that need it.
"""

from __future__ import annotations

from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.invocation_context import TrustLevel

from src.services.service import GovernanceKBBackend, LLMClient
from src.nodes.scope_classify_node import ScopeClassifyNode
from src.nodes.policy_retrieve_node import PolicyRetrieveNode
from src.nodes.compliance_answer_node import ComplianceAnswerNode
from src.utils.audit import emit_trace_event


class PersonalAIGovernanceMainNode(FunctionNode):
    """main slot — ScopeClassify → PolicyRetrieve → ComplianceAnswer."""

    # CoE CR-R1-01: declare the S-1 trust gate explicitly (agent requires VERIFIED_EXTERNAL).
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(
        self,
        retrieval_backend: GovernanceKBBackend | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        super().__init__()
        self._seq: list[FunctionNode] = [
            ScopeClassifyNode(llm_client=llm_client),
            PolicyRetrieveNode(retrieval_backend=retrieval_backend),
            ComplianceAnswerNode(llm_client=llm_client),
        ]

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        working = dict(state)
        deltas: dict[str, Any] = {}
        for node in self._seq:
            updates = node.execute(working) or {}
            working.update(updates)
            deltas.update(updates)
        # Intentional: the composite reports SUCCESS so the framework router always
        # advances to post_process. A sub-node failure is NOT signalled via status —
        # it is carried in the `error_code` delta (set by the failing sub-node), which
        # ResponseValidate inspects and surfaces in the S-4 audit + error response.
        # (Reporting ERROR here would short-circuit the pipeline before the terminal
        # audit/redaction gate runs.) Same pattern as its sibling templates.
        # S-4: the composite wrapper itself is a boundary node — record that the
        # sub-pipeline ran to completion (gate-audit-trace-check).
        emit_trace_event("main_pipeline_completed", {"sub_nodes": len(self._seq)}, state)
        deltas["status"] = AgentStatus.SUCCESS.value
        return deltas


# Backward-compat alias — the scaffold test imports `MainNode`.
MainNode = PersonalAIGovernanceMainNode
