# CMN-C1-160 — Unit Tests: Main Node (composite) contract

import inspect

from src.nodes.main_node import PersonalAIGovernanceMainNode, MainNode
from src.services.service import seed_governance_kb, StubLLMClient
from framework.schemas.agent_status import AgentStatus


class TestMainNodeContract:
    """Composite main-node contract (the node contract / GraphNode-free Cat 1)."""

    def test_execute_signature(self):
        """node contract: execute(self, state, ...) not _invoke_impl."""
        assert hasattr(PersonalAIGovernanceMainNode, "execute")
        sig = inspect.signature(PersonalAIGovernanceMainNode.execute)
        params = list(sig.parameters.keys())
        assert params[0] == "self" and params[1] == "state"
        assert "_invoke_impl" not in PersonalAIGovernanceMainNode.__dict__

    def test_alias(self):
        assert MainNode is PersonalAIGovernanceMainNode

    def test_composite_runs_full_chain(self):
        """A grounded question flows ScopeClassify → PolicyRetrieve → ComplianceAnswer."""
        node = PersonalAIGovernanceMainNode(
            retrieval_backend=seed_governance_kb(),
            llm_client=StubLLMClient(canned="reasoned summary [C1]"),
        )
        state = {
            "validated_question": "Can I paste customer personal data into a personal AI assistant?",
            "node_history": [], "error_log": [],
        }
        result = node.execute(state)
        assert result["status"] == AgentStatus.SUCCESS.value
        assert result["scope_label"] is not None
        assert result["retrieval_hit_count"] >= 1
        assert "[C1]" in result["answer"]
        assert result["verdict"] in ("permitted", "conditional", "prohibited")

    def test_error_propagates_not_status(self):
        """A pre-set error_code is carried in deltas; composite still reports SUCCESS."""
        node = PersonalAIGovernanceMainNode(retrieval_backend=seed_governance_kb())
        result = node.execute({"error_code": "INPUT_EMPTY", "node_history": []})
        # composite reports SUCCESS so router reaches post_process; error carried in state
        assert result["status"] == AgentStatus.SUCCESS.value
