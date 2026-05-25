from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from collections.abc import Callable, Iterator

import httpx

from egx_news_bot.analysis import ImpactAnalyzer
from egx_news_bot.ingestion import parse_feed
from egx_news_bot.models import NewsDocument, NewsFeedConfig, NewsImpactAssessment
from egx_news_bot.sources import DEFAULT_FEEDS


@dataclass(frozen=True)
class PollResult:
    documents: tuple[NewsDocument, ...]
    assessments: tuple[NewsImpactAssessment, ...]
    errors: tuple[str, ...]


class FeedPoller:
    def __init__(
        self,
        feeds: tuple[NewsFeedConfig, ...] = DEFAULT_FEEDS,
        analyzer: ImpactAnalyzer | None = None,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._feeds = feeds
        self._analyzer = analyzer or ImpactAnalyzer()
        self._timeout = timeout
        self._transport = transport

    def poll_once(
        self,
        *,
        limit: int | None = None,
        max_age_hours: int = 72,
        max_future_hours: int = 24,
        now: datetime | None = None,
    ) -> PollResult:
        documents: list[NewsDocument] = []
        assessments: list[NewsImpactAssessment] = []
        errors: list[str] = []
        current_time = now or datetime.now(timezone.utc)
        cutoff = current_time - timedelta(hours=max_age_hours)
        future_cutoff = current_time + timedelta(hours=max_future_hours)

        with httpx.Client(timeout=self._timeout, follow_redirects=True, transport=self._transport) as client:
            for feed in self._feeds:
                try:
                    response = client.get(feed.url)
                    response.raise_for_status()
                    feed_documents = parse_feed(response.text, feed)
                except Exception as exc:  # noqa: BLE001 - pollers should isolate source failures.
                    errors.append(f"{feed.name}: {exc}")
                    continue

                for document in feed_documents:
                    if document.published_at is not None and document.published_at < cutoff:
                        continue
                    if document.published_at is not None and document.published_at > future_cutoff:
                        continue
                    documents.append(document)
                    assessments.append(self._analyzer.analyze(document))
                    if limit is not None and len(documents) >= limit:
                        return PollResult(tuple(documents), tuple(assessments), tuple(errors))

        return PollResult(tuple(documents), tuple(assessments), tuple(errors))

    def watch(
        self,
        *,
        interval_seconds: float,
        iterations: int | None = None,
        sleep: Callable[[float], None] | None = None,
        limit: int | None = None,
        max_age_hours: int = 72,
        max_future_hours: int = 24,
    ) -> Iterator[PollResult]:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")

        sleeper = sleep or _sleep
        count = 0
        while iterations is None or count < iterations:
            yield self.poll_once(limit=limit, max_age_hours=max_age_hours, max_future_hours=max_future_hours)
            count += 1
            if iterations is None or count < iterations:
                sleeper(interval_seconds)


def _sleep(seconds: float) -> None:
    import time

    time.sleep(seconds)
