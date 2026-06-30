import re

TYPE_MAP = {
    "condo":         "Condominium",
    "condominium":   "Condominium",
    "townhome":      "Townhouse",
    "townhouse":     "Townhouse",
    "single family": "SingleFamilyResidence",
    "sfr":           "SingleFamilyResidence",
    "land":          "UnimprovedLand",
    "multi":         "MultiFamily",
    "duplex":        "Duplex",
}


def parse_property_query(query: str) -> dict:
    """
    Parse a free-text real estate query into structured filter fields
    that map directly to rets_property columns.

    Returns a dict with keys:
        city, maxPrice, beds, baths, sqft, type, pool, hasView, maxHOA
    All values are None when not mentioned.
    """
    q = query.lower()

    # --- city ---
    city_match = re.search(
        r"\bin\s+([A-Za-z][A-Za-z\s]{1,30}?)(?:\s+under|\s+with|\s+at|\s+for|\s+around|,|\.|$)",
        query,
        re.IGNORECASE,
    )
    city = city_match.group(1).strip().title() if city_match else None

    # --- max price ---
    price_match = re.search(
        r"under\s+\$?([\d,]+(?:\.\d+)?)\s*(k|m|million|thousand)?",
        q,
    )
    max_price = None
    if price_match:
        raw = float(price_match.group(1).replace(",", ""))
        suffix = (price_match.group(2) or "").lower()
        if suffix in ("m", "million"):
            raw *= 1_000_000
        elif suffix in ("k", "thousand"):
            raw *= 1_000
        max_price = int(raw)

    # --- beds ---
    beds_match = re.search(r"(\d+)[\s-]*(?:bed|beds|bedroom|bedrooms|br)\b", q)
    beds = int(beds_match.group(1)) if beds_match else None

    # --- baths ---
    baths_match = re.search(r"(\d+(?:\.\d)?)\s*(?:bath|baths|bathroom|bathrooms|ba)\b", q)
    baths = float(baths_match.group(1)) if baths_match else None

    # --- min sqft ---
    sqft_match = re.search(r"([\d,]+)\s*(?:sq\.?\s*ft|sqft|square\s*feet)", q)
    sqft = int(sqft_match.group(1).replace(",", "")) if sqft_match else None

    # --- property type ---
    prop_type = None
    for keyword, db_value in TYPE_MAP.items():
        if keyword in q:
            prop_type = db_value
            break

    # --- pool ---
    pool = "True" if re.search(r"\bpool\b", q) else None

    # --- view ---
    has_view = "True" if re.search(r"\bview\b", q) else None

    # --- max HOA ---
    hoa_match = re.search(r"hoa\s+(?:under|below|max|<)?\s*\$?([\d,]+)", q)
    max_hoa = int(hoa_match.group(1).replace(",", "")) if hoa_match else None

    return {
        "city":     city,
        "maxPrice": max_price,
        "beds":     beds,
        "baths":    baths,
        "sqft":     sqft,
        "type":     prop_type,
        "pool":     pool,
        "hasView":  has_view,
        "maxHOA":   max_hoa,
    }
