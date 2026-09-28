# CMN-C1-160 — Seed provenance: every default clause cites the APPI in force.
#
# The previous seed presented a fictitious future APPI amendment as legal fact.
# These tests pin the curated seed to verifiable official identifiers
#:
#   * every record carries a non-empty official_ref
#   * APPI records cite 平成15年法律第57号 with the correct article numbers
#     (cross-border transfer = Art.28, sensitive acquisition = Art.20(2))
#   * no record asserts unverifiable facts (invented amendments, 72h/24h
#     deadlines, guideline edition dates)
#   * Japanese questions actually retrieve (CJK-bigram tokenizer, not str.split)

import json
import re

from src.services.service import (
    APPI_REF,
    lexical_terms,
    seed_governance_kb,
)

_APPI_LAW_NO = "平成15年法律第57号"


def _records():
    return seed_governance_kb()._clauses


# official_ref acceptance rule (established on a sibling template, applied fleet-wide):
# a reference is verifiable only in one of these forms —
#   1. a statute number (…法律第N号), or an EU official identifier (CELEX n)
#   2. a NAMED external document: authority + 「…」-quoted title (version may be
#      deliberately omitted, but the document must be identifiable)
#   3. an explicit template-owned declaration ("no external source" stated)
# A bare organisation name ("NISC guidance") attributes content to an authority
# without anything a reader can check — the same shape as an invented
# amendment, one step milder — and is rejected.
_LAW_REF = re.compile(r"法律第\d+号")
_EU_OFFICIAL = re.compile(r"CELEX \d+\w*")
_NAMED_EXTERNAL_DOC = re.compile(
    r"(FISC|NISC|METI|経済産業省|内閣サイバーセキュリティセンター|金融情報システムセンター|個人情報保護委員会).*「.+」"
)
_TEMPLATE_OWNED = re.compile(r"本テンプレートの.*出典としない")


class TestSeedProvenance:
    def test_every_record_has_a_verifiable_official_ref(self):
        for c in _records():
            ref = c.get("official_ref", "")
            assert ref and (
                _LAW_REF.search(ref)
                or _EU_OFFICIAL.search(ref)
                or _NAMED_EXTERNAL_DOC.search(ref)
                or _TEMPLATE_OWNED.search(ref)
            ), (
                f"{c['clause_id']}: official_ref must cite a statute number / EU official "
                f"identifier, a NAMED external document, or declare itself template-owned — "
                f"vague authority attribution is not verifiable: {ref!r}"
            )

    def test_no_fictitious_2026_amendment(self):
        blob = json.dumps(_records(), ensure_ascii=False)
        # Forbidden markers built by concatenation so a repo-wide sweep grep
        # for the fictitious-amendment string stays at zero hits.
        assert ("APPI " + "2026") not in blob
        assert ("appi" + "2026") not in blob

    def test_appi_records_cite_the_act_in_force(self):
        appi = [c for c in _records() if c["clause_id"].startswith("appi-")]
        assert appi, "seed lost its APPI records"
        for c in appi:
            assert _APPI_LAW_NO in c["official_ref"], c["clause_id"]
            # 令和2年法律第44号改正の全面施行日。
            assert c["effective_date"] == "2022-04-01", c["clause_id"]

    def test_cross_border_is_article_28(self):
        """越境移転は必ず第28条 (第20条でも第23条でもない)。"""
        a28 = next(c for c in _records() if c["clause_id"] == "appi-a28")
        assert a28["scope"] == "cross-border"
        assert "第28条" in a28["official_ref"]
        assert "第20条" not in a28["official_ref"]
        assert "第23条" not in a28["official_ref"]

    def test_sensitive_acquisition_is_article_20_2(self):
        a20 = next(c for c in _records() if c["clause_id"] == "appi-a20")
        assert "第20条第2項" in a20["official_ref"]

    def test_breach_record_does_not_invent_gdpr_deadlines(self):
        """第26条の期限は「委員会規則の定めに従い」— GDPR の 72h/24h を APPI 義務と書かない。"""
        a26 = next(c for c in _records() if c["clause_id"] == "appi-a26")
        blob = (a26["text"] + a26["title"] + a26["official_ref"]).lower()
        assert "72" not in blob and "24" not in blob

    def test_erasure_is_an_effort_obligation(self):
        """第22条は努力義務 — 断定的な削除義務として書かない。"""
        a22 = next(c for c in _records() if c["clause_id"] == "appi-a22")
        assert "endeavour" in a22["text"] or "努力義務" in a22["text"]

    def test_ppc_guidelines_carry_no_edition_pin(self):
        """PPC ガイドラインは版・改正日を書かない (確証なしの版は捏造)。"""
        for c in _records():
            if c["clause_id"].startswith("ppc-gl"):
                assert APPI_REF not in c["official_ref"]  # ガイドラインは法令 ID を騙らない
                assert c["effective_date"] is None
                assert "令和" not in c["official_ref"] and "平成" not in c["official_ref"]


class TestJapaneseTokenizer:
    """str.split() collapses a Japanese sentence to one token → zero hits.

    The CJK-bigram tokenizer (ported from a sibling template) fixes that; these pin it.
    """

    def test_japanese_yields_bigram_terms(self):
        terms = lexical_terms("個人データの越境移転には同意が必要ですか")
        assert "越境" in terms and "移転" in terms and "同意" in terms

    def test_function_word_query_yields_no_terms(self):
        assert lexical_terms("ある") == set()

    def test_japanese_question_retrieves_article_28(self):
        hits = seed_governance_kb().search(
            "顧客の個人データを海外のAIサービスに移転してもよいですか", scope="cross-border"
        )
        assert hits, "Japanese question retrieved nothing (str.split regression)"
        assert hits[0]["clause_id"] == "appi-a28"
        assert "第28条" in hits[0]["official_ref"]

    def test_offtopic_japanese_zero_hits(self):
        hits = seed_governance_kb().search("今日の東京の天気はどうですか")
        assert hits == []


class TestArticle28ExceptionRoutes:
    """Art.28 has two
    independent exception routes — the PPC-designated equivalent-protection
    country (指定国) and the standards-compliant recipient (基準適合体制). The
    seed must state BOTH, framed as fact-dependent (verification / legal
    review), never as a categorical consent conclusion.
    """

    def _a28(self):
        return {c["clause_id"]: c for c in _records()}["appi-a28"]

    def test_a28_states_both_exception_routes(self):
        text = self._a28()["text"]
        assert "指定国" in text, "designated-country route missing"
        assert "基準適合体制" in text, "recipient-standards route missing"

    def test_a28_frames_applicability_as_fact_dependent(self):
        text = self._a28()["text"]
        assert "legal review" in text
        assert "question of fact" in text
