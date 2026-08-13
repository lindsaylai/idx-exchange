"""
Week 12: tests for orchestrator's email intent -- the draft-then-approve
flow as two separate WhatsApp turns. send_approved_email is monkeypatched
at the orchestrate module level throughout (same pattern test_whatsapp.py
uses for orchestrate() itself), so NONE of these tests can ever place a
real outbound call, regardless of what's in .env.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "property-search"))

import orchestrate
from orchestrate import classify_intent, orchestrate as run
from session import clearSession, getSession

SACRAMENTO_LISTING_ID = 1018767064
TEST_ADDRESS = "buyer@example.com"


def check(label, condition):
    print(f"{'PASS' if condition else 'FAIL'}: {label}")
    return condition


results = []

# --- a spy in place of the real send, for the whole file ---
_sent_calls = []


def _spy_send(draft, approved, transport=None):
    _sent_calls.append((draft, approved))
    return {**draft, "status": "sent"}


_original_send = orchestrate.send_approved_email
orchestrate.send_approved_email = _spy_send


# =============================================================================
# classify_intent(): "email" wins over every other intent
# =============================================================================

EMAIL_CLASSIFY_CASES = [
    "Email me a market report for San Diego",
    "Send an email listing alert for homes in Irvine under $1.5M",
    "Email me a summary of listing 1018767064",
    "Email me homes similar to listing 1018767064",
    "Can you e-mail that market report to me",
]
for message in EMAIL_CLASSIFY_CASES:
    results.append(check(f"classify_intent tags {message!r} as email", classify_intent(message) == "email"))

# non-email messages are unaffected by the new branch
results.append(check("a plain search query is still 'search'", classify_intent("Find homes in Pasadena with a pool") == "search"))
results.append(check("a plain market query is still 'market'", classify_intent("Is now a good time to buy in San Diego?") == "market"))


# =============================================================================
# Full draft-then-approve flow, per content builder
# =============================================================================

# --- market report ---
clearSession("email-market")
_sent_calls.clear()
r1 = run("email-market", f"Email {TEST_ADDRESS} a market report for San Diego")
results.append(check("market-report draft intent tagged 'email'", r1["intent"] == "email"))
results.append(check("market-report draft preview names the city", "San Diego" in r1["response"]))
results.append(check("market-report draft preview asks for yes/no", "Reply 'yes'" in r1["response"]))
results.append(check("a pending draft is now stashed on the session", getSession("email-market").get("pendingEmailDraft") is not None))
results.append(check("nothing was sent yet", len(_sent_calls) == 0))

r2 = run("email-market", "yes")
results.append(check("approving sends exactly once", len(_sent_calls) == 1))
results.append(check("approve reply confirms the recipient", TEST_ADDRESS in r2["response"]))
results.append(check("pending draft is cleared after sending", getSession("email-market").get("pendingEmailDraft") is None))

# --- decline clears the draft without sending ---
clearSession("email-decline")
_sent_calls.clear()
run("email-decline", f"Email {TEST_ADDRESS} a market report for San Diego")
r = run("email-decline", "no")
results.append(check("declining doesn't send", len(_sent_calls) == 0))
results.append(check("decline reply confirms nothing was sent", "nothing was sent" in r["response"]))
results.append(check("pending draft is cleared after declining", getSession("email-decline").get("pendingEmailDraft") is None))

# --- listing alert: a price filter must win over the bare-listing-id path
# ("$1,500,000" also matches the 6+-digit listing-id regex) ---
clearSession("email-listing")
_sent_calls.clear()
r = run("email-listing", f"Email {TEST_ADDRESS} new listings in Irvine under $1500000")
results.append(check("a price filter routes to listing alert, not property summary", "New Listing Alert" in r["response"]))
results.append(check("...not misread as 'listing #1500000'", "Property Summary" not in r["response"]))

# --- property summary: a bare listing id with no hard filter ---
clearSession("email-summary")
r = run("email-summary", f"Email {TEST_ADDRESS} a summary of listing {SACRAMENTO_LISTING_ID}")
results.append(check("bare listing id routes to property summary", "Property Summary" in r["response"]))

# --- recommendation digest: explicit listing id ---
clearSession("email-digest")
r = run("email-digest", f"Email {TEST_ADDRESS} homes similar to listing {SACRAMENTO_LISTING_ID}")
results.append(check("'similar to' phrasing routes to recommendation digest", "Recommended For You" in r["response"] or "similar" in r["response"].lower()))

# --- recommendation digest: falls back to session.lastResults when no id in the message ---
clearSession("email-digest-2")
getSession("email-digest-2")["lastResults"] = [{"L_ListingID": str(SACRAMENTO_LISTING_ID)}]
r = run("email-digest-2", f"Email {TEST_ADDRESS} me some similar listings")
results.append(check("recommend-digest email falls back to session.lastResults[0]", "Which listing?" not in r["response"] and "Search for one first" not in r["response"]))

# --- no address in the message: asks instead of guessing/crashing ---
clearSession("email-no-address")
r = run("email-no-address", "Email me a market report for San Diego")
results.append(check("missing address asks for one", "email address" in r["response"].lower()))
results.append(check("...and doesn't stash a pending draft", getSession("email-no-address").get("pendingEmailDraft") is None))

# --- no city/filter/listing: asks what to send ---
clearSession("email-ambiguous")
r = run("email-ambiguous", f"Email {TEST_ADDRESS} something")
results.append(check("an ambiguous email request asks what to send", "would you like emailed" in r["response"]))

# --- an unrelated message while a draft is pending falls through normally,
# and the pending draft survives untouched (neither sent nor discarded) ---
clearSession("email-fallthrough")
_sent_calls.clear()
run("email-fallthrough", f"Email {TEST_ADDRESS} a market report for San Diego")
r = run("email-fallthrough", "What does DOM mean?")
results.append(check("a non-yes/no message during a pending draft is routed normally", r["intent"] == "knowledge"))
results.append(check("...without sending the pending draft", len(_sent_calls) == 0))
results.append(check("...and the draft is still pending afterward", getSession("email-fallthrough").get("pendingEmailDraft") is not None))


# =============================================================================
# Restore the real send_approved_email so this module doesn't leave the
# orchestrate module monkeypatched for anything imported after it.
# =============================================================================
orchestrate.send_approved_email = _original_send

print(f"\n{sum(results)}/{len(results)} tests passed")
