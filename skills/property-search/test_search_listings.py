import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from parse_query import parse_property_query
from search_listings import searchActiveListings, getSoldComps, format_listing_card


def check(label, condition):
    print(f"{'PASS' if condition else 'FAIL'}: {label}")
    return condition


results = []

# --- searchActiveListings: parser output feeds straight into the DB query ---
filters = parse_property_query("3-bedroom condos in Irvine under $1.5M with a pool")
listings = searchActiveListings(filters)
results.append(check("Irvine condo search returns rows", len(listings) > 0))
results.append(check(
    "all rows match city/type/beds/price/pool filters",
    all(
        row["L_City"] == "Irvine"
        and row["propertyType"] == "Condominium"
        and row["beds"] >= 3
        and row["L_SystemPrice"] <= 1_500_000
        and row["PoolPrivateYN"] == "1"
        for row in listings
    ),
))
results.append(check(
    "results sorted by price ascending",
    all(a["L_SystemPrice"] <= b["L_SystemPrice"] for a, b in zip(listings, listings[1:])),
))

# --- no filters set -> just the active-listing default ---
empty_filters = parse_property_query("Show me some listings")
default_listings = searchActiveListings(empty_filters, limit=5)
results.append(check("unfiltered search still returns up to `limit` rows", len(default_listings) == 5))

# --- a filter combination with no matches should return an empty list, not error ---
impossible = searchActiveListings({**empty_filters, "city": "Nowhereville"})
results.append(check("unmatched city returns empty list", impossible == []))

# --- pagination: page 2 should pick up where page 1 left off, no overlap ---
page1 = searchActiveListings(empty_filters, page=1, limit=5)
page2 = searchActiveListings(empty_filters, page=2, limit=5)
page1_ids = {row["L_ListingID"] for row in page1}
page2_ids = {row["L_ListingID"] for row in page2}
results.append(check("page 2 has no overlap with page 1", page1_ids.isdisjoint(page2_ids)))

# --- formatted card output for a known listing ---
card = format_listing_card(listings[0])
results.append(check(
    "formatted card includes address, price, and beds/baths",
    listings[0]["L_Address"] in card
    and f"${listings[0]['L_SystemPrice']:,}" in card
    and "bd/" in card,
))

# --- getSoldComps: city-level aggregation over california_sold ---
comps = getSoldComps("San Diego", months=12, limit=10)
results.append(check("San Diego comps returns rows", len(comps) > 0))
results.append(check("all comps are in the requested city", all(row["City"] == "San Diego" for row in comps)))
results.append(check(
    "comps sorted by close date, most recent first",
    all(a["CloseDate"] >= b["CloseDate"] for a, b in zip(comps, comps[1:])),
))

no_comps = getSoldComps("Nowhereville")
results.append(check("unmatched city returns empty comps list", no_comps == []))

print(f"\n{sum(results)}/{len(results)} tests passed")
