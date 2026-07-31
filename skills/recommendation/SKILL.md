---
name: recommendation
description: Given an active MLS listing, surface the top similar listings (hybrid structured + semantic scoring) each with a comp-validated price assessment.
metadata:
  {
    "openclaw":
      {
        "requires":
          {
            "bins": ["python3"],
            "env": ["MYSQL_HOST", "MYSQL_USER", "MYSQL_DATABASE", "GEMINI_API_KEY"],
          },
      },
  }
---

# recommendation

Answers "find me something like this listing" and "is this priced fairly"
questions: given an active listing, surfaces the top 5 most similar active
listings — hybrid-scored on structured attribute closeness and semantic
closeness of remarks — each with a comp-validated price assessment against
recent sold comps in `california_sold`.

## When to use

Use this skill when the user has a specific listing in hand and wants more
like it, or wants a price sanity check — e.g.:
- "Show me listings similar to this one"
- "Find comparable homes to 4200 Amble Court"
- "Is this listing priced fairly?"

For a fresh free-text search (no starting listing), prefer `property-search`
or `semantic-search` instead.

## Week 7: Recommendations (hybrid scoring + comp validation)

```bash
cd /Users/lindsaylai/projects/idx-exchange
source venv/bin/activate
python -c "
import sys; sys.path.insert(0, 'skills/recommendation')
from recommend import find_similar_listings, format_similar_listing

for hit in find_similar_listings(1018767064, top_k=5):
    print(format_similar_listing(hit))
    print()
"
```

### Functions

- `find_similar_listings(listing_id, top_k, candidate_limit)` — looks up the
  active listing at `listing_id`, pulls up to `candidate_limit` other active
  listings closest to it by price (to bound embedding cost), scores each
  with `calculate_similarity_score`, attaches a `validate_with_comps`
  assessment, and returns the top `top_k` by score. Defaults: `top_k=5`,
  `candidate_limit=50`. Raises `ValueError` if `listing_id` isn't an active
  listing.
- `calculate_similarity_score(target, candidate, target_emb, candidate_emb)`
  — hybrid score out of 100: **60 structured** (price diff <$50k/$150k/$300k
  → 20/12/5 pts, same beds → 15, same city → 15, sqft diff <300/700 → 10/5)
  **+ 40 semantic** (cosine similarity of the two remarks embeddings × 40).
- `validate_with_comps(city, sqft, price)` — averages `$/sqft` over sold
  comps in `city` from the trailing 6 months with living area within ±20%
  of `sqft`, scales by `sqft` to get a `comp_price`, and returns `delta_pct`
  (how far `price` sits above/below it) plus a `flag`: `"underpriced"`
  (≤‑7%), `"fair"`, `"overpriced"` (≥+7%), or `"no comps"`.
- `format_similar_listing(row)` — renders a `find_similar_listings()` row as
  a display-ready card (address, price, similarity score, comp flag +
  delta, remarks snippet).

### Notes

- **Candidate pool is price-proximity-bounded, not city/bed-filtered:**
  `find_similar_listings` pulls the `candidate_limit` active listings
  closest to the target by price (any city, any bed count), then lets
  `calculate_similarity_score`'s city/bed terms differentiate within that
  set. A hard filter on city or beds would make those terms constant and
  redundant.
- **Embeds fresh per call, not from the Week 6 cache:** the candidate set
  depends on the target listing, so the target's + each candidate's remarks
  are embedded together on every call rather than read from
  `semantic-search`'s static index. `candidate_limit` defaults to 50 (vs.
  semantic-search's 1,000) specifically to bound that per-call embedding
  cost.
- **Same TF-IDF fallback as Week 6:** if the Gemini embeddings call fails
  (free-tier quota, key, network), falls back to a `TfidfVectorizer` fit
  fresh on the target + this call's candidate remarks.
- `validate_with_comps` anchors its 6-month window to `CURDATE()` on both
  ends, not just a lower bound — same reason as `search_listings.getSoldComps`
  and `market_stats.py`: a few `california_sold` rows have corrupted,
  far-future `CloseDate` values that would otherwise skew the window.
- The ±20% living-area band and ±7% under/overpriced thresholds are judgment
  calls, not derived from the data — tune the constants in `recommend.py` if
  they flag too aggressively or not enough in practice.
- Reuses `property-search`'s `db.get_cursor()` and `semantic-search`'s
  `embed_texts()` rather than duplicating either.

Tests: `python skills/recommendation/test_recommend.py` (runs against the
local `idx_exchange` MySQL database; exercises the scoring math directly,
a comp-validation case with no comps, and the TF-IDF fallback embedding
path).
