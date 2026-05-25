from __future__ import annotations

from dataclasses import dataclass

from egx_news_bot.normalization import normalize_arabic


@dataclass(frozen=True)
class CompanySeed:
    ticker: str | None
    isin: str | None
    name_ar: str
    name_en: str | None
    sector: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class CompanyMention:
    ticker: str | None
    isin: str | None
    name_ar: str
    name_en: str | None
    sector: str
    matched_alias: str
    match_method: str
    match_score: float
    start: int


class EntityRegistry:
    def __init__(self, companies: list[CompanySeed] | tuple[CompanySeed, ...]) -> None:
        self._companies = tuple(companies)

    def find_mentions(self, text: str) -> list[CompanyMention]:
        normalized_text = normalize_arabic(text)
        mentions: list[CompanyMention] = []

        for company in self._companies:
            aliases = (company.ticker or "", company.isin or "", company.name_ar, company.name_en or "", *company.aliases)
            best: CompanyMention | None = None
            for alias in aliases:
                alias = alias.strip()
                if not alias:
                    continue
                normalized_alias = normalize_arabic(alias)
                if not normalized_alias:
                    continue
                start = normalized_text.find(normalized_alias)
                if start == -1:
                    continue
                candidate = CompanyMention(
                    ticker=company.ticker,
                    isin=company.isin,
                    name_ar=company.name_ar,
                    name_en=company.name_en,
                    sector=company.sector,
                    matched_alias=alias,
                    match_method="alias",
                    match_score=1.0,
                    start=start,
                )
                if best is None or candidate.start < best.start or len(alias) > len(best.matched_alias):
                    best = candidate
            if best is not None:
                mentions.append(best)

        return sorted(mentions, key=lambda mention: mention.start)


DEFAULT_COMPANIES: tuple[CompanySeed, ...] = (
    CompanySeed(
        ticker="COMI",
        isin="EGS60121C018",
        name_ar="البنك التجاري الدولي مصر",
        name_en="Commercial International Bank Egypt",
        sector="Banks",
        aliases=("البنك التجاري الدولي", "CIB", "Commercial International Bank", "التجاري الدولي"),
    ),
    CompanySeed(
        ticker="TMGH",
        isin="EGS691S1C011",
        name_ar="مجموعة طلعت مصطفى القابضة",
        name_en="Talaat Moustafa Group Holding",
        sector="Real Estate",
        aliases=("طلعت مصطفى", "Talaat Moustafa", "TMG", "Madinaty", "مدينتي"),
    ),
    CompanySeed(
        ticker="HRHO",
        isin="EGS69101C011",
        name_ar="اي اف جي القابضة",
        name_en="EFG Holding",
        sector="Non-bank Financial Services",
        aliases=("اي اف جي", "EFG Hermes", "EFG Holding", "هيرميس"),
    ),
    CompanySeed(
        ticker="ETEL",
        isin="EGS48031C016",
        name_ar="المصرية للاتصالات",
        name_en="Telecom Egypt",
        sector="Telecom",
        aliases=("Telecom Egypt", "WE", "المصرية للاتصالات"),
    ),
    CompanySeed(
        ticker="SWDY",
        isin="EGS3G0Z1C014",
        name_ar="السويدي اليكتريك",
        name_en="Elsewedy Electric",
        sector="Industrials",
        aliases=("السويدي", "Elsewedy", "El Sewedy", "SWDY"),
    ),
    CompanySeed(
        ticker="ABUK",
        isin="EGS38191C010",
        name_ar="ابو قير للاسمدة والصناعات الكيماوية",
        name_en="Abu Qir Fertilizers",
        sector="Basic Resources",
        aliases=("ابو قير للاسمدة", "Abu Qir", "ABUK"),
    ),
)


def default_registry() -> EntityRegistry:
    return EntityRegistry(DEFAULT_COMPANIES)

