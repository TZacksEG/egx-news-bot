import json
import re

import httpx
import pytest

from egx_news_bot.analysis import ImpactAnalyzer
from egx_news_bot.models import (
    EvidenceSnippet,
    NewsDocument,
    NewsImpactAssessment,
    SectorImpact,
    StockImpactCandidate,
)
from egx_news_bot.telegram import (
    NEWS_SEPARATOR,
    TelegramClient,
    TelegramConfig,
    TelegramConfigError,
    TelegramDeliveryError,
    TelegramNotifier,
    render_telegram_message,
)


def _assessment():
    document = NewsDocument(
        external_id="sample-1",
        source_name="Manual Source",
        source_url="https://example.com/news/1",
        title="طلعت مصطفى توقع عقد تطوير مشروع جديد بقيمة 20 مليار جنيه",
        body="قالت الشركة إن العقد يدعم توسعاتها ومبيعاتها المستقبلية.",
        language="ar",
        published_at=None,
        credibility=0.7,
    )
    return ImpactAnalyzer().analyze(document)


def test_render_telegram_message_shows_news_impact_and_evidence():
    message = render_telegram_message(_assessment())

    assert message.startswith("\u200fملخص الخبر:\n")
    assert "تقرير تأثير الخبر على البورصة المصرية" not in message
    assert "طلعت مصطفى توقع عقد تطوير مشروع جديد بقيمة 20 مليار جنيه" in message
    assert message.index("تأثير الخبر:") < message.index("السهم المرتبط:")
    assert message.index("السهم المرتبط:") < message.index("القطاع المتأثر:")
    assert message.index("القطاع المتأثر:") < message.index("إشارة عامة:")
    assert message.index("إشارة عامة:") < message.index("سبب التقييم:")
    assert message.index("سبب التقييم:") < message.index("المصدر:")
    assert message.index("المصدر:") < message.index("نوع الخبر:")
    assert "نوع الخبر:\n\u200fعقد أو مشروع جديد" in message
    assert "طريقة التحليل" not in message
    assert "الرابط:" not in message
    assert "مراجعة بشرية" not in message
    assert "تأثير الخبر:\n\u200fإيجابي للسهم\n\u200fجيد للسهم" in message
    assert "السهم المرتبط:\n\u200fمجموعة طلعت مصطفى القابضة" in message
    assert "القطاع المتأثر:\n\u200fالعقارات" in message
    assert "الاتجاه: مستفيد" in message
    assert "قوة التأثير: 80/100" in message
    assert "الثقة: 87%" in message
    assert "إشارة عامة:\n\u200fأقرب للشراء/المتابعة" in message
    assert "مش توصية شراء أو بيع." in message
    assert "سبب التقييم:\n\u200fالشركة مذكورة بوضوح في خبر له تأثير مباشر عليها." in message
    assert "المصدر:\n\u200fمصدر اقتصادي" in message
    assert "https://example.com/news/1" not in message
    assert message.endswith(NEWS_SEPARATOR)
    assert re.search(r"[A-Za-z]", message) is None


def test_render_telegram_message_shows_negative_stock_signal_without_sell_advice():
    document = NewsDocument(
        external_id="sample-2",
        source_name="Manual Source",
        source_url="https://example.com/news/2",
        title="زيادة تكلفة الطاقة تضغط على أرباح شركة أسمنت",
        body="ارتفاع التكلفة يضغط على هوامش الربح.",
        language="ar",
        published_at=None,
        credibility=0.7,
    )
    evidence = EvidenceSnippet(
        text="ارتفاع التكلفة يضغط على هوامش الربح.",
        normalized_text="ارتفاع التكلفة يضغط على هوامش الربح.",
        location="body",
        reason="input cost pressure",
    )
    assessment = NewsImpactAssessment(
        document=document,
        event_type="input_cost_change",
        sectors=(
            SectorImpact(
                sector="Cement",
                direction="loser",
                direction_score=-0.7,
                strength=72,
                confidence=0.81,
                rationale="Higher energy costs can pressure margins.",
                evidence=(evidence,),
            ),
        ),
        stocks=(
            StockImpactCandidate(
                ticker="ARCC",
                isin=None,
                company_name_ar="العربية للأسمنت",
                company_name_en="Arabian Cement",
                sector="Cement",
                direction="loser",
                direction_score=-0.75,
                strength=74,
                confidence=0.83,
                impact_type="margin_pressure",
                horizon="short",
                rationale="The company is exposed to higher fuel input costs.",
                evidence=(evidence,),
            ),
        ),
        market_wide=False,
        needs_review=False,
        analysis_method="ai",
        summary="ارتفاع تكلفة الطاقة قد يضغط على هوامش شركات الأسمنت.",
    )

    message = render_telegram_message(assessment)

    assert "السهم المرتبط:\n\u200fالعربية للأسمنت" in message
    assert "الاتجاه: متضرر" in message
    assert "قوة التأثير: 74/100" in message
    assert "تأثير الخبر:\n\u200fسلبي للسهم\n\u200fسيئ للسهم" in message
    assert "إشارة عامة:\n\u200fأقرب للبيع/تخفيف المخاطر" in message
    assert "بيع" in message
    assert "The company" not in message
    assert "ARCC" not in message
    assert "إيجابي للسهم" not in message
    assert re.search(r"[A-Za-z]", message) is None


def test_render_telegram_message_does_not_print_raw_english_news_fields():
    evidence = EvidenceSnippet(
        text="US banks report record profits",
        normalized_text="us banks report record profits",
        location="title",
        reason="english_evidence",
        translated_hint="أرباح قوية في قطاع بنوك عالمي.",
    )
    assessment = NewsImpactAssessment(
        document=NewsDocument(
            external_id="english-1",
            source_name="Daily News Egypt",
            source_url="https://example.com/english",
            title="US banks report record profits",
            body="Wall Street banks had a strong quarter.",
            language="en",
            published_at=None,
            credibility=0.7,
        ),
        event_type="earnings_growth",
        sectors=(
            SectorImpact(
                sector="Banks",
                direction="beneficiary",
                direction_score=0.5,
                strength=45,
                confidence=0.7,
                rationale="تأثيره على البورصة المصرية غير مباشر.",
                evidence=(evidence,),
            ),
        ),
        stocks=(),
        market_wide=False,
        needs_review=True,
        analysis_method="ai",
        summary="خبر عالمي عن أرباح البنوك وتأثيره المحلي غير واضح.",
    )

    message = render_telegram_message(assessment)

    assert "US banks" not in message
    assert "Daily News Egypt" not in message
    assert "https://example.com/english" not in message
    assert "خبر عالمي عن أرباح البنوك وتأثيره المحلي غير واضح." in message
    assert re.search(r"[A-Za-z]", message) is None


def test_telegram_client_reads_required_config_from_env():
    env = {
        "TELEGRAM_BOT_TOKEN": "token-123",
        "TELEGRAM_CHAT_ID": "-100123",
    }

    config = TelegramConfig.from_env(env)

    assert config.bot_token == "token-123"
    assert config.chat_id == "-100123"


def test_telegram_client_rejects_missing_secret_config():
    with pytest.raises(TelegramConfigError, match="TELEGRAM_BOT_TOKEN"):
        TelegramConfig.from_env({"TELEGRAM_CHAT_ID": "-100123"})

    with pytest.raises(TelegramConfigError, match="TELEGRAM_CHAT_ID"):
        TelegramConfig.from_env({"TELEGRAM_BOT_TOKEN": "token-123"})


def test_telegram_client_posts_send_message_payload():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    client = TelegramClient(
        TelegramConfig(bot_token="token-123", chat_id="-100123"),
        transport=httpx.MockTransport(handler),
    )

    result = client.send_message("hello market")

    assert result.message_id == 42
    assert requests[0].method == "POST"
    assert requests[0].url == "https://api.telegram.org/bottoken-123/sendMessage"
    payload = json.loads(requests[0].content)
    assert payload == {
        "chat_id": "-100123",
        "text": "hello market",
        "disable_web_page_preview": True,
    }


def test_telegram_client_sanitizes_http_errors_without_leaking_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})

    client = TelegramClient(
        TelegramConfig(bot_token="secret-token", chat_id="-100123"),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(TelegramDeliveryError) as exc_info:
        client.send_message("hello market")

    message = str(exc_info.value)
    assert "401" in message
    assert "secret-token" not in message
    assert "api.telegram.org" not in message


def test_telegram_client_reports_get_updates_conflict_without_leaking_token():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={
                "ok": False,
                "description": "Conflict: terminated by other getUpdates request; make sure that only one bot instance is running",
            },
        )

    client = TelegramClient(
        TelegramConfig(bot_token="secret-token", chat_id="-100123"),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(TelegramDeliveryError) as exc_info:
        client.get_updates(timeout=5)

    message = str(exc_info.value)
    assert "409" in message
    assert "only one bot instance" in message
    assert "secret-token" not in message
    assert "api.telegram.org" not in message


def test_telegram_notifier_sends_rendered_assessment_message():
    sent: list[str] = []

    class FakeClient:
        def send_message(self, text: str):
            sent.append(text)
            return None

    notifier = TelegramNotifier(FakeClient())

    notifier.send_assessment(_assessment())

    assert len(sent) == 1
    assert sent[0].startswith("\u200fملخص الخبر:\n")
    assert "تقرير تأثير الخبر على البورصة المصرية" not in sent[0]
    assert "السهم المرتبط:\n\u200fمجموعة طلعت مصطفى القابضة" in sent[0]
