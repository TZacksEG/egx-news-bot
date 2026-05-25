from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import xml.etree.ElementTree as ET

from egx_news_bot.models import NewsDocument, NewsFeedConfig


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        return " ".join(self.parts)


def parse_feed(xml_text: str, source: NewsFeedConfig) -> list[NewsDocument]:
    root = ET.fromstring(xml_text)
    items = _rss_items(root) or _atom_entries(root)
    return [_document_from_item(item, source) for item in items]


def _rss_items(root: ET.Element) -> list[ET.Element]:
    return root.findall("./channel/item")


def _atom_entries(root: ET.Element) -> list[ET.Element]:
    namespace = _namespace(root.tag)
    if namespace:
        return root.findall(f".//{{{namespace}}}entry")
    return root.findall(".//entry")


def _document_from_item(item: ET.Element, source: NewsFeedConfig) -> NewsDocument:
    title = _first_text(item, ("title",)) or ""
    link = _link(item) or source.url
    body = _clean_html(_first_text(item, ("description", "summary", "content")) or "")
    external_id = _first_text(item, ("guid", "id")) or _stable_id(source.name, link, title)
    published = _parse_datetime(_first_text(item, ("pubDate", "published", "updated")))
    return NewsDocument(
        external_id=external_id,
        source_name=source.name,
        source_url=link,
        title=_clean_html(title),
        body=body or None,
        language=source.language,
        published_at=published,
        credibility=source.credibility,
        tags=source.tags,
    )


def _first_text(item: ET.Element, names: tuple[str, ...]) -> str | None:
    for name in names:
        node = _find_child(item, name)
        if node is not None and node.text:
            return node.text.strip()
    return None


def _find_child(item: ET.Element, local_name: str) -> ET.Element | None:
    for child in item:
        if _local_name(child.tag) == local_name:
            return child
    return None


def _link(item: ET.Element) -> str | None:
    link = _find_child(item, "link")
    if link is None:
        return None
    href = link.attrib.get("href")
    if href:
        return href.strip()
    return link.text.strip() if link.text else None


def _clean_html(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(unescape(value))
    text = parser.text() or unescape(value)
    return " ".join(text.split())


def _parse_datetime(value: str | None):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stable_id(source_name: str, link: str, title: str) -> str:
    digest = sha256(f"{source_name}|{link}|{title}".encode("utf-8")).hexdigest()
    return digest[:16]


def _namespace(tag: str) -> str | None:
    if tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return None


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag
