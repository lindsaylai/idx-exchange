"""
Week 5: Market Statistics Agent.

Aggregations over california_sold: a multi-city summary table, a
single-city snapshot (median price, DOM, list-to-close ratio), and a
month-over-month price trend. Reuses the connection pool from the
property-search skill rather than opening a second one.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "property-search"))

import pandas as pd
from sqlalchemy import create_engine, text

from db import get_cursor, _load_dotenv, _ENV_PATH

_load_dotenv(_ENV_PATH)

_ENGINE = None


def _get_engine():
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = create_engine(
            "mysql+mysqlconnector://{user}:{password}@{host}/{database}".format(
                user=os.environ.get("MYSQL_USER", "root"),
                password=os.environ.get("MYSQL_PASSWORD", ""),
                host=os.environ.get("MYSQL_HOST", "localhost"),
                database=os.environ.get("MYSQL_DATABASE", "idx_exchange"),
            )
        )
    return _ENGINE


# "Recent" is anchored to CURDATE() rather than MAX(CloseDate) — same reason
# as search_listings.getSoldComps(): a handful of rows have corrupted,
# far-future CloseDate values that would otherwise skew the window.
_SUMMARY_QUERY = """
    SELECT
        City,
        COUNT(*) AS sold_count,
        ROUND(AVG(ClosePrice), 0) AS avg_close_price,
        ROUND(AVG(ClosePrice / NULLIF(LivingArea, 0)), 0) AS avg_price_per_sqft,
        ROUND(AVG(DaysOnMarket), 1) AS avg_dom,
        ROUND(AVG(ClosePrice / NULLIF(ListPrice, 0)) * 100, 1) AS list_to_close_pct
    FROM california_sold
    WHERE PropertyType = 'Residential'
      AND CloseDate <= CURDATE()
      AND CloseDate >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)
      AND LivingArea > 0
    GROUP BY City
    ORDER BY sold_count DESC
    LIMIT %s
"""


def get_city_market_summary(months: int = 12, limit: int = 25) -> list[dict]:
    """Top `limit` California cities by sold volume over the trailing `months`."""
    with get_cursor() as cursor:
        cursor.execute(_SUMMARY_QUERY, (months, limit))
        return cursor.fetchall()


_CITY_STATS_QUERY = """
    SELECT
        COUNT(*) AS sold_count,
        ROUND(AVG(ClosePrice), 0) AS avg_close_price,
        ROUND(AVG(ClosePrice / NULLIF(LivingArea, 0)), 0) AS avg_price_per_sqft,
        ROUND(AVG(DaysOnMarket), 1) AS avg_dom,
        ROUND(AVG(ClosePrice / NULLIF(ListPrice, 0)) * 100, 1) AS list_to_close_pct
    FROM california_sold
    WHERE City = %s
      AND PropertyType = 'Residential'
      AND CloseDate <= CURDATE()
      AND CloseDate >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)
"""

# MySQL has no MEDIAN()/PERCENTILE_CONT aggregate, so the median is computed
# by ranking rows and averaging the middle one (or two, for an even count).
_MEDIAN_QUERY = """
    SELECT AVG(ClosePrice) AS median_close_price
    FROM (
        SELECT ClosePrice,
               ROW_NUMBER() OVER (ORDER BY ClosePrice) AS rn,
               COUNT(*) OVER () AS cnt
        FROM california_sold
        WHERE City = %s
          AND PropertyType = 'Residential'
          AND CloseDate <= CURDATE()
          AND CloseDate >= DATE_SUB(CURDATE(), INTERVAL %s MONTH)
          AND ClosePrice IS NOT NULL
    ) ranked
    WHERE rn IN (FLOOR((cnt + 1) / 2), CEIL((cnt + 1) / 2))
"""


def get_city_stats(city: str, months: int = 12) -> dict:
    """
    Single-city market snapshot over the trailing `months`: sold count,
    avg/median close price, avg price/sqft, avg days on market, and the
    list-to-close ratio (closing price as a % of list price).
    """
    with get_cursor() as cursor:
        cursor.execute(_CITY_STATS_QUERY, (city, months))
        stats = cursor.fetchone()
        cursor.execute(_MEDIAN_QUERY, (city, months))
        median_row = cursor.fetchone()

    stats["median_close_price"] = (
        int(median_row["median_close_price"])
        if median_row and median_row["median_close_price"] is not None
        else None
    )
    stats["city"] = city
    stats["months"] = months
    return stats


_TREND_QUERY = text("""
    SELECT
        DATE_FORMAT(CloseDate, '%Y-%m') AS month,
        COUNT(*) AS sales,
        ROUND(AVG(ClosePrice), 0) AS avg_price,
        ROUND(AVG(DaysOnMarket), 1) AS avg_dom
    FROM california_sold
    WHERE City = :city
      AND PropertyType = 'Residential'
      AND CloseDate <= CURDATE()
      AND CloseDate >= DATE_SUB(CURDATE(), INTERVAL :months MONTH)
    GROUP BY DATE_FORMAT(CloseDate, '%Y-%m')
    ORDER BY month
""")


def get_price_trend(city: str, months: int = 24) -> pd.DataFrame:
    """Month-over-month sales count, avg price, avg DOM, and % price change for a city."""
    df = pd.read_sql(_TREND_QUERY, _get_engine(), params={"city": city, "months": months})
    df["price_change_pct"] = df["avg_price"].pct_change() * 100
    return df


def format_market_summary(city: str, months: int = 12) -> str:
    """Render get_city_stats() + the latest trend point as a readable answer."""
    stats = get_city_stats(city, months=months)
    if not stats["sold_count"]:
        return f"No sold comps found for {city} in the last {months} months."

    trend = get_price_trend(city, months=months)
    trend_line = ""
    if len(trend) >= 2:
        change = trend["price_change_pct"].iloc[-1]
        if pd.notna(change):
            direction = "up" if change >= 0 else "down"
            trend_line = f" Prices are {direction} {abs(change):.1f}% month-over-month."

    return (
        f"{city}: {stats['sold_count']} homes sold in the last {months} months. "
        f"Median close price ${stats['median_close_price']:,} "
        f"(avg ${stats['avg_close_price']:,.0f}, ${stats['avg_price_per_sqft']:,.0f}/sqft). "
        f"Averaging {stats['avg_dom']:.0f} days on market, closing at "
        f"{stats['list_to_close_pct']:.1f}% of list price.{trend_line}"
    )
