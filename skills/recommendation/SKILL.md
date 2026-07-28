# recommendation

Answers "find me something like this" and "is this a good deal" questions by
ranking listings with a hybrid score — semantic fit to the descriptive part
of the query, blended with how the listing prices against recent sold comps
in its own city — rather than either structured filters or similarity alone.

## When to use

Use this skill when the user's query mixes hard filters with descriptive
language, or when they're asking whether a listing is priced well — e.g.:
- "3 bed home in Sacramento with a modern kitchen and lots of natural light"
- "Find me a fixer-upper with potential under $500k in Oakland"
- "Is this place a good deal?"

For pure hard filters, prefer `property-search`; for pure descriptive
similarity with no comp check, `semantic-search` is cheaper (reads a
prebuilt cache instead of embedding fresh on every call).

## Week 7: Recommendations (hybrid scoring + comp validation)

```bash
cd /Users/lindsaylai/projects/idx-exchange
source venv/bin/activate
python -c "
import sys; sys.path.insert(0, 'skills/recommendation')
from recommend import recommend, format_recommendation

for hit in recommend('3 bed home in Sacramento with a modern kitchen and lots of natural light', top_k=5):
    print(format_recommendation(hit))
    print()
"
```

### Functions

- `recommend(query, top_k, candidate_limit, alpha)` — parses `query` into
  hard filters (`parse_property_query`), pulls up to `candidate_limit`
  matching active listings with remarks, embeds the query + candidate
  remarks together, and ranks by `alpha * semantic fit + (1 - alpha) *
  comp-relative value`. Defaults: `top_k=5`, `candidate_limit=50`,
  `alpha=0.6`.
- `validate_against_comps(listing, months)` — compares a listing's
  price/sqft to the median price/sqft of recent sold comps in its own city
  (`getSoldComps`). Returns `compCount`, `medianPricePerSqft`, `valueRatio`,
  and a `flag`: `"underpriced"` (≤0.93x), `"fair"`, `"overpriced"` (≥1.07x),
  or `"no comps"` when the city has no priced comps or the listing has no
  sqft to compare.
- `format_recommendation(row)` — renders a `recommend()` row as a
  display-ready card (address, price, hybrid score, comp flag + ratio,
  remarks snippet).

### Notes

- **Hybrid scoring, not a rerank of a fixed list:** the candidate pool
  itself comes from the query's own structured filters
  (`property-search.parse_property_query`), so a query with no filters
  ("something cozy") still returns something rather than nothing — it
  just draws from a broader, unfiltered candidate set.
- **Comp validation ties into the ranking, not just a display flag:** the
  "value" half of the hybrid score is exactly what `validate_against_comps`
  computes (`1.5 - valueRatio`, clamped to `[0, 1]`), so recommendations
  that undercut nearby sold comps get pulled toward the top, not just
  labeled after the fact.
- **Embeds fresh per call, not from the Week 6 cache:** `semantic-search`'s
  index is a static batch of up to 1,000 listings, but `recommend()`'s
  candidate set depends on the query's own filters and won't generally
  overlap it — so the query and its candidates' remarks are embedded
  together on every call. `candidate_limit` defaults to 50 (vs.
  semantic-search's 1,000) specifically to bound that per-call embedding
  cost.
- **Same TF-IDF fallback as Week 6:** if the OpenAI embeddings call fails
  (quota, key, network), falls back to a `TfidfVectorizer` fit fresh on the
  query + this call's candidate remarks. Since it's fit per-call rather
  than cached, there's no stale-vectorizer file to clean up — unlike
  `semantic-search.build_index()`.
- Reuses `property-search`'s `_FILTER_COLUMNS` map, `getSoldComps()`, and
  `parse_property_query()`, and `semantic-search`'s `embed_texts()`, rather
  than duplicating any of them.
- Median price/sqft is computed by hand (sorted-list midpoint) since the
  comp set here is a small in-memory list from `getSoldComps()`, not a SQL
  aggregate — see `market_stats.py` for the `ROW_NUMBER()` equivalent when
  doing this in SQL instead.
- The ±7% underpriced/overpriced band is a judgment call, not derived from
  the data — tune `_UNDERPRICED_MAX_RATIO` / `_OVERPRICED_MIN_RATIO` in
  `recommend.py` if it flags too aggressively or not enough in practice.

Tests: `python skills/recommendation/test_recommend.py` (runs against the
local `idx_exchange` MySQL database; exercises both the OpenAI and TF-IDF
fallback embedding paths, and a comp-validation case with no comps).
