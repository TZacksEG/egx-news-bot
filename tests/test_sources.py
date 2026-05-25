from egx_news_bot.sources import DEFAULT_FEEDS


def test_default_feeds_cover_verified_egypt_market_news_sources():
    urls = {feed.url for feed in DEFAULT_FEEDS}
    names = {feed.name for feed in DEFAULT_FEEDS}

    assert "Arab Finance Macroeconomy" in names
    assert "Al Borsa News" in names
    assert "Daily News Egypt" in names
    assert "Daily News Egypt Business" in names
    assert "Enterprise AM" in names
    assert "Economy Plus" in names
    assert "Hapi Journal" in names
    assert "Youm7 Economy and Bourse" in names
    assert "Masrawy Economy" in names
    assert "Masrawy Banking" in names
    assert "Amwal Al Ghad English" in names
    assert "Egyptian Streets Business" in names
    assert "Invest-Gate Real Estate" in names
    assert "Egypt Oil & Gas" in names
    assert "Property Plus" in names
    assert "https://www.arabfinance.com/en/rss/rssbycat/1" in urls
    assert "https://www.alborsaanews.com/feed" in urls
    assert "https://www.dailynewsegypt.com/feed/" in urls
    assert "https://www.dailynewsegypt.com/category/business/feed/" in urls
    assert "https://www.youm7.com/rss/SectionRss?SectionID=297&output=xml" in urls
    assert "https://www.masrawy.com/rss/feed/206/%D8%A5%D9%82%D8%AA%D8%B5%D8%A7%D8%AF" in urls
    assert "https://www.masrawy.com/rss/feed/847/%D8%A3%D8%AE%D8%A8%D8%A7%D8%B1-%D8%A7%D9%84%D8%A8%D9%86%D9%88%D9%83" in urls
    assert "https://en.amwalalghad.com/feed/" in urls
    assert "https://egyptianstreets.com/category/business-technology/feed/" in urls
    assert "https://invest-gate.me/feed/" in urls
    assert "https://egyptoil-gas.com/feed/" in urls
    assert "https://propertypluseg.com/feed/" in urls
    assert len(urls) == len(DEFAULT_FEEDS)
    assert all(0.0 < feed.credibility <= 1.0 for feed in DEFAULT_FEEDS)
