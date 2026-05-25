from __future__ import annotations

import re


_DIACRITICS = re.compile(r"[\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed]")
_TATWEEL = "\u0640"
_PUNCTUATION = re.compile(r"[^\w\s\u0600-\u06ff]")
_WHITESPACE = re.compile(r"\s+")

_DIGITS = str.maketrans(
    {
        "٠": "0",
        "١": "1",
        "٢": "2",
        "٣": "3",
        "٤": "4",
        "٥": "5",
        "٦": "6",
        "٧": "7",
        "٨": "8",
        "٩": "9",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
    }
)


def normalize_arabic(text: str) -> str:
    normalized = text.translate(_DIGITS).replace(_TATWEEL, "")
    normalized = _DIACRITICS.sub("", normalized)
    normalized = re.sub("[أإآٱ]", "ا", normalized)
    normalized = normalized.replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    normalized = normalized.replace("ة", "ه")
    normalized = _PUNCTUATION.sub(" ", normalized.lower())
    return _WHITESPACE.sub(" ", normalized).strip()

