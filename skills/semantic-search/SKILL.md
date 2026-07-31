---
name: semantic-search
description: Semantic similarity search over active MLS listings via a local sentence-transformers model (TF-IDF fallback) for fuzzy, descriptive property queries beyond structured filters.
metadata:
  {
    "openclaw":
      {
        "requires":
          {
            "bins": ["python3"],
            "env": ["MYSQL_HOST", "MYSQL_USER", "MYSQL_DATABASE"],
          },
      },
  }
---

# semantic-search

Answers fuzzy, descriptive queries ("something cozy with mountain views", "a
fixer-upper with potential") by embedding each listing's type, city,
beds/baths, sqft, year built, and price alongside `rets_property.L_Remarks`,
then ranking listings by cosine similarity, instead of matching on structured
filters alone.

## When to use

Use this skill when the user describes a *feel* or set of qualities rather
than hard filters — e.g.:
- "Find me something with a modern kitchen and lots of natural light"
- "Show me quiet properties away from the road"
- "I want a fixer-upper with potential in the hills"

For hard filters (city, price, beds, baths) prefer `property-search`; the two
are combined via hybrid scoring in `recommendation` (Week 7).

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

- `embed_texts(texts, batch_size)` — embeds a list of strings locally with
  `sentence-transformers`' `all-MiniLM-L6-v2`, batched via the model's own
  `batch_size` param (no API call involved).
- `build_index(limit, vectors_path, meta_path)` — pulls `limit` active
  listings with non-empty `L_Remarks`, embeds a combined
  type/city/beds/baths/sqft/year/price/remarks string per listing (see
  `_listing_embedding_text()`), and caches the vectors (`.npy`) + metadata
  (`.json`) to `data/`. Returns the row count indexed.
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
- Embeddings run on a local `sentence-transformers` model rather than a
  hosted API (OpenAI and Gemini were both tried here first — see git
  history) — no API key, no network dependency after the first model
  download, no rate limit, no cost. The model lazy-loads on first call via
  `_get_model()` and is cached in-process; the underlying weights are
  cached on disk by `sentence-transformers`/HuggingFace Hub the first time
  any process on the machine loads them (see the README's prefetch step).
- **TF-IDF fallback:** if the local model can't be loaded for any reason
  (no cached weights and no network on a first-ever run, disk/memory
  issue — rare in practice), `build_index()` catches the failure broadly,
  fits a `scikit-learn` `TfidfVectorizer` on the same batch of remarks
  instead, and persists the fitted vectorizer
  (`listing_embeddings_vectorizer.pkl`) next to the cache. `meta.json`
  records which backend (`"sentence-transformers"` or `"tfidf"`) produced
  the index, so `semantic_search()` embeds the query the same way.
- **`semantic_search()` can also fail on a *query*,** even when the index
  itself built successfully — a different failure mode than
  `build_index()`'s, since a TF-IDF query vector isn't comparable to a
  sentence-transformers-embedded corpus matrix (different vector space
  entirely). Rather than silently producing a meaningless comparison,
  `semantic_search()` raises a clear `RuntimeError` in this case — re-run
  `build_index()` to force the TF-IDF backend for both the corpus and
  future queries.

Tests: `python skills/semantic-search/test_semantic_search.py` (builds a
small 30-listing index in a temp directory; runs against MySQL and the
local embedding model, no network dependency beyond the one-time model
download).
