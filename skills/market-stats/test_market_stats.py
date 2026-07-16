import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from market_stats import get_city_market_summary, get_city_stats, get_price_trend, format_market_summary


def check(label, condition):
    print(f"{'PASS' if condition else 'FAIL'}: {label}")
    return condition


results = []

# --- multi-city summary ---
summary = get_city_market_summary(months=12, limit=5)
results.append(check("summary returns rows", len(summary) > 0))
results.append(check("summary capped at `limit`", len(summary) <= 5))
results.append(check(
    "summary sorted by sold_count descending",
    all(a["sold_count"] >= b["sold_count"] for a, b in zip(summary, summary[1:])),
))
results.append(check(
    "summary rows have the expected fields",
    all(
        row["avg_close_price"] is not None
        and row["avg_dom"] is not None
        and row["list_to_close_pct"] is not None
        for row in summary
    ),
))

# --- single-city stats ---
stats = get_city_stats("San Diego", months=12)
results.append(check("San Diego has sold comps", stats["sold_count"] > 0))
results.append(check("San Diego has a median close price", stats["median_close_price"] is not None))
results.append(check(
    "median is between the average and a sane bound (not None/zero from a bad query)",
    0 < stats["median_close_price"] < stats["avg_close_price"] * 3,
))

no_stats = get_city_stats("Nowhereville", months=12)
results.append(check("unmatched city returns a zero count, not an error", no_stats["sold_count"] == 0))
results.append(check("unmatched city has no median (avoids division by zero)", no_stats["median_close_price"] is None))

# --- price trend ---
trend = get_price_trend("San Diego", months=12)
results.append(check("trend has rows", len(trend) > 0))
results.append(check("trend months are in ascending order", list(trend["month"]) == sorted(trend["month"])))
results.append(check("trend's first row has no prior month to compare (NaN % change)", trend["price_change_pct"].iloc[0] != trend["price_change_pct"].iloc[0]))

# --- formatted natural-language summary ---
answer = format_market_summary("San Diego", months=12)
results.append(check("formatted summary mentions the city", "San Diego" in answer))
results.append(check("formatted summary includes a median price", "Median close price $" in answer))
results.append(check("formatted summary includes days on market", "days on market" in answer))
results.append(check("formatted summary includes the list-to-close ratio", "% of list price" in answer))

no_data_answer = format_market_summary("Nowhereville", months=12)
results.append(check("no-data city gets a clear message, not a crash", "No sold comps found" in no_data_answer))

print(f"\n{sum(results)}/{len(results)} tests passed")
