from egx_news_bot.entities import CompanySeed, EntityRegistry
from egx_news_bot.normalization import normalize_arabic


def test_normalize_arabic_removes_matching_noise():
    text = "إعــلان شركة طلعت مُصطفى ٢٠٢٦"

    assert normalize_arabic(text) == "اعلان شركه طلعت مصطفي 2026"


def test_entity_registry_resolves_arabic_and_english_aliases():
    registry = EntityRegistry(
        [
            CompanySeed(
                ticker="TMGH",
                isin="EGS691S1C011",
                name_ar="مجموعة طلعت مصطفى القابضة",
                name_en="Talaat Moustafa Group Holding",
                sector="Real Estate",
                aliases=("طلعت مصطفى", "Talaat Moustafa", "TMG", "TMGH"),
            ),
            CompanySeed(
                ticker="COMI",
                isin="EGS60121C018",
                name_ar="البنك التجاري الدولي مصر",
                name_en="Commercial International Bank Egypt",
                sector="Banks",
                aliases=("البنك التجاري الدولي", "CIB", "COMI"),
            ),
        ]
    )

    matches = registry.find_mentions("البنك التجاري الدولي CIB يعلن تمويلا جديدا لمجموعة طلعت مصطفى")

    assert [match.ticker for match in matches] == ["COMI", "TMGH"]
    assert matches[0].match_method == "alias"
    assert matches[0].match_score == 1.0

