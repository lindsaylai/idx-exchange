"""
Week 6: Embeddings & Vector Search.

Builds a local vector index over rets_property.L_Remarks with OpenAI's
text-embedding-3-small, then answers free-text "find me something like..."
queries via cosine similarity. No external vector DB -- just numpy + scikit-learn
over a cached index file. Reuses the connection pool from the property-search
skill rather than opening a second one.

Falls back to a local TF-IDF vectorizer (fit at index-build time) whenever the
OpenAI embeddings call fails for any reason -- missing/invalid key, no quota,
no network -- so the pipeline stays testable and usable offline. The index
cache records which backend produced it so a query embeds with the matching
one.
"""

import json
import os
import pickle
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "property-search"))

import numpy as np
import openai
from openai import OpenAI
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from db import get_cursor, _load_dotenv, _ENV_PATH

_load_dotenv(_ENV_PATH)

_EMBEDDING_MODEL = "text-embedding-3-small"
_BACKEND_OPENAI = "openai"
_BACKEND_TFIDF = "tfidf"

_INDEX_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
_VECTORS_PATH = os.path.join(_INDEX_DIR, "listing_embeddings.npy")
_META_PATH = os.path.join(_INDEX_DIR, "listing_embeddings_meta.json")
_VECTORIZER_PATH = os.path.join(_INDEX_DIR, "listing_embeddings_vectorizer.pkl")

_CLIENT = None


def _get_client() -> OpenAI:
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    return _CLIENT


def embed_texts(texts: list[str], batch_size: int = 100) -> np.ndarray:
    """Embed a list of texts with text-embedding-3-small, chunked into batches."""
    vectors = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        response = _get_client().embeddings.create(model=_EMBEDDING_MODEL, input=batch)
        vectors.extend(item.embedding for item in response.data)
    return np.array(vectors, dtype=np.float32)


_LISTINGS_QUERY = """
    SELECT L_ListingID, L_Address, L_City, L_SystemPrice,
           L_Keyword2 AS beds, LM_Dec_3 AS baths, L_Remarks
    FROM rets_property
    WHERE L_Status = 'Active'
      AND L_Remarks IS NOT NULL
      AND L_Remarks != ''
    ORDER BY L_ListingID
    LIMIT %s
"""


def build_index(
    limit: int = 1000,
    vectors_path: str = _VECTORS_PATH,
    meta_path: str = _META_PATH,
    vectorizer_path: str = _VECTORIZER_PATH,
) -> int:
    """
    Pull `limit` active listings with remarks, embed L_Remarks, and cache the
    resulting vectors + metadata to disk. Scoped to `limit` (default 1,000 of
    ~53K active listings) to keep embedding cost/time bounded for local dev --
    re-run with a larger limit for a fuller index. Returns the row count indexed.

    Tries OpenAI embeddings first; if that call fails for any reason (no
    quota, bad/missing key, no network), falls back to a TF-IDF vectorizer
    fit on this batch of remarks, and persists the fitted vectorizer so
    semantic_search() can embed queries the same way.
    """
    with get_cursor() as cursor:
        cursor.execute(_LISTINGS_QUERY, (limit,))
        rows = cursor.fetchall()

    if not rows:
        return 0

    remarks = [row["L_Remarks"] for row in rows]
    vectorizer = None
    try:
        matrix = embed_texts(remarks)
        backend = _BACKEND_OPENAI
    except openai.OpenAIError as e:
        print(
            f"OpenAI embeddings unavailable ({e.__class__.__name__}); "
            "falling back to a local TF-IDF index.",
            file=sys.stderr,
        )
        vectorizer = TfidfVectorizer(max_features=2000, stop_words="english")
        matrix = vectorizer.fit_transform(remarks).toarray().astype(np.float32)
        backend = _BACKEND_TFIDF

    os.makedirs(os.path.dirname(vectors_path), exist_ok=True)
    np.save(vectors_path, matrix)

    if vectorizer is not None:
        with open(vectorizer_path, "wb") as f:
            pickle.dump(vectorizer, f)
    elif os.path.exists(vectorizer_path):
        os.remove(vectorizer_path)  # stale fallback artifact from a prior build

    meta = {
        "backend": backend,
        "rows": [
            {
                "listingId": row["L_ListingID"],
                "address": row["L_Address"],
                "city": row["L_City"],
                "price": row["L_SystemPrice"],
                "beds": row["beds"],
                "baths": row["baths"],
                "remarks": row["L_Remarks"],
            }
            for row in rows
        ],
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, default=lambda v: float(v) if isinstance(v, Decimal) else str(v))

    return len(rows)


def _load_index(vectors_path: str, meta_path: str, vectorizer_path: str):
    if not os.path.exists(vectors_path) or not os.path.exists(meta_path):
        raise FileNotFoundError(
            f"No embedding index at {vectors_path} -- run build_index() first."
        )
    matrix = np.load(vectors_path)
    with open(meta_path) as f:
        meta = json.load(f)

    vectorizer = None
    if meta["backend"] == _BACKEND_TFIDF:
        with open(vectorizer_path, "rb") as f:
            vectorizer = pickle.load(f)

    return matrix, meta["rows"], meta["backend"], vectorizer


def semantic_search(
    query: str,
    top_k: int = 5,
    vectors_path: str = _VECTORS_PATH,
    meta_path: str = _META_PATH,
    vectorizer_path: str = _VECTORIZER_PATH,
) -> list[dict]:
    """Embed `query` and return the top_k most similar indexed listings by cosine similarity."""
    matrix, rows, backend, vectorizer = _load_index(vectors_path, meta_path, vectorizer_path)
    if backend == _BACKEND_TFIDF:
        query_vector = vectorizer.transform([query]).toarray().astype(np.float32)
    else:
        query_vector = embed_texts([query])

    scores = cosine_similarity(query_vector, matrix)[0]
    top_indices = np.argsort(scores)[::-1][:top_k]
    return [{**rows[i], "score": float(scores[i])} for i in top_indices]


def format_semantic_result(row: dict) -> str:
    """Render a single semantic_search() row as a display-ready card."""
    price = f"${row['price']:,}" if row.get("price") else "price n/a"
    beds = row["beds"] if row.get("beds") is not None else "?"
    baths = row["baths"] if row.get("baths") is not None else "?"
    remarks = row["remarks"]
    snippet = remarks[:160] + ("..." if len(remarks) > 160 else "")
    return (
        f"{row['address']}, {row['city']} — {price} ({row['score']:.3f} match)\n"
        f"{beds}bd/{baths}ba — {snippet}"
    )
