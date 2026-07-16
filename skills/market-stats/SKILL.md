# market-stats

Answers market questions ("Is now a good time to buy in San Diego?", "What's the
average price per sq ft in Pasadena?") with data-backed aggregations over
`california_sold`.

## When to use

Use this skill when the user asks about market conditions, pricing trends, or
comps at the city level, rather than searching for a specific listing — e.g.:
- "Is now a good time to buy in San Diego?"
- "What's the average price per sq ft in Pasadena?"
- "How's the market in Oakland compared to last month?"

## Week 5: Market Statistics

```bash
cd /Users/lindsaylai/projects/idx-exchange
source venv/bin/activate
python -c "
import sys; sys.path.insert(0, 'skills/market-stats')
from market_stats import format_market_summary

print(format_market_summary('San Diego', months=12))
"
```

### Functions

- `get_city_market_summary(months, limit)` — top `limit` California cities by
  sold volume over the trailing `months`: sold count, avg close price, avg
  price/sqft, avg days on market, list-to-close ratio.
- `get_city_stats(city, months)` — single-city snapshot: sold count, avg/median
  close price, avg price/sqft, avg DOM, list-to-close ratio.
- `get_price_trend(city, months)` — a pandas DataFrame of month-over-month sold
  count, avg price, avg DOM, and `price_change_pct`.
- `format_market_summary(city, months)` — renders `get_city_stats()` plus the
  latest `get_price_trend()` point as one readable sentence.

### Notes

- Reuses the connection pool from `property-search/db.py` rather than opening a
  second one — `market_stats.py` adds `../property-search` to `sys.path` itself.
- MySQL has no `MEDIAN()`/`PERCENTILE_CONT` aggregate, so the median close price
  is computed by ranking rows with `ROW_NUMBER() OVER (...)` and averaging the
  middle one (or two, for an even count).
- `get_price_trend()` uses SQLAlchemy's `text()` with named `:params`, not the
  positional `%s`-list style — with the SQLAlchemy 2.0 / pandas 3.0 versions
  installed here, `pd.read_sql(query, engine, params=[...])` raises
  `List argument must consist only of tuples or dictionaries`.
- "Recent" is anchored to `CURDATE()`, not `MAX(CloseDate)`, for the same
  reason as `search_listings.getSoldComps()`: a few `california_sold` rows have
  corrupted, far-future `CloseDate` values that would otherwise skew the window.

Tests: `python skills/market-stats/test_market_stats.py` (runs against the
local `idx_exchange` MySQL database).
