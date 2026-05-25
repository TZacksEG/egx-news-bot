from datetime import timezone

from egx_news_bot.ingestion import NewsFeedConfig, parse_feed


RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Market feed</title>
    <item>
      <guid>story-1</guid>
      <title>طلعت مصطفى توقع عقد تطوير مشروع جديد بقيمة 20 مليار جنيه</title>
      <link>https://example.com/story-1</link>
      <description><![CDATA[<p>تستهدف الشركة زيادة المبيعات من المشروع الجديد.</p>]]></description>
      <pubDate>Sun, 24 May 2026 10:15:00 +0200</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM_UPDATED_RSS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:a10="http://www.w3.org/2005/Atom" version="2.0">
  <channel>
    <item>
      <guid>story-2</guid>
      <title>EGX shows positive performance on Sunday</title>
      <link>https://example.com/story-2</link>
      <description>EGX shows positive performance on Sunday</description>
      <a10:updated>2026-05-24T15:10:00+03:00</a10:updated>
    </item>
  </channel>
</rss>
"""


def test_parse_feed_extracts_rss_items_as_news_documents():
    source = NewsFeedConfig(
        name="Example Finance",
        url="https://example.com/feed",
        language="ar",
        credibility=0.72,
        tags=("real_estate",),
    )

    documents = parse_feed(RSS_XML, source)

    assert len(documents) == 1
    document = documents[0]
    assert document.external_id == "story-1"
    assert document.source_name == "Example Finance"
    assert document.source_url == "https://example.com/story-1"
    assert document.language == "ar"
    assert document.credibility == 0.72
    assert document.tags == ("real_estate",)
    assert document.title == "طلعت مصطفى توقع عقد تطوير مشروع جديد بقيمة 20 مليار جنيه"
    assert document.body == "تستهدف الشركة زيادة المبيعات من المشروع الجديد."
    assert document.published_at is not None
    assert document.published_at.tzinfo == timezone.utc
    assert document.published_at.isoformat() == "2026-05-24T08:15:00+00:00"


def test_parse_feed_accepts_atom_updated_timestamps_inside_rss_items():
    source = NewsFeedConfig(
        name="Arab Finance",
        url="https://example.com/feed",
        language="en",
        credibility=0.78,
    )

    document = parse_feed(ATOM_UPDATED_RSS_XML, source)[0]

    assert document.published_at is not None
    assert document.published_at.isoformat() == "2026-05-24T12:10:00+00:00"
