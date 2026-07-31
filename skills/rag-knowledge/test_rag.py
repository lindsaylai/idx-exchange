import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from rag import (
    chunk_text,
    load_source_documents,
    index_documents,
    build_index,
    retrieve,
    rag_answer,
    format_rag_answer,
)


def check(label, condition):
    print(f"{'PASS' if condition else 'FAIL'}: {label}")
    return condition


results = []

# --- chunk_text ---
short = chunk_text("short text", chunk_size=600, overlap=100)
results.append(check("chunk_text returns the whole string when under chunk_size", short == ["short text"]))

long_text = "x" * 1500
long_chunks = chunk_text(long_text, chunk_size=600, overlap=100)
results.append(check("chunk_text splits long text into multiple chunks", len(long_chunks) > 1))
results.append(check("chunk_text respects chunk_size", all(len(c) <= 600 for c in long_chunks)))
results.append(check("chunk_text covers the full input", "".join(long_chunks).replace("", "") and len(long_chunks[0]) == 600))

# --- load_source_documents ---
docs = load_source_documents()
results.append(check("load_source_documents finds the knowledge docs", len(docs) >= 4))
results.append(check(
    "each doc has a title and non-empty content",
    all(d["title"] and d["content"].strip() for d in docs),
))

# --- index_documents ---
indexed = index_documents(docs)
results.append(check("index_documents produces chunks for every doc", len(indexed) >= len(docs)))
results.append(check(
    "each indexed chunk carries its source title",
    all(c["source"] in {d["title"] for d in docs} for c in indexed),
))

# Build a small index in a temp dir so the test doesn't touch (or depend on)
# any index a real run of build_index() has already cached under data/.
tmp_dir = tempfile.mkdtemp()
vectors_path = os.path.join(tmp_dir, "test_vectors.npy")
meta_path = os.path.join(tmp_dir, "test_meta.json")
vectorizer_path = os.path.join(tmp_dir, "test_vectorizer.pkl")

chunk_count = build_index(vectors_path=vectors_path, meta_path=meta_path, vectorizer_path=vectorizer_path)
results.append(check("build_index indexes chunks", chunk_count > 0))
results.append(check("build_index output file exists", os.path.exists(vectors_path)))

# --- retrieve ---
hits = retrieve(
    "What does DOM mean?",
    top_k=4,
    vectors_path=vectors_path,
    meta_path=meta_path,
    vectorizer_path=vectorizer_path,
)
results.append(check("retrieve returns results", len(hits) > 0))
results.append(check("retrieve respects top_k", len(hits) <= 4))
results.append(check(
    "results are sorted by descending similarity score",
    all(a["score"] >= b["score"] for a, b in zip(hits, hits[1:])),
))
results.append(check(
    "the DOM glossary entry is retrieved for a DOM query",
    any("Days on Market" in h["chunk"] or "DOM" in h["chunk"] for h in hits),
))

# --- rag_answer ---
result = rag_answer(
    "What does DOM mean?",
    top_k=4,
    vectors_path=vectors_path,
    meta_path=meta_path,
    vectorizer_path=vectorizer_path,
)
results.append(check("rag_answer returns a non-empty answer", bool(result["answer"].strip())))
results.append(check("rag_answer cites at least one source", len(result["sources"]) > 0))
results.append(check("rag_answer tags its backend", result["backend"] in ("gemini", "extractive")))

card = format_rag_answer(result)
results.append(check("formatted card includes the answer", result["answer"] in card))
results.append(check("formatted card lists sources", "Sources:" in card))

print(f"\n{sum(results)}/{len(results)} tests passed")
