"""
Week 9: Multi-Agent Orchestration. Week 12: capstone integration adds the
email intent below.

Classifies each incoming message's intent and routes it to the specialized
skill(s) that handle it, merging results for mixed-intent queries. Per the
handbook's Agent Registry (Week 9) plus emailDraftAgent (Week 11, wired in
for the Week 12 capstone), this fans out to:

    search     -> property-search   (Week 2-4: structured filters, session memory)
    semantic   -> semantic-search   (Week 6: fuzzy/descriptive queries)
    market     -> market-stats      (Week 5: aggregations over california_sold)
    recommend  -> recommendation    (Week 7: similar listings + comp validation)
    knowledge  -> rag-knowledge     (Week 8: definitional/schema questions)
    email      -> email-agent       (Week 11: draft-then-approve, two WhatsApp turns)
    mixed      -> search + market in parallel, merged

Intent classification is a keyword/regex heuristic, same style as
parse_query.parse_property_query(), rather than an LLM call: routing six
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
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "email-agent"))

from parse_query import parse_property_query
from session import getSession, handleMessage
from market_stats import format_market_summary
from semantic_search import semantic_search, format_semantic_result
from recommend import find_similar_listings, format_similar_listing
from rag import rag_answer, format_rag_answer
from email_agent import (
    draft_market_report,
    draft_listing_alert,
    draft_property_summary,
    draft_recommendation_digest,
    send_approved_email,
)

INTENTS = ("search", "semantic", "market", "recommend", "knowledge", "email", "mixed")

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

# Checked first, before every other branch: "email me a market report for
# San Diego" carries market signals too, but the overriding intent is
# unambiguous -- the user wants it emailed, not recited back. A message
# mentioning "email"/"e-mail" for any other reason in this domain is
# vanishingly unlikely, so no further disambiguation is done here.
_EMAIL_INTENT_RE = re.compile(r"\be-?mail\b", re.IGNORECASE)


def classify_intent(message: str) -> str:
    """
    Return one of INTENTS for a free-text message.

    "email" wins over every other intent when the message mentions
    email/e-mail at all -- see _EMAIL_INTENT_RE's comment.

    "mixed" fires when a message both requests listings (a hard filter, or
    a request verb + property noun) and carries a market signal in the same
    breath -- the handbook's own example: "Find me affordable homes in
    Pasadena and tell me whether prices are rising."

    A request-verb-only match ("show me ... properties") with no hard
    filter and a competing descriptive/vibe cue is read as "semantic"
    instead of "search" -- see _REQUEST_VERB_RE's comment.
    """
    if _EMAIL_INTENT_RE.search(message):
        return "email"

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
# Pasadena and tell me..." vs. its "...in Pasadena under $..." shape, or
# "a market report for San Diego" -- Week 12's email intent's phrasing) --
# just the run of capitalized word(s) right after "in "/"for ".
_CITY_EXTRACT_RE = re.compile(r"\b(?:in|for)\s+((?:[A-Z][a-zA-Z]+\s*){1,3})")


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


# --- Week 12: email draft-then-approve, as two separate WhatsApp turns ----

_EMAIL_ADDRESS_RE = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_APPROVE_RE = re.compile(r"^\s*(yes|yep|yeah|send it|approved?|confirm(ed)?|go ahead|do it)[.!]?\s*$", re.IGNORECASE)
_DECLINE_RE = re.compile(r"^\s*(no|nope|cancel|don'?t send|discard|never ?mind)[.!]?\s*$", re.IGNORECASE)
_HTML_PARAGRAPH_BOUNDARY_RE = re.compile(r"</p>\s*<p>", re.IGNORECASE)
_HTML_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _extract_email_address(message: str) -> str | None:
    match = _EMAIL_ADDRESS_RE.search(message)
    return match.group(0) if match else None


def _format_draft_preview(draft: dict) -> str:
    """Plain-text rendering of an HTML email draft for a WhatsApp bubble."""
    # Order matters: collapse </p><p> boundaries into a blank line *before*
    # stripping tags, otherwise adjacent cards (each its own <p>...</p>,
    # per email_agent.py's content builders) run together with no separator.
    body = _HTML_PARAGRAPH_BOUNDARY_RE.sub("\n\n", draft["body"])
    body = _HTML_BR_RE.sub("\n", body)
    body = _HTML_TAG_RE.sub("", body).strip()
    return (
        f"Draft ready -- to: {draft['to']}, subject: {draft['subject']}\n\n"
        f"{body}\n\n"
        f"Reply 'yes' to send, or 'no' to discard."
    )


def _handle_pending_draft_reply(message: str, pending_draft: dict, session: dict) -> dict | None:
    """
    If `message` is a clear yes/no reply to `pending_draft`, act on it and
    return a result dict. Otherwise return None so the caller falls through
    to normal intent classification -- e.g. the user changed their mind and
    asked for something else instead of replying yes/no; the pending draft
    is left in place either way (a fresh "email ..." request will replace
    it; anything else just leaves it there for a later yes/no).
    """
    stripped = message.strip()
    if _APPROVE_RE.match(stripped):
        result = send_approved_email(pending_draft, approved=True)
        session["pendingEmailDraft"] = None
        return {"intent": "email", "response": f"Sent to {result['to']}."}
    if _DECLINE_RE.match(stripped):
        session["pendingEmailDraft"] = None
        return {"intent": "email", "response": "Okay, discarded that draft -- nothing was sent."}
    return None


# Fields checked against parse_property_query()'s output to decide whether
# a message names enough hard filters to be a listing-alert search, as
# opposed to a bare city mention (-> market report instead).
_ALERT_FILTER_KEYS = ("maxPrice", "beds", "baths", "sqft", "type", "pool", "hasView", "maxHOA")


def _handle_email_intent(message: str, user_id: str, session: dict) -> dict:
    """
    Build the right kind of draft for an "email ..." request and stash it
    on the session as pending -- never sends. Which content builder runs is
    decided by the same signals the other intents already use, checked in
    this order:
      1. "similar to" / "comparable" phrasing -> recommendation digest
         (listing id from the message, else the user's last search result)
      2. hard filters (beds/baths/price/type) -> listing alert -- checked
         *before* the bare-listing-id case below, since a price like
         "$1,500,000" also matches the 6+-digit listing-id pattern and
         would otherwise be misread as "email me listing 1500000"
      3. a bare listing id in the message      -> property summary
      4. a named city with no hard filters      -> market report
      5. none of the above                      -> ask what to send
    """
    to = _extract_email_address(message)
    if not to:
        return {"intent": "email", "response": "What email address should I send this to?"}

    parsed = parse_property_query(message)
    has_hard_filter = any(parsed.get(k) is not None for k in _ALERT_FILTER_KEYS)

    try:
        if _RECOMMEND_RE.search(message):
            listing_id = _extract_listing_id(message, user_id)
            if listing_id is None:
                return {
                    "intent": "email",
                    "response": "Which listing should the recommendations be based on? Search for one first.",
                }
            draft = draft_recommendation_digest(to, listing_id)
        elif has_hard_filter:
            draft = draft_listing_alert(to, parsed)
        elif _LISTING_ID_RE.search(message):
            draft = draft_property_summary(to, _LISTING_ID_RE.search(message).group(1))
        else:
            city = _extract_city(message, user_id)
            if not city:
                return {
                    "intent": "email",
                    "response": "What would you like emailed -- a market report, listing alert, "
                    "property summary, or similar-listings digest?",
                }
            draft = draft_market_report(to, city)
    except ValueError as e:
        return {"intent": "email", "response": str(e)}

    session["pendingEmailDraft"] = draft
    return {"intent": "email", "response": _format_draft_preview(draft)}


def orchestrate(user_id: str, message: str) -> dict:
    """
    Classify `message`'s intent and route it to the matching skill(s).

    Returns {"intent": <one of INTENTS>, "response": <display-ready string>}.
    """
    session = getSession(user_id)
    pending_draft = session.get("pendingEmailDraft")
    if pending_draft is not None:
        reply = _handle_pending_draft_reply(message, pending_draft, session)
        if reply is not None:
            return reply

    intent = classify_intent(message)

    if intent == "email":
        return _handle_email_intent(message, user_id, session)

    if intent == "mixed":
        city = _extract_city(message, user_id)
        # Pre-seed the search leg's session city from this skill's own
        # lenient extraction before handleMessage() runs its stricter
        # parse_property_query() pass -- otherwise a phrasing
        # parse_property_query() can't cleanly terminate ("...in Pasadena
        # and tell me...") makes property-search ask "what city?" on the
        # very message that just named one. _merge_filters() only ever
        # *sets* session["city"] when its own parse finds one -- it never
        # clears an already-set value -- so this is safe to pre-seed.
        if city and session.get("city") is None:
            session["city"] = city
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
