import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from recommend import recommend, validate_against_comps, format_recommendation, _value_score


def check(label, condition):
    print(f"{'PASS' if condition else 'FAIL'}: {label}")
    return condition


results = []

# --- validate_against_comps ---
comp = validate_against_comps({"city": "Sacramento", "price": 500000, "sqft": 2000})
results.append(check("validate_against_comps returns a flag", comp["flag"] in ("underpriced", "fair", "overpriced", "no comps")))
results.append(check(
    "validate_against_comps returns None ratio only when flagged 'no comps'",
    (comp["valueRatio"] is None) == (comp["flag"] == "no comps"),
))

no_comps = validate_against_comps({"city": "Nowhereville", "price": 500000, "sqft": 2000})
results.append(check("validate_against_comps handles a city with no comps", no_comps["flag"] == "no comps"))
results.append(check("validate_against_comps with no comps has no median", no_comps["medianPricePerSqft"] is None))

# --- _value_score ---
results.append(check("_value_score is neutral (0.5) with no comps", _value_score(None) == 0.5))
results.append(check("_value_score rewards being priced below comps", _value_score(0.8) > _value_score(1.0)))
results.append(check("_value_score is bounded in [0, 1]", 0.0 <= _value_score(0.2) <= 1.0 and 0.0 <= _value_score(3.0) <= 1.0))

# --- recommend (hybrid scoring) ---
hits = recommend("homes in Sacramento with a view", top_k=5, candidate_limit=25)
results.append(check("recommend returns results", len(hits) > 0))
results.append(check("recommend respects top_k", len(hits) <= 5))
results.append(check(
    "results are sorted by descending hybrid score",
    all(a["hybridScore"] >= b["hybridScore"] for a, b in zip(hits, hits[1:])),
))
results.append(check(
    "each hit has the expected fields",
    all(
        "listingId" in hit and "semanticScore" in hit and "valueScore" in hit
        and "hybridScore" in hit and "comp" in hit
        for hit in hits
    ),
))
results.append(check("hybrid scores are bounded in [0, 1]", all(-0.0001 <= hit["hybridScore"] <= 1.0001 for hit in hits)))

empty = recommend("homes in Nowhereville", top_k=5, candidate_limit=25)
results.append(check("recommend returns no results for an unmatched query", empty == []))

# --- formatted card ---
card = format_recommendation(hits[0])
results.append(check("formatted card includes the address", hits[0]["address"] in card))
results.append(check("formatted card includes the hybrid score", "hybrid score)" in card))

print(f"\n{sum(results)}/{len(results)} tests passed")
