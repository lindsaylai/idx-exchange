import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from parse_query import parse_property_query


def test(query, expected):
    result = parse_property_query(query)
    failures = []
    for key, val in expected.items():
        if result.get(key) != val:
            failures.append(f"  {key}: expected {val!r}, got {result.get(key)!r}")
    if failures:
        print(f"FAIL: {query!r}")
        for f in failures:
            print(f)
    else:
        print(f"PASS: {query!r}")
    return len(failures) == 0


tests = [
    (
        "Show me 3-bedroom condos in Irvine under $1.5M with a pool.",
        {"city": "Irvine", "maxPrice": 1_500_000, "beds": 3, "type": "Condominium", "pool": "True"},
    ),
    (
        "Find single family homes in Pasadena under $800k with at least 4 beds",
        {"city": "Pasadena", "maxPrice": 800_000, "beds": 4, "type": "SingleFamilyResidence"},
    ),
    (
        "2 bed 2 bath condo in Santa Monica under $900,000",
        {"city": "Santa Monica", "maxPrice": 900_000, "beds": 2, "baths": 2.0, "type": "Condominium"},
    ),
    (
        "Townhomes in Long Beach with a view",
        {"city": "Long Beach", "type": "Townhouse", "hasView": "True"},
    ),
    (
        "Homes in San Diego under $1.2 million with 2000 sqft",
        {"city": "San Diego", "maxPrice": 1_200_000, "sqft": 2000},
    ),
    (
        "Show me SFR listings in Glendale with HOA under $300",
        {"city": "Glendale", "type": "SingleFamilyResidence", "maxHOA": 300, "maxPrice": None},
    ),
    (
        "4 bedroom houses in Riverside under $600k with a pool and a view",
        {"city": "Riverside", "maxPrice": 600_000, "beds": 4, "pool": "True", "hasView": "True"},
    ),
    (
        "Condos in Beverly Hills under $2.5M with at least 2.5 baths",
        {"city": "Beverly Hills", "maxPrice": 2_500_000, "type": "Condominium", "baths": 2.5},
    ),
    (
        "Any land for sale in Malibu",
        {"city": "Malibu", "type": "UnimprovedLand"},
    ),
    (
        "3 bed 2 bath homes in Burbank under $750,000 with at least 1500 sq ft",
        {"city": "Burbank", "maxPrice": 750_000, "beds": 3, "baths": 2.0, "sqft": 1500},
    ),
    (
        "Townhouse in Torrance under $800k",
        {"city": "Torrance", "maxPrice": 800_000, "type": "Townhouse"},
    ),
    (
        "Find me a condo in Newport Beach with ocean view under $3 million",
        {"city": "Newport Beach", "maxPrice": 3_000_000, "type": "Condominium", "hasView": "True"},
    ),
    # bare budget mentions (no "under") — e.g. a direct answer to "what's your budget?"
    ("2M", {"maxPrice": 2_000_000}),
    ("2mil", {"maxPrice": 2_000_000}),
    ("budget is 2 million", {"maxPrice": 2_000_000}),
    ("about $900,000", {"maxPrice": 900_000}),
    # common city abbreviations
    ("hi i need homes in sf, ca", {"city": "San Francisco"}),
    ("homes in la under $900k", {"city": "Los Angeles", "maxPrice": 900_000}),
    # type keywords must respect word boundaries, not match as a substring of
    # an unrelated word (e.g. "land" inside "oakland") or fail on plurals
    ("oakland", {"type": None}),
    ("condos in oakland", {"type": "Condominium"}),
    ("townhouses in torrance", {"type": "Townhouse"}),
]

passed = sum(test(q, exp) for q, exp in tests)
print(f"\n{passed}/{len(tests)} tests passed")
