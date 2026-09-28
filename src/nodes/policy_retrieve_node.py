"""PolicyRetrieveNode — main slot sub-node.

Hybrid vector + keyword search over the governance KB (the APPI in force —
平成15年法律第57号, PPC guidelines, cross-border transfer rules, corporate AI-use policy). The retrieval backend is
dependency-injected (Protocol) so the node is offline-testable; production binds
the real hybrid index, tests bind the in-memory seed KB.

Retrieval is biased toward the classified scope. A zero-hit result is not an error
— it flows downstream as an out-of-scope answer. When ScopeClassify asked for
clarification, this node self-skips (no retrieval on an unresolved question).
"""

from __future__ import annotations

from typing import Any

import json

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus

from src.services.service import GovernanceKBBackend, InMemoryGovernanceBackend, seed_governance_kb
from src.utils.audit import emit_trace_event
from framework.schemas.trust_level import TrustLevel

_TOP_K = 6


class PolicyRetrieveNode(FunctionNode):
    """Retrieve ranked governance/APPI clauses for the question + scope."""

    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, retrieval_backend: GovernanceKBBackend | None = None) -> None:
        super().__init__()
        # Default to the seeded in-memory KB so the node is runnable offline.
        self._backend: GovernanceKBBackend = retrieval_backend or seed_governance_kb()

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("error_code") or state.get("clarification_needed"):
            return {}

        query = state.get("validated_question") or state.get("question") or ""
        scope = state.get("scope_label")

        clauses = self._backend.search(query, top_k=_TOP_K, scope=scope) or []
        emit_trace_event(
            "policy_retrieved",
            {"hit_count": len(clauses), "scope": scope},
            state,
        )

        return {
            "retrieved_clauses": json.dumps(clauses, ensure_ascii=False),
            "retrieval_hit_count": len(clauses),
            "status": AgentStatus.SUCCESS.value,
        }


__all__ = ["PolicyRetrieveNode", "InMemoryGovernanceBackend", "seed_governance_kb"]
