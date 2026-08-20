import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "property-search"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "semantic-search"))

from orchestrate import classify_intent, orchestrate
from session import clearSession, getSession
from semantic_search import build_index as build_semantic_index


def check(label, condition):
    print(f"{'PASS' if condition else 'FAIL'}: {label}")
    return condition


results = []

# A real active Sacramento listing, same one recommendation's own test suite
# uses -- looked up directly against the DB.
SACRAMENTO_LISTING_ID = 1018767064

# --- classify_intent: one case per intent, plus the handbook's own examples ---
CLASSIFY_CASES = [
    ("Show me 3-bedroom condos in Irvine under $1.5M with a pool.", "search"),
    ("Find homes in Pasadena with a pool", "search"),
    ("Any land for sale in Malibu?", "search"),
    ("Find me something with a modern kitchen and lots of natural light", "semantic"),
    ("Show me quiet properties away from the road", "semantic"),
    ("I want a fixer-upper with potential in the hills", "semantic"),
    ("Is now a good time to buy in San Diego?", "market"),
    ("What is the average price per sq ft in Pasadena?", "market"),
    ("How's the market in Oakland compared to last month?", "market"),
    ("Show me listings similar to this one", "recommend"),
    ("Is this listing priced fairly?", "recommend"),
    ("Find comparable homes to 4200 Amble Court", "recommend"),
    ("What does DOM mean?", "knowledge"),
    ("What columns are in california_sold?", "knowledge"),
    ("What is a list-to-close ratio?", "knowledge"),
    ("Find me affordable homes in Pasadena and tell me whether prices are rising.", "mixed"),
]
for message, expected in CLASSIFY_CASES:
    results.append(check(f"classify_intent({expected!r}): {message!r}", classify_intent(message) == expected))

# --- orchestrate(): search routes to property-search's session flow ---
clearSession("orch-search")
search_result = orchestrate("orch-search", "Find homes in Irvine under $1.5M")
results.append(check("search intent tagged correctly", search_result["intent"] == "search"))
results.append(check(
    "search response continues the property-search conversation (asks for the next missing filter)",
    "?" in search_result["response"] or "Irvine" in search_result["response"],
))

# --- orchestrate(): market routes to market-stats with a city pulled from free text ---
market_result = orchestrate("orch-market", "Is now a good time to buy in San Diego?")
results.append(check("market intent tagged correctly", market_result["intent"] == "market"))
results.append(check("market response names the city", "San Diego" in market_result["response"]))
results.append(check("market response includes a median price", "Median close price $" in market_result["response"]))

# --- orchestrate(): market with no resolvable city asks instead of crashing ---
no_city_result = orchestrate("orch-market-2", "How's the market doing lately?")
results.append(check(
    "market intent with no city asks which city, doesn't crash",
    no_city_result["intent"] == "market" and "city" in no_city_result["response"].lower(),
))

# --- orchestrate(): knowledge routes to rag-knowledge, grounded and sourced ---
for question in ("What does DOM mean?", "What columns are in california_sold?", "What is a list-to-close ratio?"):
    knowledge_result = orchestrate("orch-knowledge", question)
    results.append(check(f"knowledge intent tagged correctly for {question!r}", knowledge_result["intent"] == "knowledge"))
    results.append(check(f"knowledge response for {question!r} cites sources", "Sources:" in knowledge_result["response"]))

# --- orchestrate(): recommend, given an explicit listing id in the message ---
recommend_result = orchestrate("orch-recommend", f"Find comparable homes to {SACRAMENTO_LISTING_ID}")
results.append(check("recommend intent tagged correctly", recommend_result["intent"] == "recommend"))
results.append(check(
    "recommend response isn't the no-listing fallback",
    "Which listing?" not in recommend_result["response"],
))

# --- orchestrate(): recommend falls back to the user's last search result ---
clearSession("orch-recommend-2")
getSession("orch-recommend-2")["lastResults"] = [{"L_ListingID": str(SACRAMENTO_LISTING_ID)}]
session_recommend_result = orchestrate("orch-recommend-2", "Show me listings similar to this one")
results.append(check(
    "recommend with no id in the message falls back to session.lastResults[0]",
    session_recommend_result["intent"] == "recommend" and "Which listing?" not in session_recommend_result["response"],
))

# --- orchestrate(): recommend with nothing to go on asks instead of crashing ---
clearSession("orch-recommend-3")
no_listing_result = orchestrate("orch-recommend-3", "Is this listing priced fairly?")
results.append(check(
    "recommend with no id and no session history asks which listing, doesn't crash",
    no_listing_result["intent"] == "recommend" and "Which listing?" in no_listing_result["response"],
))

# --- orchestrate(): semantic routes to semantic-search (needs a local index) ---
build_semantic_index(limit=200)
semantic_result = orchestrate("orch-semantic", "I want a fixer-upper with potential in the hills")
results.append(check("semantic intent tagged correctly", semantic_result["intent"] == "semantic"))
results.append(check("semantic response returns at least one match", " match)" in semantic_result["response"]))

# --- orchestrate(): mixed runs search + market together and merges both ---
clearSession("orch-mixed")
mixed_result = orchestrate("orch-mixed", "Find me affordable homes in Pasadena and tell me whether prices are rising.")
results.append(check("mixed intent tagged correctly", mixed_result["intent"] == "mixed"))
results.append(check("mixed response includes the market leg (Pasadena stats)", "Pasadena" in mixed_result["response"]))
results.append(check("mixed response merges both legs with a separator", "---" in mixed_result["response"]))
results.append(check(
    "mixed's search leg doesn't re-ask for the city the message just named",
    "What city" not in mixed_result["response"],
))
results.append(check(
    "the pre-seeded city is on the session for the next turn",
    getSession("orch-mixed").get("city") == "Pasadena",
))

print(f"\n{sum(results)}/{len(results)} tests passed")
