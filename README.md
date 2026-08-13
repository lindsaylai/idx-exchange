# IDX Exchange — Multi-Agent Real Estate Assistant

A production multi-agent AI assistant built on OpenClaw for the IDX Exchange Summer 2026 internship. Supports natural language MLS property search, market analytics, semantic recommendations, RAG knowledge retrieval, and WhatsApp + email communication — powered by two California MLS datasets totaling 667K+ records.

## Databases

| Table | Rows | Description |
|-------|------|-------------|
| `rets_property` | ~228K | Active MLS listings — 130+ fields including remarks, photos, agent info, HOA |
| `california_sold` | ~439K | Sold transactions 2021–2025 — close price, DOM, comps, coordinates |

Both tables live in MySQL schema `idx_exchange`. Join via `CAST(rets_property.L_ListingID AS UNSIGNED) = california_sold.ListingKey`.

## Setup

**1. Clone and create Python environment**
```bash
git clone https://github.com/lindsaylai/idx-exchange.git
cd idx-exchange
python3 -m venv venv
source venv/bin/activate
pip install pandas sentence-transformers google-genai mysql-connector-python sqlalchemy scikit-learn numpy
```

**2. Prefetch the local embedding model**
```bash
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```
One-time ~90MB download from the HuggingFace Hub, cached under `~/.cache/huggingface/`. Doing this explicitly up front makes setup reproducible — without it, the model just downloads lazily on first real use instead (in `semantic-search`, `recommendation`, or `rag-knowledge`), which works fine too, just less predictably.

**3. Configure environment variables**
```bash
cp .env.example .env  # then fill in your values
```

```env
GEMINI_API_KEY=...
MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_DATABASE=idx_exchange
EMAIL_USER=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
```
`GEMINI_API_KEY` is only needed for `rag-knowledge`'s answer generation (`gemini-2.5-flash`) — embeddings across all skills run locally and need no API key at all.

**4. Import MLS data**
```bash
mysql -u root -e "CREATE DATABASE idx_exchange CHARACTER SET utf8mb4;"
mysql -u root idx_exchange < data/rets_property.sql
mysql -u root idx_exchange < data/california_sold.sql
```

**5. Install and configure OpenClaw**
```bash
npm install -g openclaw
openclaw onboard
openclaw channels login --channel whatsapp
```

## Project Structure

```
idx-exchange/
├── skills/
│   └── property-search/
│       ├── SKILL.md              # OpenClaw skill definition
│       ├── parse_query.py        # NL query → structured filters
│       ├── test_parse_query.py
│       ├── db.py                 # MySQL connection pool
│       ├── search_listings.py    # searchActiveListings() + getSoldComps()
│       ├── test_search_listings.py
│       ├── session.py            # multi-turn conversation + session memory
│       ├── test_session.py
│       └── chat.py               # interactive CLI for manual testing
│   └── market-stats/
│       ├── SKILL.md
│       ├── market_stats.py       # city summaries, median price, DOM, trends
│       └── test_market_stats.py
│   └── semantic-search/
│       ├── SKILL.md
│       ├── semantic_search.py    # embeddings + cosine-similarity search over L_Remarks
│       └── test_semantic_search.py
│   └── recommendation/
│       ├── SKILL.md
│       ├── recommend.py          # hybrid scoring (semantic fit + comp-relative value)
│       └── test_recommend.py
│   └── rag-knowledge/
│       ├── SKILL.md
│       ├── rag.py                # chunk/index/retrieve + grounded answer generation
│       └── test_rag.py
│   └── orchestrator/
│       ├── SKILL.md
│       ├── orchestrate.py        # classify_intent() + orchestrate() -- routes/merges across all 6 skills
│       ├── test_orchestrate.py
│       ├── test_orchestrate_email.py  # Week 12: email intent's draft/approve/decline flow
│       ├── chat.py               # interactive CLI for manual testing (raw orchestrate() output)
│       ├── whatsapp.py           # handle_whatsapp_message() -- WhatsApp-shaped reply + error boundary
│       ├── test_whatsapp.py
│       └── whatsapp_chat.py      # interactive CLI simulating the actual WhatsApp experience
│   └── email-agent/
│       ├── SKILL.md
│       ├── email_agent.py        # draft_email()/send_approved_email() + 4 content builders
│       ├── test_email_agent.py
│       └── chat.py               # interactive CLI -- previews drafts only, never sends
├── docs/
│   └── knowledge/             # RAG source docs: field defs, glossary, CA disclosures, internal docs
│   └── architecture.md       # Full system architecture + flow diagrams
├── data/                     # SQL dumps (gitignored)
└── venv/                     # Python environment (gitignored)
```

## Progress

| Week | Module | Status |
|------|--------|--------|
| 0 | Environment Setup | Done |
| 1 | OpenClaw Architecture | Done |
| 2 | NL Property Search | Done |
| 3 | Database Integration | Done |
| 4 | Conversational Agent | Done |
| 5 | Market Analytics | Done |
| 6 | Embeddings & Vector Search | Done |
| 7 | Recommendation Engine | Done |
| 8 | RAG Pipeline | Done |
| 9 | Multi-Agent Orchestration | Done |
| 10 | WhatsApp Layer | Done — live gateway now routes through `orchestrator` |
| 11 | Email Agents & Safety | Done |
| 12 | Capstone Demo | Done (integration) — live demo/video/reflection still on you, see below |

## Tech Stack

- **Database:** MySQL
- **Language:** Python 3.11
- **Embeddings:** local `sentence-transformers` (`all-MiniLM-L6-v2`) — used by `semantic-search`, `recommendation`, and `rag-knowledge`. No API, no key, no rate limit, no cost; TF-IDF fallback if the model can't load at all (rare — first-run-only network dependency).
- **RAG answer generation:** Google Gemini `gemini-2.5-flash` (Week 8, `rag-knowledge`) — free tier, and the same LLM already designated for OpenClaw orchestration; falls back to returning the top retrieved chunk verbatim if unavailable.
- No OpenAI dependency, and no hosted embeddings dependency either — both were tried (see git history) and dropped in favor of the fully local embedding model above, since embeddings happen in bursts (indexing hundreds of listings/chunks at once) that reliably tripped free-tier per-minute quotas on both OpenAI and Gemini. Gemini is still used for `rag-knowledge`'s generation step, where traffic is much lighter (one call per question).

**Multi-agent orchestration (Week 9):** `skills/orchestrator/orchestrate.py`
classifies each message's intent (`search`, `semantic`, `market`,
`recommend`, `knowledge`, `email`, or `mixed`) via keyword/regex heuristics
— same style as `parse_query.py`, not an LLM call — and routes it to the
matching skill(s) above, running two in parallel and merging their replies
for a mixed-intent query. See `skills/orchestrator/SKILL.md` for the full
classification precedence and known limitations.

**WhatsApp communication layer (Week 10):**
`skills/orchestrator/whatsapp.py` wraps `orchestrate()` for the WhatsApp
channel — an intent-tagged emoji prefix, a length cap for a single text
bubble, and a try/except boundary so a skill-level failure becomes a
friendly reply instead of a dropped message. This project's OpenClaw
gateway is already linked to a real WhatsApp account; `~/.openclaw/openclaw.json`'s
`skills.entries` now registers `orchestrator` as the sole skill (replacing
the four individually-registered pre-orchestrator entries), so WhatsApp
messages route through `orchestrate()`. See `skills/orchestrator/SKILL.md`'s
"Live WhatsApp wiring" section for details and the rollback path.

**Email agent & safety guardrails (Week 11):** `skills/email-agent/email_agent.py`
implements a strict two-step draft-then-approve workflow — `draft_email()`
and four content builders (`draft_market_report`, `draft_listing_alert`,
`draft_property_summary`, `draft_recommendation_digest`) can only ever
produce a pending draft; `send_approved_email()` is the sole function that
can send, and refuses unless it's handed a real draft *and* an explicit
`approved=True`. Also added a hard `_MAX_ROWS = 50` cap (clamped in the
function itself, not just a default) to every other skill's row-returning
query — `search_listings.py`, `market_stats.py`, `semantic_search.py`,
`recommend.py`, `rag.py` — per the handbook's "never bulk-export MLS data"
rule. See `skills/email-agent/SKILL.md` for the full guardrail table.

**Capstone integration (Week 12):** `orchestrator` now has an `email`
intent that calls straight into `email-agent`'s content builders and, on a
later "yes"/"no" turn, its approval gate — the draft-and-approve flow
happens as two separate WhatsApp turns, exactly as the handbook's demo
script requires ("this flow requires two steps by design and can't be
compressed further"). A price filter like "under $1,500,000" is
disambiguated from a bare listing id (both match a 6+-digit regex) by
checking hard filters first. See `skills/orchestrator/SKILL.md`'s "Week 12:
email intent" section for the full routing precedence, and
`test_orchestrate_email.py` (29 checks, all against a monkeypatched send —
zero risk of a real email during testing) for the draft/approve/decline
cycle end to end.

**What's still on you, not this repo, per the handbook's Week 12
checklist:** the 5-minute live demo over WhatsApp + screen share, a backup
demo video recording, and a written reflection ("what worked, what you'd
change") — all genuinely require you, not something a repo commit can
produce. The "architecture diagram" and "schema annotation document" items
are already covered by `docs/architecture.md`'s mermaid diagrams and
`docs/knowledge/mls_field_definitions.md`'s full column reference,
respectively.
