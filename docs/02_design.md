# Template Design Specification — CMN-C1-160

**Template ID:** CMN-C1-160
**Agent Class:** PersonalAIGovernanceQAAgent
**Category:** Cat 1 (single technical capability — personal-AI governance & APPI 2026 compliance Q&A)
**Industry:** CMN (cross-industry)
**Source:** the original template proposal

> **Clarifications carried from evaluation:**
> - **(F-01)** L1 base is `AgentBaseGraph` (L1-direct per the 2026-05-18 policy). `ChatAgent` /
>   `RAGAgent` is a *pattern reference only* (concept), **not** an L2 inheritance. The
>   `config/agent.yaml` `base_type` label is conceptual; the runtime base is `AgentBaseGraph`.
> - **(F-02)** Scope boundary: this template answers **governance / compliance Q&A** about
>   employee personal-AI use ("can I paste a customer list into my personal AI assistant?",
>   "what does APPI 2026 require before using an external AI on HR data?") under APPI 2026 +
>   corporate AI-use policy. It is **not** a DLP enforcement engine, **not** a live traffic
>   monitor, and **not** formal legal advice (advisory output, fail-closed disclaimer).

## Position in AgentCore Architecture

- **L1 Base: `AgentBaseGraph`** (Cat 1, L1-direct per the graph contract; `agents/base/*` not used; ChatAgent/RAGAgent is a pattern, not an L2 class)
- **Three-Layer Separation:**
  - State: flat TypedDict composition (`PersonalAIGovernanceState(AgentState)`) — no Pydantic
  - Node: L1 inheritance (`FunctionNode`, `execute(self, state, config=None) -> dict` override only)
  - Graph: composition (`register_nodes()` fills the 3 writable slots)

## Architecture Overview

### Node Configuration

The SoT workflow is composed into the framework's three writable slots. The domain nodes map as:

| Slot | Node | Responsibility | Inherits |
|------|------|---------------|----------|
| initialize | InitializeNode | schema_version, session_id, trust_level | default (framework) |
| **pre_process** | **QueryNormalizeNode** | S-1 input boundary: NFKC normalize, injection reject, size cap (≤2000); **extraction only** — intent (permitted-use / data-handling / cross-border / disclosure-obligation) + context tokens (AI tool name, data type, department). No classification here. | FunctionNode |
| **main** | **PersonalAIGovernanceMainNode** composing → | composite of the 3 reasoning sub-nodes below | FunctionNode |
| ↳ | ScopeClassifyNode | classify governance scope (permitted-use / prohibited-use / data-handling / cross-border transfer / disclosure) **and** data sensitivity (personal-data / sensitive-personal-data / pseudonymized / anonymized) + APPI applicability; heuristic keyword scoring + LLM disambiguation; emits clarification signal when confidence < threshold | FunctionNode |
| ↳ | PolicyRetrieveNode | hybrid vector+keyword retrieval over the governance KB (APPI 2026 amendments, PPC guidelines, cross-border transfer rules, corporate AI-use policy) + personal-AI-tool capability/data-handling docs; scope filter + rerank | FunctionNode |
| ↳ | ComplianceAnswerNode | LLM compliance judgment (permitted? required handling? remediation steps?) rendered as a cited Markdown answer with inline `[C#]`; out-of-scope deflection / clarification on low confidence or 0 hits | FunctionNode |
| **post_process** | **ResponseValidateNode** | **S-3 gate**: citation presence check (reject uncited substantive answer), **mandatory APPI legal disclaimer fail-closed**, sensitive-value redaction; **S-4 audit** (always fires) | FunctionNode |
| finalize | FinalizeNode | response_metadata, total_time_ms | default (framework) |

### Data Flow

```
START → initialize → pre_process(QueryNormalize) → main(PersonalAIGovernanceMain) → {route}
        → post_process(ResponseValidate) → finalize → END
                                            ↓ (retry, max 3)
                                          pre_process
```

Error propagation: any sub-node sets `error_code`; downstream sub-nodes self-skip (`return {}`).
A low scope-confidence or insufficient-context state short-circuits to a **clarification**
response (not a guess). Out-of-scope queries (formal legal opinion, individual disciplinary
judgement, live data-flow blocking) are deflected with a scope notice. ResponseValidate's S-4
audit fires on every path, including errors and clarifications.

LLM binding (ADR-8): explicit `llm_client` > `config["llm"]` (adapted by
`service.resolve_llm_client`) > none. With none, ScopeClassify keeps its heuristic result
(no LLM disambiguation; a weak heuristic still leads to clarification) and ComplianceAnswer
puts a named `LLM_NOT_CONFIGURED` notice in the rationale slot; the deterministic verdict,
remediation steps and citations are delivered unchanged and `error_code` stays unset. No
stub LLM is ever bound by default.

### Error / degradation codes (`status=success` + non-empty `output`)

| code | Set by | Meaning | Output text |
|------|--------|---------|-------------|
| node error (`status=error`) | framework `__call__` | a sub-node raised (missing upstream state, backend failure, **a bound LLM that raised** — the adapter never swallows it) | nothing published; the exception is named in `error_log` |
| `LLM_NOT_CONFIGURED` (S-4 `llm_not_configured` + rationale notice; **not** an `error_code`) | ScopeClassify / ComplianceAnswer | no LLM bound (`llm_client` / `config["llm"]`) | the full deterministic answer with the notice where the rationale would be |

### State Definition (`src/schemas/state.py`)

| Field | Type | Purpose | Written by |
|-------|------|---------|-----------|
| question / business_context | Optional[str] | caller input (business_context = JSON of AI-tool / data-type / department hints) | caller |
| validated_question / extracted_context | Optional[str] | normalized question + extracted intent/context JSON | QueryNormalize |
| scope_label / data_sensitivity / appi_applicable | Optional[str] / Optional[str] / Optional[bool] | governance scope + data sensitivity class + APPI applicability | ScopeClassify |
| scope_confidence / clarification_needed / clarification_prompt | Optional[float] / Optional[bool] / Optional[str] | low-confidence / insufficient-context branch | ScopeClassify |
| retrieved_clauses / retrieval_hit_count | Optional[str] / Optional[int] | ranked clause list JSON + count | PolicyRetrieve |
| answer / citations / remediation_steps / verdict | Optional[str] | cited Markdown answer + citation/remediation JSON + permitted/conditional/prohibited verdict | ComplianceAnswer |
| validation_status / redaction_count / disclaimer_applied / audit_logged | Optional[str/int/bool] | S-3/S-4 outcome | ResponseValidate |
| error_code / error_message | Optional[str] | error propagation | any node |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serialized strings); no Pydantic / dataclass (msgpack)
- No JWT, API keys, credentials, or raw personal/customer data values in State (checkpoint DB leakage)
- InvocationContext via `config["configurable"]` only (not in State)

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (caller_trust_level, session_id) — via `config["configurable"]`
- [x] **S-1**: QueryNormalizeNode does NFKC + injection reject + size cap (≤2000) in `execute()`.
- [x] **S-2**: framework `@final` `_security_gate_input()` runs automatically (FunctionNode); no domain `_extra_security_gate_input()` needed.
- [x] **S-3**: framework `@final` `_security_gate_output()` (credential scan) runs automatically; **domain S-3 logic** (citation gate, mandatory APPI legal-disclaimer fail-close, sensitive redaction) lives in `ResponseValidateNode.execute()` — a deliberate domain output validation, not an override.
- [x] **S-4**: `emit_trace_event()` (`shared.utils.audit_logger`) called inside `execute()` of ScopeClassify, PolicyRetrieve, ComplianceAnswer, ResponseValidate. `node_start`/`node_complete`/`node_error` are NOT emitted by templates (framework owns them).

### Composition Pattern
- **Pattern:** Standalone (Cat 1) — single-agent, no GraphNode/RemoteAgentNode subgraph
- **Sub-node invocation:** `PersonalAIGovernanceMainNode` instantiates its 3 sub-nodes in `__init__()` (`self._seq = [...]`) and calls each via `sub_node.execute(state, config)` **directly — not `__call__()`**. The composite therefore owns a single S-2/S-3/S-4 boundary and the framework hooks are **not** re-invoked per sub-node (no duplicate gate/audit). Same composite pattern as its sibling templates.
- **Error propagation strategy:** propagate via `error_code`; clarification short-circuit; terminal audit always fires

## Import Isolation Confirmation
- [x] Template does not import `agenticstar` (Level 0) — PB-4 AST scan
- [x] Import targets: `framework/` (FunctionNode, AgentBaseGraph, AgentState, AgentStatus, InvocationContext) + `shared/` (audit_logger via wrapper) only

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | **AgentBaseGraph** | Fixed pipeline, no autonomous loop (Cat 1) |
| QueryNormalize scope | normalize + classify | normalize / extract only | **extract only** | keep prompt + state separate from ScopeClassify |
| Scope classification | LLM only | heuristic + LLM | **heuristic + LLM** | auditable keyword baseline; LLM disambiguates ambiguous data-type vs use-type questions |
| Compliance verdict | free-text | structured (permitted/conditional/prohibited) + cited answer | **structured + cited** | downstream UX + auditability; verdict drives disclaimer emphasis |
| Low-confidence handling | best-effort guess | clarification short-circuit | **clarification** | SoT: never guess on a compliance question; ask for missing data-type/tool context |
| APPI legal disclaimer | best-effort | S-3 fail-closed | **fail-closed** | advisory output must always carry "not formal legal advice" disclaimer |
| Retrieval backend | committed index | DI Protocol + seed KB | **DI Protocol** | offline-testable; prod binds real hybrid governance index |
| ADR-8 LLM binding (2026-09-03) | silent `StubLLMClient` default | explicit kw > `config["llm"]` > none, named `LLM_NOT_CONFIGURED` | **Option B** | the Marketplace runner constructs `Graph(config=config.yaml)` and the fleet entry point can only place the Azure client under `config["llm"]`; a silent stub ran on the Pod even with keys registered and hid the gap. The LLM is advisory (disambiguation + rationale), so the deterministic answer is kept in full and the missing LLM is named rather than faked. Stub = tests only (explicit injection) |

## Design Review Notes

Review verdict: **✅ Approve** (minor, non-blocking). Resolved in-doc here:

- **`scope_confidence` clarification threshold:** default **`0.6`**, DI-overridable via
  `config["configurable"]["scope_confidence_threshold"]` (constant fallback when unset).
  `ScopeClassifyNode` sets `clarification_needed = True` and emits `clarification_prompt`
  when `scope_confidence < threshold` (never guesses a compliance verdict on low confidence).
- **`extracted_context` typing:** stored as a **JSON-serialized `str`** (TypedDict primitive
  constraint) — never a dict / Python object in State. Same for all `*_context` / `*_clauses`
  / `citations` / `remediation_steps` JSON fields.
