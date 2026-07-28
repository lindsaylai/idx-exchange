import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from recommend import (
    calculate_similarity_score,
    validate_with_comps,
    find_similar_listings,
    format_similar_listing,
)

# A real active Sacramento listing with remarks, looked up directly for this test.
SACRAMENTO_LISTING_ID = 1018767064


def check(label, condition):
    print(f"{'PASS' if condition else 'FAIL'}: {label}")
    return condition


results = []

# --- calculate_similarity_score ---
target = {"price": 500000, "beds": 3, "city": "Sacramento", "sqft": 1800}
identical = {"price": 500000, "beds": 3, "city": "Sacramento", "sqft": 1800}
distant = {"price": 900000, "beds": 5, "city": "Fresno", "sqft": 4000}
same_emb = [1.0, 0.0, 0.0]
diff_emb = [0.0, 1.0, 0.0]

score_identical = calculate_similarity_score(target, identical, same_emb, same_emb)
score_distant = calculate_similarity_score(target, distant, same_emb, diff_emb)
results.append(check("identical structured attrs + identical embedding scores near 100", score_identical > 95))
results.append(check("distant listing scores much lower", score_distant < score_identical))
results.append(check("score is bounded in [0, 100]", 0.0 <= score_identical <= 100.0 and 0.0 <= score_distant <= 100.0))

no_sqft_target = {"price": 500000, "beds": 3, "city": "Sacramento", "sqft": None}
no_sqft_candidate = {"price": 500000, "beds": 3, "city": "Sacramento", "sqft": None}
results.append(check(
    "missing sqft on either side doesn't crash and doesn't award sqft points",
    calculate_similarity_score(no_sqft_target, no_sqft_candidate, same_emb, same_emb) <= 90,
))

# --- validate_with_comps ---
comp = validate_with_comps("Sacramento", 1800, 500000)
results.append(check("validate_with_comps returns a flag", comp["flag"] in ("underpriced", "fair", "overpriced", "no comps")))
results.append(check(
    "validate_with_comps returns None delta only when flagged 'no comps'",
    (comp["delta_pct"] is None) == (comp["flag"] == "no comps"),
))
results.append(check("validate_with_comps echoes the list price back", comp["list_price"] == 500000))

no_comps = validate_with_comps("Nowhereville", 1800, 500000)
results.append(check("validate_with_comps handles a city with no comps", no_comps["flag"] == "no comps"))
results.append(check("validate_with_comps with no comps has no comp_price", no_comps["comp_price"] == 0))

# --- find_similar_listings ---
hits = find_similar_listings(SACRAMENTO_LISTING_ID, top_k=5, candidate_limit=25)
results.append(check("find_similar_listings returns results", len(hits) > 0))
results.append(check("find_similar_listings respects top_k", len(hits) <= 5))
results.append(check(
    "results are sorted by descending similarity score",
    all(a["similarityScore"] >= b["similarityScore"] for a, b in zip(hits, hits[1:])),
))
results.append(check(
    "each hit has the expected fields",
    all("listingId" in hit and "similarityScore" in hit and "comp" in hit for hit in hits),
))
results.append(check(
    "the target listing itself is never returned as a match",
    all(hit["listingId"] != SACRAMENTO_LISTING_ID for hit in hits),
))

try:
    find_similar_listings(999999999999, top_k=5)
    results.append(check("find_similar_listings raises for an unknown listing id", False))
except ValueError:
    results.append(check("find_similar_listings raises for an unknown listing id", True))

# --- formatted card ---
card = format_similar_listing(hits[0])
results.append(check("formatted card includes the address", hits[0]["address"] in card))
results.append(check("formatted card includes the similarity score", "similarity)" in card))

print(f"\n{sum(results)}/{len(results)} tests passed")
