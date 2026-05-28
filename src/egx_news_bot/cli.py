from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import json
from os import environ
from pathlib import Path
from typing import Any

from egx_news_bot.ai_analysis import AIAnalysisConfig, AIConfigError, AIImpactAnalyzer, OpenAIResponsesClient
from egx_news_bot.analysis import ImpactAnalyzer
from egx_news_bot.feedback import FeedbackStore, default_feedback_db_path
from egx_news_bot.models import NewsDocument, NewsImpactAssessment
from egx_news_bot.poller import FeedPoller, PollResult
from egx_news_bot.relevance import is_egypt_market_related
from egx_news_bot.telegram import (
    TelegramClient,
    TelegramConfig,
    TelegramConfigError,
    TelegramDeliveryError,
    TelegramNotifier,
    process_feedback_updates,
)


def main() -> None:
    parser = argparse.ArgumentParser(prog="egx-news-bot")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Analyze one news item.")
    analyze.add_argument("--title", required=True)
    analyze.add_argument("--body", default="")
    analyze.add_argument("--source-name", default="manual")
    analyze.add_argument("--source-url", default="manual://news")
    analyze.add_argument("--language", default="ar")
    analyze.add_argument("--credibility", type=float, default=0.7)
    analyze.add_argument("--analysis-mode", choices=("ai", "rules"), default=None)

    poll = subparsers.add_parser("poll", help="Poll configured feeds.")
    poll.add_argument("--once", action="store_true", help="Poll once and exit.")
    poll.add_argument("--limit", type=int, default=10)
    poll.add_argument("--max-age-hours", type=int, default=72)
    poll.add_argument("--analysis-mode", choices=("ai", "rules"), default=None)

    telegram = subparsers.add_parser("send-telegram", help="Poll feeds once and send Telegram alerts.")
    telegram.add_argument("--limit", type=int, default=10)
    telegram.add_argument("--max-age-hours", type=int, default=72)
    telegram.add_argument("--min-strength", type=int, default=65)
    telegram.add_argument("--include-review", action="store_true")
    telegram.add_argument("--analysis-mode", choices=("ai", "rules"), default=None)
    telegram.add_argument("--feedback-db", default=None)

    feedback = subparsers.add_parser("collect-feedback", help="Collect Telegram button feedback.")
    feedback.add_argument("--timeout", type=int, default=0)
    feedback.add_argument("--feedback-db", default=None)

    args = parser.parse_args()
    if args.command == "analyze":
        _run_analyze(args)
        return
    if args.command == "poll":
        _run_poll(args)
        return
    if args.command == "send-telegram":
        _run_send_telegram(args)
        return
    if args.command == "collect-feedback":
        _run_collect_feedback(args)
        return


def _run_analyze(args: argparse.Namespace) -> None:
    document = NewsDocument(
        external_id=None,
        source_name=args.source_name,
        source_url=args.source_url,
        title=args.title,
        body=args.body or None,
        language=args.language,
        published_at=datetime.now(timezone.utc),
        credibility=args.credibility,
        tags=(),
    )
    assessment = build_analyzer(args.analysis_mode).analyze(document)
    print(json.dumps(_jsonable(assessment), ensure_ascii=False, indent=2))


def _run_poll(args: argparse.Namespace) -> None:
    if not args.once:
        raise SystemExit("Only --once polling is implemented in the CLI. Use FeedPoller from Python for schedules.")
    result = FeedPoller(analyzer=build_analyzer(args.analysis_mode)).poll_once(
        limit=args.limit,
        max_age_hours=args.max_age_hours,
    )
    print(json.dumps(_jsonable(result), ensure_ascii=False, indent=2))


def _run_send_telegram(args: argparse.Namespace) -> None:
    try:
        config = TelegramConfig.from_env()
    except TelegramConfigError as exc:
        raise SystemExit(str(exc)) from None
    with TelegramClient(config) as client:
        feedback_store = build_feedback_store(args.feedback_db)
        send_telegram_from_poll(
            poller=FeedPoller(
                analyzer=build_analyzer(args.analysis_mode),
                document_filter=lambda document: not feedback_store.has_sent_alert(
                    external_id=document.external_id,
                    source_url=document.source_url,
                    title=document.title,
                ),
            ),
            notifier=TelegramNotifier(client, feedback_store=feedback_store),
            limit=args.limit,
            max_age_hours=args.max_age_hours,
            min_strength=args.min_strength,
            include_review=args.include_review,
        )


def _run_collect_feedback(args: argparse.Namespace) -> None:
    try:
        config = TelegramConfig.from_env()
    except TelegramConfigError as exc:
        raise SystemExit(str(exc)) from None
    with TelegramClient(config) as client:
        try:
            collect_telegram_feedback(
                client=client,
                store=build_feedback_store(args.feedback_db),
                timeout=args.timeout,
            )
        except TelegramDeliveryError as exc:
            raise SystemExit(str(exc)) from None


def build_analyzer(analysis_mode: str | None):
    mode = analysis_mode or environ.get("EGX_NEWS_BOT_ANALYSIS_MODE", "ai")
    if mode == "rules":
        return ImpactAnalyzer()
    if mode != "ai":
        raise SystemExit(f"Unsupported analysis mode: {mode}")
    try:
        config = AIAnalysisConfig.from_env()
    except AIConfigError as exc:
        raise SystemExit(str(exc)) from None
    return AIImpactAnalyzer(OpenAIResponsesClient(config))


def build_feedback_store(db_path: str | Path | None = None) -> FeedbackStore:
    return FeedbackStore(db_path or default_feedback_db_path())


def collect_telegram_feedback(*, client, store: FeedbackStore, timeout: int = 0):
    if timeout < 0:
        raise ValueError("timeout must be non-negative")
    updates = client.get_updates(offset=store.get_telegram_update_offset(), timeout=timeout)
    result = process_feedback_updates(updates, store=store, client=client)
    if result.next_offset is not None:
        store.set_telegram_update_offset(result.next_offset)
    print(
        "Processed "
        f"{result.processed} Telegram feedback callback{'s' if result.processed != 1 else ''}. "
        f"Ignored {result.ignored} update{'s' if result.ignored != 1 else ''}."
    )
    return result


def send_telegram_from_poll(
    *,
    poller,
    notifier,
    limit: int,
    max_age_hours: int,
    min_strength: int,
    include_review: bool,
) -> int:
    if min_strength < 0:
        raise ValueError("min_strength must be non-negative")
    if limit < 1 or limit > 100:
        raise ValueError("limit must be between 1 and 100")

    result: PollResult = poller.poll_once(limit=limit, max_age_hours=max_age_hours)
    sent_count = 0
    for assessment in result.assessments:
        if not _should_send_alert(assessment, min_strength=min_strength, include_review=include_review):
            continue
        notifier.send_assessment(assessment)
        sent_count += 1
    print(f"Sent {sent_count} Telegram alert{'s' if sent_count != 1 else ''}.")
    if result.errors:
        print(f"Source errors: {len(result.errors)}")
    return sent_count


def _should_send_alert(
    assessment: NewsImpactAssessment,
    *,
    min_strength: int,
    include_review: bool,
) -> bool:
    if assessment.impact_scope == "not_egx_related":
        return False
    if assessment.impact_scope == "sector_only" and not is_egypt_market_related(assessment.document):
        return False
    if assessment.needs_review and not include_review:
        return False
    return _assessment_strength(assessment) >= min_strength


def _assessment_strength(assessment: NewsImpactAssessment) -> int:
    strengths = [sector.strength for sector in assessment.sectors]
    strengths.extend(stock.strength for stock in assessment.stocks)
    return max(strengths, default=0)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, tuple | list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


if __name__ == "__main__":
    main()
