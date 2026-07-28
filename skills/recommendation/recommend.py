"""
Week 7: Recommendations.

Per the intern handbook's Week 7 deliverable: a recommendation skill that
surfaces the top-5 similar active listings to a given listing, each with a
comp-validated price assessment sourced from california_sold.

Similarity is a hybrid of structured attribute closeness to the target
listing (60%: price, beds, city, sqft) and semantic closeness of L_Remarks
(40%: cosine similarity of embeddings). Comp validation checks a listing's
price against the average $/sqft of recent, size-comparable sold comps in
its own city.

Reuses the property-search connection pool and the semantic-search
embed_texts() helper, rather than duplicating either.
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
from semantic_search import embed_texts

_BACKEND_OPENAI = "openai"
_BACKEND_TFIDF = "tfidf"

_LISTING_COLUMNS = """
    L_ListingID AS listingId, L_Address AS address, L_City AS city,
    L_SystemPrice AS price, L_Keyword2 AS beds, LM_Dec_3 AS baths,
    LM_Int2_3 AS sqft, L_Remarks AS remarks
"""

# delta_pct outside +/-7% of the comp price reads as a real signal rather
# than noise -- same band as market-stats' list-to-close spread.
_UNDERPRICED_MAX_DELTA = -7.0
_OVERPRICED_MIN_DELTA = 7.0


def _get_active_listing(listing_id) -> dict | None:
    query = f"""
        SELECT {_LISTING_COLUMNS}
        FROM rets_property
        WHERE L_ListingID = %s AND L_Status = 'Active'
    """
    with get_cursor() as cursor:
        cursor.execute(query, (listing_id,))
        return cursor.fetchone()


def _get_candidate_listings(target: dict, limit: int) -> list[dict]:
    """
    Other active listings with remarks, closest to the target by price.
    Pre-filtering to the `limit` closest by price bounds embedding cost for
    calculate_similarity_score() below, without ruling out same-city/same-bed
    matches the way a hard filter would.
    """
    query = f"""
        SELECT {_LISTING_COLUMNS}
        FROM rets_property
        WHERE L_Status = 'Active'
          AND L_ListingID != %s
          AND L_Remarks IS NOT NULL
          AND L_Remarks != ''
        ORDER BY ABS(L_SystemPrice - %s) ASC
        LIMIT %s
    """
    with get_cursor() as cursor:
        cursor.execute(query, (target["listingId"], target["price"], limit))
        return cursor.fetchall()


def _embed_batch(target_text: str, candidate_texts: list[str]):
    """
    Embed the target's remarks + each candidate's remarks together so they
    land in the same vector space. Tries OpenAI first; on any OpenAI error
    (quota, key, network) falls back to a TF-IDF vectorizer fit fresh on
    this batch -- same graceful-degradation pattern as
    semantic_search.build_index(), but scoped per-call since the candidate
    set here is query-dependent rather than a static cached index.
    """
    texts = [target_text] + candidate_texts
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
    return vectors[0], vectors[1:], backend


def calculate_similarity_score(
    target: dict,
    candidate: dict,
    target_emb,
    candidate_emb,
) -> float:
    """
    Hybrid similarity score out of 100: structured attribute closeness to
    `target` (60 pts: price, beds, city, sqft) plus semantic closeness of
    L_Remarks (40 pts: cosine similarity of the two embeddings).
    """
    score = 0.0

    price_diff = abs(target["price"] - candidate["price"])
    if price_diff < 50_000:
        score += 20
    elif price_diff < 150_000:
        score += 12
    elif price_diff < 300_000:
        score += 5

    if target.get("beds") is not None and target["beds"] == candidate.get("beds"):
        score += 15

    if target.get("city") and target["city"] == candidate.get("city"):
        score += 15

    if target.get("sqft") and candidate.get("sqft"):
        sqft_diff = abs(target["sqft"] - candidate["sqft"])
        if sqft_diff < 300:
            score += 10
        elif sqft_diff < 700:
            score += 5

    sem_sim = cosine_similarity(
        np.array(target_emb).reshape(1, -1),
        np.array(candidate_emb).reshape(1, -1),
    )[0][0]
    score += sem_sim * 40

    return round(score, 2)


# california_sold has a handful of rows with corrupted, far-future CloseDate
# values (see search_listings.getSoldComps / market_stats) that would
# otherwise skew "recent" -- anchor the window to CURDATE(), not just a
# lower bound.
_COMP_QUERY = """
    SELECT
        AVG(ClosePrice / NULLIF(LivingArea, 0)) AS avg_ppsf,
        COUNT(*) AS comp_count
    FROM california_sold
    WHERE City = %s AND PropertyType = 'Residential'
      AND LivingArea BETWEEN %s AND %s
      AND CloseDate >= DATE_SUB(CURDATE(), INTERVAL 6 MONTH)
      AND CloseDate <= CURDATE()
"""


def validate_with_comps(city: str, sqft: int, price: int) -> dict:
    """
    Check a listing's price against recent, size-comparable sold comps
    (+/-20% living area) in the same city: average $/sqft over those comps,
    scaled by `sqft` to get a comp price, and `delta_pct` = how far `price`
    sits above/below it.
    """
    with get_cursor() as cursor:
        cursor.execute(_COMP_QUERY, (city, sqft * 0.8, sqft * 1.2))
        result = cursor.fetchone()

    avg_ppsf = float(result["avg_ppsf"]) if result["avg_ppsf"] else 0
    comp_price = avg_ppsf * sqft
    comp_count = result["comp_count"]
    delta_pct = round((price - comp_price) / comp_price * 100, 1) if comp_price else None

    if delta_pct is None:
        flag = "no comps"
    elif delta_pct <= _UNDERPRICED_MAX_DELTA:
        flag = "underpriced"
    elif delta_pct >= _OVERPRICED_MIN_DELTA:
        flag = "overpriced"
    else:
        flag = "fair"

    return {
        "comp_price": round(comp_price),
        "list_price": price,
        "comp_count": comp_count,
        "delta_pct": delta_pct,
        "flag": flag,
    }


def find_similar_listings(listing_id, top_k: int = 5, candidate_limit: int = 50) -> list[dict]:
    """
    Find the top_k active listings most similar to `listing_id`, each with a
    comp-validated price assessment. Raises ValueError if `listing_id` isn't
    an active listing.
    """
    target = _get_active_listing(listing_id)
    if target is None:
        raise ValueError(f"No active listing found for id {listing_id}")

    candidates = _get_candidate_listings(target, limit=candidate_limit)
    if not candidates:
        return []

    target_emb, candidate_embs, backend = _embed_batch(
        target["remarks"], [c["remarks"] for c in candidates]
    )

    results = []
    for candidate, candidate_emb in zip(candidates, candidate_embs):
        similarity_score = calculate_similarity_score(target, candidate, target_emb, candidate_emb)
        comp = validate_with_comps(candidate["city"], candidate["sqft"], candidate["price"]) if candidate.get("sqft") else {
            "comp_price": None, "list_price": candidate["price"], "comp_count": 0, "delta_pct": None, "flag": "no comps",
        }
        results.append({**candidate, "similarityScore": similarity_score, "comp": comp, "backend": backend})

    results.sort(key=lambda r: r["similarityScore"], reverse=True)
    return results[:top_k]


_FLAG_LABELS = {
    "underpriced": "priced below comps",
    "overpriced": "priced above comps",
    "fair": "priced in line with comps",
    "no comps": "no recent comps to compare",
}


def format_similar_listing(row: dict) -> str:
    """Render a single find_similar_listings() row as a display-ready card."""
    price = f"${row['price']:,}" if row.get("price") else "price n/a"
    beds = row["beds"] if row.get("beds") is not None else "?"
    baths = row["baths"] if row.get("baths") is not None else "?"
    comp = row["comp"]
    comp_str = _FLAG_LABELS[comp["flag"]]
    if comp["delta_pct"] is not None:
        comp_str += f" ({comp['delta_pct']:+.1f}% vs. comp price ${comp['comp_price']:,})"
    remarks = row.get("remarks") or ""
    snippet = remarks[:160] + ("..." if len(remarks) > 160 else "")
    return (
        f"{row['address']}, {row['city']} — {price} ({row['similarityScore']:.1f}/100 similarity)\n"
        f"{beds}bd/{baths}ba — {comp_str}\n"
        f"{snippet}"
    )
