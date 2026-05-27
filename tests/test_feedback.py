from pathlib import Path

from egx_news_bot.feedback import FeedbackRecord, FeedbackStore

TEST_USER_ID = 123456789


def test_feedback_store_records_alert_and_user_feedback(tmp_path):
    db_path = tmp_path / "feedback.sqlite3"
    store = FeedbackStore(db_path)

    alert_id = store.record_alert(
        external_id="article-1",
        source_name="Al Borsa",
        source_url="https://example.com/article-1",
        title="Market news",
        event_type="contract",
        analysis_method="ai",
        max_strength=82,
    )

    store.record_feedback(
        FeedbackRecord(
            alert_id=alert_id,
            action="too_strong",
            user_id=TEST_USER_ID,
            username="tester",
            message_id=42,
        )
    )

    rows = store.list_feedback()

    assert rows[0]["alert_id"] == alert_id
    assert rows[0]["action"] == "too_strong"
    assert rows[0]["user_id"] == TEST_USER_ID
    assert rows[0]["title"] == "Market news"
    assert rows[0]["max_strength"] == 82


def test_feedback_store_reuses_alert_id_for_same_external_id(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.sqlite3")

    first = store.record_alert(
        external_id="article-1",
        source_name="Source",
        source_url="https://example.com/article-1",
        title="Old title",
        event_type="unclassified",
        analysis_method="ai",
        max_strength=0,
    )
    second = store.record_alert(
        external_id="article-1",
        source_name="Source",
        source_url="https://example.com/article-1",
        title="Updated title",
        event_type="contract",
        analysis_method="ai",
        max_strength=90,
    )

    alerts = store.list_alerts()

    assert first == second
    assert len(alerts) == 1
    assert alerts[0]["title"] == "Updated title"
    assert alerts[0]["max_strength"] == 90


def test_feedback_store_tracks_only_successfully_sent_alerts(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.sqlite3")

    alert_id = store.record_alert(
        external_id="article-1",
        source_name="Source",
        source_url="https://example.com/article-1",
        title="Market news",
        event_type="contract",
        analysis_method="ai",
        max_strength=90,
    )

    assert not store.has_sent_alert(
        external_id="article-1",
        source_url="https://example.com/article-1",
        title="Market news",
    )

    store.mark_alert_sent(alert_id, 123)

    assert store.has_sent_alert(
        external_id="article-1",
        source_url="https://example.com/article-1",
        title="Market news",
    )
    assert store.list_alerts()[0]["telegram_message_id"] == 123


def test_feedback_store_persists_telegram_update_offset(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.sqlite3")

    assert store.get_telegram_update_offset() is None

    store.set_telegram_update_offset(103)

    reopened = FeedbackStore(tmp_path / "feedback.sqlite3")
    assert reopened.get_telegram_update_offset() == 103
