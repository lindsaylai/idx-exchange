"""
Week 7: Recommendations.

Combines structured filtering (property-search), free-text similarity
(semantic-search), and sold-comp pricing (california_sold) into one ranked
recommendation list: parse the query into hard filters, pull matching active
listings with their remarks, rank them by a hybrid score that blends
semantic fit to the query's descriptive language with how good a deal each
listing is relative to recent sold comps in its own city, and flag each
result as under/over/fairly priced.

Reuses the property-search connection pool and filter map, and the
semantic-search embed_texts() helper, rather than duplicating either.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "property-search"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "semantic-search"))

import numpy as np
import openai
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from db import get_cursor
from parse_query import parse_property_query
from search_listings import _FILTER_COLUMNS, getSoldComps
from semantic_search import embed_texts

_BACKEND_OPENAI = "openai"
_BACKEND_TFIDF = "tfidf"

_CANDIDATE_COLUMNS = """
    L_ListingID AS listingId, L_Address AS address, L_City AS city,
    L_SystemPrice AS price, L_Keyword2 AS beds, LM_Dec_3 AS baths,
    LM_Int2_3 AS sqft, L_Remarks AS remarks
"""

# Comp $/sqft vs. this listing's $/sqft, outside +/-7%, reads as a real signal
# rather than noise -- california_sold's own list-to-close spread (see
# market-stats) runs a couple of points tighter than that on average.
_UNDERPRICED_MAX_RATIO = 0.93
_OVERPRICED_MIN_RATIO = 1.07


def _search_with_remarks(filters: dict, limit: int) -> list[dict]:
    """Like search_listings.searchActiveListings(), but also selects L_Remarks."""
    where = ["L_Status = 'Active'", "L_Remarks IS NOT NULL", "L_Remarks != ''"]
    params = []
    for key, (column, comparator, transform) in _FILTER_COLUMNS.items():
        value = filters.get(key)
        if value is None:
            continue
        where.append(f"{column} {comparator} %s")
        params.append(transform(value))

    query = f"""
        SELECT {_CANDIDATE_COLUMNS}
        FROM rets_property
        WHERE {' AND '.join(where)}
        ORDER BY L_SystemPrice ASC
        LIMIT %s
    """
    params.append(limit)

    with get_cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


def _hybrid_embed(query: str, remarks: list[str]):
    """
    Embed the query + candidate remarks together so they land in the same
    vector space. Tries OpenAI first; on any OpenAI error (quota, key,
    network) falls back to a TF-IDF vectorizer fit fresh on this batch --
    same graceful-degradation pattern as semantic_search.build_index(), but
    scoped per-call since recommend() ranks a fresh, filter-dependent
    candidate set each time rather than a static cached index.
    """
    texts = [query] + remarks
    try:
        vectors = embed_texts(texts)
        backend = _BACKEND_OPENAI
    except openai.OpenAIError as e:
        print(
            f"OpenAI embeddings unavailable ({e.__class__.__name__}); "
            "falling back to a local TF-IDF index for recommendation scoring.",
            file=sys.stderr,
        )
        vectorizer = TfidfVectorizer(max_features=1000, stop_words="english")
        vectors = vectorizer.fit_transform(texts).toarray().astype(np.float32)
        backend = _BACKEND_TFIDF
    return vectors[0:1], vectors[1:], backend


def validate_against_comps(listing: dict, months: int = 12) -> dict:
    """
    Compare a listing's price/sqft to recent sold comps in its own city.

    Returns compCount, medianPricePerSqft, valueRatio (listing $/sqft over
    comp median $/sqft), and a flag ("underpriced" / "fair" / "overpriced" /
    "no comps"). Median is computed by hand (sorted midpoint) since this is
    a small in-memory list, not a SQL aggregate -- see market_stats.py for
    the ROW_NUMBER() equivalent when doing this in SQL instead.
    """
    comps = getSoldComps(listing["city"], months=months, limit=50)
    priced = [c for c in comps if c["ClosePrice"] and c["LivingArea"]]

    if not priced or not listing.get("sqft"):
        return {"compCount": len(priced), "medianPricePerSqft": None, "valueRatio": None, "flag": "no comps"}

    comp_ppsf = sorted(float(c["ClosePrice"]) / c["LivingArea"] for c in priced)
    n = len(comp_ppsf)
    median_ppsf = comp_ppsf[n // 2] if n % 2 else (comp_ppsf[n // 2 - 1] + comp_ppsf[n // 2]) / 2

    listing_ppsf = float(listing["price"]) / listing["sqft"]
    value_ratio = listing_ppsf / median_ppsf

    if value_ratio <= _UNDERPRICED_MAX_RATIO:
        flag = "underpriced"
    elif value_ratio >= _OVERPRICED_MIN_RATIO:
        flag = "overpriced"
    else:
        flag = "fair"

    return {
        "compCount": len(priced),
        "medianPricePerSqft": round(median_ppsf, 2),
        "valueRatio": round(value_ratio, 3),
        "flag": flag,
    }


def _value_score(value_ratio: float | None) -> float:
    """Higher score for listings priced below comps; 0.5 (neutral) with no comps to judge against."""
    if value_ratio is None:
        return 0.5
    return float(np.clip(1.5 - value_ratio, 0.0, 1.0))


def recommend(query: str, top_k: int = 5, candidate_limit: int = 50, alpha: float = 0.6) -> list[dict]:
    """
    Parse `query` into hard filters, pull up to `candidate_limit` matching
    active listings, and rank them by a hybrid score:

        alpha * semantic fit to the query's remarks  +  (1 - alpha) * comp-relative value

    `candidate_limit` defaults to 50 (rather than semantic-search's 1,000)
    to bound OpenAI embedding cost -- recommend() embeds this batch fresh on
    every call instead of reading a prebuilt cache, since the candidate set
    depends on the query's own filters.
    """
    filters = parse_property_query(query)
    candidates = _search_with_remarks(filters, limit=candidate_limit)
    if not candidates:
        return []

    remarks = [c["remarks"] for c in candidates]
    query_vector, candidate_vectors, backend = _hybrid_embed(query, remarks)
    semantic_scores = cosine_similarity(query_vector, candidate_vectors)[0]

    lo, hi = semantic_scores.min(), semantic_scores.max()
    semantic_norm = (semantic_scores - lo) / (hi - lo) if hi > lo else np.ones_like(semantic_scores)

    results = []
    for candidate, sem_score, sem_norm in zip(candidates, semantic_scores, semantic_norm):
        comp = validate_against_comps(candidate)
        value_score = _value_score(comp["valueRatio"])
        hybrid_score = alpha * sem_norm + (1 - alpha) * value_score
        results.append({
            **candidate,
            "semanticScore": float(sem_score),
            "valueScore": value_score,
            "hybridScore": float(hybrid_score),
            "comp": comp,
            "backend": backend,
        })

    results.sort(key=lambda r: r["hybridScore"], reverse=True)
    return results[:top_k]


_FLAG_LABELS = {
    "underpriced": "priced below comps",
    "overpriced": "priced above comps",
    "fair": "priced in line with comps",
    "no comps": "no recent comps to compare",
}


def format_recommendation(row: dict) -> str:
    """Render a single recommend() row as a display-ready card."""
    price = f"${row['price']:,}" if row.get("price") else "price n/a"
    beds = row["beds"] if row.get("beds") is not None else "?"
    baths = row["baths"] if row.get("baths") is not None else "?"
    comp = row["comp"]
    comp_str = _FLAG_LABELS[comp["flag"]]
    if comp["valueRatio"] is not None:
        comp_str += f" ({comp['valueRatio']:.2f}x comp $/sqft)"
    remarks = row.get("remarks") or ""
    snippet = remarks[:160] + ("..." if len(remarks) > 160 else "")
    return (
        f"{row['address']}, {row['city']} — {price} ({row['hybridScore']:.3f} hybrid score)\n"
        f"{beds}bd/{baths}ba — {comp_str}\n"
        f"{snippet}"
    )
