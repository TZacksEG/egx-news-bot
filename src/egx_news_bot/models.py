from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class NewsFeedConfig:
    name: str
    url: str
    language: str
    credibility: float
    tags: tuple[str, ...] = ()
    poll_interval_seconds: int = 300


@dataclass(frozen=True)
class NewsDocument:
    external_id: str | None
    source_name: str
    source_url: str
    title: str
    body: str | None
    language: str
    published_at: datetime | None
    credibility: float
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceSnippet:
    text: str
    normalized_text: str
    location: str
    reason: str
    translated_hint: str | None = None


@dataclass(frozen=True)
class SectorImpact:
    sector: str
    direction: str
    direction_score: float
    strength: int
    confidence: float
    rationale: str
    evidence: tuple[EvidenceSnippet, ...] = ()


@dataclass(frozen=True)
class StockImpactCandidate:
    ticker: str | None
    isin: str | None
    company_name_ar: str
    company_name_en: str | None
    sector: str
    direction: str
    direction_score: float
    strength: int
    confidence: float
    impact_type: str
    horizon: str
    rationale: str
    evidence: tuple[EvidenceSnippet, ...] = ()


@dataclass(frozen=True)
class NewsImpactAssessment:
    document: NewsDocument
    event_type: str
    sectors: tuple[SectorImpact, ...] = field(default_factory=tuple)
    stocks: tuple[StockImpactCandidate, ...] = field(default_factory=tuple)
    market_wide: bool = False
    needs_review: bool = True
    analysis_method: str = "rules"
    summary: str | None = None

    @property
    def impact_scope(self) -> str:
        if self.stocks:
            return "stock_related"
        if self.sectors:
            return "sector_only"
        return "not_egx_related"
