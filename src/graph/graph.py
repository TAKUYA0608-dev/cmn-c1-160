"""CMN-C1-160 PersonalAIGovernanceQAAgent — graph composition.

L1-direct inheritance from AgentBaseGraph (Cat 1). The SoT workflow is composed into
the framework's three writable slots; the framework owns initialize/finalize, edge
wiring, and routing (START → initialize → pre_process → main → post_process → finalize
→ END, with the RETRY edge back to pre_process).

    pre_process  = QueryNormalizeNode             (S-1 input boundary + context extraction)
    main         = PersonalAIGovernanceMainNode   (ScopeClassify → PolicyRetrieve
                                                   → ComplianceAnswer)
    post_process = ResponseValidateNode           (S-3 citation/redaction/APPI-disclaimer + S-4)

Cat 1 shape: `main` is a composite FunctionNode (single graph slot, single execute()
boundary) — NOT a Cat 2 GraphNode-in-main. Retrieval + LLM backends are dependency-
injected so the agent is offline-testable; production binds the real hybrid governance
KB index; tests bind in-memory / stub backends.

LLM binding: explicit `llm_client` kw > `config["llm"]` (the Marketplace entry point
places a lazy Azure client there; adapted by `resolve_llm_client`) > none. With none,
the rationale narrative is replaced by a named `LLM_NOT_CONFIGURED` notice and the
deterministic verdict / remediation / citations are still delivered — no stub is bound.
"""

from __future__ import annotations

from typing import Any

from framework.graph.agent_base_graph import AgentBaseGraph

from src.schemas.state import PersonalAIGovernanceState
from src.services.service import GovernanceKBBackend, LLMClient, resolve_llm_client
from src.nodes.query_normalize_node import QueryNormalizeNode
from src.nodes.main_node import PersonalAIGovernanceMainNode
from src.nodes.response_validate_node import ResponseValidateNode


class PersonalAIGovernanceQAAgent(AgentBaseGraph):
    """Enterprise personal-AI governance / APPI compliance Q&A agent (Cat 1)."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        retrieval_backend: GovernanceKBBackend | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._retrieval_backend = retrieval_backend
        self._llm_client = resolve_llm_client(llm_client, config)
        super().__init__(config)

    @property
    def name(self) -> str:
        return "PersonalAIGovernanceQAAgent"

    @property
    def state_schema(self) -> type:
        """Domain State so per-node fields survive node merges (LangGraph drops
        keys not declared in the schema)."""
        return PersonalAIGovernanceState

    def register_nodes(self) -> None:
        super().register_nodes()  # framework injects InitializeNode + FinalizeNode
        self._nodes["pre_process"] = QueryNormalizeNode()
        self._nodes["main"] = PersonalAIGovernanceMainNode(
            retrieval_backend=self._retrieval_backend,
            llm_client=self._llm_client,
        )
        self._nodes["post_process"] = ResponseValidateNode()

    def get_output(self, state: dict[str, Any]) -> dict[str, Any]:
        """Surface the compliance-answer payload (this agent writes answer/verdict/
        citations, not the framework-default output)."""
        # The Marketplace runner rejects a successful invocation whose output
        # is missing (verified on a deployed Pod), and a degraded run
        # (SUCCESS + error_code) leaves "answer" unset. Report the degradation —
        # this states what happened, it does not invent an answer.
        #
        # Only on SUCCESS: a request refused by the S-2 gate (status ERROR) must
        # keep publishing nothing, or the refusal is undone.
        _output = state.get("answer")
        if not _output and str(state.get("status", "")).lower().endswith("success"):
            _code = state.get("error_code") or "NO_CONTENT"
            _output = (
                "This request could not be completed "
                f"(error_code={_code}). No content was produced; "
                "see error_code and error_log for the degradation cause."
            )
        return {
            "output": _output,
            "answer": state.get("answer"),
            "verdict": state.get("verdict"),
            "scope_label": state.get("scope_label"),
            "data_sensitivity": state.get("data_sensitivity"),
            "appi_applicable": state.get("appi_applicable"),
            "scope_confidence": state.get("scope_confidence"),
            "clarification_needed": state.get("clarification_needed"),
            "citations": state.get("citations"),
            "remediation_steps": state.get("remediation_steps"),
            "retrieved_clauses": state.get("retrieved_clauses"),
            "retrieval_hit_count": state.get("retrieval_hit_count"),
            "validation_status": state.get("validation_status"),
            "redaction_count": state.get("redaction_count"),
            "disclaimer_applied": state.get("disclaimer_applied"),
            "audit_logged": state.get("audit_logged"),
            "status": state.get("status"),
            "error_code": state.get("error_code"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
            "error_log": state.get("error_log", []),
        }


# Backward-compat alias — the scaffold (api/server.py) imports `Graph`.
Graph = PersonalAIGovernanceQAAgent
