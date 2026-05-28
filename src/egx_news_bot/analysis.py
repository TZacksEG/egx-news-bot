from __future__ import annotations

from dataclasses import dataclass

from egx_news_bot.entities import CompanyMention, EntityRegistry, default_registry
from egx_news_bot.models import (
    EvidenceSnippet,
    NewsDocument,
    NewsImpactAssessment,
    SectorImpact,
    StockImpactCandidate,
)
from egx_news_bot.normalization import normalize_arabic


@dataclass(frozen=True)
class _EventRule:
    event_type: str
    keywords: tuple[str, ...]
    base_strength: int
    stock_direction: str
    sector_direction: str
    market_wide: bool = False


_DIRECT_RULES: tuple[_EventRule, ...] = (
    _EventRule("contract", ("عقد", "ترسيه", "تطوير مشروع", "contract", "award"), 72, "beneficiary", "beneficiary"),
    _EventRule("earnings_growth", ("نمو الارباح", "ارتفاع الارباح", "increase in profit", "profit growth"), 68, "beneficiary", "beneficiary"),
    _EventRule("dividend", ("توزيع ارباح", "كوبون", "dividend"), 62, "beneficiary", "beneficiary"),
    _EventRule("loss", ("خساير", "تراجع الارباح", "net loss", "losses"), 72, "loser", "loser"),
    _EventRule("trading_halt", ("ايقاف التداول", "وقف التداول", "suspend trading"), 78, "loser", "loser"),
)

_MACRO_RATE_CUT = ("خفض اسعار الفايده", "يخفض اسعار الفايده", "خفض الفايده", "rate cut", "cuts interest")
_MACRO_RATE_HIKE = ("رفع اسعار الفايده", "يرفع اسعار الفايده", "رفع الفايده", "rate hike", "raises interest")
_GAS_PRICE_HIKE = ("رفع اسعار الغاز", "زياده اسعار الغاز", "natural gas price increase")


class ImpactAnalyzer:
    def __init__(self, registry: EntityRegistry | None = None) -> None:
        self._registry = registry or default_registry()

    def analyze(self, document: NewsDocument) -> NewsImpactAssessment:
        text = _combined_text(document)
        normalized = normalize_arabic(text)
        mentions = self._registry.find_mentions(text)

        if _contains(normalized, _MACRO_RATE_CUT):
            return self._interest_rate_cut(document, normalized)
        if _contains(normalized, _MACRO_RATE_HIKE):
            return self._interest_rate_hike(document, normalized)
        if _contains(normalized, _GAS_PRICE_HIKE):
            return self._gas_price_hike(document, normalized, mentions)

        rule = _match_direct_rule(normalized)
        if rule is None:
            return self._neutral(document, normalized, mentions)
        return self._direct_company_impact(document, normalized, mentions, rule)

    def _direct_company_impact(
        self,
        document: NewsDocument,
        normalized: str,
        mentions: list[CompanyMention],
        rule: _EventRule,
    ) -> NewsImpactAssessment:
        evidence = (_evidence(document.title, "title", rule.event_type),)
        mentioned = mentions[:5]
        sectors = _sector_impacts_from_mentions(mentioned, rule, document, evidence)
        stocks = tuple(
            _stock_candidate(
                mention=mention,
                direction=rule.stock_direction,
                strength=_bounded(rule.base_strength + _magnitude_boost(normalized)),
                confidence=_confidence(document.credibility, entity_quality=mention.match_score, directness=1.0),
                impact_type="direct",
                horizon="1d",
                rationale="الشركة مذكورة بوضوح في خبر له تأثير مباشر عليها.",
                evidence=evidence,
            )
            for mention in mentioned
        )
        best_confidence = max((stock.confidence for stock in stocks), default=0.0)
        return NewsImpactAssessment(
            document=document,
            event_type=rule.event_type,
            sectors=sectors,
            stocks=stocks,
            market_wide=False,
            needs_review=not stocks or best_confidence < 0.65,
        )

    def _interest_rate_cut(self, document: NewsDocument, normalized: str) -> NewsImpactAssessment:
        evidence = (_evidence(document.title, "title", "interest_rate_cut"),)
        boost = _magnitude_boost(normalized)
        sectors = (
            SectorImpact(
                sector="Real Estate",
                direction="beneficiary",
                direction_score=0.75,
                strength=_bounded(72 + boost),
                confidence=_confidence(document.credibility, entity_quality=0.8, directness=0.9),
                rationale="خفض الفائدة ممكن يقلل تكلفة التمويل ويدعم الطلب على العقارات.",
                evidence=evidence,
            ),
            SectorImpact(
                sector="Non-bank Financial Services",
                direction="beneficiary",
                direction_score=0.55,
                strength=_bounded(62 + boost),
                confidence=_confidence(document.credibility, entity_quality=0.75, directness=0.8),
                rationale="انخفاض تكلفة التمويل ممكن يدعم الطلب على التمويل وأسعار الأصول.",
                evidence=evidence,
            ),
            SectorImpact(
                sector="Banks",
                direction="mixed",
                direction_score=0.05,
                strength=_bounded(52 + boost // 2),
                confidence=_confidence(document.credibility, entity_quality=0.75, directness=0.8),
                rationale="خفض الفائدة ممكن يدعم نمو الائتمان لكنه يضغط على عوائد بعض الأصول.",
                evidence=evidence,
            ),
        )
        return NewsImpactAssessment(
            document=document,
            event_type="interest_rate_cut",
            sectors=sectors,
            stocks=(),
            market_wide=True,
            needs_review=False,
        )

    def _interest_rate_hike(self, document: NewsDocument, normalized: str) -> NewsImpactAssessment:
        evidence = (_evidence(document.title, "title", "interest_rate_hike"),)
        boost = _magnitude_boost(normalized)
        sectors = (
            SectorImpact(
                sector="Banks",
                direction="mixed",
                direction_score=0.1,
                strength=_bounded(58 + boost),
                confidence=_confidence(document.credibility, entity_quality=0.75, directness=0.8),
                rationale="رفع الفائدة ممكن يدعم العوائد لكنه يضغط على نمو الائتمان وجودة الأصول.",
                evidence=evidence,
            ),
            SectorImpact(
                sector="Real Estate",
                direction="loser",
                direction_score=-0.7,
                strength=_bounded(72 + boost),
                confidence=_confidence(document.credibility, entity_quality=0.75, directness=0.8),
                rationale="رفع الفائدة بيزود تكلفة التمويل وممكن يضعف الطلب على العقارات.",
                evidence=evidence,
            ),
        )
        return NewsImpactAssessment(
            document=document,
            event_type="interest_rate_hike",
            sectors=sectors,
            stocks=(),
            market_wide=True,
            needs_review=False,
        )

    def _gas_price_hike(
        self,
        document: NewsDocument,
        normalized: str,
        mentions: list[CompanyMention],
    ) -> NewsImpactAssessment:
        evidence = (_evidence(document.title, "title", "gas_price_hike"),)
        sectors = (
            SectorImpact(
                sector="Basic Resources",
                direction="loser",
                direction_score=-0.75,
                strength=_bounded(76 + _magnitude_boost(normalized)),
                confidence=_confidence(document.credibility, entity_quality=0.75, directness=0.85),
                rationale="زيادة أسعار الغاز ممكن تضغط على الشركات كثيفة استهلاك الطاقة.",
                evidence=evidence,
            ),
            SectorImpact(
                sector="Industrials",
                direction="loser",
                direction_score=-0.6,
                strength=_bounded(68 + _magnitude_boost(normalized)),
                confidence=_confidence(document.credibility, entity_quality=0.7, directness=0.8),
                rationale="ارتفاع تكلفة الوقود ممكن يقلل هوامش ربح الشركات الصناعية.",
                evidence=evidence,
            ),
        )
        stocks = tuple(
            _stock_candidate(
                mention=mention,
                direction="loser",
                strength=74,
                confidence=_confidence(document.credibility, entity_quality=mention.match_score, directness=0.9),
                impact_type="direct",
                horizon="1d",
                rationale="الشركة المذكورة معرضة لتغير تكلفة الطاقة في الخبر.",
                evidence=evidence,
            )
            for mention in mentions
        )
        return NewsImpactAssessment(
            document=document,
            event_type="gas_price_hike",
            sectors=sectors,
            stocks=stocks,
            market_wide=True,
            needs_review=False,
        )

    def _neutral(
        self,
        document: NewsDocument,
        normalized: str,
        mentions: list[CompanyMention],
    ) -> NewsImpactAssessment:
        evidence = (_evidence(document.title, "title", "unclassified"),)
        stocks = tuple(
            _stock_candidate(
                mention=mention,
                direction="neutral",
                strength=25,
                confidence=_confidence(document.credibility, entity_quality=mention.match_score, directness=0.35),
                impact_type="direct",
                horizon="intraday",
                rationale="الشركة اتذكرت في الخبر لكن التأثير الاستثماري مش واضح.",
                evidence=evidence,
            )
            for mention in mentions[:5]
        )
        return NewsImpactAssessment(
            document=document,
            event_type="unclassified",
            sectors=(),
            stocks=stocks,
            market_wide=False,
            needs_review=True,
        )


def _combined_text(document: NewsDocument) -> str:
    return f"{document.title}\n{document.body or ''}"


def _contains(normalized: str, keywords: tuple[str, ...]) -> bool:
    return any(normalize_arabic(keyword) in normalized for keyword in keywords)


def _match_direct_rule(normalized: str) -> _EventRule | None:
    for rule in _DIRECT_RULES:
        if _contains(normalized, rule.keywords):
            return rule
    return None


def _sector_impacts_from_mentions(
    mentions: list[CompanyMention],
    rule: _EventRule,
    document: NewsDocument,
    evidence: tuple[EvidenceSnippet, ...],
) -> tuple[SectorImpact, ...]:
    seen: set[str] = set()
    impacts: list[SectorImpact] = []
    for mention in mentions:
        if mention.sector in seen:
            continue
        seen.add(mention.sector)
        strength = _bounded(rule.base_strength + 4)
        impacts.append(
            SectorImpact(
                sector=mention.sector,
                direction=rule.sector_direction,
                direction_score=_direction_score(rule.sector_direction),
                strength=strength,
                confidence=_confidence(document.credibility, entity_quality=mention.match_score, directness=0.9),
                rationale="القطاع متأثر من خلال الشركة المذكورة في الخبر.",
                evidence=evidence,
            )
        )
    return tuple(impacts)


def _stock_candidate(
    mention: CompanyMention,
    direction: str,
    strength: int,
    confidence: float,
    impact_type: str,
    horizon: str,
    rationale: str,
    evidence: tuple[EvidenceSnippet, ...],
) -> StockImpactCandidate:
    return StockImpactCandidate(
        ticker=mention.ticker,
        isin=mention.isin,
        company_name_ar=mention.name_ar,
        company_name_en=mention.name_en,
        sector=mention.sector,
        direction=direction,
        direction_score=_direction_score(direction),
        strength=strength,
        confidence=confidence,
        impact_type=impact_type,
        horizon=horizon,
        rationale=rationale,
        evidence=evidence,
    )


def _direction_score(direction: str) -> float:
    if direction == "beneficiary":
        return 0.75
    if direction == "loser":
        return -0.75
    if direction == "mixed":
        return 0.05
    return 0.0


def _confidence(source_credibility: float, *, entity_quality: float, directness: float) -> float:
    value = 0.30 * entity_quality + 0.25 * directness + 0.30 * source_credibility + 0.15 * 0.75
    return round(max(0.0, min(1.0, value)), 2)


def _magnitude_boost(normalized: str) -> int:
    if "مليار" in normalized or "billion" in normalized:
        return 8
    if "مليون" in normalized or "million" in normalized:
        return 4
    if "200 نقطه" in normalized or "200 basis" in normalized:
        return 8
    if "100 نقطه" in normalized or "100 basis" in normalized:
        return 5
    return 0


def _evidence(text: str, location: str, reason: str) -> EvidenceSnippet:
    snippet = text.strip()
    if len(snippet) > 180:
        snippet = f"{snippet[:177]}..."
    return EvidenceSnippet(
        text=snippet,
        normalized_text=normalize_arabic(snippet),
        location=location,
        reason=reason,
    )


def _bounded(value: int) -> int:
    return max(0, min(100, value))
