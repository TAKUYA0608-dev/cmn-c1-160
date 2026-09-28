# CMN-C1-160 — Integration: the production path, on the real SDK.
#
# Every test here builds the agent the way the Marketplace runner does —
# `Graph(config=<config/config.yaml dict>)`, no `llm_client` keyword — or adds one
# dependency at a time to prove a specific seam, then goes through the framework's
# own `invoke()` with a runner-shaped InvocationContext. Node-by-node tests cannot
# see what these pin: the `config["llm"]` seam, the kw > config precedence, and
# the named no-LLM degradation (deterministic answer kept, no stub rationale).

import json
import pathlib

import pytest
import yaml

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import Graph
from src.services.service import (
    LLM_NOT_CONFIGURED,
    ConfigLLMAdapter,
    StubLLMClient,
    resolve_llm_client,
)

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_QUESTION = "Can I transfer customer personal data to an overseas personal AI service?"


def _runner_config() -> dict:
    """The dict the runner passes: config/config.yaml as loaded, nothing added."""
    cfg = yaml.safe_load((_REPO_ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    assert isinstance(cfg, dict) and cfg, "config/config.yaml must load to a non-empty dict"
    return cfg


def _ctx() -> InvocationContext:
    return InvocationContext(caller_id="marketplace-user", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)


def _invoke(agent, message: str = _QUESTION) -> dict:
    agent.compile()
    return agent.invoke(message, ctx=_ctx(), input_context={"conversation_history": []})


def _is_success(out: dict) -> bool:
    return str(out.get("status", "")).lower().endswith("success")


class _ScriptedLLM:
    """A config["llm"]-shaped client: `invoke(prompt) -> str`, no `generate`."""

    def __init__(self, reply: str = "SCRIPTED RATIONALE: Art.28 governs the overseas transfer.") -> None:
        self.prompts: list[str] = []
        self.reply = reply

    def invoke(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


class _RaisingLLM:
    def invoke(self, prompt: str) -> str:
        raise RuntimeError("upstream LLM failure (simulated)")


class TestBareRunnerConstruction:
    """`Graph(config=...)` alone — exactly what the Marketplace runner does."""

    def test_deterministic_answer_is_kept_and_the_missing_llm_is_named(self):
        out = _invoke(Graph(config=_runner_config()))
        assert _is_success(out), out.get("status")
        assert out.get("output"), "a runner-shaped invocation produced no output"
        # The deterministic path is complete without an LLM: verdict, remediation
        # and the cited clauses are all delivered ...
        assert out.get("verdict") in {"conditional", "prior_consent_required_unless_verified_exception"}
        cits = json.loads(out.get("citations") or "[]")
        assert cits and all(c.get("official_ref") for c in cits), "citations did not reach the caller"
        assert out.get("error_code") is None, out.get("error_code")
        # ... and the gap is named where the rationale would be.
        assert LLM_NOT_CONFIGURED in out["output"]
        assert "Per the cited APPI / governance clauses" not in out["output"], "a stub rationale leaked through"

    def test_bare_graph_binds_no_llm(self):
        assert Graph(config=_runner_config())._llm_client is None
        assert Graph()._llm_client is None


class TestConfigLlmSeam:
    """`config["llm"]` reaches the answer node; explicit kw wins over it."""

    def test_scripted_config_llm_shapes_the_rationale(self):
        llm = _ScriptedLLM()
        out = _invoke(Graph(config={**_runner_config(), "llm": llm}))
        assert _is_success(out) and out.get("error_code") is None, out
        # The heuristic scope is confident for this question, so only the
        # rationale step consults the client.
        assert len(llm.prompts) >= 1, "the config['llm'] client was never called"
        rationale_prompt = llm.prompts[-1]
        assert "compliance reasoning" in rationale_prompt
        assert str(out.get("verdict")) in rationale_prompt, "the deterministic verdict did not reach the prompt"
        assert llm.reply in out["output"], "the rationale does not derive from the client's reply"
        assert LLM_NOT_CONFIGURED not in out["output"]

    def test_explicit_llm_client_wins_over_config_llm(self):
        config_llm = _ScriptedLLM(reply="FROM CONFIG")
        out = _invoke(
            Graph(config={**_runner_config(), "llm": config_llm}, llm_client=StubLLMClient(canned="FROM EXPLICIT KW"))
        )
        assert "FROM EXPLICIT KW" in out["output"]
        assert config_llm.prompts == [], "config['llm'] was called although an explicit client was given"

    def test_adapter_prefers_invoke_then_complete_and_coerces_message_content(self):
        class _Msg:
            content = "reply text"

        class _CompleteOnly:
            def complete(self, prompt, **kw):
                return _Msg()

        assert ConfigLLMAdapter(_ScriptedLLM(reply="x")).generate("p") == "x"
        assert ConfigLLMAdapter(_CompleteOnly()).generate("p") == "reply text"
        with pytest.raises(TypeError):
            ConfigLLMAdapter(object())
        assert resolve_llm_client(None, {"llm": None}) is None
        assert resolve_llm_client(None, None) is None
        stub = StubLLMClient()
        assert resolve_llm_client(None, {"llm": stub}) is stub  # already speaks generate()

    def test_a_raising_client_surfaces_as_a_named_error_not_a_guess(self):
        # The adapter never swallows the client's exception. This template's
        # composite main node carries no degrade guard, so the framework marks the
        # node as failed: status=error, the exception named in error_log, nothing
        # published — a visible failure, never a guessed or stub answer.
        out = _invoke(Graph(config={**_runner_config(), "llm": _RaisingLLM()}))
        assert not _is_success(out), out.get("status")
        assert not out.get("answer") and not out.get("output"), "an answer was published although the LLM failed"
        log = " ".join(str(e) for e in (out.get("error_log") or []))
        assert "upstream LLM failure (simulated)" in log, "the LLM failure was not named in error_log"
