# semantic-search

Answers fuzzy, descriptive queries ("something cozy with mountain views", "a
fixer-upper with potential") by embedding `rets_property.L_Remarks` and
ranking listings by cosine similarity, instead of matching on structured
filters alone.

## When to use

Use this skill when the user describes a *feel* or set of qualities rather
than hard filters — e.g.:
- "Find me something with a modern kitchen and lots of natural light"
- "Show me quiet properties away from the road"
- "I want a fixer-upper with potential in the hills"

For hard filters (city, price, beds, baths) prefer `property-search`; the two
can be combined later (Week 7 hybrid scoring).

## Week 6: Embeddings & Vector Search

```bash
cd /Users/lindsaylai/projects/idx-exchange
source venv/bin/activate
python -c "
import sys; sys.path.insert(0, 'skills/semantic-search')
from semantic_search import build_index, semantic_search, format_semantic_result

build_index(limit=1000)  # one-time (or periodic) local cache build

for hit in semantic_search('cozy mountain cabin with a view', top_k=5):
    print(format_semantic_result(hit))
    print()
"
```

### Functions

- `embed_texts(texts, batch_size)` — embeds a list of strings with OpenAI
  `text-embedding-3-small`, chunked into batches of `batch_size`.
- `build_index(limit, vectors_path, meta_path)` — pulls `limit` active
  listings with non-empty `L_Remarks`, embeds the remarks, and caches the
  vectors (`.npy`) + metadata (`.json`) to `data/`. Returns the row count
  indexed.
- `semantic_search(query, top_k, vectors_path, meta_path)` — embeds `query`
  and returns the `top_k` most similar cached listings, ranked by cosine
  similarity (`scikit-learn`'s `cosine_similarity`), each tagged with `score`.
- `format_semantic_result(row)` — renders a `semantic_search()` row as a
  display-ready card (address, price, beds/baths, match score, remarks
  snippet).

### Notes

- No external vector database — the index is just a cached `numpy` matrix
  plus a JSON metadata list, searched with `scikit-learn` cosine similarity.
  That's enough for a few thousand listings; revisit (e.g. FAISS, a MySQL
  vector column) if the indexed set grows much larger.
- `build_index()` defaults to `limit=1000` (of ~53K active listings with
  remarks) to keep embedding cost and local-dev runtime bounded — re-run with
  a larger `limit` for fuller coverage. The cache lives under `data/`, which
  is gitignored, same as the SQL dumps — each machine builds its own.
- Reuses the connection pool from `property-search/db.py` rather than opening
  a second one — `semantic_search.py` adds `../property-search` to
  `sys.path` itself, same pattern as `market-stats`.
- Embeddings use `text-embedding-3-small` per the project's tech stack; the
  OpenAI client reads `OPENAI_API_KEY` from `.env` via the same
  `_load_dotenv()` helper `db.py` and `market_stats.py` use.
- **TF-IDF fallback:** if the OpenAI embeddings call fails for any reason
  (the dev account currently has `insufficient_quota` — 429 — but this also
  covers a missing key or no network), `build_index()` catches
  `openai.OpenAIError`, fits a `scikit-learn` `TfidfVectorizer` on the same
  batch of remarks instead, and persists the fitted vectorizer
  (`listing_embeddings_vectorizer.pkl`) next to the cache. `meta.json`
  records which backend (`"openai"` or `"tfidf"`) produced the index, so
  `semantic_search()` embeds the query the same way. Once billing/quota is
  fixed, delete the `data/listing_embeddings*` cache files and re-run
  `build_index()` to pick OpenAI embeddings back up automatically — no code
  changes needed.

Tests: `python skills/semantic-search/test_semantic_search.py` (builds a
small 30-listing index in a temp directory; runs against MySQL and — quota
permitting — the live OpenAI API, otherwise the TF-IDF fallback kicks in
automatically).
