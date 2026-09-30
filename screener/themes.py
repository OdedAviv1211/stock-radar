"""סיווג מניות לקטגוריות/נושאים (שרשרת ה-AI, דיבידנד, טכנולוגיה, אנרגיה...).
אפשר להוסיף טיקרים לרשימות כאן בחופשיות."""

AI_CHAIN = {
    "שבבים ומעבדים": ["NVDA", "AMD", "AVGO", "MRVL", "ARM", "QCOM", "INTC", "TSM", "ALAB", "CRDO",
                       "MCHP", "NXPI", "ADI", "TXN", "LSCC", "SITM", "AMBA", "POET", "NVTS", "GFS", "SNPS", "CDNS"],
    "ציוד לייצור שבבים": ["ASML", "AMAT", "LRCX", "KLAC", "TER", "ONTO", "CAMT", "NVMI", "ACMR", "AEHR",
                           "FORM", "UCTT", "ICHR", "ENTG", "MKSI", "COHU", "KLIC", "CAMT.TA", "NVMI.TA", "TSEM", "TSEM.TA"],
    "זיכרון ואחסון": ["MU", "WDC", "STX", "SNDK", "PSTG", "NTAP"],
    "תקשורת ואופטיקה": ["ANET", "CIEN", "COHR", "LITE", "FN", "AAOI", "CLS", "CSCO", "JNPR", "INFN", "MTSI", "NOK", "CRDO"],
    "שרתים ומרכזי נתונים": ["SMCI", "DELL", "HPE", "EQIX", "DLR", "CRWV", "NBIS", "APLD", "IREN", "CORZ", "WULF", "CIFR", "GDS"],
    "חשמל, קירור ותשתית": ["VRT", "ETN", "VST", "CEG", "TLN", "GEV", "NRG", "OKLO", "SMR", "BE", "PWR", "MOD",
                           "NNE", "LEU", "CCJ", "HUBB", "POWL", "EME", "FIX", "STRL", "MTZ", "ENLT.TA"],
    "תוכנה וענן AI": ["MSFT", "GOOGL", "GOOG", "AMZN", "META", "ORCL", "PLTR", "SNOW", "NOW", "CRM", "AI",
                       "PATH", "DDOG", "MDB", "NET", "SOUN", "BBAI", "TEM", "APP", "IOT", "ESTC", "GTLB", "CFLT"],
}

SPECIAL = {
    "סייבר": ["CRWD", "PANW", "ZS", "FTNT", "S", "CHKP", "CYBR", "OKTA", "TENB", "RPD", "QLYS", "VRNS", "RBRK", "HACK"],
    "קריפטו ובלוקצ'יין": ["COIN", "MSTR", "MARA", "RIOT", "CLSK", "HOOD", "HUT", "BTDR", "GLXY", "CRCL", "BMNR", "SBET"],
    "קוונטום": ["IONQ", "RGTI", "QBTS", "QUBT", "ARQQ"],
    "חלל": ["RKLB", "ASTS", "LUNR", "PL", "RDW", "KRMN", "FLY"],
    "ביטחון": ["LMT", "RTX", "NOC", "GD", "LHX", "HII", "KTOS", "AVAV", "ESLT", "ESLT.TA", "AXON", "PLTR", "NXSN.TA", "ARYT.TA"],
}

# מיפוי סקטורים (משני מקורות: Nasdaq ו-Yahoo) לשמות בעברית
SECTOR_HE = {
    "Technology": "טכנולוגיה",
    "Health Care": "בריאות וביוטק", "Healthcare": "בריאות וביוטק",
    "Finance": "פיננסים", "Financial Services": "פיננסים", "Financial": "פיננסים",
    "Energy": "אנרגיה",
    "Utilities": "תשתיות וחשמל",
    "Industrials": "תעשייה",
    "Consumer Discretionary": "צריכה מחזורית", "Consumer Cyclical": "צריכה מחזורית",
    "Consumer Staples": "צריכה בסיסית", "Consumer Defensive": "צריכה בסיסית",
    "Real Estate": "נדל\"ן",
    "Basic Materials": "חומרי גלם", "Materials": "חומרי גלם",
    "Telecommunications": "תקשורת ומדיה", "Communication Services": "תקשורת ומדיה",
    "Miscellaneous": "אחר", "": "אחר", None: "אחר",
}

# חברות ש-NVIDIA מחזיקה/השקיעה בהן (13F ל-30.6.2026 + השקעות אסטרטגיות רשמיות). מתעדכן ידנית / ע"י חדר המחקר.
# ממצא הבדיקה: אות חזק ביום ההכרזה, לא אות איכות לטווח ארוך – לכן זו תגית ונימוק, בלי תוספת לציון.
NVDA_INVESTEES = {
    "INTC": "Intel", "SPCX": "SpaceX (כולל xAI)", "CRWV": "CoreWeave", "COHR": "Coherent", "NOK": "Nokia",
    "SNPS": "Synopsys", "NBIS": "Nebius Group", "GENB": "Generate Biomedicines", "LITE": "Lumentum",
    "MRVL": "Marvell Technology", "GLW": "Corning", "IREN": "IREN",
}

_AI_LOOKUP = {t: sub for sub, ts in AI_CHAIN.items() for t in ts}
_SPECIAL_LOOKUP = {}
for theme, ts in SPECIAL.items():
    for t in ts:
        _SPECIAL_LOOKUP.setdefault(t, theme)

AI_INDUSTRY_KEYWORDS = ("semiconductor",)


def sector_he(sector):
    return SECTOR_HE.get(sector, sector or "אחר")


def classify(ticker, sector, industry, div_yield=None):
    """מחזיר (קטגוריה ראשית, תת-קטגוריה, רשימת תגיות)."""
    tags = []
    ind = (industry or "").lower()
    base = ticker.replace(".TA", "")
    if ticker.endswith(".TA"):
        tags.append("ישראל")
    if div_yield is not None and div_yield >= 0.03:
        tags.append("דיבידנד")
    if ticker in NVDA_INVESTEES:
        tags.append("השקעת NVIDIA")

    if ticker in _AI_LOOKUP or base in _AI_LOOKUP:
        sub = _AI_LOOKUP.get(ticker) or _AI_LOOKUP.get(base)
        tags.append("שרשרת ה-AI")
        return "שרשרת ה-AI", sub, tags
    if any(k in ind for k in AI_INDUSTRY_KEYWORDS):
        tags.append("שרשרת ה-AI")
        return "שרשרת ה-AI", "שבבים ומעבדים", tags
    if ticker in _SPECIAL_LOOKUP or base in _SPECIAL_LOOKUP:
        th = _SPECIAL_LOOKUP.get(ticker) or _SPECIAL_LOOKUP.get(base)
        return th, th, tags
    if "biotech" in ind or "pharmaceutical" in ind:
        return "בריאות וביוטק", "ביוטק ופארמה", tags
    if div_yield is not None and div_yield >= 0.04:
        return "דיבידנד", sector_he(sector), tags
    return sector_he(sector), sector_he(sector), tags


ALL_THEMES = ["שרשרת ה-AI", "סייבר", "קריפטו ובלוקצ'יין", "קוונטום", "חלל", "ביטחון", "דיבידנד",
              "טכנולוגיה", "בריאות וביוטק", "פיננסים", "אנרגיה", "תשתיות וחשמל", "תעשייה",
              "צריכה מחזורית", "צריכה בסיסית", "נדל\"ן", "חומרי גלם", "תקשורת ומדיה", "אחר"]
