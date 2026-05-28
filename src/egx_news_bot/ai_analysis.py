from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from os import environ
from typing import Any, Mapping, Protocol

import httpx

from egx_news_bot.analysis import ImpactAnalyzer
from egx_news_bot.entities import CompanySeed, EntityRegistry, canonical_sector, default_registry
from egx_news_bot.models import (
    EvidenceSnippet,
    NewsDocument,
    NewsImpactAssessment,
    SectorImpact,
    StockImpactCandidate,
)
from egx_news_bot.normalization import normalize_arabic
from egx_news_bot.relevance import is_egypt_market_related


class AIConfigError(ValueError):
    pass


class AIAnalysisError(RuntimeError):
    pass


@dataclass(frozen=True)
class AIAnalysisConfig:
    api_key: str
    model: str = "gpt-5.4-mini"
    base_url: str = "https://api.openai.com/v1"
    reasoning_effort: str = "low"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "AIAnalysisConfig":
        values = env or environ
        api_key = values.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise AIConfigError("OPENAI_API_KEY is required for AI analysis")
        return cls(
            api_key=api_key,
            model=values.get("OPENAI_MODEL", "gpt-5.4-mini").strip() or "gpt-5.4-mini",
            base_url=values.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            reasoning_effort=values.get("OPENAI_REASONING_EFFORT", "low").strip() or "low",
        )


class AIClient(Protocol):
    def analyze(self, document: NewsDocument, rule_assessment: NewsImpactAssessment) -> dict[str, Any]:
        ...


class OpenAIResponsesClient:
    def __init__(
        self,
        config: AIAnalysisConfig,
        *,
        timeout: float = 45.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OpenAIResponsesClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def analyze(self, document: NewsDocument, rule_assessment: NewsImpactAssessment) -> dict[str, Any]:
        response = self._client.post(
            f"{self._config.base_url}/responses",
            headers={
                "Authorization": f"Bearer {self._config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self._config.model,
                "input": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": _analysis_input(document, rule_assessment)},
                ],
                "reasoning": {"effort": self._config.reasoning_effort},
                "text": {
                    "format": {
                        "type": "json_schema",
                        "name": "egx_news_impact",
                        "strict": True,
                        "schema": IMPACT_SCHEMA,
                    }
                },
            },
        )
        if response.status_code >= 400:
            detail = _response_error_detail(response)
            suffix = f": {detail}" if detail else ""
            raise AIAnalysisError(f"OpenAI Responses API failed with status {response.status_code}{suffix}")
        text = extract_response_text(response.json())
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise AIAnalysisError("OpenAI response did not contain valid JSON") from exc


class AIImpactAnalyzer:
    def __init__(
        self,
        client: AIClient,
        *,
        rule_analyzer: ImpactAnalyzer | None = None,
        registry: EntityRegistry | None = None,
    ) -> None:
        self._registry = registry or default_registry()
        self._client = client
        self._rule_analyzer = rule_analyzer or ImpactAnalyzer(self._registry)

    def analyze(self, document: NewsDocument) -> NewsImpactAssessment:
        rule_assessment = self._rule_analyzer.analyze(document)
        payload = self._client.analyze(document, rule_assessment)
        return assessment_from_ai_payload(document, payload, registry=self._registry)


def extract_response_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                return content["text"]
    raise AIAnalysisError("OpenAI response did not include output_text")


def _response_error_detail(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:300] if text else None
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()[:300]
    description = payload.get("description") if isinstance(payload, dict) else None
    if isinstance(description, str) and description.strip():
        return description.strip()[:300]
    return None


def assessment_from_ai_payload(
    document: NewsDocument,
    payload: dict[str, Any],
    *,
    registry: EntityRegistry | None = None,
) -> NewsImpactAssessment:
    company_registry = registry or default_registry()
    stocks = tuple(
        stock
        for item in payload.get("stocks", [])
        if (stock := _validated_stock_from_payload(item, company_registry)) is not None
    )
    sectors = tuple(
        sector
        for item in payload.get("sectors", [])
        if (sector := _sector_from_payload(item)) is not None
    )
    sectors = _ensure_stock_sectors(sectors, stocks)
    if not stocks and sectors and not is_egypt_market_related(document):
        sectors = ()

    needs_review = bool(payload.get("needs_review", True))
    if not stocks and not sectors:
        needs_review = True
    return NewsImpactAssessment(
        document=document,
        event_type=str(payload.get("event_type") or "unclassified") if (stocks or sectors) else "unclassified",
        sectors=sectors,
        stocks=stocks,
        market_wide=bool(payload.get("market_wide", False)) and bool(stocks or sectors),
        needs_review=needs_review,
        analysis_method="ai",
        summary=str(payload["summary"]) if payload.get("summary") else None,
    )


def _sector_from_payload(item: dict[str, Any]) -> SectorImpact | None:
    sector = canonical_sector(str(item.get("sector") or ""))
    if sector is None:
        return None
    return SectorImpact(
        sector=sector,
        direction=_direction(item.get("direction")),
        direction_score=_float(item.get("direction_score"), 0.0, -1.0, 1.0),
        strength=_int(item.get("strength"), 0, 0, 100),
        confidence=_float(item.get("confidence"), 0.0, 0.0, 1.0),
        rationale=str(item.get("rationale") or ""),
        evidence=tuple(_evidence_from_payload(evidence) for evidence in item.get("evidence", [])),
    )


def _validated_stock_from_payload(item: dict[str, Any], registry: EntityRegistry) -> StockImpactCandidate | None:
    company = registry.find_company(
        ticker=_optional_str(item.get("ticker")),
        isin=_optional_str(item.get("isin")),
        name_ar=_optional_str(item.get("company_name_ar")),
        name_en=_optional_str(item.get("company_name_en")),
    )
    if company is None:
        return None
    return _stock_from_payload(item, company)


def _stock_from_payload(item: dict[str, Any], company: CompanySeed) -> StockImpactCandidate:
    return StockImpactCandidate(
        ticker=company.ticker,
        isin=company.isin,
        company_name_ar=company.name_ar,
        company_name_en=company.name_en,
        sector=company.sector,
        direction=_direction(item.get("direction")),
        direction_score=_float(item.get("direction_score"), 0.0, -1.0, 1.0),
        strength=_int(item.get("strength"), 0, 0, 100),
        confidence=_float(item.get("confidence"), 0.0, 0.0, 1.0),
        impact_type=str(item.get("impact_type") or "unknown"),
        horizon=str(item.get("horizon") or "unknown"),
        rationale=str(item.get("rationale") or ""),
        evidence=tuple(_evidence_from_payload(evidence) for evidence in item.get("evidence", [])),
    )


def _ensure_stock_sectors(
    sectors: tuple[SectorImpact, ...],
    stocks: tuple[StockImpactCandidate, ...],
) -> tuple[SectorImpact, ...]:
    by_sector = {sector.sector: sector for sector in sectors}
    for stock in stocks:
        if stock.sector in by_sector:
            continue
        by_sector[stock.sector] = SectorImpact(
            sector=stock.sector,
            direction=stock.direction,
            direction_score=stock.direction_score,
            strength=stock.strength,
            confidence=stock.confidence,
            rationale=stock.rationale,
            evidence=stock.evidence,
        )
    return tuple(by_sector.values())


def _evidence_from_payload(item: dict[str, Any]) -> EvidenceSnippet:
    text = str(item.get("text") or "")
    return EvidenceSnippet(
        text=text,
        normalized_text=normalize_arabic(text),
        location=str(item.get("location") or "article"),
        reason=str(item.get("reason") or "ai_reasoning"),
        translated_hint=_optional_str(item.get("translated_hint")),
    )


def _analysis_input(document: NewsDocument, rule_assessment: NewsImpactAssessment) -> str:
    data = {
        "task": "Analyze this Egyptian-market news item for likely EGX stock and sector impact. Public text must be Egyptian Arabic only.",
        "document": {
            "source_name": document.source_name,
            "source_url": document.source_url,
            "title": document.title,
            "body": document.body,
            "language": document.language,
            "published_at": document.published_at.isoformat() if document.published_at else None,
            "credibility": document.credibility,
            "tags": document.tags,
        },
        "known_egx_universe": {
            "stocks": [
                {
                    "ticker": company.ticker,
                    "isin": company.isin,
                    "name_ar": company.name_ar,
                    "name_en": company.name_en,
                    "sector": company.sector,
                    "aliases": company.aliases,
                }
                for company in default_registry().companies
            ],
            "sectors": default_registry().sectors(),
        },
        "rule_based_hints": asdict(rule_assessment),
        "scoring": {
            "strength": "0-100 materiality score. 65+ means worth alerting.",
            "confidence": "0-1 confidence in the interpretation.",
            "direction": "beneficiary, loser, mixed, or neutral.",
        },
    }
    return json.dumps(data, ensure_ascii=False, default=_json_default)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _direction(value: Any) -> str:
    text = str(value or "neutral").strip().lower()
    return text if text in {"beneficiary", "loser", "mixed", "neutral"} else "neutral"


def _float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


_SYSTEM_PROMPT = """You are an Egyptian Exchange market-impact analyst.

Read Arabic or English business news and decide whether it matters for EGX sectors or listed stocks.
You must distinguish general world news from Egypt/EGX-relevant news.
If no concrete listed-stock or sector impact exists, return unclassified with low strength and needs_review=true.

Rules:
- Do not provide investment advice or buy/sell instructions.
- Prefer direct named-company impacts over broad speculation.
- Only include a stock if it is clearly one of the known EGX-listed companies supplied in the user payload by ticker, ISIN, Arabic name, English name, or alias.
- Only include sectors from the supplied EGX sector universe.
- Public-facing free text fields must be Egyptian Arabic only: summary, rationale, and translated_hint. Do not write English phrases in these fields.
- If the article is global news with no clear Egyptian market channel, return no stocks, no sectors, low strength, and needs_review=true.
- Use evidence from the article title/body.
- Keep scores conservative unless the news is company-specific, macro-material, or regulatory.
- Return only JSON matching the schema.
"""


IMPACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "event_type", "market_wide", "needs_review", "sectors", "stocks"],
    "properties": {
        "summary": {"type": "string"},
        "event_type": {"type": "string"},
        "market_wide": {"type": "boolean"},
        "needs_review": {"type": "boolean"},
        "sectors": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "sector",
                    "direction",
                    "direction_score",
                    "strength",
                    "confidence",
                    "rationale",
                    "evidence",
                ],
                "properties": {
                    "sector": {"type": "string"},
                    "direction": {"type": "string", "enum": ["beneficiary", "loser", "mixed", "neutral"]},
                    "direction_score": {"type": "number", "minimum": -1, "maximum": 1},
                    "strength": {"type": "integer", "minimum": 0, "maximum": 100},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "rationale": {"type": "string"},
                    "evidence": {"type": "array", "items": {"$ref": "#/$defs/evidence"}},
                },
            },
        },
        "stocks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "ticker",
                    "isin",
                    "company_name_ar",
                    "company_name_en",
                    "sector",
                    "direction",
                    "direction_score",
                    "strength",
                    "confidence",
                    "impact_type",
                    "horizon",
                    "rationale",
                    "evidence",
                ],
                "properties": {
                    "ticker": {"type": ["string", "null"]},
                    "isin": {"type": ["string", "null"]},
                    "company_name_ar": {"type": "string"},
                    "company_name_en": {"type": ["string", "null"]},
                    "sector": {"type": "string"},
                    "direction": {"type": "string", "enum": ["beneficiary", "loser", "mixed", "neutral"]},
                    "direction_score": {"type": "number", "minimum": -1, "maximum": 1},
                    "strength": {"type": "integer", "minimum": 0, "maximum": 100},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "impact_type": {"type": "string"},
                    "horizon": {"type": "string"},
                    "rationale": {"type": "string"},
                    "evidence": {"type": "array", "items": {"$ref": "#/$defs/evidence"}},
                },
            },
        },
    },
    "$defs": {
        "evidence": {
            "type": "object",
            "additionalProperties": False,
            "required": ["text", "location", "reason", "translated_hint"],
            "properties": {
                "text": {"type": "string"},
                "location": {"type": "string"},
                "reason": {"type": "string"},
                "translated_hint": {"type": ["string", "null"]},
            },
        }
    },
}
