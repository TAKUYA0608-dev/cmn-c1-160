# CMN-C1-160 — E2E: official_ref reaches the caller through a bare Graph().
#
# The seed's provenance is only worth anything if the *caller* receives it:
# a bare Graph() (no DI — the default seed KB + stub LLM, i.e. exactly what a
# fresh deployment runs) must answer a Japanese cross-border question with
# citations that carry the verifiable official_ref (…第28条). Removing the
# official_ref propagation in ComplianceAnswerNode makes this fail (non-vacuity
# verified by sabotage during development).

import json

from framework.schemas.invocation_context import InvocationContext, TrustLevel

from src.graph.graph import Graph


def _ctx():
    return InvocationContext(session_id="e2e-prov", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)


class TestBareGraphCitationProvenance:
    def test_japanese_cross_border_question_cites_article_28(self):
        agent = Graph()  # bare: default seed KB + stub LLM (fresh-deployment shape)
        agent.compile()
        out = agent.invoke("顧客の個人データを海外のAIサービスに移転してもよいですか", ctx=_ctx())
        assert out.get("answer")
        assert not out.get("error_code")
        citations = json.loads(out.get("citations") or "[]")
        assert citations, "grounded answer carried no citations"
        refs = [c.get("official_ref") for c in citations]
        assert all(refs), f"citation without official_ref: {citations}"
        assert any("第28条" in r for r in refs), f"Art.28 missing from refs: {refs}"
        # The fictitious amendment must never resurface caller-side (markers
        # built by concatenation so the repo-wide sweep grep stays at zero).
        blob = json.dumps(out, ensure_ascii=False, default=str)
        assert ("APPI " + "2026") not in blob and ("appi" + "2026") not in blob

    def test_english_cross_border_question_also_carries_refs(self):
        agent = Graph()
        agent.compile()
        out = agent.invoke(
            "Can I transfer customer personal data to an overseas personal AI service?",
            ctx=_ctx(),
        )
        citations = json.loads(out.get("citations") or "[]")
        assert citations and all(c.get("official_ref") for c in citations)
