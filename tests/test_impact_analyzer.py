from egx_news_bot.analysis import ImpactAnalyzer
from egx_news_bot.entities import CompanySeed, EntityRegistry
from egx_news_bot.models import NewsDocument


def _registry() -> EntityRegistry:
    return EntityRegistry(
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


def test_direct_company_contract_news_scores_named_stock_and_sector_positive():
    document = NewsDocument(
        external_id="n1",
        source_name="Al Borsa",
        source_url="https://example.com/n1",
        title="طلعت مصطفى توقع عقد تطوير مشروع جديد بقيمة 20 مليار جنيه",
        body="قالت الشركة إن العقد يدعم توسعاتها ومبيعاتها المستقبلية.",
        language="ar",
        published_at=None,
        credibility=0.75,
        tags=("real_estate",),
    )

    assessment = ImpactAnalyzer(_registry()).analyze(document)

    assert assessment.event_type == "contract"
    assert assessment.market_wide is False
    assert assessment.needs_review is False
    assert assessment.sectors[0].sector == "Real Estate"
    assert assessment.sectors[0].direction == "beneficiary"
    assert assessment.sectors[0].strength >= 65
    assert assessment.stocks[0].ticker == "TMGH"
    assert assessment.stocks[0].direction == "beneficiary"
    assert assessment.stocks[0].impact_type == "direct"
    assert assessment.stocks[0].strength >= 70
    assert assessment.stocks[0].confidence >= 0.70
    assert assessment.stocks[0].evidence


def test_macro_interest_rate_cut_scores_real_estate_positive_and_banks_mixed():
    document = NewsDocument(
        external_id="n2",
        source_name="CBE",
        source_url="https://example.com/n2",
        title="البنك المركزي يخفض أسعار الفائدة 200 نقطة أساس",
        body="خفض لجنة السياسة النقدية أسعار العائد الأساسية بما يدعم تكلفة التمويل.",
        language="ar",
        published_at=None,
        credibility=0.95,
        tags=("macro",),
    )

    assessment = ImpactAnalyzer(_registry()).analyze(document)

    sectors = {impact.sector: impact for impact in assessment.sectors}
    assert assessment.event_type == "interest_rate_cut"
    assert assessment.market_wide is True
    assert sectors["Real Estate"].direction == "beneficiary"
    assert sectors["Real Estate"].strength >= 70
    assert sectors["Banks"].direction == "mixed"
    assert sectors["Banks"].confidence >= 0.70

