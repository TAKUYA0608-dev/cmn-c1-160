# CMN-C1-160 — E2E: the RENDERED advice (not just the seed record) states the
# fact-dependent Article 28 / Article 20(2) framing.
#
# The seed being accurate does not cure incomplete caller-facing advice, so
# these tests assert against the answer the caller actually receives through a
# bare Graph().invoke().

from framework.schemas.invocation_context import InvocationContext, TrustLevel

from src.graph.graph import Graph


def _invoke(question):
    agent = Graph()
    agent.compile()
    ctx = InvocationContext(caller_id="e2e-advice", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)
    return agent.invoke(question, ctx=ctx)


class TestRenderedCrossBorderAdvice:
    def test_answer_states_both_article28_routes_and_review(self):
        out = _invoke("Can I transfer customer personal data to an overseas personal AI service? 越境")
        answer = out.get("answer") or ""
        assert "指定国" in answer, "designated-country route missing from the rendered advice"
        assert "基準適合体制" in answer, "recipient-standards route missing from the rendered advice"
        assert "legal review" in answer, "fact-dependence / legal-review framing missing"


class TestSensitiveDataVerdictIsNotCategorical:
    def test_sensitive_question_gets_consent_not_prohibition(self):
        """A sensitivity label alone (病歴 / 要配慮) must not produce a
        categorical PROHIBITED verdict."""
        out = _invoke("May I put customer 病歴 (medical history) into a personal AI tool?")
        assert out.get("verdict") == "prior_consent_required_unless_verified_exception"
        assert out.get("verdict") != "prohibited"
        answer = out.get("answer") or ""
        assert "legal review" in answer
