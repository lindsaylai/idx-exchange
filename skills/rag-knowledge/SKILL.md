---
name: rag-knowledge
description: Answer conceptual/definitional real estate and MLS-schema questions by retrieving relevant chunks from indexed knowledge docs (field definitions, glossary, CA disclosure requirements, live market reports) and grounding the answer in them.
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

# rag-knowledge

Answers conceptual and definitional questions ("What does DOM mean?", "What
columns are in california_sold?", "What is a list-to-close ratio?", "What
disclosures does a CA seller have to make?") by retrieving relevant chunks
from a small indexed knowledge base and generating an answer grounded in
that retrieved context, instead of answering from unverified model
knowledge.

## When to use

Use this skill for terminology, schema, and general real-estate-knowledge
questions rather than questions about specific listings or live market
numbers — e.g.:
- "What does DOM mean?"
- "What columns does rets_property have?"
- "What disclosures is a CA home seller required to make?"
- "What's the difference between list price and original list price?"

For a specific listing search, prefer `property-search` or
`semantic-search`; for city-level pricing/trend numbers, prefer
`market-stats`.

## Week 8: RAG Pipeline

```bash
cd /Users/lindsaylai/projects/idx-exchange
source venv/bin/activate
python -c "
import sys; sys.path.insert(0, 'skills/rag-knowledge')
from rag import build_index, rag_answer, format_rag_answer

build_index()  # one-time (or periodic) local cache build over docs/knowledge/

result = rag_answer('What does DOM mean?')
print(format_rag_answer(result))
"
```

### Knowledge sources (`docs/knowledge/`)

- `mls_field_definitions.md` — full column reference for `rets_property`
  and `california_sold`, plus the join pattern between them.
- `glossary.md` — real estate terminology (DOM, comps, list-to-close
  ratio, $/sqft, escrow, contingency, HOA, MLS, RESO, APN, etc.), defined
  to match how this project's own agents compute them where applicable.
- `ca_disclosure_requirements.md` — a general, non-legal-advice summary of
  California residential disclosure requirements (TDS, NHD, agency
  disclosure, lead paint, Mello-Roos/HOA, buyer's right to cancel).
- `internal_documentation.md` — what this assistant is and which skill
  handles which kind of question.

### Functions

- `chunk_text(text, chunk_size, overlap)` — splits text into overlapping,
  whitespace-trimmed chunks. Defaults `chunk_size=600`, `overlap=100`, per
  the handbook's chunking template.
- `load_source_documents(docs_dir)` — reads every `.md` file in
  `docs/knowledge/` as a `{"title", "content"}` doc.
- `market_report_document(city, months)` — a live `{"title", "content"}`
  doc built from `market_stats.format_market_summary()` (Week 5), not a
  static file — see Notes.
- `index_documents(docs, chunk_size, overlap)` — chunks a list of docs into
  `{"source", "chunk"}` entries tagged with their doc title.
- `build_index(docs_dir, market_cities, months, ...)` — loads the static
  docs (+ a `market_report_document` per city in `market_cities`, if any),
  chunks and embeds everything, and caches vectors + metadata to `data/`.
  Returns the chunk count indexed.
- `retrieve(query, top_k)` — embeds `query` and returns the `top_k` most
  similar indexed chunks by cosine similarity.
- `rag_answer(query, top_k)` — retrieves context via `retrieve()`, then
  generates an answer constrained to that context. Returns
  `{"answer", "sources", "backend"}`.
- `format_rag_answer(result)` — renders a `rag_answer()` result as a
  display-ready card (answer + cited sources).

### Notes

- **Embedding fallback:** same pattern as `semantic-search` and
  `recommendation` — embeddings run on a local `sentence-transformers`
  model (no API, no key, no rate limit); if that fails to load for any
  reason (rare — no cached weights and no network on a first-ever run),
  `build_index()` falls back to a `TfidfVectorizer` fit on the chunk set
  and persists it so `retrieve()` embeds queries the same way. `meta.json`
  records which backend built the index. A *query-time* failure (index
  built fine, but a later `retrieve()` call fails) raises a clear
  `RuntimeError` instead of crashing or silently comparing incompatible
  vector spaces — see `semantic-search`'s notes for why.
- **Answer-generation fallback:** `rag_answer()` uses Gemini
  (`gemini-2.5-flash`) for generation — it's the LLM `docs/architecture.md`
  already designates for OpenClaw orchestration, and it has a free tier,
  so this is the one hosted API dependency in this skill (embeddings are
  local). If that call fails, it falls back to returning the single most
  relevant chunk verbatim, tagged `backend: "extractive"` — the caller can
  always tell a generated answer from the fallback and format accordingly.
  Requires `GEMINI_API_KEY` in `.env` (same key your OpenClaw gateway
  already uses, at `~/.openclaw/.env` — copy the value over, it's a
  separate gitignored file local to this project).
- **Market reports are generated, not stored:** per the handbook's
  knowledge-source list ("market reports sourced via the market analytics
  agent"), `market_report_document()` reuses
  `market_stats.format_market_summary()` rather than duplicating its SQL
  or maintaining a stale static snapshot. Pass `market_cities=[...]` to
  `build_index()` to fold a given city's live report into the index; by
  default no market cities are indexed, since the set of cities worth
  covering is open-ended and this keeps the base index small and static.
- Reuses `semantic-search`'s `embed_texts()` and `market-stats`'s
  `format_market_summary()` rather than duplicating either — `rag.py` adds
  both skills' directories to `sys.path` itself, same pattern as
  `recommendation`.
- The index cache (`data/rag_index.npy`, `data/rag_index_meta.json`,
  `data/rag_index_vectorizer.pkl`) lives under `data/`, which is
  gitignored — same as the other embedding caches, each machine builds its
  own.

Tests: `python skills/rag-knowledge/test_rag.py` (builds a temp-dir index
over the real `docs/knowledge/` docs; exercises chunking, retrieval, and
both the Gemini and extractive-fallback answer paths).
