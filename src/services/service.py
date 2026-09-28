"""CMN-C1-160 — service layer: governance clause retrieval + LLM (DI).

The external services (the governance/APPI clause retriever, and the LLM) are
injected so the template is offline-testable and deployment-agnostic. Production
binds the real hybrid vector+keyword store over the curated governance KB (the
APPI in force — 平成15年法律第57号, PPC guidelines, cross-border transfer rules,
corporate AI-use policy) + platform LLM client (resolved via `ctx.secrets`);
tests bind the in-memory / stub implementations defined here.

No `agenticstar` (Level 0) imports; no `framework.*` dependency — pure domain logic.
"""

from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

# Governance scopes (ScopeClassifyNode output domain).
SCOPES: tuple[str, ...] = (
    "permitted-use",
    "prohibited-use",
    "data-handling",
    "cross-border",
    "disclosure",
)

# Data-sensitivity tiers (low → high) used by ScopeClassify / answer emphasis.
SENSITIVITY_ORDER: tuple[str, ...] = (
    "anonymized",
    "pseudonymized",
    "personal-data",
    "sensitive-personal-data",
)

# ── Official references (single source of truth for citations/remediation) ──
# The Act in force: 平成15年法律第57号, as amended by 令和2年法律第44号,
# fully in force since 2022-04-01. No other legal facts are asserted here.
APPI_REF = "個人情報の保護に関する法律（平成15年法律第57号）"
_EGOV = "e-Gov 法令ID 415AC0000000057"
APPI_EFFECTIVE = "2022-04-01"  # 令和2年法律第44号改正の全面施行日
ART28_CROSS_BORDER_REF = f"{APPI_REF}第28条 ({_EGOV})"
ART20_SENSITIVE_REF = f"{APPI_REF}第20条第2項 ({_EGOV})"
# PPC guidelines: the edition/revision date is intentionally NOT stated —
# no verified pin is available, and an unverifiable version string would be
# a fabricated legal fact.
PPC_GUIDELINES_REF = "個人情報保護委員会「個人情報の保護に関する法律についてのガイドライン（通則編）」"


# ★ 日本語 KB × 語彙検索の構造欠陥 (本番 Pod で実証):
# str.split() は空白区切りなので日本語の文が 1 トークンに潰れ、日本語質問は
# 何も引けない。内容語 + CJK 文字 bigram + 機能語除去で解決する
# (実装は 328 の service.lexical_terms を移植 — a sibling template と同じ形)。
_CJK_RE = re.compile(r"[぀-ヿ一-鿿ｦ-ﾟ]+")
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_.-]*")

# Function words carry no topical signal but are dense in prose, so they let an
# out-of-scope question score highly on any chunk (328 measured "What is the
# weather in Tokyo today?" at 0.429 on stopword overlap alone). Dropped before
# scoring in both scripts.
_STOPWORDS: frozenset[str] = frozenset(
    """
a an the and or but if then than that this these those of in on at to for from by with
without about into over under as is are was were be been being do does did doing have
has had having i you he she it we they me my your his her its our their what which who
whom when where why how should would could can may might must will shall not no yes so
such only own same too very just also there here up down out off again further once
""".split()
)

# Japanese function-word bigrams. Bigram indexing makes a short, function-word
# query dangerous rather than merely imprecise: "ある" yields the single term
# {ある}, and any chunk containing it scores 1.0. Dropping these before scoring
# makes such a query yield no terms at all — the correct outcome for a query
# with no topical content (same list as sibling templates).
_JA_FUNCTION_BIGRAMS: frozenset[str] = frozenset(
    """
する すれ すな すべ して した しな しま しょ され せる れる られ でき きる こう
ある あり あっ ない なく なし いる いた いま なる なっ なり なら れば
これ それ あれ どれ この その あの どの どう そう ああ いう
れは れを れが れに れで はこ はそ はど はな はで はと
こと もの ため とき よう ところ ばあ あい
です ます ませ まし だっ であ でし でも ても とも
から まで より ので のに には では との への とし につ いて ついて ため
がで がい がな をど をす をし にす にお おけ ける
うす うか うし うも いか いき かた たら
るこ るの るか ると るが るを るに るで るは るも るま
たこ たの たか たと たが たを たに
のこ のか のと のが のを のに のは のも
なの なか なと なが なに ので うな あな
""".split()
)


def lexical_terms(text: str) -> set[str]:
    """Topical lexical terms: content words plus CJK character bigrams.

    Punctuation is stripped so "retrieval?" and "retrieval" are the same term,
    and function words are dropped in both scripts (`_STOPWORDS`,
    `_JA_FUNCTION_BIGRAMS`). A query left with no terms retrieves nothing,
    which is the intended outcome for a query with no topical content.
    """
    terms = {t for t in _WORD_RE.findall(text.lower()) if t not in _STOPWORDS}
    for run in _CJK_RE.findall(text):
        if len(run) == 1:
            terms.add(run)
        else:
            terms |= {run[i : i + 2] for i in range(len(run) - 1)} - _JA_FUNCTION_BIGRAMS
    return terms


def _meaningful_terms(text: str) -> set[str]:
    """Topical terms — content words + CJK bigrams (328 の lexical_terms)."""
    return lexical_terms(text)


@runtime_checkable
class GovernanceKBBackend(Protocol):
    """Governance/APPI clause retriever boundary.

    `search` returns a ranked list of clause dicts, each shaped:
        {"clause_id": str, "source": str, "title": str, "text": str,
         "score": float, "scope": str | None,
         "official_ref": str, "effective_date": str | None}
    `scope`, when given, biases ranking toward clauses tagged for that scope.
    """

    def search(self, query: str, top_k: int = 6, scope: str | None = None) -> list[dict[str, Any]]: ...


@runtime_checkable
class LLMClient(Protocol):
    """LLM boundary — `generate(prompt) -> str`."""

    def generate(self, prompt: str) -> str: ...


class InMemoryGovernanceBackend:
    """In-memory GovernanceKBBackend for tests / local runs.

    Seed with `add([clause, ...])`; `search` ranks by naive lexical overlap and,
    when a `scope` is given, boosts clauses tagged for that scope (or tagged
    cross-scope / generic). Production swaps in the real hybrid vector+keyword
    index over the curated governance KB. The scope boost only re-ranks
    *lexical matches* — it never creates a hit from zero overlap (off-topic
    questions still return zero hits → out-of-scope safe answer downstream).
    """

    def __init__(self) -> None:
        self._clauses: list[dict[str, Any]] = []

    def add(self, clauses: list[dict[str, Any]]) -> None:
        self._clauses.extend(clauses)

    def search(self, query: str, top_k: int = 6, scope: str | None = None) -> list[dict[str, Any]]:
        terms = _meaningful_terms(query)

        def score(c: dict[str, Any]) -> float:
            words = _meaningful_terms(str(c.get("text", ""))) | _meaningful_terms(str(c.get("title", "")))
            base = (len(terms & words) / len(terms)) if terms and words else 0.0
            tag = c.get("scope")
            if base > 0.0 and scope and tag in (scope, None, "generic"):
                base += 0.15  # scope-relevance boost (incl. generic clauses)
            return round(base, 4)

        ranked = sorted(
            ({**c, "score": score(c)} for c in self._clauses),
            key=lambda c: c["score"],
            reverse=True,
        )
        return [c for c in ranked if c["score"] > 0.0][:top_k]


class StubLLMClient:
    """Deterministic stub LLM for tests / local runs — returns a templated answer.

    Never bound by default: with no LLM resolved (see `resolve_llm_client`) the
    LLM steps are skipped and the answer says so (`LLM_NOT_CONFIGURED`); the
    deterministic verdict / remediation / citations are still produced.
    """

    def __init__(self, canned: str | None = None) -> None:
        self._canned = canned

    def generate(self, prompt: str) -> str:
        if self._canned is not None:
            return self._canned
        tail = prompt.strip().splitlines()[-1][:200] if prompt.strip() else ""
        return f"Per the cited APPI / governance clauses: {tail} [C1]"


# ── LLM seam: config["llm"] → LLMClient ───────────────────────────────────────
# Reason code surfaced (S-4 event + answer text) when no LLM is bound anywhere.
LLM_NOT_CONFIGURED = "LLM_NOT_CONFIGURED"


def _as_text(result: Any) -> str:
    """Coerce a client reply to text: str as-is, message-like objects via `.content`."""
    if isinstance(result, str):
        return result
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content
    return "" if result is None else str(result)


class ConfigLLMAdapter:
    """Adapt a `config["llm"]` object to this template's `LLMClient` Protocol.

    The fleet entry point places a lazily-resolved chat client under `config["llm"]`
    that answers `invoke(prompt) -> str` (and `complete(prompt, **kw) -> str`); this
    template's nodes speak `generate(prompt) -> str`. The adapter forwards to `invoke`
    first, then `complete`, and never swallows the client's exceptions — a configured
    but failing LLM must surface, not silently degrade.
    """

    def __init__(self, client: Any) -> None:
        call = getattr(client, "invoke", None)
        if not callable(call):
            call = getattr(client, "complete", None)
        if not callable(call):
            raise TypeError(
                "config['llm'] must expose generate(prompt), invoke(prompt) or "
                f"complete(prompt); got {type(client).__name__}"
            )
        self._client = client
        self._call = call

    def generate(self, prompt: str) -> str:
        return _as_text(self._call(prompt))


def resolve_llm_client(explicit: LLMClient | None, config: Any) -> LLMClient | None:
    """Precedence: explicit `llm_client` kw > `config["llm"]` > None.

    None means "no LLM bound": ScopeClassify skips its LLM disambiguation (heuristic
    only) and ComplianceAnswer names `LLM_NOT_CONFIGURED` in place of the rationale,
    while the deterministic verdict / remediation / citations are produced as usual.
    An object under `config["llm"]` that answers none of generate/invoke/complete
    raises at construction (misconfiguration is not a reason to degrade quietly).
    """
    if explicit is not None:
        return explicit
    candidate = config.get("llm") if isinstance(config, dict) else None
    if candidate is None:
        return None
    if isinstance(candidate, LLMClient):
        return candidate
    return ConfigLLMAdapter(candidate)


def seed_governance_kb() -> InMemoryGovernanceBackend:
    """Return an InMemoryGovernanceBackend seeded with clauses of the APPI in force.

    Every record cites a verifiable official identifier in ``official_ref`` — a
    compliance template must not present unverifiable legal facts as its
    bare-Graph default. The APPI
    records below are the Act as amended by Act No. 44 of 2020 (令和2年法律第44号),
    fully in force since 2022-04-01. The previously seeded fictitious future
    amendment does not exist; the obligations are expressed through the
    articles of the Act that actually apply.
    Production replaces this with the full curated/indexed KB (KB curation
    gate); the clause shape is identical. Texts are 日英併記 so Japanese and
    English questions both retrieve.
    """
    backend = InMemoryGovernanceBackend()
    backend.add(
        [
            {
                "clause_id": "appi-a17",
                "source": "APPI (in force)",
                "scope": "permitted-use",
                "title": "Specification of the purpose of use (利用目的の特定)",
                "text": (
                    "the purpose of use of personal information must be specified as far as "
                    "possible; bringing personal data into an external or personal ai assistant "
                    "requires that purpose to be specified before use "
                    "利用目的の特定 個人情報 目的 特定 AIアシスタント 利用"
                ),
                "official_ref": f"{APPI_REF}第17条 ({_EGOV})",
                "effective_date": APPI_EFFECTIVE,
            },
            {
                "clause_id": "appi-a18",
                "source": "APPI (in force)",
                "scope": "permitted-use",
                "title": "Restriction on use beyond the specified purpose (目的外利用の制限)",
                "text": (
                    "personal information may not be handled beyond the scope necessary to "
                    "achieve the specified purpose without the prior consent of the principal; "
                    "using personal data with a new external ai assistant for a new purpose "
                    "needs consent; statutory exceptions (e.g. 法令に基づく場合) exist under "
                    "the article itself 目的外利用 同意 利用目的の変更 個人データ 使用"
                ),
                "official_ref": f"{APPI_REF}第18条 ({_EGOV})",
                "effective_date": APPI_EFFECTIVE,
            },
            {
                "clause_id": "appi-a20",
                "source": "APPI (in force)",
                "scope": "prohibited-use",
                "title": "Restriction on acquiring sensitive personal information (要配慮個人情報)",
                "text": (
                    "sensitive personal information (要配慮個人情報 — health, medical history, "
                    "criminal record, race, creed, social status) may not be acquired without "
                    "the principal's prior consent unless an exception under the article applies; "
                    "inputting such data into an uncontrolled personal ai tool risks unlawful "
                    "acquisition/provision 要配慮個人情報 取得 同意 病歴 医療 犯罪歴"
                ),
                "official_ref": f"{APPI_REF}第20条第2項 ({_EGOV})",
                "effective_date": APPI_EFFECTIVE,
            },
            {
                "clause_id": "appi-a28",
                "source": "APPI (in force)",
                "scope": "cross-border",
                "title": "Restriction on provision to a third party in a foreign country (外国第三者提供)",
                # Art.28 has TWO independent exception routes: (i) a PPC-DESIGNATED
                # country with an equivalent protection regime (指定国), and
                # (ii) a recipient maintaining a standards-compliant system
                # (基準適合体制). Stating only one overstates the consent duty.
                "text": (
                    "providing personal data to a third party or ai service located in a foreign "
                    "country requires the principal's prior consent under Article 28, unless "
                    "(i) the destination country is designated by the Personal Information "
                    "Protection Commission as having a personal-information protection system "
                    "recognised as equivalent to Japan's (指定国), or (ii) the recipient "
                    "maintains a system meeting the standards prescribed by Commission rules "
                    "(基準適合体制). Whether either basis applies to a specific transfer is a "
                    "question of fact requiring verification and legal review — this record "
                    "states the rule, it does not decide the user's facts. Information on the "
                    "destination country must be provided when obtaining consent; personal ai "
                    "tools that egress data to overseas regions are in scope "
                    "越境移転 海外移転 外国 第三者提供 同意 指定国 同等の水準 基準適合体制 移転 海外"
                ),
                "official_ref": ART28_CROSS_BORDER_REF,
                "effective_date": APPI_EFFECTIVE,
            },
            {
                "clause_id": "appi-a22",
                "source": "APPI (in force)",
                "scope": "data-handling",
                "title": "Accuracy of data and erasure when no longer needed (努力義務)",
                "text": (
                    "a handling operator must endeavour to keep personal data accurate and up to "
                    "date and to erase it without delay when its use is no longer needed — an "
                    "obligation of effort, not an absolute deletion deadline; applies to copies "
                    "held in ai tools 消去 削除 保持 保存期間 正確性 努力義務"
                ),
                "official_ref": f"{APPI_REF}第22条 ({_EGOV})",
                "effective_date": APPI_EFFECTIVE,
            },
            {
                "clause_id": "appi-a26",
                "source": "APPI (in force)",
                "scope": "data-handling",
                "title": "Reporting of a leakage etc. and notification to the principal (漏えい等報告)",
                "text": (
                    "a leakage of personal data likely to harm the rights and interests of an "
                    "individual — including exposure through an unapproved ai tool — must be "
                    "reported to the Personal Information Protection Commission as prescribed by "
                    "Commission rules, and the principal notified "
                    "漏えい 報告 個人情報保護委員会 本人通知 インシデント"
                ),
                "official_ref": f"{APPI_REF}第26条 ({_EGOV})",
                "effective_date": APPI_EFFECTIVE,
            },
            {
                "clause_id": "ppc-gl-handling",
                "source": "PPC Guidelines",
                "scope": "data-handling",
                "title": "Commission guidelines — minimisation and records for AI processing",
                "text": (
                    "the Commission's general-rules guidelines explain the handling duties: "
                    "minimise the personal data exposed to ai systems; pseudonymise or anonymise "
                    "where the task allows; retain audit records of what data was processed and "
                    "why ガイドライン 通則編 最小化 仮名加工 匿名加工 記録"
                ),
                # 版・改正日は意図的に記載しない (確証が取れないため — 版なしが正)。
                "official_ref": PPC_GUIDELINES_REF,
                "effective_date": None,
            },
            {
                "clause_id": "ppc-gl-disclosure",
                "source": "PPC Guidelines",
                "scope": "disclosure",
                "title": "Commission guidelines — purpose publication and data-subject rights",
                "text": (
                    "the Commission's general-rules guidelines explain how the purpose of use is "
                    "specified and publicised and how data subjects learn that processing of "
                    "their personal data is occurring and exercise access and deletion rights "
                    "ガイドライン 通則編 公表 開示 本人 権利 利用目的"
                ),
                # 版・改正日は意図的に記載しない (確証が取れないため — 版なしが正)。
                "official_ref": PPC_GUIDELINES_REF,
                "effective_date": None,
            },
            {
                "clause_id": "gdpr-a22",
                "source": "GDPR cross-reference",
                "scope": "generic",
                "title": "Automated individual decision-making — GDPR cross-reference",
                "text": (
                    "under the GDPR a data subject has the right not to be subject to a decision "
                    "based solely on automated processing producing legal or similarly "
                    "significant effects; provide human involvement and a route to contest "
                    "自動化された決定 プロファイリング"
                ),
                "official_ref": "Regulation (EU) 2016/679 (CELEX 32016R0679), Article 22",
                "effective_date": "2018-05-25",
            },
            {
                "clause_id": "corp-ai-policy-byo",
                "source": "Corporate AI-use policy",
                "scope": "generic",
                "title": "Bring-your-own personal AI assistant policy",
                "text": (
                    "employees may use approved personal ai assistants for non-confidential, "
                    "non-personal-data tasks; corporate email, customer data, and source code "
                    "must not be pasted into a personal ai tool that is not on the approved, "
                    "contracted list 社内規程 承認済み ツール 業務利用"
                ),
                # 社内規程の例示レコード — 法令ではないので法令 ID は持たない (捏造しない)。
                "official_ref": "本テンプレートの例示レコード（実在の社内規程・外部の公的文書を出典としない。例示であることを明示）",
                "effective_date": None,
            },
        ]
    )
    return backend
