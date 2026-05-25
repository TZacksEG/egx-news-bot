from datetime import datetime, timezone

import httpx

from egx_news_bot.ingestion import NewsFeedConfig
from egx_news_bot.poller import FeedPoller


RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <guid>poll-1</guid>
      <title>البنك المركزي يخفض أسعار الفائدة 200 نقطة أساس</title>
      <link>https://example.com/poll-1</link>
      <description>خبر اقتصادي عاجل</description>
      <pubDate>Sun, 24 May 2026 10:15:00 +0200</pubDate>
    </item>
  </channel>
</rss>
"""

FUTURE_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <guid>future-1</guid>
      <title>Bad future-dated item</title>
      <link>https://example.com/future-1</link>
      <description>Bad date</description>
      <pubDate>Sun, 24 May 2252 10:15:00 +0200</pubDate>
    </item>
  </channel>
</rss>
"""


def test_poll_once_fetches_feed_and_scores_documents():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, text=RSS_XML)

    poller = FeedPoller(
        feeds=(
            NewsFeedConfig(
                name="Test Feed",
                url="https://example.com/feed",
                language="ar",
                credibility=0.9,
                tags=("macro",),
            ),
        ),
        transport=httpx.MockTransport(handler),
    )

    result = poller.poll_once(limit=1, max_age_hours=24 * 365)

    assert calls == 1
    assert not result.errors
    assert result.documents[0].external_id == "poll-1"
    assert result.assessments[0].event_type == "interest_rate_cut"


def test_watch_repeats_polling_without_sleeping_when_iterations_are_limited():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, text=RSS_XML)

    poller = FeedPoller(
        feeds=(
            NewsFeedConfig(
                name="Test Feed",
                url="https://example.com/feed",
                language="ar",
                credibility=0.9,
                tags=("macro",),
            ),
        ),
        transport=httpx.MockTransport(handler),
    )

    results = list(
        poller.watch(
            interval_seconds=60,
            iterations=2,
            sleep=lambda _seconds: None,
            limit=1,
            max_age_hours=24 * 365,
        )
    )

    assert len(results) == 2
    assert calls == 2
    assert all(result.assessments[0].event_type == "interest_rate_cut" for result in results)


def test_poll_once_drops_items_with_impossible_future_dates():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=FUTURE_RSS_XML)

    poller = FeedPoller(
        feeds=(
            NewsFeedConfig(
                name="Future Feed",
                url="https://example.com/feed",
                language="en",
                credibility=0.6,
            ),
        ),
        transport=httpx.MockTransport(handler),
    )

    result = poller.poll_once(
        max_age_hours=24,
        max_future_hours=24,
        now=datetime(2026, 5, 24, 12, 0, tzinfo=timezone.utc),
    )

    assert result.documents == ()
    assert result.assessments == ()
