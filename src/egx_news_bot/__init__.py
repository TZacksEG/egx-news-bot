"""Egyptian market news ingestion and impact scoring app."""

from egx_news_bot.ai_analysis import AIAnalysisConfig, AIImpactAnalyzer, OpenAIResponsesClient
from egx_news_bot.analysis import ImpactAnalyzer
from egx_news_bot.entities import EntityRegistry, default_registry
from egx_news_bot.feedback import FeedbackStore
from egx_news_bot.ingestion import NewsFeedConfig, parse_feed
from egx_news_bot.telegram import TelegramClient, TelegramConfig, TelegramNotifier

__all__ = [
    "EntityRegistry",
    "AIAnalysisConfig",
    "AIImpactAnalyzer",
    "FeedbackStore",
    "ImpactAnalyzer",
    "NewsFeedConfig",
    "OpenAIResponsesClient",
    "TelegramClient",
    "TelegramConfig",
    "TelegramNotifier",
    "default_registry",
    "parse_feed",
]
