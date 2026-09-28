# Test Specification — CMN-C1-160 PersonalAIGovernanceQAAgent

## Test Strategy
- Coverage target: **≥ 80%** (achieved **87%** across `src/`, excl. FastAPI entrypoint)
- Test types: Unit (per-node) / Agent e2e (framework invoke) / Proof-of-Boundary
- Backends are dependency-injected: tests bind `seed_governance_kb()` (in-memory governance KB) + `StubLLMClient` — no network, fully deterministic.
- Layout: `tests/unit/` (per-node + agent e2e), `tests/proof_of_boundary/` (PB scanners).

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| TC-01 | State contract: flat TypedDict (`PersonalAIGovernanceState`) | No Pydantic/dataclass; PB-2 state-safety scan | ✅ pass |
| TC-02 | Input rejection fires | QueryNormalize rejects empty / oversized (≤2000) / injection (`error_code` set) | ✅ pass |
| TC-03 | No JWT/Credential in State or `src/` | CI `gate-credential-scan`: 0 violations | ✅ CI |
| TC-04 | InvocationContext via `config["configurable"]` only | not stored in State | ✅ pass |
| TC-05 | S-4: no duplicate lifecycle events in `execute()` | `node_start/complete/error` absent from `execute()` bodies | ✅ 0 duplicates |
| TC-06 | S-2: `_security_gate_input()` not overridden (FunctionNode `@final`) | domain input checks in QueryNormalize.`execute()` only | ✅ 0 overrides |
| TC-07 | S-3: `_security_gate_output()` not overridden (FunctionNode `@final`) | domain S-3 in ResponseValidate.`execute()` only | ✅ 0 overrides |
| TC-08 | `required_trust_level` = `VERIFIED_EXTERNAL` (valid enum) | declared on boundary nodes + `config/agent.yaml`; CI criterion #13 | ✅ valid |
| TC-11 | S-4: ≥1 domain `emit_trace_event()` per side-effect node | ScopeClassify / PolicyRetrieve / ComplianceAnswer / ResponseValidate emit domain events | ✅ ≥1 each |

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result | Result |
|-------|----------|------|----------------|--------|
| PB-2 | State serialization | Post-invoke State is primitives + JSON strings only | No Pydantic/dataclass | ✅ pass |
| PB-4 | Import isolation | No Level 0 (`agenticstar`) imports — AST scan over `src/` | 0 violations | ✅ pass |
| PB-1/5/6 | Audit / checkpoint / invoke order | exercised via agent e2e (`test_agent.py`) + framework `__call__` | order + audit verified | ✅ via e2e |

## Business Logic Tests (domain)

| Test file | Coverage |
|-----------|----------|
| `test_nodes.py` → TestQueryNormalize (5) | NFKC normalization + synonym, injection / empty / oversize rejection, intent + tool/data context extraction, trust-level declared |
| `test_nodes.py` → TestScopeClassify (3) | prohibited+sensitive classification, **low-confidence clarification**, DI threshold override (`scope_confidence_threshold`) |
| `test_nodes.py` → TestPolicyRetrieve (3) | scope-biased hits, zero-hit off-topic, self-skip on clarification |
| `test_nodes.py` → TestComplianceAnswer (4) | cited [C#] answer + verdict (conditional), prohibited verdict, zero-hit safe answer, clarification short-circuit |
| `test_nodes.py` → TestResponseValidate (4) | mandatory APPI disclaimer fail-closed, uncited-substantive reject, redaction (My Number / internal IP), audit on error path |
| `test_main_node.py` (4) | 3-step composite full chain, deltas-only + SUCCESS-on-error pattern, node contract (`execute` not `_invoke_impl`), `MainNode` alias |
| `test_agent.py` (5) | framework invoke e2e: grounded verdict + disclaimer + audit, off-topic safe answer, injection blocked, `Graph` alias, name |

## Test Execution Summary
- Total tests: **30** — Pass: **30** / Fail: 0 / Skip: 0
- Coverage: **87%** (`--cov=src`); domain nodes 93–100%, FastAPI entrypoint excluded
