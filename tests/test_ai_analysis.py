import json
from datetime import datetime, timezone

import httpx
import pytest

from egx_news_bot.ai_analysis import (
    AIAnalysisError,
    AIAnalysisConfig,
    AIConfigError,
    AIImpactAnalyzer,
    IMPACT_SCHEMA,
    OpenAIResponsesClient,
    assessment_from_ai_payload,
    extract_response_text,
)
from egx_news_bot.analysis import ImpactAnalyzer
from egx_news_bot.entities import CompanySeed, EntityRegistry
from egx_news_bot.models import NewsDocument


def _document() -> NewsDocument:
    return NewsDocument(
        external_id="n1",
        source_name="Al Borsa",
        source_url="https://example.com/n1",
        title="طلعت مصطفى توقع عقد تطوير مشروع جديد بقيمة 20 مليار جنيه",
        body="قالت الشركة إن العقد يدعم توسعاتها ومبيعاتها المستقبلية.",
        language="ar",
        published_at=None,
        credibility=0.75,
        tags=("real_estate",),
    )


def _ai_payload() -> dict:
    return {
        "summary": "عقد تطوير كبير ممكن يدعم شركة طلعت مصطفى وقطاع العقارات.",
        "event_type": "contract",
        "market_wide": False,
        "needs_review": False,
        "sectors": [
            {
                "sector": "Real Estate",
                "direction": "beneficiary",
                "direction_score": 0.82,
                "strength": 84,
                "confidence": 0.86,
                "rationale": "العقد الكبير ممكن يدعم المبيعات المتوقعة وثقة المستثمرين في القطاع.",
                "evidence": [
                    {
                        "text": "عقد تطوير مشروع جديد بقيمة 20 مليار جنيه",
                        "location": "title",
                        "reason": "large_contract",
                        "translated_hint": "عقد تطوير جديد بقيمة كبيرة.",
                    }
                ],
            }
        ],
        "stocks": [
            {
                "ticker": "TMGH",
                "isin": "EGS691S1C011",
                "company_name_ar": "مجموعة طلعت مصطفى القابضة",
                "company_name_en": "Talaat Moustafa Group Holding",
                "sector": "Real Estate",
                "direction": "beneficiary",
                "direction_score": 0.86,
                "strength": 88,
                "confidence": 0.89,
                "impact_type": "direct",
                "horizon": "1d",
                "rationale": "الشركة مذكورة في الخبر وحجم العقد مؤثر.",
                "evidence": [
                    {
                        "text": "طلعت مصطفى توقع عقد تطوير مشروع جديد",
                        "location": "title",
                        "reason": "named_company_contract",
                        "translated_hint": "طلعت مصطفى وقعت عقد تطوير جديد.",
                    }
                ],
            }
        ],
    }


def test_ai_config_requires_openai_key_for_ai_mode():
    with pytest.raises(AIConfigError, match="OPENAI_API_KEY"):
        AIAnalysisConfig.from_env({})

    config = AIAnalysisConfig.from_env({"OPENAI_API_KEY": "sk-test"})

    assert config.api_key == "sk-test"
    assert config.model == "gpt-5.4-mini"


def test_extract_response_text_reads_responses_api_output_text():
    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "{\"event_type\":\"contract\"}",
                    }
                ],
            }
        ]
    }

    assert extract_response_text(payload) == "{\"event_type\":\"contract\"}"


def test_openai_responses_client_posts_structured_schema_and_parses_json():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(_ai_payload()),
                            }
                        ],
                    }
                ]
            },
        )

    client = OpenAIResponsesClient(
        AIAnalysisConfig(api_key="sk-test", model="gpt-5.4-mini"),
        transport=httpx.MockTransport(handler),
    )
    rule_assessment = ImpactAnalyzer().analyze(_document())

    result = client.analyze(_document(), rule_assessment)

    assert result["event_type"] == "contract"
    assert requests[0].url == "https://api.openai.com/v1/responses"
    assert requests[0].headers["authorization"] == "Bearer sk-test"
    body = json.loads(requests[0].content)
    assert body["model"] == "gpt-5.4-mini"
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["strict"] is True
    assert body["input"][0]["role"] == "system"
    assert "Egyptian Arabic only" in body["input"][0]["content"]
    user_content = json.loads(body["input"][1]["content"])
    assert "known_egx_universe" in user_content
    assert any(stock["ticker"] == "TMGH" for stock in user_content["known_egx_universe"]["stocks"])


def test_openai_responses_client_serializes_rule_hints_with_datetimes():
    requests: list[httpx.Request] = []
    document = NewsDocument(
        external_id="n2",
        source_name="Arab Finance",
        source_url="https://example.com/n2",
        title="EGX market news",
        body="Market update body.",
        language="en",
        published_at=datetime(2026, 5, 25, 9, 30, tzinfo=timezone.utc),
        credibility=0.7,
        tags=("market",),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(_ai_payload())}],
                    }
                ]
            },
        )

    client = OpenAIResponsesClient(
        AIAnalysisConfig(api_key="sk-test", model="gpt-5.4-mini"),
        transport=httpx.MockTransport(handler),
    )

    client.analyze(document, ImpactAnalyzer().analyze(document))

    body = json.loads(requests[0].content)
    user_content = json.loads(body["input"][1]["content"])
    assert user_content["document"]["published_at"] == "2026-05-25T09:30:00+00:00"
    assert (
        user_content["rule_based_hints"]["document"]["published_at"]
        == "2026-05-25T09:30:00+00:00"
    )


def test_openai_responses_client_reports_sanitized_openai_error_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"message": "Invalid schema for response_format", "type": "invalid_request_error"}},
        )

    client = OpenAIResponsesClient(
        AIAnalysisConfig(api_key="secret-key", model="gpt-5.4-mini"),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(AIAnalysisError) as exc_info:
        client.analyze(_document(), ImpactAnalyzer().analyze(_document()))

    message = str(exc_info.value)
    assert "400" in message
    assert "Invalid schema for response_format" in message
    assert "secret-key" not in message


def test_impact_schema_strict_objects_require_all_declared_properties():
    def walk(schema: dict, path: str = "$"):
        if schema.get("type") == "object" and schema.get("additionalProperties") is False:
            properties = set(schema.get("properties", {}))
            required = set(schema.get("required", []))
            assert required == properties, path
        for key, value in schema.items():
            if isinstance(value, dict):
                walk(value, f"{path}.{key}")
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    if isinstance(item, dict):
                        walk(item, f"{path}.{key}[{index}]")

    walk(IMPACT_SCHEMA)


def test_ai_impact_analyzer_returns_ai_assessment_dataclasses():
    class FakeClient:
        def analyze(self, document, rule_assessment):
            return _ai_payload()

    assessment = AIImpactAnalyzer(FakeClient()).analyze(_document())

    assert assessment.analysis_method == "ai"
    assert assessment.summary == "عقد تطوير كبير ممكن يدعم شركة طلعت مصطفى وقطاع العقارات."
    assert assessment.event_type == "contract"
    assert assessment.needs_review is False
    assert assessment.sectors[0].sector == "Real Estate"
    assert assessment.sectors[0].strength == 84
    assert assessment.stocks[0].ticker == "TMGH"
    assert assessment.stocks[0].strength == 88
    assert assessment.stocks[0].evidence[0].reason == "named_company_contract"


def test_ai_payload_validation_keeps_only_real_registry_stocks_and_canonical_sector():
    registry = EntityRegistry(
        [
            CompanySeed(
                ticker="TMGH",
                isin="EGS691S1C011",
                name_ar="مجموعة طلعت مصطفى القابضة",
                name_en="Talaat Moustafa Group Holding",
                sector="Real Estate",
                aliases=("طلعت مصطفى", "TMGH"),
            )
        ]
    )
    payload = _ai_payload()
    payload["stocks"] = (
        payload["stocks"]
        + [
            {
                "ticker": "AAPL",
                "isin": None,
                "company_name_ar": "أبل",
                "company_name_en": "Apple",
                "sector": "Technology",
                "direction": "beneficiary",
                "direction_score": 0.5,
                "strength": 90,
                "confidence": 0.9,
                "impact_type": "direct",
                "horizon": "1d",
                "rationale": "مش شركة مقيدة في مصر.",
                "evidence": [],
            }
        ]
    )
    payload["sectors"] = [
        {
            **payload["sectors"][0],
            "sector": "property",
        }
    ]

    assessment = assessment_from_ai_payload(_document(), payload, registry=registry)

    assert assessment.impact_scope == "stock_related"
    assert [stock.ticker for stock in assessment.stocks] == ["TMGH"]
    assert assessment.stocks[0].company_name_ar == "مجموعة طلعت مصطفى القابضة"
    assert assessment.sectors[0].sector == "Real Estate"


def test_ai_payload_validation_marks_unknown_global_news_as_not_egx_related():
    document = NewsDocument(
        external_id="global-1",
        source_name="Global Source",
        source_url="https://example.com/global",
        title="Apple shares rise after US technology rally",
        body="The story is about Wall Street technology stocks.",
        language="en",
        published_at=None,
        credibility=0.7,
    )
    payload = {
        "summary": "خبر عالمي مش مرتبط بسهم مصري مقيد.",
        "event_type": "earnings_growth",
        "market_wide": True,
        "needs_review": False,
        "sectors": [
            {
                "sector": "Technology",
                "direction": "beneficiary",
                "direction_score": 0.6,
                "strength": 80,
                "confidence": 0.9,
                "rationale": "قطاع غير موجود في قائمة قطاعات البورصة المصرية.",
                "evidence": [],
            }
        ],
        "stocks": [
            {
                "ticker": "AAPL",
                "isin": None,
                "company_name_ar": "أبل",
                "company_name_en": "Apple",
                "sector": "Technology",
                "direction": "beneficiary",
                "direction_score": 0.6,
                "strength": 85,
                "confidence": 0.9,
                "impact_type": "direct",
                "horizon": "1d",
                "rationale": "مش سهم مصري.",
                "evidence": [],
            }
        ],
    }

    assessment = assessment_from_ai_payload(document, payload)

    assert assessment.impact_scope == "not_egx_related"
    assert assessment.stocks == ()
    assert assessment.sectors == ()
    assert assessment.needs_review is True
    assert assessment.market_wide is False
