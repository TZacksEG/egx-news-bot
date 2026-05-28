from __future__ import annotations

from dataclasses import dataclass

from egx_news_bot.normalization import normalize_arabic

CANONICAL_EGX_SECTORS: tuple[str, ...] = (
    "Banks",
    "Basic Resources",
    "Chemicals",
    "Construction and Materials",
    "Education Services",
    "Food, Beverages and Tobacco",
    "Healthcare and Pharmaceuticals",
    "Industrial Goods, Services and Automobiles",
    "Non-bank Financial Services",
    "Real Estate",
    "Shipping and Transportation Services",
    "Telecom",
    "Travel and Leisure",
    "Utilities",
)

_SECTOR_ALIASES: dict[str, tuple[str, ...]] = {
    "Banks": ("banks", "banking", "بنوك", "البنوك", "القطاع المصرفي"),
    "Basic Resources": ("basic resources", "materials", "fertilizers", "metals", "موارد اساسيه", "اسمده", "معادن"),
    "Chemicals": ("chemicals", "كيماويات", "بتروكيماويات"),
    "Construction and Materials": ("construction", "cement", "building materials", "مقاولات", "اسمنت", "مواد بناء"),
    "Education Services": ("education", "تعليم", "خدمات تعليم"),
    "Food, Beverages and Tobacco": ("food", "beverages", "tobacco", "اغذيه", "مشروبات", "تبغ"),
    "Healthcare and Pharmaceuticals": ("healthcare", "pharma", "pharmaceuticals", "رعايه صحيه", "ادويه"),
    "Industrial Goods, Services and Automobiles": (
        "industrials",
        "industrial",
        "automobiles",
        "صناعه",
        "صناعات",
        "سيارات",
    ),
    "Non-bank Financial Services": (
        "non-bank financial services",
        "financial services",
        "fintech",
        "خدمات ماليه",
        "خدمات ماليه غير مصرفيه",
    ),
    "Real Estate": ("real estate", "property", "عقارات", "العقارات", "تطوير عقاري"),
    "Shipping and Transportation Services": ("transportation", "shipping", "logistics", "نقل", "شحن", "لوجستيات"),
    "Telecom": ("telecom", "telecommunications", "اتصالات", "الاتصالات"),
    "Travel and Leisure": ("travel", "tourism", "leisure", "سياحه", "ترفيه"),
    "Utilities": ("utilities", "electricity", "power", "مرافق", "كهرباء", "طاقه"),
}


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

    @property
    def companies(self) -> tuple[CompanySeed, ...]:
        return self._companies

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

    def find_company(
        self,
        *,
        ticker: str | None = None,
        isin: str | None = None,
        name_ar: str | None = None,
        name_en: str | None = None,
    ) -> CompanySeed | None:
        if isin:
            normalized_isin = isin.strip().upper()
            for company in self._companies:
                if company.isin and company.isin.upper() == normalized_isin:
                    return company

        if ticker:
            normalized_ticker = _normalize_ticker(ticker)
            for company in self._companies:
                if company.ticker and _normalize_ticker(company.ticker) == normalized_ticker:
                    return company

        names = tuple(name for name in (name_ar, name_en) if name and name.strip())
        for name in names:
            normalized_name = normalize_arabic(name)
            if not normalized_name:
                continue
            for company in self._companies:
                aliases = (company.name_ar, company.name_en or "", *company.aliases)
                for alias in aliases:
                    normalized_alias = normalize_arabic(alias)
                    if normalized_alias and normalized_alias == normalized_name:
                        return company
        return None

    def sectors(self) -> tuple[str, ...]:
        return tuple(sorted({company.sector for company in self._companies} | set(CANONICAL_EGX_SECTORS)))


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
        sector="Industrial Goods, Services and Automobiles",
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
    CompanySeed(
        ticker="BTFH",
        isin=None,
        name_ar="بلتون القابضة",
        name_en="Beltone Holding",
        sector="Non-bank Financial Services",
        aliases=("بلتون", "Beltone", "Beltone Financial Holding"),
    ),
    CompanySeed(
        ticker="MASR",
        isin=None,
        name_ar="مدينة مصر للاسكان والتعمير",
        name_en="Madinet Masr",
        sector="Real Estate",
        aliases=("مدينة مصر", "Madinet Masr", "Madinet Nasr", "مدينة نصر للاسكان"),
    ),
    CompanySeed(
        ticker="PHDC",
        isin=None,
        name_ar="بالم هيلز للتعمير",
        name_en="Palm Hills Developments",
        sector="Real Estate",
        aliases=("بالم هيلز", "Palm Hills"),
    ),
    CompanySeed(
        ticker="ORHD",
        isin=None,
        name_ar="اوراسكوم للتنمية مصر",
        name_en="Orascom Development Egypt",
        sector="Real Estate",
        aliases=("اوراسكوم للتنمية", "Orascom Development"),
    ),
    CompanySeed(
        ticker="ORAS",
        isin=None,
        name_ar="اوراسكوم كونستراكشون",
        name_en="Orascom Construction",
        sector="Construction and Materials",
        aliases=("اوراسكوم للانشاء", "اوراسكوم كونستراكشون", "Orascom Construction"),
    ),
    CompanySeed(
        ticker="MFPC",
        isin=None,
        name_ar="مصر لانتاج الاسمدة - موبكو",
        name_en="Misr Fertilizers Production - MOPCO",
        sector="Basic Resources",
        aliases=("موبكو", "MOPCO", "Misr Fertilizers"),
    ),
    CompanySeed(
        ticker="SKPC",
        isin=None,
        name_ar="سيدي كرير للبتروكيماويات",
        name_en="Sidi Kerir Petrochemicals",
        sector="Chemicals",
        aliases=("سيدي كرير", "سيدبك", "Sidi Kerir", "Sidpec"),
    ),
    CompanySeed(
        ticker="PACH",
        isin=None,
        name_ar="البويات والصناعات الكيماوية - باكين",
        name_en="Paints and Chemical Industries - Pachin",
        sector="Chemicals",
        aliases=("باكين", "Pachin", "Paints and Chemical Industries"),
    ),
    CompanySeed(
        ticker="KZPC",
        isin=None,
        name_ar="كفر الزيات للمبيدات والكيماويات",
        name_en="Kafr El Zayat Pesticides",
        sector="Chemicals",
        aliases=("كفر الزيات", "Kafr El Zayat Pesticides"),
    ),
    CompanySeed(
        ticker="LCSW",
        isin=None,
        name_ar="ليسيكو مصر",
        name_en="Lecico Egypt",
        sector="Industrial Goods, Services and Automobiles",
        aliases=("ليسيكو", "Lecico"),
    ),
    CompanySeed(
        ticker="FWRY",
        isin=None,
        name_ar="فوري لتكنولوجيا البنوك والمدفوعات الالكترونية",
        name_en="Fawry",
        sector="Non-bank Financial Services",
        aliases=("فوري", "Fawry"),
    ),
    CompanySeed(
        ticker="EAST",
        isin=None,
        name_ar="الشرقية للدخان",
        name_en="Eastern Company",
        sector="Food, Beverages and Tobacco",
        aliases=("الشرقية للدخان", "ايسترن كومباني", "Eastern Company"),
    ),
    CompanySeed(
        ticker="EFID",
        isin=None,
        name_ar="ايديتا للصناعات الغذائية",
        name_en="Edita Food Industries",
        sector="Food, Beverages and Tobacco",
        aliases=("ايديتا", "Edita"),
    ),
    CompanySeed(
        ticker="JUFO",
        isin=None,
        name_ar="جهينة للصناعات الغذائية",
        name_en="Juhayna Food Industries",
        sector="Food, Beverages and Tobacco",
        aliases=("جهينة", "Juhayna"),
    ),
    CompanySeed(
        ticker="CLHO",
        isin=None,
        name_ar="مجموعة مستشفيات كليوباترا",
        name_en="Cleopatra Hospital Group",
        sector="Healthcare and Pharmaceuticals",
        aliases=("كليوباترا", "Cleopatra Hospital"),
    ),
    CompanySeed(
        ticker="ISPH",
        isin=None,
        name_ar="ابن سينا فارما",
        name_en="Ibnsina Pharma",
        sector="Healthcare and Pharmaceuticals",
        aliases=("ابن سينا", "Ibnsina"),
    ),
    CompanySeed(
        ticker="ESRS",
        isin=None,
        name_ar="حديد عز",
        name_en="Ezz Steel",
        sector="Basic Resources",
        aliases=("حديد عز", "Ezz Steel"),
    ),
    CompanySeed(
        ticker="AMOC",
        isin=None,
        name_ar="الاسكندرية للزيوت المعدنية",
        name_en="Alexandria Mineral Oils",
        sector="Basic Resources",
        aliases=("اموك", "AMOC", "Alexandria Mineral Oils"),
    ),
    CompanySeed(
        ticker="EKHO",
        isin=None,
        name_ar="القابضة المصرية الكويتية",
        name_en="Egyptian Kuwaiti Holding",
        sector="Basic Resources",
        aliases=("المصرية الكويتية", "Egyptian Kuwaiti Holding"),
    ),
    CompanySeed(
        ticker="ALCN",
        isin=None,
        name_ar="الاسكندرية لتداول الحاويات والبضائع",
        name_en="Alexandria Containers",
        sector="Shipping and Transportation Services",
        aliases=("الاسكندرية للحاويات", "Alexandria Containers"),
    ),
)


def default_registry() -> EntityRegistry:
    return EntityRegistry(DEFAULT_COMPANIES)


def canonical_sector(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_arabic(value)
    if not normalized:
        return None
    for sector in CANONICAL_EGX_SECTORS:
        if normalize_arabic(sector) == normalized:
            return sector
        for alias in _SECTOR_ALIASES.get(sector, ()):
            if normalize_arabic(alias) == normalized:
                return sector
    return None


def _normalize_ticker(value: str) -> str:
    ticker = value.strip().upper()
    if ticker.endswith(".CA"):
        ticker = ticker[:-3]
    return ticker
