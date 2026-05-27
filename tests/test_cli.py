import pytest

from egx_news_bot.ai_analysis import AIConfigError
from egx_news_bot import cli
from egx_news_bot.feedback import FeedbackStore
from egx_news_bot.models import NewsDocument, NewsImpactAssessment, SectorImpact
from egx_news_bot.telegram import TelegramConfigError, TelegramDeliveryError

TEST_USER_ID = 123456789


class FakePoller:
    def __init__(self, assessments: tuple[NewsImpactAssessment, ...]):
        self.assessments = assessments

    def poll_once(self, *, limit: int | None = None, max_age_hours: int = 72):
        return type(
            "PollResult",
            (),
            {
                "documents": tuple(assessment.document for assessment in self.assessments),
                "assessments": self.assessments,
                "errors": (),
            },
        )()


class FakeNotifier:
    def __init__(self):
        self.sent: list[NewsImpactAssessment] = []

    def send_assessment(self, assessment: NewsImpactAssessment):
        self.sent.append(assessment)
        return None


def _assessment(*, strength: int, needs_review: bool = False) -> NewsImpactAssessment:
    document = NewsDocument(
        external_id="n1",
        source_name="source",
        source_url="https://example.com/n1",
        title="market news",
        body=None,
        language="en",
        published_at=None,
        credibility=0.75,
    )
    sector = SectorImpact(
        sector="Real Estate",
        direction="beneficiary",
        direction_score=0.75,
        strength=strength,
        confidence=0.8,
        rationale="rationale",
    )
    return NewsImpactAssessment(
        document=document,
        event_type="contract",
        sectors=(sector,),
        stocks=(),
        market_wide=False,
        needs_review=needs_review,
    )


def test_send_telegram_from_poll_sends_only_actionable_alerts(capsys):
    notifier = FakeNotifier()
    assessments = (
        _assessment(strength=80),
        _assessment(strength=30),
        _assessment(strength=90, needs_review=True),
    )

    sent_count = cli.send_telegram_from_poll(
        poller=FakePoller(assessments),
        notifier=notifier,
        limit=10,
        max_age_hours=72,
        min_strength=65,
        include_review=False,
    )

    captured = capsys.readouterr()
    assert sent_count == 1
    assert notifier.sent == [assessments[0]]
    assert "Sent 1 Telegram alert" in captured.out


def test_send_telegram_from_poll_can_include_review_items():
    notifier = FakeNotifier()
    review_assessment = _assessment(strength=90, needs_review=True)

    sent_count = cli.send_telegram_from_poll(
        poller=FakePoller((review_assessment,)),
        notifier=notifier,
        limit=10,
        max_age_hours=72,
        min_strength=65,
        include_review=True,
    )

    assert sent_count == 1
    assert notifier.sent == [review_assessment]


def test_send_telegram_from_poll_rejects_non_positive_min_strength():
    with pytest.raises(ValueError, match="min_strength"):
        cli.send_telegram_from_poll(
            poller=FakePoller(()),
            notifier=FakeNotifier(),
            limit=10,
            max_age_hours=72,
            min_strength=-1,
            include_review=False,
        )


def test_send_telegram_from_poll_rejects_too_many_messages_per_run():
    with pytest.raises(ValueError, match="limit"):
        cli.send_telegram_from_poll(
            poller=FakePoller(()),
            notifier=FakeNotifier(),
            limit=101,
            max_age_hours=72,
            min_strength=65,
            include_review=False,
        )


def test_run_send_telegram_reports_missing_env_as_cli_error(monkeypatch):
    monkeypatch.setattr(cli.TelegramConfig, "from_env", lambda: (_ for _ in ()).throw(TelegramConfigError("missing token")))

    with pytest.raises(SystemExit, match="missing token"):
        cli._run_send_telegram(
            type(
                "Args",
                (),
                {
                    "limit": 10,
                    "max_age_hours": 72,
                    "min_strength": 65,
                    "include_review": False,
                    "analysis_mode": "rules",
                },
            )()
        )


def test_build_analyzer_reports_missing_openai_key_for_ai_mode(monkeypatch):
    monkeypatch.setattr(cli.AIAnalysisConfig, "from_env", lambda: (_ for _ in ()).throw(AIConfigError("missing key")))

    with pytest.raises(SystemExit, match="missing key"):
        cli.build_analyzer("ai")


def test_build_analyzer_keeps_rules_mode_without_openai_key():
    analyzer = cli.build_analyzer("rules")

    assert isinstance(analyzer, cli.ImpactAnalyzer)


def test_collect_telegram_feedback_uses_stored_offset_and_updates_it(tmp_path, capsys):
    store = FeedbackStore(tmp_path / "feedback.sqlite3")
    alert_id = store.record_alert(
        external_id="n1",
        source_name="source",
        source_url="https://example.com/n1",
        title="market news",
        event_type="contract",
        analysis_method="ai",
        max_strength=80,
    )
    store.set_telegram_update_offset(100)

    class FakeClient:
        offset = None
        timeout = None
        answers: list[tuple[str, str]] = []

        def get_updates(self, *, offset=None, timeout=0):
            self.offset = offset
            self.timeout = timeout
            return [
                {
                    "update_id": 101,
                    "callback_query": {
                        "id": "callback-1",
                        "from": {"id": TEST_USER_ID, "username": "tester"},
                        "message": {"message_id": 42},
                        "data": f"egx_feedback:{alert_id}:good",
                    },
                }
            ]

        def answer_callback_query(self, callback_query_id: str, text: str) -> None:
            self.answers.append((callback_query_id, text))

    client = FakeClient()

    result = cli.collect_telegram_feedback(client=client, store=store, timeout=5)

    captured = capsys.readouterr()
    assert client.offset == 100
    assert client.timeout == 5
    assert result.processed == 1
    assert store.get_telegram_update_offset() == 102
    assert store.list_feedback()[0]["action"] == "good"
    assert client.answers == [("callback-1", "تم تسجيل تصويتك")]
    assert "Processed 1 Telegram feedback callback" in captured.out


def test_run_collect_feedback_reports_telegram_delivery_error_as_cli_error(monkeypatch):
    monkeypatch.setattr(cli.TelegramConfig, "from_env", lambda: object())

    class FakeTelegramClient:
        def __init__(self, config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return None

    monkeypatch.setattr(cli, "TelegramClient", FakeTelegramClient)
    monkeypatch.setattr(cli, "build_feedback_store", lambda _path: object())
    monkeypatch.setattr(
        cli,
        "collect_telegram_feedback",
        lambda **_kwargs: (_ for _ in ()).throw(
            TelegramDeliveryError("Telegram getUpdates failed with status 409: only one bot instance")
        ),
    )

    with pytest.raises(SystemExit, match="only one bot instance"):
        cli._run_collect_feedback(type("Args", (), {"timeout": 0, "feedback_db": None})())
