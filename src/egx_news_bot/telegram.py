from __future__ import annotations

from dataclasses import dataclass
from os import environ
from typing import Any, Mapping, Protocol

import httpx

from egx_news_bot.feedback import FeedbackRecord, FeedbackStore, VALID_FEEDBACK_ACTIONS
from egx_news_bot.models import NewsImpactAssessment

NEWS_SEPARATOR = "-------------------------------------------------------"
RTL_MARK = "\u200f"
SUBMITTED_CALLBACK_DATA = "egx_feedback_submitted"

_DIRECTION_LABELS = {
    "beneficiary": "مستفيد",
    "loser": "متضرر",
    "mixed": "مختلط",
    "neutral": "محايد",
}


class TelegramConfigError(ValueError):
    pass


class TelegramDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "TelegramConfig":
        values = env or environ
        bot_token = values.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = values.get("TELEGRAM_CHAT_ID", "").strip()
        if not bot_token:
            raise TelegramConfigError("TELEGRAM_BOT_TOKEN is required")
        if not chat_id:
            raise TelegramConfigError("TELEGRAM_CHAT_ID is required")
        return cls(bot_token=bot_token, chat_id=chat_id)


@dataclass(frozen=True)
class TelegramSendResult:
    message_id: int | None


@dataclass(frozen=True)
class ParsedFeedbackCallback:
    alert_id: int
    action: str


@dataclass(frozen=True)
class TelegramFeedbackProcessResult:
    processed: int
    ignored: int
    next_offset: int | None


class MessageClient(Protocol):
    def send_message(self, text: str, reply_markup: dict | None = None) -> TelegramSendResult | None:
        ...


class CallbackAnswerClient(Protocol):
    def answer_callback_query(self, callback_query_id: str, text: str) -> None:
        ...

    def edit_message_reply_markup(
        self,
        *,
        chat_id: int | str,
        message_id: int,
        reply_markup: dict | None = None,
    ) -> None:
        ...


class TelegramClient:
    def __init__(
        self,
        config: TelegramConfig,
        *,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._config = config
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TelegramClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def send_message(self, text: str, reply_markup: dict | None = None) -> TelegramSendResult:
        payload = {
            "chat_id": self._config.chat_id,
            "text": text,
            "disable_web_page_preview": False,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        response = self._client.post(
            f"https://api.telegram.org/bot{self._config.bot_token}/sendMessage",
            json=payload,
        )
        if response.status_code >= 400:
            raise TelegramDeliveryError(_telegram_error_message(response, "sendMessage"))
        payload = response.json()
        if not payload.get("ok"):
            description = payload.get("description") or "Telegram API returned ok=false"
            raise TelegramDeliveryError(description)
        result = payload.get("result") or {}
        return TelegramSendResult(message_id=result.get("message_id"))

    def get_updates(self, *, offset: int | None = None, timeout: int = 0) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": ["callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        response = self._client.post(
            f"https://api.telegram.org/bot{self._config.bot_token}/getUpdates",
            json=payload,
            timeout=max(20.0, float(timeout) + 10.0),
        )
        if response.status_code >= 400:
            raise TelegramDeliveryError(_telegram_error_message(response, "getUpdates"))
        response_payload = response.json()
        if not response_payload.get("ok"):
            description = response_payload.get("description") or "Telegram API returned ok=false"
            raise TelegramDeliveryError(description)
        result = response_payload.get("result") or []
        if not isinstance(result, list):
            raise TelegramDeliveryError("Telegram getUpdates returned a non-list result")
        return result

    def answer_callback_query(self, callback_query_id: str, text: str) -> None:
        response = self._client.post(
            f"https://api.telegram.org/bot{self._config.bot_token}/answerCallbackQuery",
            json={
                "callback_query_id": callback_query_id,
                "text": text,
            },
        )
        if response.status_code >= 400:
            raise TelegramDeliveryError(_telegram_error_message(response, "answerCallbackQuery"))
        payload = response.json()
        if not payload.get("ok"):
            description = payload.get("description") or "Telegram API returned ok=false"
            raise TelegramDeliveryError(description)

    def edit_message_reply_markup(
        self,
        *,
        chat_id: int | str,
        message_id: int,
        reply_markup: dict | None = None,
    ) -> None:
        response = self._client.post(
            f"https://api.telegram.org/bot{self._config.bot_token}/editMessageReplyMarkup",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": reply_markup if reply_markup is not None else {"inline_keyboard": []},
            },
        )
        if response.status_code >= 400:
            raise TelegramDeliveryError(_telegram_error_message(response, "editMessageReplyMarkup"))
        payload = response.json()
        if not payload.get("ok"):
            description = payload.get("description") or "Telegram API returned ok=false"
            raise TelegramDeliveryError(description)


class TelegramNotifier:
    def __init__(self, client: MessageClient, feedback_store: FeedbackStore | None = None) -> None:
        self._client = client
        self._feedback_store = feedback_store

    def send_assessment(self, assessment: NewsImpactAssessment) -> TelegramSendResult | None:
        alert_id = None
        if self._feedback_store is not None:
            if self.has_sent_assessment(assessment):
                return None
            alert_id = self._feedback_store.record_alert(
                external_id=assessment.document.external_id,
                source_name=assessment.document.source_name,
                source_url=assessment.document.source_url,
                title=assessment.document.title,
                event_type=assessment.event_type,
                analysis_method=assessment.analysis_method,
                max_strength=_assessment_strength(assessment),
            )
        message = render_telegram_message(assessment)
        if alert_id is None:
            return self._client.send_message(message)
        result = self._client.send_message(message, reply_markup=feedback_keyboard(alert_id))
        self._feedback_store.mark_alert_sent(alert_id, result.message_id if result is not None else None)
        return result

    def has_sent_assessment(self, assessment: NewsImpactAssessment) -> bool:
        if self._feedback_store is None:
            return False
        return self._feedback_store.has_sent_alert(
            external_id=assessment.document.external_id,
            source_url=assessment.document.source_url,
            title=assessment.document.title,
        )


def feedback_keyboard(alert_id: int) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "تمام", "callback_data": f"egx_feedback:{alert_id}:good"},
                {"text": "غلط", "callback_data": f"egx_feedback:{alert_id}:wrong"},
            ],
            [
                {"text": "مبالغ فيه", "callback_data": f"egx_feedback:{alert_id}:too_strong"},
                {"text": "أضعف من اللازم", "callback_data": f"egx_feedback:{alert_id}:too_weak"},
            ],
            [
                {"text": "مش متعلق بالبورصة", "callback_data": f"egx_feedback:{alert_id}:not_relevant"},
            ],
        ]
    }


def feedback_submitted_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [{"text": "تم إرسال رأيك", "callback_data": SUBMITTED_CALLBACK_DATA}],
        ]
    }


def parse_feedback_callback(data: str) -> ParsedFeedbackCallback | None:
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "egx_feedback":
        return None
    try:
        alert_id = int(parts[1])
    except ValueError:
        return None
    action = parts[2]
    if action not in VALID_FEEDBACK_ACTIONS:
        return None
    return ParsedFeedbackCallback(alert_id=alert_id, action=action)


def process_feedback_updates(
    updates: list[dict[str, Any]],
    *,
    store: FeedbackStore,
    client: CallbackAnswerClient,
) -> TelegramFeedbackProcessResult:
    processed = 0
    ignored = 0
    next_offset = None
    for update in updates:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            next_offset = max(next_offset or 0, update_id + 1)

        callback = update.get("callback_query")
        if not isinstance(callback, dict):
            ignored += 1
            continue

        data = callback.get("data")
        callback_id = callback.get("id")
        if data == SUBMITTED_CALLBACK_DATA:
            if isinstance(callback_id, str):
                try:
                    client.answer_callback_query(callback_id, "تم تسجيل رأيك قبل كده")
                except TelegramDeliveryError:
                    pass
            ignored += 1
            continue
        parsed = parse_feedback_callback(data) if isinstance(data, str) else None
        user = callback.get("from") or {}
        user_id = user.get("id") if isinstance(user, dict) else None
        if parsed is None or not isinstance(user_id, int):
            ignored += 1
            continue

        message = callback.get("message") or {}
        message_id = message.get("message_id") if isinstance(message, dict) else None
        username = user.get("username") if isinstance(user, dict) else None
        store.record_feedback(
            FeedbackRecord(
                alert_id=parsed.alert_id,
                action=parsed.action,
                user_id=user_id,
                username=username if isinstance(username, str) else None,
                message_id=message_id if isinstance(message_id, int) else None,
            )
        )
        if isinstance(callback_id, str):
            try:
                client.answer_callback_query(callback_id, "تم تسجيل رأيك")
            except TelegramDeliveryError:
                pass
        chat_id = _message_chat_id(message)
        if chat_id is not None and isinstance(message_id, int):
            try:
                client.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=feedback_submitted_keyboard(),
                )
            except TelegramDeliveryError:
                pass
        processed += 1
    return TelegramFeedbackProcessResult(processed=processed, ignored=ignored, next_offset=next_offset)


def _message_chat_id(message: Any) -> int | str | None:
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict):
        return None
    chat_id = chat.get("id")
    return chat_id if isinstance(chat_id, int | str) else None


def _telegram_error_message(response: httpx.Response, method: str) -> str:
    detail = _telegram_error_detail(response)
    suffix = f": {detail}" if detail else ""
    return f"Telegram {method} failed with status {response.status_code}{suffix}"


def _telegram_error_detail(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:300] if text else None
    if not isinstance(payload, dict):
        return None
    description = payload.get("description")
    if isinstance(description, str) and description.strip():
        return description.strip()[:300]
    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()[:300]
    return None


def render_telegram_message(assessment: NewsImpactAssessment) -> str:
    document = assessment.document
    lines = [
        "تقرير تأثير الخبر على البورصة المصرية",
        "",
        f"الخبر: {document.title}",
        f"المصدر: {document.source_name}",
        f"الرابط: {document.source_url}",
        f"نوع الحدث: {assessment.event_type}",
        f"طريقة التحليل: {assessment.analysis_method}",
        f"تأثير عام على السوق: {_yes_no(assessment.market_wide)}",
        f"مراجعة بشرية: {_yes_no(assessment.needs_review)}",
    ]
    if assessment.summary:
        lines.append(f"الملخص: {assessment.summary}")

    lines.extend(_recommendation_lines(assessment))

    if assessment.sectors:
        lines.extend(["", "تأثير القطاعات"])
        lines.extend(_sector_line(sector) for sector in assessment.sectors[:5])

    if assessment.stocks:
        lines.extend(["", "تأثير الأسهم"])
        for stock in assessment.stocks[:8]:
            label = stock.ticker or stock.company_name_en or stock.company_name_ar
            lines.append(
                f"{label}: {_direction_label(stock.direction)} | درجة {stock.strength}/100 | "
                f"ثقة {_percent(stock.confidence)}"
            )
            lines.append(f"ليه: {stock.rationale}")

    evidence = _first_evidence(assessment)
    if evidence:
        lines.extend(["", "الدليل:", evidence])

    lines.extend(["", NEWS_SEPARATOR])
    return "\n".join(_rtl(line) for line in lines)


def _sector_line(sector) -> str:
    return (
        f"{sector.sector}: {_direction_label(sector.direction)} | درجة {sector.strength}/100 | "
        f"ثقة {_percent(sector.confidence)}"
    )


def _recommendation_lines(assessment: NewsImpactAssessment) -> list[str]:
    stock = max(assessment.stocks, key=lambda item: item.strength, default=None)
    sector = max(assessment.sectors, key=lambda item: item.strength, default=None)
    target = stock or sector
    if target is None:
        verdict = "ضعيف أو غير واضح"
        good_bad = "غير واضح للسهم"
        signal = "متابعة فقط، مفيش إشارة شراء أو بيع واضحة"
    else:
        is_stock = stock is not None
        verdict, good_bad, signal = _trading_signal(
            direction=target.direction,
            strength=target.strength,
            is_stock=is_stock,
        )
    return [
        "",
        "الحكم والتصرف",
        f"التقييم: {verdict}",
        f"هل الخبر جيد ولا سيئ؟ {good_bad}",
        f"إشارة عامة: {signal}",
        "ملاحظة: ده تحليل آلي عام، مش توصية استثمارية شخصية.",
    ]


def _trading_signal(*, direction: str, strength: int, is_stock: bool) -> tuple[str, str, str]:
    subject = "للسهم" if is_stock else "للقطاع"
    if direction == "beneficiary" and strength >= 65:
        return f"إيجابي {subject}", f"جيد {subject}", "أقرب للشراء/المتابعة، مش توصية شراء"
    if direction == "loser" and strength >= 65:
        return f"سلبي {subject}", f"سيئ {subject}", "أقرب للبيع/تخفيف المخاطر، مش توصية بيع"
    if direction == "mixed":
        return f"مختلط {subject}", f"مختلط {subject}", "انتظار/متابعة، مفيش إشارة شراء أو بيع واضحة"
    return "ضعيف أو غير واضح", f"غير واضح {subject}", "انتظار/متابعة، مفيش إشارة شراء أو بيع واضحة"


def _direction_label(direction: str) -> str:
    return _DIRECTION_LABELS.get(direction, direction)


def _yes_no(value: bool) -> str:
    return "نعم" if value else "لا"


def _rtl(line: str) -> str:
    if not line or line == NEWS_SEPARATOR:
        return line
    return f"{RTL_MARK}{line}"


def _first_evidence(assessment: NewsImpactAssessment) -> str | None:
    for stock in assessment.stocks:
        if stock.evidence:
            return stock.evidence[0].text
    for sector in assessment.sectors:
        if sector.evidence:
            return sector.evidence[0].text
    return None


def _percent(value: float) -> str:
    return f"{round(value * 100)}%"


def _assessment_strength(assessment: NewsImpactAssessment) -> int:
    strengths = [sector.strength for sector in assessment.sectors]
    strengths.extend(stock.strength for stock in assessment.stocks)
    return max(strengths, default=0)
