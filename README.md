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
pip install pandas openai mysql-connector-python sqlalchemy scikit-learn numpy
```

**2. Configure environment variables**
```bash
cp .env.example .env  # then fill in your values
```

```env
OPENAI_API_KEY=sk-...
MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=
MYSQL_DATABASE=idx_exchange
EMAIL_USER=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
```

**3. Import MLS data**
```bash
mysql -u root -e "CREATE DATABASE idx_exchange CHARACTER SET utf8mb4;"
mysql -u root idx_exchange < data/rets_property.sql
mysql -u root idx_exchange < data/california_sold.sql
```

**4. Install and configure OpenClaw**
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
├── docs/
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
| 6 | Embeddings & Vector Search | — |
| 7 | Recommendation Engine | — |
| 8 | RAG Pipeline | — |
| 9 | Multi-Agent Orchestration | — |
| 10 | WhatsApp Layer | — |
| 11 | Email Agents & Safety | — |
| 12 | Capstone Demo | — |

## Tech Stack

- **Agent runtime:** OpenClaw
- **LLM:** Gemini 2.5 Flash
- **Database:** MySQL
- **Language:** Python 3.11 + TypeScript
- **Embeddings:** OpenAI `text-embedding-3-small`
- **Channel:** WhatsApp
