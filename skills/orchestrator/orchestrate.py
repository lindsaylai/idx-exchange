"""
Week 9: Multi-Agent Orchestration.

Classifies each incoming message's intent and routes it to the specialized
skill(s) that handle it, merging results for mixed-intent queries. Per the
handbook's Agent Registry (Week 9), this fans out to:

    search     -> property-search   (Week 2-4: structured filters, session memory)
    semantic   -> semantic-search   (Week 6: fuzzy/descriptive queries)
    market     -> market-stats      (Week 5: aggregations over california_sold)
    recommend  -> recommendation    (Week 7: similar listings + comp validation)
    knowledge  -> rag-knowledge     (Week 8: definitional/schema questions)
    mixed      -> search + market in parallel, merged

emailDraftAgent isn't in this registry -- it's Week 11, not yet built (see
docs/architecture.md's roadmap).

Intent classification is a keyword/regex heuristic, same style as
parse_query.parse_property_query(), rather than an LLM call: routing five
well-separated skills doesn't need one, and it keeps this project's only
paid-API dependency (Gemini) confined to rag-knowledge's generation step,
consistent with README's Tech Stack notes.
"""

import concurrent.futures
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "property-search"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "market-stats"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "semantic-search"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "recommendation"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "rag-knowledge"))

from parse_query import parse_property_query
from session import getSession, handleMessage
from market_stats import format_market_summary
from semantic_search import semantic_search, format_semantic_result
from recommend import find_similar_listings, format_similar_listing
from rag import rag_answer, format_rag_answer

INTENTS = ("search", "semantic", "market", "recommend", "knowledge", "mixed")

# Order of precedence when classifying -- see classify_intent()'s docstring
# for the reasoning behind each branch. Each regex is a set of surface
# patterns pulled from the handbook's own example queries for that week,
# not an exhaustive NLU model -- see the orchestrator's SKILL.md for the
# known edge cases this heuristic doesn't handle.
_KNOWLEDGE_RE = re.compile(
    r"\bwhat\b.*\b(does|is|are|mean|columns?|fields?)\b|\bdefine\b|\bexplain\b|\bmeaning of\b",
    re.IGNORECASE,
)
_MARKET_RE = re.compile(
    r"\bmarket\b|\btrend(s|ing)?\b|\brising\b|\bfalling\b|\bappreciat|\bdepreciat|"
    r"\bgood time to (buy|sell)\b|\bdays on market\b|\bdom\b|\bprice per (sq ?ft|square foot)\b|"
    r"\bmedian price\b|\baverage price\b|\blist-to-close\b|\bbuyer'?s market\b|\bseller'?s market\b",
    re.IGNORECASE,
)
_RECOMMEND_RE = re.compile(
    r"\bsimilar to\b|\blike this (one|listing)\b|\bcomparable (to|homes)\b|\bmore like\b|"
    r"\bpriced fairly\b|\bgood deal\b|\bcomps for\b",
    re.IGNORECASE,
)
# Strong, filterable signals -- if any of these fire, the message names a
# hard constraint property-search can actually query on.
_HARD_FILTER_RE = re.compile(
    r"under \$|\$[\d,]+|\d+[\s-]*(bed|beds|bedroom|bedrooms)\b|\d+(?:\.\d+)?[\s-]*(bath|baths|bathroom)\b|"
    r"\bpool\b|\bfor sale\b|\b(condo|condominium|townhome|townhouse|single family|duplex|land)\b",
    re.IGNORECASE,
)
# Weak signal -- a request verb plus a generic property noun, with no hard
# filter attached (e.g. "Show me quiet properties away from the road").
# Deliberately not sufficient on its own to mean "search": the handbook's
# own semantic-search examples use this same generic phrasing.
_REQUEST_VERB_RE = re.compile(r"\b(find|show me|search for|looking for|give me|any)\b", re.IGNORECASE)
_PROPERTY_NOUN_RE = re.compile(
    r"\b(homes?|houses?|condos?|condominiums?|townhomes?|townhouses?|propert(y|ies)|listings?|land)\b",
    re.IGNORECASE,
)
_SEMANTIC_HINT_RE = re.compile(
    r"\bcozy\b|\bcharming\b|\bfixer.?upper\b|\bpotential\b|\bnatural light\b|\bquiet\b|"
    r"\bcharacter\b|\bmodern kitchen\b|\bsomething (with|like)\b",
    re.IGNORECASE,
)
# Loose "in <Capitalized word>" check used only to prefer "market" over the
# generic "what is...?" knowledge pattern when a place is actually named
# (e.g. "What's the average price per sq ft in Pasadena?" vs. the
# place-agnostic "What is a list-to-close ratio?"). Not used for precise
# city extraction -- that's parse_property_query()'s job.
_CITY_MENTION_RE = re.compile(r"\bin\s+[A-Z][a-zA-Z]+")

_LISTING_ID_RE = re.compile(r"\b(\d{6,})\b")


def classify_intent(message: str) -> str:
    """
    Return one of INTENTS for a free-text message.

    "mixed" fires when a message both requests listings (a hard filter, or
    a request verb + property noun) and carries a market signal in the same
    breath -- the handbook's own example: "Find me affordable homes in
    Pasadena and tell me whether prices are rising."

    A request-verb-only match ("show me ... properties") with no hard
    filter and a competing descriptive/vibe cue is read as "semantic"
    instead of "search" -- see _REQUEST_VERB_RE's comment.
    """
    has_hard_filter = bool(_HARD_FILTER_RE.search(message))
    has_request_phrase = bool(_REQUEST_VERB_RE.search(message) and _PROPERTY_NOUN_RE.search(message))
    has_semantic_hint = bool(_SEMANTIC_HINT_RE.search(message))
    has_market = bool(_MARKET_RE.search(message))
    names_city = bool(_CITY_MENTION_RE.search(message))

    is_semantic_leaning = has_request_phrase and not has_hard_filter and has_semantic_hint
    is_search = has_hard_filter or (has_request_phrase and not is_semantic_leaning)

    if is_search and has_market:
        return "mixed"
    if _RECOMMEND_RE.search(message):
        return "recommend"
    if has_market and names_city:
        return "market"
    if _KNOWLEDGE_RE.search(message):
        return "knowledge"
    if has_market:
        return "market"
    if is_search:
        return "search"
    if has_semantic_hint:
        return "semantic"
    return "search"  # ambiguous message: same default a lone property-search skill would give


# Lenient fallback for pulling a city out of a message that names one
# without the clean phrasing parse_property_query() expects ("...in
# Pasadena and tell me..." vs. its "...in Pasadena under $..." shape) --
# just the run of capitalized word(s) right after "in ".
_CITY_EXTRACT_RE = re.compile(r"\bin\s+((?:[A-Z][a-zA-Z]+\s*){1,3})")


def _extract_city(message: str, user_id: str | None) -> str | None:
    city = parse_property_query(message).get("city")
    if not city:
        match = _CITY_EXTRACT_RE.search(message)
        city = match.group(1).strip() if match else None
    if city:
        return city
    if user_id:
        return getSession(user_id).get("city")
    return None


def _extract_listing_id(message: str, user_id: str | None):
    """A bare MLS/listing number in the message wins; otherwise fall back
    to the first result from that user's last property-search, matching
    the handbook's `recommendationAgent(session.lastResults?.[0])`."""
    match = _LISTING_ID_RE.search(message)
    if match:
        return match.group(1)
    if user_id:
        last_results = getSession(user_id).get("lastResults")
        if last_results:
            return last_results[0]["L_ListingID"]
    return None


def _format_combined(search_reply: str, market_reply: str) -> str:
    return f"{search_reply}\n\n---\n\n{market_reply}"


def orchestrate(user_id: str, message: str) -> dict:
    """
    Classify `message`'s intent and route it to the matching skill(s).

    Returns {"intent": <one of INTENTS>, "response": <display-ready string>}.
    """
    intent = classify_intent(message)

    if intent == "mixed":
        city = _extract_city(message, user_id)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            search_future = pool.submit(handleMessage, user_id, message)
            market_future = pool.submit(format_market_summary, city) if city else None
            search_reply = search_future.result()
            market_reply = (
                market_future.result()
                if market_future is not None
                else "(couldn't tell which city to pull market trends for -- try naming one)"
            )
        return {"intent": "mixed", "response": _format_combined(search_reply, market_reply)}

    if intent == "market":
        city = _extract_city(message, user_id)
        if not city:
            return {"intent": "market", "response": "Which city's market are you asking about?"}
        return {"intent": "market", "response": format_market_summary(city)}

    if intent == "recommend":
        listing_id = _extract_listing_id(message, user_id)
        if listing_id is None:
            return {
                "intent": "recommend",
                "response": "Which listing? Search for one first, then ask for similar listings.",
            }
        try:
            hits = find_similar_listings(listing_id, top_k=5)
        except ValueError as e:
            return {"intent": "recommend", "response": str(e)}
        if not hits:
            return {"intent": "recommend", "response": "No similar active listings found."}
        return {"intent": "recommend", "response": "\n\n".join(format_similar_listing(h) for h in hits)}

    if intent == "knowledge":
        result = rag_answer(message)
        return {"intent": "knowledge", "response": format_rag_answer(result)}

    if intent == "semantic":
        hits = semantic_search(message, top_k=5)
        if not hits:
            return {
                "intent": "semantic",
                "response": "No matching listings found -- run semantic-search's build_index() first, "
                "or try a broader description.",
            }
        return {"intent": "semantic", "response": "\n\n".join(format_semantic_result(h) for h in hits)}

    # default: "search"
    return {"intent": "search", "response": handleMessage(user_id, message)}
