import json

import httpx

from egx_news_bot.analysis import ImpactAnalyzer
from egx_news_bot.feedback import FeedbackStore
from egx_news_bot.models import NewsDocument
from egx_news_bot.telegram import (
    TelegramClient,
    TelegramConfig,
    TelegramDeliveryError,
    TelegramNotifier,
    parse_feedback_callback,
    process_feedback_updates,
)

TEST_USER_ID = 123456789
PUBLIC_KEYBOARD = {
    "inline_keyboard": [
        [
            {"text": "👍 مفيد 1", "callback_data": "egx_feedback:1:good"},
            {"text": "⚠️ مبالغ فيه 0", "callback_data": "egx_feedback:1:too_strong"},
        ],
        [{"text": "⚪ غير مؤثر 0", "callback_data": "egx_feedback:1:not_relevant"}],
        [{"text": "فتح الخبر الأصلي", "url": "https://example.com/news/1"}],
    ]
}


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


def test_notifier_sends_public_vote_buttons_and_source_link(tmp_path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    store = FeedbackStore(tmp_path / "feedback.sqlite3")
    client = TelegramClient(
        TelegramConfig(bot_token="token-123", chat_id="-100123"),
        transport=httpx.MockTransport(handler),
    )
    notifier = TelegramNotifier(client, feedback_store=store)

    notifier.send_assessment(_assessment())

    payload = json.loads(requests[0].content)
    assert payload["reply_markup"]["inline_keyboard"][0][0]["text"] == "👍 مفيد 0"
    assert payload["reply_markup"]["inline_keyboard"][0][1]["text"] == "⚠️ مبالغ فيه 0"
    assert payload["reply_markup"]["inline_keyboard"][1][0]["text"] == "⚪ غير مؤثر 0"
    assert payload["reply_markup"]["inline_keyboard"][2][0] == {
        "text": "فتح الخبر الأصلي",
        "url": "https://example.com/news/1",
    }
    callback_data = payload["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    parsed = parse_feedback_callback(callback_data)
    assert parsed is not None
    assert parsed.action == "good"
    assert store.list_alerts()[0]["alert_id"] == parsed.alert_id
    assert store.list_alerts()[0]["telegram_message_id"] == 42


def test_notifier_skips_previously_sent_alert_without_posting(tmp_path):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 43}})

    store = FeedbackStore(tmp_path / "feedback.sqlite3")
    client = TelegramClient(
        TelegramConfig(bot_token="token-123", chat_id="-100123"),
        transport=httpx.MockTransport(handler),
    )
    notifier = TelegramNotifier(client, feedback_store=store)

    assert notifier.send_assessment(_assessment()) is not None
    assert notifier.send_assessment(_assessment()) is None

    assert len(requests) == 1


def test_parse_feedback_callback_rejects_unknown_payloads():
    assert parse_feedback_callback("other:123:good") is None
    assert parse_feedback_callback("egx_feedback:abc:good") is None
    assert parse_feedback_callback("egx_feedback:123:unknown") is None


def test_telegram_client_fetches_callback_updates_answers_and_edits_keyboard():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/getUpdates"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": [
                        {
                            "update_id": 51,
                            "callback_query": {
                                "id": "callback-1",
                                "data": "egx_feedback:1:good",
                            },
                        }
                    ],
                },
            )
        if request.url.path.endswith("/answerCallbackQuery"):
            return httpx.Response(200, json={"ok": True, "result": True})
        if request.url.path.endswith("/editMessageReplyMarkup"):
            return httpx.Response(200, json={"ok": True, "result": True})
        raise AssertionError(f"unexpected Telegram API call: {request.url}")

    client = TelegramClient(
        TelegramConfig(bot_token="token-123", chat_id="-100123"),
        transport=httpx.MockTransport(handler),
    )

    updates = client.get_updates(offset=50, timeout=3)
    client.answer_callback_query("callback-1", "تم تسجيل تصويتك")
    client.edit_message_reply_markup(chat_id=123, message_id=42, reply_markup=PUBLIC_KEYBOARD)

    assert updates[0]["update_id"] == 51
    get_payload = json.loads(requests[0].content)
    assert get_payload == {
        "offset": 50,
        "timeout": 3,
        "allowed_updates": ["callback_query"],
    }
    answer_payload = json.loads(requests[1].content)
    assert answer_payload == {"callback_query_id": "callback-1", "text": "تم تسجيل تصويتك"}
    edit_payload = json.loads(requests[2].content)
    assert edit_payload == {
        "chat_id": 123,
        "message_id": 42,
        "reply_markup": PUBLIC_KEYBOARD,
    }


def test_telegram_client_uses_request_timeout_longer_than_update_long_poll():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"ok": True, "result": []})

    client = TelegramClient(
        TelegramConfig(bot_token="token-123", chat_id="-100123"),
        transport=httpx.MockTransport(handler),
    )

    client.get_updates(timeout=30)

    assert requests[0].extensions["timeout"]["read"] >= 40


def test_process_feedback_updates_records_callbacks_and_returns_next_offset(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.sqlite3")
    alert_id = store.record_alert(
        external_id="sample-1",
        source_name="Manual Source",
        source_url="https://example.com/news/1",
        title="Market news",
        event_type="contract",
        analysis_method="ai",
        max_strength=82,
    )
    answers: list[tuple[str, str]] = []
    edits: list[tuple[int, int, dict | None]] = []

    class FakeClient:
        def answer_callback_query(self, callback_query_id: str, text: str) -> None:
            answers.append((callback_query_id, text))

        def edit_message_reply_markup(self, *, chat_id, message_id: int, reply_markup=None) -> None:
            edits.append((chat_id, message_id, reply_markup))

    result = process_feedback_updates(
        [
            {
                "update_id": 100,
                    "callback_query": {
                        "id": "callback-1",
                        "from": {"id": TEST_USER_ID, "username": "tester"},
                        "message": {"chat": {"id": 123}, "message_id": 42},
                        "data": f"egx_feedback:{alert_id}:too_strong",
                },
            },
            {"update_id": 101, "message": {"text": "ignored"}},
            {
                "update_id": 102,
                "callback_query": {
                    "id": "callback-2",
                    "from": {"id": 1},
                    "data": "not-a-feedback-payload",
                },
            },
        ],
        store=store,
        client=FakeClient(),
    )

    feedback = store.list_feedback()

    assert result.processed == 1
    assert result.ignored == 2
    assert result.next_offset == 103
    assert feedback[0]["alert_id"] == alert_id
    assert feedback[0]["action"] == "too_strong"
    assert feedback[0]["user_id"] == TEST_USER_ID
    assert feedback[0]["username"] == "tester"
    assert feedback[0]["message_id"] == 42
    assert answers == [("callback-1", "تم تسجيل تصويتك")]
    assert edits == [
        (
            123,
            42,
            {
                "inline_keyboard": [
                    [
                        {"text": "👍 مفيد 0", "callback_data": f"egx_feedback:{alert_id}:good"},
                        {"text": "⚠️ مبالغ فيه 1", "callback_data": f"egx_feedback:{alert_id}:too_strong"},
                    ],
                    [{"text": "⚪ غير مؤثر 0", "callback_data": f"egx_feedback:{alert_id}:not_relevant"}],
                    [{"text": "فتح الخبر الأصلي", "url": "https://example.com/news/1"}],
                ]
            },
        )
    ]


def test_process_feedback_updates_answers_submitted_keyboard_without_new_feedback(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.sqlite3")
    answers: list[tuple[str, str]] = []
    edits: list[tuple[int, int, dict | None]] = []

    class FakeClient:
        def answer_callback_query(self, callback_query_id: str, text: str) -> None:
            answers.append((callback_query_id, text))

        def edit_message_reply_markup(self, *, chat_id, message_id: int, reply_markup=None) -> None:
            edits.append((chat_id, message_id, reply_markup))

    result = process_feedback_updates(
        [
            {
                "update_id": 150,
                "callback_query": {
                    "id": "callback-submitted",
                    "from": {"id": TEST_USER_ID},
                    "message": {"chat": {"id": 123}, "message_id": 44},
                    "data": "egx_feedback_submitted",
                },
            }
        ],
        store=store,
        client=FakeClient(),
    )

    assert result.processed == 0
    assert result.ignored == 1
    assert result.next_offset == 151
    assert store.list_feedback() == []
    assert answers == [("callback-submitted", "تم تسجيل تصويتك قبل كده")]
    assert edits == []


def test_process_feedback_updates_keeps_recorded_feedback_when_callback_answer_is_stale(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.sqlite3")
    alert_id = store.record_alert(
        external_id="sample-2",
        source_name="Manual Source",
        source_url="https://example.com/news/2",
        title="Market news 2",
        event_type="contract",
        analysis_method="ai",
        max_strength=82,
    )
    edits: list[tuple[int, int, dict | None]] = []

    class FakeClient:
        def answer_callback_query(self, callback_query_id: str, text: str) -> None:
            raise TelegramDeliveryError("Telegram answerCallbackQuery failed with status 400: query is too old")

        def edit_message_reply_markup(self, *, chat_id, message_id: int, reply_markup=None) -> None:
            edits.append((chat_id, message_id, reply_markup))

    result = process_feedback_updates(
        [
            {
                "update_id": 200,
                "callback_query": {
                    "id": "callback-stale",
                    "from": {"id": TEST_USER_ID},
                    "message": {"chat": {"id": 123}, "message_id": 55},
                    "data": f"egx_feedback:{alert_id}:wrong",
                },
            }
        ],
        store=store,
        client=FakeClient(),
    )

    feedback = store.list_feedback()

    assert result.processed == 1
    assert result.next_offset == 201
    assert feedback[0]["action"] == "wrong"
    assert edits == [
        (
            123,
            55,
            {
                "inline_keyboard": [
                    [
                        {"text": "👍 مفيد 0", "callback_data": f"egx_feedback:{alert_id}:good"},
                        {"text": "⚠️ مبالغ فيه 0", "callback_data": f"egx_feedback:{alert_id}:too_strong"},
                    ],
                    [{"text": "⚪ غير مؤثر 0", "callback_data": f"egx_feedback:{alert_id}:not_relevant"}],
                    [{"text": "فتح الخبر الأصلي", "url": "https://example.com/news/2"}],
                ]
            },
        )
    ]
