"""AgentCore Platform v1.0"""

# Node contract (agents_layer_design.md §1):
#  - Extend FunctionNode; implement execute(state) -> dict
#  - Return ONLY the fields this node changes (never full state)
#  - Return AgentStatus enum constants — never plain strings [A1]
#  - Read input_context via state.get("input_context", {}) — read-only [C1]
#  - Never import from mediator/, api/, or other agents

from typing import Any

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel
from src.utils.audit import emit_trace_event


class PreProcessNode(FunctionNode):
    """Validate and enrich incoming input before main processing."""

    required_trust_level = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        user_input = state.get("user_input", "")
        input_context = state.get("input_context", {})  # read-only [C1]

        if not user_input or not user_input.strip():
            return {
                "status": AgentStatus.ERROR.value,
                "error_log": ["PreProcessNode: user_input is empty or missing"],
            }

        # TODO: add domain-specific validation / enrichment
        emit_trace_event("input_accepted", {"length": len(user_input.strip())}, state)
        return {
            "validated_input": user_input.strip(),
            "enriched_context": {
                "source": "PersonalAIGovernanceQAAgent",
                "channel": input_context.get("channel", "unknown"),
            },
            "status": AgentStatus.SUCCESS.value,
        }
