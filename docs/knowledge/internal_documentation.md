# IDX Exchange Assistant — Internal Documentation

This document describes the IDX Exchange multi-agent real estate assistant
itself, for grounding meta-questions about what the assistant can do and
which skill handles what.

## What this assistant is

A multi-agent AI assistant, built for the IDX Exchange Summer 2026
internship, over two California MLS datasets: `rets_property` (~228K active
listings) and `california_sold` (~439K sold transactions, 2021–2025). Both
live in the `idx_exchange` MySQL schema. See the `mls_field_definitions`
document for the full column reference.

## Skills and when each one is used

- **property-search** — Parses a free-text query naming a city, budget,
  bed/bath count, property type, or amenities into structured filters and
  runs parameterized SQL against `rets_property`. Supports multi-turn
  conversation: preferences mentioned earlier in a session carry forward
  and refine later results. Use for hard-filter searches with explicit
  criteria.

- **market-stats** — Answers questions about city-level pricing and
  market conditions via aggregations over `california_sold`: median/avg
  close price, price per sqft, average days on market, list-to-close
  ratio, and month-over-month price trends.

- **semantic-search** — Answers fuzzy, descriptive property queries that
  don't map to hard filters (a feel, vibe, or set of qualities rather than
  specific numbers), by embedding listing remarks and structured
  attributes with a local `sentence-transformers` model and ranking by
  cosine similarity.

- **recommendation** — Given a specific active listing, surfaces the top 5
  most similar other active listings (hybrid score: 60% structured
  attribute closeness, 40% semantic similarity of remarks) and validates
  each candidate's price against recent same-city sold comps from
  `california_sold`. Use for "find me more like this" and "is this priced
  fairly" questions.

- **rag-knowledge** — For questions about the data model, industry
  vocabulary, seller compliance obligations, or the assistant itself,
  retrieves grounded context from a small internal knowledge base rather
  than SQL-querying the MLS tables directly.

## Design notes

- No skill exports or bulk-downloads full MLS datasets; result sets are
  capped (typically ≤50 rows per query) per the project's safety
  guardrails.
- All SQL is parameterized — no user input is ever string-concatenated
  into a query.
- Embeddings across all skills run on a local `sentence-transformers`
  model — no API, no key, no rate limit, no cost — falling back further to
  a local TF-IDF vectorizer in the rare case the model itself can't load
  (no cached weights and no network on a first-ever run). `rag-knowledge`
  is the only skill with a hosted API dependency at all, for its answer
  generation step (Gemini).
- As of Week 8, skills run as plain Python modules invoked directly (see
  each skill's `SKILL.md` for a runnable example) — OpenClaw agent
  orchestration, intent routing, and the WhatsApp channel are Week 9+
  deliverables, not yet wired into this repo.
