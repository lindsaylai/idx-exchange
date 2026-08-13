"""
Week 8: Retrieval-Augmented Generation (RAG).

A document-aware knowledge assistant that answers conceptual/definitional
questions (MLS field meanings, real estate terminology, CA disclosure
requirements) by retrieving relevant chunks from docs/knowledge/ -- plus,
optionally, a live market snapshot from Week 5's market-stats agent -- and
grounding an answer in that retrieved context, instead of answering from the
model's own (unverified) knowledge.

Same index-to-disk / embed-with-fallback shape as semantic-search's listing
index: chunks are embedded with a local sentence-transformers model
(all-MiniLM-L6-v2), falling back to a local TF-IDF vectorizer if that
fails for any reason.

Answer generation uses Gemini (`gemini-2.5-flash`) -- it's the LLM this
project's architecture already designates for orchestration (see
docs/architecture.md), and it has a free tier, so this skill's one hosted
API dependency is on a free provider. Same degrade-gracefully principle as
everywhere else: if the Gemini call fails for any reason, fall back to
returning the top retrieved chunk verbatim (clearly labeled) rather than
failing outright.
"""

import json
import os
import pickle
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "property-search"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "semantic-search"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "market-stats"))

import numpy as np
from google import genai
from google.genai import errors as genai_errors
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from db import _load_dotenv, _ENV_PATH
from semantic_search import embed_texts
from market_stats import format_market_summary

_load_dotenv(_ENV_PATH)

_GEMINI_MODEL = "gemini-2.5-flash"
_BACKEND_TFIDF = "tfidf"
_BACKEND_LOCAL = "sentence-transformers"
_BACKEND_GEMINI = "gemini"
_BACKEND_EXTRACTIVE = "extractive"

_DOCS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "knowledge")
_INDEX_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
_VECTORS_PATH = os.path.join(_INDEX_DIR, "rag_index.npy")
_META_PATH = os.path.join(_INDEX_DIR, "rag_index_meta.json")
_VECTORIZER_PATH = os.path.join(_INDEX_DIR, "rag_index_vectorizer.pkl")

_GEMINI_CLIENT = None


def _get_gemini_client() -> genai.Client:
    global _GEMINI_CLIENT
    if _GEMINI_CLIENT is None:
        _GEMINI_CLIENT = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
    return _GEMINI_CLIENT


def chunk_text(text: str, chunk_size: int = 600, overlap: int = 100) -> list[str]:
    """
    Split `text` into overlapping, whitespace-trimmed chunks of up to
    chunk_size chars. Both ends of every chunk snap to the nearest newline
    (or, failing that, space), so a chunk never starts or ends mid-word --
    or mid markdown-table-row like `| \\`ClosePrice\\` | ...` -- and no
    trailing overlap-only fragment gets emitted once the text is exhausted.
    """
    chunks, start, n = [], 0, len(text)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            boundary = text.rfind("\n", start, end)
            if boundary <= start:
                boundary = text.rfind(" ", start, end)
            if boundary > start:
                end = boundary
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break

        next_start = end - overlap
        if next_start <= start:
            next_start = end
        else:
            # snap forward to just past the next newline/space so the next
            # chunk doesn't itself start mid-word
            space_pos = text.find(" ", next_start, end)
            newline_pos = text.find("\n", next_start, end)
            candidates = [p for p in (space_pos, newline_pos) if p != -1]
            if candidates:
                next_start = min(candidates) + 1
        start = next_start
    return chunks


def load_source_documents(docs_dir: str = _DOCS_DIR) -> list[dict]:
    """Read every .md file in docs_dir as a {"title", "content"} document."""
    docs = []
    for filename in sorted(os.listdir(docs_dir)):
        if not filename.endswith(".md"):
            continue
        with open(os.path.join(docs_dir, filename)) as f:
            content = f.read()
        title = filename[: -len(".md")].replace("_", " ").title()
        docs.append({"title": title, "content": content})
    return docs


def market_report_document(city: str, months: int = 12) -> dict:
    """
    A live market snapshot for `city`, sourced from Week 5's market-stats
    agent rather than a static file -- the handbook lists "market reports
    sourced via the market analytics agent" as a Week 8 knowledge source.
    """
    return {
        "title": f"Market Report: {city}",
        "content": format_market_summary(city, months=months),
    }


def _split_into_sections(text: str) -> list[str]:
    """
    Split markdown text on '## ' headers, keeping each header with the
    content that follows it as one section. Two unrelated sections (e.g.
    the rets_property and california_sold tables in the same doc) should
    never end up sharing a chunk -- splitting first keeps chunk_text()'s
    boundary search confined to one section at a time.
    """
    parts = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    return [p for p in parts if p.strip()]


_SECTION_HEADER_RE = re.compile(r"^(## .+)$", re.MULTILINE)


def index_documents(docs: list[dict], chunk_size: int = 600, overlap: int = 100) -> list[dict]:
    """
    Chunk every doc's content into {"source", "chunk"} entries tagged with
    their doc title. Every chunk past the first one in a section is
    prefixed with that section's "## " header -- e.g. a data-row chunk deep
    in the california_sold table otherwise never repeats the words
    "california_sold" or "Sold Transactions" (that context only lives in
    the header line, which lands in an earlier chunk), so a query naming
    the table would score that chunk no better than an unrelated one. Every
    chunk needs to carry its own context, not just inherit it positionally.
    """
    indexed = []
    for doc in docs:
        for section in _split_into_sections(doc["content"]):
            header_match = _SECTION_HEADER_RE.match(section)
            header = header_match.group(1) if header_match else None
            for i, chunk in enumerate(chunk_text(section, chunk_size=chunk_size, overlap=overlap)):
                if header and i > 0 and not chunk.startswith(header):
                    chunk = f"{header}\n\n{chunk}"
                indexed.append({"source": doc["title"], "chunk": chunk})
    return indexed


def build_index(
    docs_dir: str = _DOCS_DIR,
    market_cities: list[str] | None = None,
    months: int = 12,
    chunk_size: int = 600,
    overlap: int = 100,
    vectors_path: str = _VECTORS_PATH,
    meta_path: str = _META_PATH,
    vectorizer_path: str = _VECTORIZER_PATH,
) -> int:
    """
    Load the static knowledge docs in docs_dir, plus a live market_report_document
    per city in market_cities (if given), chunk and embed all of it, and cache
    the result to disk. Returns the number of chunks indexed.
    """
    docs = load_source_documents(docs_dir)
    for city in market_cities or []:
        docs.append(market_report_document(city, months=months))

    chunks = index_documents(docs, chunk_size=chunk_size, overlap=overlap)
    if not chunks:
        return 0

    texts = [c["chunk"] for c in chunks]
    vectorizer = None
    try:
        matrix = embed_texts(texts)
        backend = _BACKEND_LOCAL
    except Exception as e:
        print(
            f"Local embedding model unavailable ({e.__class__.__name__}: {str(e)[:200]}); "
            "falling back to a local TF-IDF index for RAG retrieval.",
            file=sys.stderr,
        )
        vectorizer = TfidfVectorizer(max_features=2000, stop_words="english")
        matrix = vectorizer.fit_transform(texts).toarray().astype(np.float32)
        backend = _BACKEND_TFIDF

    os.makedirs(os.path.dirname(vectors_path), exist_ok=True)
    np.save(vectors_path, matrix)

    if vectorizer is not None:
        with open(vectorizer_path, "wb") as f:
            pickle.dump(vectorizer, f)
    elif os.path.exists(vectorizer_path):
        os.remove(vectorizer_path)  # stale fallback artifact from a prior build

    with open(meta_path, "w") as f:
        json.dump({"backend": backend, "chunks": chunks}, f)

    return len(chunks)


def _load_index(vectors_path: str, meta_path: str, vectorizer_path: str):
    if not os.path.exists(vectors_path) or not os.path.exists(meta_path):
        raise FileNotFoundError(f"No RAG index at {vectors_path} -- run build_index() first.")
    matrix = np.load(vectors_path)
    with open(meta_path) as f:
        meta = json.load(f)

    vectorizer = None
    if meta["backend"] == _BACKEND_TFIDF:
        with open(vectorizer_path, "rb") as f:
            vectorizer = pickle.load(f)

    return matrix, meta["chunks"], meta["backend"], vectorizer


# Week 11 safety guardrail: never return more than this many rows from a
# single query, regardless of what a caller asks for.
_MAX_ROWS = 50


def retrieve(
    query: str,
    top_k: int = 4,
    vectors_path: str = _VECTORS_PATH,
    meta_path: str = _META_PATH,
    vectorizer_path: str = _VECTORIZER_PATH,
) -> list[dict]:
    """Embed `query` and return the top_k most similar indexed chunks, ranked
    by cosine similarity. `top_k` is capped at `_MAX_ROWS`."""
    top_k = min(top_k, _MAX_ROWS)
    matrix, chunks, backend, vectorizer = _load_index(vectors_path, meta_path, vectorizer_path)
    if backend == _BACKEND_TFIDF:
        query_vector = vectorizer.transform([query]).toarray().astype(np.float32)
    else:
        try:
            query_vector = embed_texts([query])
        except Exception as e:
            # This index's cached matrix is in the local model's vector space
            # -- a TF-IDF query vector wouldn't be comparable to it, so
            # there's no same-space fallback to degrade to here (unlike
            # build_index()).
            raise RuntimeError(
                "This index was built with the local embedding model, but "
                f"embedding the query failed ({e.__class__.__name__}: "
                f"{str(e)[:200]}). Run build_index() again to force the "
                "TF-IDF backend for both the corpus and future queries."
            ) from e

    scores = cosine_similarity(query_vector, matrix)[0]
    top_indices = np.argsort(scores)[::-1][:top_k]
    return [{**chunks[i], "score": float(scores[i])} for i in top_indices]


def rag_answer(
    query: str,
    top_k: int = 4,
    vectors_path: str = _VECTORS_PATH,
    meta_path: str = _META_PATH,
    vectorizer_path: str = _VECTORIZER_PATH,
) -> dict:
    """
    Retrieve the top_k relevant chunks for `query` and generate an answer
    grounded in them. Tries a Gemini generation call constrained to the
    retrieved context; on any Gemini error, falls back to returning the top
    chunk verbatim, tagged with backend="extractive" so callers can tell a
    real generated answer from the fallback.
    """
    chunks = retrieve(
        query, top_k=top_k, vectors_path=vectors_path, meta_path=meta_path, vectorizer_path=vectorizer_path
    )
    if not chunks:
        return {"answer": "No indexed knowledge to answer from -- run build_index() first.", "sources": [], "backend": None}

    context = "\n\n".join(f"[{c['source']}]\n{c['chunk']}" for c in chunks)
    sources = sorted({c["source"] for c in chunks})

    try:
        response = _get_gemini_client().models.generate_content(
            model=_GEMINI_MODEL,
            contents=(
                "Answer using only the context below. If the context doesn't "
                f"cover the question, say so.\n\nContext:\n{context}\n\n"
                f"Question: {query}"
            ),
        )
        answer = response.text
        backend = _BACKEND_GEMINI
    except genai_errors.APIError as e:
        print(
            f"Gemini generation unavailable ({e.__class__.__name__}: {str(e)[:200]}); "
            "falling back to the top retrieved chunk.",
            file=sys.stderr,
        )
        answer = chunks[0]["chunk"]
        backend = _BACKEND_EXTRACTIVE

    return {"answer": answer, "sources": sources, "backend": backend}


def format_rag_answer(result: dict) -> str:
    """Render a rag_answer() result as a display-ready card."""
    sources = ", ".join(result["sources"]) if result["sources"] else "none"
    return f"{result['answer']}\n\nSources: {sources}"
