"""
Week 3: Database Integration.

Turns the structured filters produced by parse_query.parse_property_query()
into parameterized SQL against the MLS tables.
"""

from db import get_cursor

# rets_property stores boolean-ish flags as '1' (true) / '' or NULL (false),
# not as the "True" string the parser emits.
_TRUE_FLAG = "1"

_ACTIVE_LISTING_COLUMNS = """
    L_ListingID, L_Address, L_City, L_SystemPrice,
    L_Keyword2 AS beds, LM_Dec_3 AS baths, LM_Int2_3 AS sqft,
    L_Type_ AS propertyType, PoolPrivateYN, ViewYN, AssociationFee, PhotoCount
"""

# Each entry: filters key -> (column, SQL comparator, value transform)
_FILTER_COLUMNS = {
    "city": ("L_City", "=", str),
    "maxPrice": ("L_SystemPrice", "<=", int),
    "beds": ("L_Keyword2", ">=", int),
    "baths": ("LM_Dec_3", ">=", float),
    "sqft": ("LM_Int2_3", ">=", int),
    "type": ("L_Type_", "=", str),
    "pool": ("PoolPrivateYN", "=", lambda v: _TRUE_FLAG),
    "hasView": ("ViewYN", "=", lambda v: _TRUE_FLAG),
    "maxHOA": ("AssociationFee", "<=", int),
}


def searchActiveListings(filters: dict, page: int = 1, limit: int = 10) -> list[dict]:
    """
    Query rets_property for active listings matching the given filters.

    `filters` is the dict returned by parse_property_query() — any key
    left as None is skipped. Results are ordered by price ascending and
    paginated (`page` is 1-indexed).
    """
    where = ["L_Status = 'Active'"]
    params = []
    for key, (column, comparator, transform) in _FILTER_COLUMNS.items():
        value = filters.get(key)
        if value is None:
            continue
        where.append(f"{column} {comparator} %s")
        params.append(transform(value))

    query = f"""
        SELECT {_ACTIVE_LISTING_COLUMNS}
        FROM rets_property
        WHERE {' AND '.join(where)}
        ORDER BY L_SystemPrice ASC
        LIMIT %s OFFSET %s
    """
    params.extend([limit, (page - 1) * limit])

    with get_cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


def format_listing_card(row: dict) -> str:
    """Render a single searchActiveListings() row as a display-ready card."""
    beds = row["beds"] if row["beds"] is not None else "?"
    baths = row["baths"] if row["baths"] is not None else "?"
    sqft = f"{row['sqft']:,} sqft" if row["sqft"] is not None else "sqft n/a"
    price = f"${row['L_SystemPrice']:,}"
    tags = []
    if row.get("PoolPrivateYN") == _TRUE_FLAG:
        tags.append("pool")
    if row.get("ViewYN") == _TRUE_FLAG:
        tags.append("view")
    tag_str = f" [{', '.join(tags)}]" if tags else ""
    photos = row.get("PhotoCount")
    photo_str = f", {photos} photos" if photos is not None else ""
    return (
        f"{row['L_Address']}, {row['L_City']} — {price}\n"
        f"{beds}bd/{baths}ba, {sqft}, {row['propertyType']}{photo_str}{tag_str}"
    )


def getSoldComps(city: str, months: int = 12, limit: int = 25) -> list[dict]:
    """
    Query california_sold for recent comps in a city, relative to today.

    A handful of rows in this dataset have corrupted CloseDate values far in
    the future (data entry errors), so the cutoff is anchored to CURDATE()
    rather than MAX(CloseDate), which those outliers would otherwise skew.
    """
    query = """
        SELECT ListingKey, UnparsedAddress, City, ClosePrice, CloseDate,
               DaysOnMarket, LivingArea, BedroomsTotal, BathroomsTotalInteger
        FROM california_sold
        WHERE City = %s
          AND CloseDate >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)
          AND CloseDate <= CURDATE()
        ORDER BY CloseDate DESC
        LIMIT %s
    """
    with get_cursor() as cursor:
        cursor.execute(query, (city, months, limit))
        return cursor.fetchall()
