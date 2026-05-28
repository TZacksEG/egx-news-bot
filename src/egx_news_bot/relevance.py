from __future__ import annotations

from egx_news_bot.models import NewsDocument
from egx_news_bot.normalization import normalize_arabic

_EGYPT_MARKET_KEYWORDS: tuple[str, ...] = (
    "مصر",
    "المصري",
    "المصريه",
    "القاهره",
    "البورصه",
    "البورصه المصريه",
    "سوق المال",
    "الرقابه الماليه",
    "البنك المركزي",
    "الجنيه",
    "الحكومه",
    "وزاره الماليه",
    "قناه السويس",
    "صندوق مصر السيادي",
    "egypt",
    "egyptian",
    "cairo",
    "egx",
    "cbe",
)


def is_egypt_market_related(document: NewsDocument) -> bool:
    text = normalize_arabic(f"{document.title}\n{document.body or ''}\n{document.source_name}")
    return any(normalize_arabic(keyword) in text for keyword in _EGYPT_MARKET_KEYWORDS)
