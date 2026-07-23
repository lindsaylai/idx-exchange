import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from semantic_search import build_index, semantic_search, format_semantic_result


def check(label, condition):
    print(f"{'PASS' if condition else 'FAIL'}: {label}")
    return condition


results = []

# Build a small index in a temp dir so the test doesn't touch (or depend on)
# any index a real run of build_index() has already cached under data/.
tmp_dir = tempfile.mkdtemp()
vectors_path = os.path.join(tmp_dir, "test_vectors.npy")
meta_path = os.path.join(tmp_dir, "test_meta.json")
vectorizer_path = os.path.join(tmp_dir, "test_vectorizer.pkl")

indexed_count = build_index(limit=30, vectors_path=vectors_path, meta_path=meta_path, vectorizer_path=vectorizer_path)
results.append(check("build_index indexes rows", indexed_count > 0))
results.append(check("build_index respects `limit`", indexed_count <= 30))

# --- semantic search ---
hits = semantic_search(
    "home with a pool and mountain views",
    top_k=5,
    vectors_path=vectors_path,
    meta_path=meta_path,
    vectorizer_path=vectorizer_path,
)
results.append(check("search returns results", len(hits) > 0))
results.append(check("search respects top_k", len(hits) <= 5))
results.append(check(
    "results are sorted by descending similarity score",
    all(a["score"] >= b["score"] for a, b in zip(hits, hits[1:])),
))
results.append(check(
    "each hit has the expected fields",
    all(
        "listingId" in hit and "address" in hit and "remarks" in hit and "score" in hit
        for hit in hits
    ),
))
results.append(check("similarity scores are bounded in [-1, 1]", all(-1.0001 <= hit["score"] <= 1.0001 for hit in hits)))

# --- formatted card ---
card = format_semantic_result(hits[0])
results.append(check("formatted card includes the address", hits[0]["address"] in card))
results.append(check("formatted card includes a match score", "match)" in card))

print(f"\n{sum(results)}/{len(results)} tests passed")
