# property-search

Parse a free-text real estate query into structured filters, then query the MLS database.

## When to use

Use this skill when the user asks to find, search, or show properties — e.g.:
- "Show me 3-bedroom condos in Irvine under $1.5M"
- "Find homes in Pasadena with a pool"
- "Any land for sale in Malibu?"

## Week 2: Query Parser

Run `parse_query.py` to convert the user's message into a structured filter object.

```bash
cd /Users/lindsaylai/projects/idx-exchange
source venv/bin/activate
python -c "
from skills.property_search.parse_query import parse_property_query
import json
result = parse_property_query('<USER_QUERY>')
print(json.dumps(result, indent=2))
"
```

### Output fields → rets_property columns

| Field      | DB Column        | Example        |
|------------|------------------|----------------|
| city       | L_City           | "Irvine"       |
| maxPrice   | L_SystemPrice    | 1500000        |
| beds       | L_Keyword2       | 3              |
| baths      | LM_Dec_3         | 2.5            |
| sqft       | LM_Int2_3        | 1800           |
| type       | L_Type_          | "Condominium"  |
| pool       | PoolPrivateYN    | "True"         |
| hasView    | ViewYN           | "True"         |
| maxHOA     | AssociationFee   | 300            |

All values are `null` when not mentioned in the query.

## Week 3: Database query

Filters from the parser feed straight into `searchActiveListings()` against `rets_property`.
Sold comps come from `getSoldComps()` against `california_sold`.

```bash
cd /Users/lindsaylai/projects/idx-exchange
source venv/bin/activate
python -c "
import sys; sys.path.insert(0, 'skills/property-search')
from parse_query import parse_property_query
from search_listings import searchActiveListings, getSoldComps, format_listing_card

filters = parse_property_query('<USER_QUERY>')
for row in searchActiveListings(filters, page=1, limit=10):
    print(format_listing_card(row))
"
```

- Connection pooling lives in `db.py` (`get_connection()` / `get_cursor()`), backed by
  `mysql.connector.pooling.MySQLConnectionPool` and configured from `.env`.
- All queries are parameterized (`%s` placeholders) — filter values from the parser are
  never string-concatenated into SQL.
- `searchActiveListings(filters, page, limit)` paginates via `LIMIT`/`OFFSET`
  (`page` is 1-indexed).
- `format_listing_card(row)` renders a `searchActiveListings()` row as a display-ready
  card (address, price, beds/baths, sqft, photo count, pool/view tags).
- `PoolPrivateYN` / `ViewYN` store `'1'` for true (not the parser's `"True"` string) —
  `search_listings.py` translates between the two.
- `getSoldComps(city, months)` anchors "recent" to `CURDATE()`, not `MAX(CloseDate)`,
  since a few rows in `california_sold` have corrupted future-dated `CloseDate` values.
- Key join for comps: `CAST(rets_property.L_ListingID AS UNSIGNED) = california_sold.ListingKey`

Tests: `python skills/property-search/test_search_listings.py` (runs against the local
`idx_exchange` MySQL database).

## Week 4: Conversational agent

`session.py` turns the single-turn search above into a multi-turn conversation. Each
call to `handleMessage(user_id, message)` parses the new message, merges any filters
it contains into that user's session, and either asks a follow-up question or runs
the search — matching the example flow:

```
User: "Find homes in Irvine"                        -> "What is your budget?"
User: "Under $1.2M"                                  -> "Any preferences — condo, townhome, or single family?"
User: "Single family with at least 3 beds"           -> [formatted results]
```

```bash
cd /Users/lindsaylai/projects/idx-exchange
source venv/bin/activate
python -c "
import sys; sys.path.insert(0, 'skills/property-search')
from session import handleMessage

for msg in ['Find homes in Irvine', 'Under \$1.2M', 'Single family with at least 3 beds']:
    print('User:', msg)
    print('Agent:', handleMessage('demo-user', msg))
    print()
"
```

- `getSession(user_id)` / `updateSession(user_id, updates)` / `clearSession(user_id)`
  manage an in-memory session per user (`city`, `maxPrice`, `beds`, `baths`, `sqft`,
  `type`, `pool`, `hasView`, `maxHOA`, `lastResults`, `conversationStep`).
- Missing must-have filters (`city` → `maxPrice` → `type`) are asked for one at a time,
  in that order, until all three are known — a single message that already specifies
  everything skips straight to results.
- Once a session has results, every subsequent message is treated as a refinement:
  its filters are merged in and the search re-runs immediately, no more questions.
- Sessions are isolated per `user_id` and reset with `clearSession(user_id)`.

Tests: `python skills/property-search/test_session.py`.
