"""
Week 4: Conversational Property Search Agent.

Turns the single-turn search from Week 3 into a multi-turn conversation:
each message's parsed filters are merged into a per-user session. Until
the first search has run, missing must-have filters (city, budget, type)
are asked for one at a time, matching the handbook's example flow. Once
results exist, every new message is treated as a refinement and
immediately re-searches with the updated filters.
"""

import re

from parse_query import parse_property_query, CITY_ABBREVIATIONS
from search_listings import searchActiveListings, format_listing_card

_FILTER_KEYS = ("city", "maxPrice", "beds", "baths", "sqft", "type", "pool", "hasView", "maxHOA")

_sessions: dict[str, dict] = {}


def _default_session() -> dict:
    session = {key: None for key in _FILTER_KEYS}
    session["lastResults"] = None
    session["conversationStep"] = 0
    session["awaiting"] = None
    return session


def getSession(user_id: str) -> dict:
    if user_id not in _sessions:
        _sessions[user_id] = _default_session()
    return _sessions[user_id]


def updateSession(user_id: str, updates: dict) -> dict:
    session = getSession(user_id)
    session.update(updates)
    return session


def clearSession(user_id: str) -> None:
    _sessions.pop(user_id, None)


def _merge_filters(session: dict, message: str) -> None:
    parsed = parse_property_query(message)
    for key in _FILTER_KEYS:
        if parsed.get(key) is not None:
            session[key] = parsed[key]


def _apply_pending_answer(session: dict, message: str) -> None:
    """
    parse_property_query() expects full sentences ("in Oakland", "under
    $900k") and returns None for bare replies like a one-word answer to
    "What city are you interested in?". If the field we just asked about is
    still unset after the general-purpose parse, treat the raw reply as a
    direct answer to that specific question instead of asking it again.
    """
    awaiting = session.get("awaiting")
    stripped = message.strip()

    if awaiting == "city" and session["city"] is None and stripped:
        city = stripped.title()
        session["city"] = CITY_ABBREVIATIONS.get(city.lower(), city)
    elif awaiting == "maxPrice" and session["maxPrice"] is None:
        if re.fullmatch(r"\$?[\d,]+(?:\.\d+)?", stripped):
            session["maxPrice"] = int(float(stripped.replace("$", "").replace(",", "")))


def _search_and_format(session: dict) -> str:
    filters = {key: session[key] for key in _FILTER_KEYS}
    results = searchActiveListings(filters, page=1, limit=5)
    session["lastResults"] = results
    if not results:
        return "No listings matched — try widening your search."
    return "\n\n".join(format_listing_card(row) for row in results)


def handleMessage(user_id: str, message: str) -> str:
    """Process one turn of conversation and return the agent's reply."""
    session = getSession(user_id)
    _merge_filters(session, message)
    _apply_pending_answer(session, message)
    session["conversationStep"] += 1

    # Once we've searched at least once, treat every new message as a refinement.
    if session["lastResults"] is not None:
        session["awaiting"] = None
        return _search_and_format(session)

    if session["city"] is None:
        session["awaiting"] = "city"
        return "What city are you interested in?"
    if session["maxPrice"] is None:
        session["awaiting"] = "maxPrice"
        return "What is your budget?"
    if session["type"] is None:
        session["awaiting"] = "type"
        return "Any preferences — condo, townhome, or single family?"

    session["awaiting"] = None
    return _search_and_format(session)
