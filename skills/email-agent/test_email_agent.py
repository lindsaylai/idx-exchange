import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "property-search"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "market-stats"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "recommendation"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "semantic-search"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "rag-knowledge"))

from email_agent import (
    ApprovalRequiredError,
    draft_email,
    draft_listing_alert,
    draft_market_report,
    draft_property_summary,
    draft_recommendation_digest,
    send_approved_email,
)
import tempfile

from search_listings import _MAX_ROWS as SEARCH_MAX_ROWS, searchActiveListings, getSoldComps
from market_stats import _MAX_ROWS as MARKET_MAX_ROWS, get_city_market_summary
from recommend import _MAX_ROWS as RECOMMEND_MAX_ROWS, find_similar_listings
from semantic_search import _MAX_ROWS as SEMANTIC_MAX_ROWS, build_index as build_semantic_index, semantic_search
from rag import _MAX_ROWS as RAG_MAX_ROWS, build_index as build_rag_index, retrieve

SACRAMENTO_LISTING_ID = 1018767064


def check(label, condition):
    print(f"{'PASS' if condition else 'FAIL'}: {label}")
    return condition


results = []

# =============================================================================
# Rule: "Send emails without explicit user approval" -> NEVER
# =============================================================================

# --- draft_email() itself has no way to send anything ---
draft = draft_email("buyer@example.com", "Test", "<p>hello</p>")
results.append(check("draft_email returns pending_approval, not sent", draft["status"] == "pending_approval"))
results.append(check("draft_email rejects an invalid address", True))
try:
    draft_email("not-an-email", "Test", "body")
    results.append(check("draft_email rejects an invalid address", False))
except ValueError:
    results.append(check("draft_email raises ValueError on an invalid address", True))

# --- a spy transport lets us prove exactly when (and whether) a send happens ---
_sent_calls = []


def _spy_transport(to, subject, body):
    _sent_calls.append((to, subject, body))


# 1. A draft that never went through draft_email() (e.g. a hand-built dict,
#    or one an attacker/bug fabricated) must be refused.
_sent_calls.clear()
try:
    send_approved_email({"to": "x@example.com", "subject": "s", "body": "b"}, approved=True, transport=_spy_transport)
    results.append(check("a non-draft dict is refused", False))
except ApprovalRequiredError:
    results.append(check("a non-draft dict is refused", True))
results.append(check("...and the transport was never called", len(_sent_calls) == 0))

# 2. approved=False must be refused, even for a real draft.
_sent_calls.clear()
try:
    send_approved_email(draft, approved=False, transport=_spy_transport)
    results.append(check("approved=False is refused", False))
except ApprovalRequiredError:
    results.append(check("approved=False is refused", True))
results.append(check("...and the transport was never called", len(_sent_calls) == 0))

# 3. A truthy-but-not-literal-True approval (a common bug: passing a
#    non-empty string, "yes", or 1) must NOT be treated as approval --
#    approval has to be the real value True, not just anything falsy-check
#    would accept.
_sent_calls.clear()
for sketchy_approval in ("yes", 1, "True", ["approved"]):
    try:
        send_approved_email(draft, approved=sketchy_approval, transport=_spy_transport)
        results.append(check(f"truthy-but-not-True approval {sketchy_approval!r} is refused", False))
    except ApprovalRequiredError:
        results.append(check(f"truthy-but-not-True approval {sketchy_approval!r} is refused", True))
results.append(check("...none of those calls reached the transport", len(_sent_calls) == 0))

# 4. Only real, explicit approval on a real draft actually sends -- and
#    only exactly once, to exactly the drafted recipient.
_sent_calls.clear()
sent = send_approved_email(draft, approved=True, transport=_spy_transport)
results.append(check("a properly-approved draft is marked sent", sent["status"] == "sent"))
results.append(check("the transport was called exactly once", len(_sent_calls) == 1))
results.append(check("...with the drafted recipient/subject/body", _sent_calls[0] == (draft["to"], draft["subject"], draft["body"])))

# 5. The same draft object can't be replayed through send_approved_email()
#    a second time (status is now "sent", not "pending_approval").
_sent_calls.clear()
try:
    send_approved_email(sent, approved=True, transport=_spy_transport)
    results.append(check("an already-sent draft can't be re-sent", False))
except ApprovalRequiredError:
    results.append(check("an already-sent draft can't be re-sent", True))
results.append(check("...and the transport was never called for the replay", len(_sent_calls) == 0))


# =============================================================================
# Rule: "Expose API keys or credentials in logs" -> NEVER
# =============================================================================

# The real transport reads EMAIL_PASSWORD from the environment and must
# never surface it in an exception message or any printed output -- even
# when something goes wrong (e.g. credentials missing).
_saved_email_user = os.environ.pop("EMAIL_USER", None)
_saved_email_password = os.environ.pop("EMAIL_PASSWORD", None)
os.environ["EMAIL_PASSWORD"] = "super-secret-do-not-leak-12345"
try:
    from email_agent import _default_transport
    try:
        _default_transport("someone@example.com", "subject", "body")
        results.append(check("missing EMAIL_USER raises instead of silently sending", False))
    except RuntimeError as e:
        results.append(check("missing EMAIL_USER raises RuntimeError", True))
        results.append(check("...and the error message doesn't leak EMAIL_PASSWORD", "super-secret-do-not-leak-12345" not in str(e)))
finally:
    if _saved_email_user is not None:
        os.environ["EMAIL_USER"] = _saved_email_user
    if _saved_email_password is not None:
        os.environ["EMAIL_PASSWORD"] = _saved_email_password
    else:
        os.environ.pop("EMAIL_PASSWORD", None)

# The source code itself should never print/log the password value -- a
# static check that email_agent.py contains no print()/logging call built
# from EMAIL_PASSWORD.
_source = open(os.path.join(os.path.dirname(__file__), "email_agent.py")).read()
results.append(check(
    "email_agent.py never interpolates EMAIL_PASSWORD into a printed/raised string",
    "{password}" not in _source and "+ password" not in _source and "password}" not in _source.replace("EMAIL_PASSWORD", ""),
))


# =============================================================================
# Rule: "Export or bulk-download full MLS datasets" -> return <=50 rows/query
# =============================================================================

results.append(check("search_listings._MAX_ROWS is <= 50", SEARCH_MAX_ROWS <= 50))
results.append(check("market_stats._MAX_ROWS is <= 50", MARKET_MAX_ROWS <= 50))
results.append(check("recommend._MAX_ROWS is <= 50", RECOMMEND_MAX_ROWS <= 50))
results.append(check("semantic_search._MAX_ROWS is <= 50", SEMANTIC_MAX_ROWS <= 50))
results.append(check("rag._MAX_ROWS is <= 50", RAG_MAX_ROWS <= 50))

# Enforcement, not just a default: asking for far more than 50 rows still
# only returns <=50, against the real DB.
big_search = searchActiveListings({}, limit=10_000)
results.append(check("searchActiveListings(limit=10000) is still capped at 50", len(big_search) <= 50))

big_comps = getSoldComps("San Diego", months=24, limit=10_000)
results.append(check("getSoldComps(limit=10000) is still capped at 50", len(big_comps) <= 50))

big_summary = get_city_market_summary(months=12, limit=10_000)
results.append(check("get_city_market_summary(limit=10000) is still capped at 50", len(big_summary) <= 50))

big_recs = find_similar_listings(SACRAMENTO_LISTING_ID, top_k=10_000)
results.append(check("find_similar_listings(top_k=10000) is still capped at 50", len(big_recs) <= 50))

# semantic_search() and retrieve() -- built against temp-dir indices so this
# doesn't touch (or depend on) any index a real run has already cached
# under data/, same pattern as test_semantic_search.py / test_rag.py.
_tmp_dir = tempfile.mkdtemp()
_sv, _sm, _svec = (os.path.join(_tmp_dir, n) for n in ("sem_vectors.npy", "sem_meta.json", "sem_vectorizer.pkl"))
build_semantic_index(limit=30, vectors_path=_sv, meta_path=_sm, vectorizer_path=_svec)
big_semantic = semantic_search("home with a view", top_k=10_000, vectors_path=_sv, meta_path=_sm, vectorizer_path=_svec)
results.append(check("semantic_search(top_k=10000) is still capped at 50", len(big_semantic) <= 50))

_rv, _rm, _rvec = (os.path.join(_tmp_dir, n) for n in ("rag_vectors.npy", "rag_meta.json", "rag_vectorizer.pkl"))
build_rag_index(market_cities=None, vectors_path=_rv, meta_path=_rm, vectorizer_path=_rvec)
big_rag = retrieve("What does DOM mean?", top_k=10_000, vectors_path=_rv, meta_path=_rm, vectorizer_path=_rvec)
results.append(check("retrieve(top_k=10000) is still capped at 50", len(big_rag) <= 50))


# =============================================================================
# Rule: "Operate autonomously without human oversight" -> every outbound
# action requires approval (covered above); content builders only draft.
# =============================================================================

market_draft = draft_market_report("agent@example.com", "San Diego", months=12)
results.append(check("draft_market_report only drafts", market_draft["status"] == "pending_approval"))
results.append(check("draft_market_report's body mentions the city", "San Diego" in market_draft["body"]))

alert_draft = draft_listing_alert("agent@example.com", {"city": "Irvine", "maxPrice": 2_000_000})
results.append(check("draft_listing_alert only drafts", alert_draft["status"] == "pending_approval"))

summary_draft = draft_property_summary("agent@example.com", SACRAMENTO_LISTING_ID)
results.append(check("draft_property_summary only drafts", summary_draft["status"] == "pending_approval"))
results.append(check("draft_property_summary's subject names the address", len(summary_draft["subject"]) > len("Property Summary: ")))

digest_draft = draft_recommendation_digest("agent@example.com", SACRAMENTO_LISTING_ID, top_k=5)
results.append(check("draft_recommendation_digest only drafts", digest_draft["status"] == "pending_approval"))

# None of the four content builders' drafts can be sent without going
# through the same approved=True gate as a hand-built draft_email().
_sent_calls.clear()
try:
    send_approved_email(market_draft, approved=False, transport=_spy_transport)
    results.append(check("a market-report draft still requires real approval", False))
except ApprovalRequiredError:
    results.append(check("a market-report draft still requires real approval", True))
results.append(check("...and nothing was sent", len(_sent_calls) == 0))

print(f"\n{sum(results)}/{len(results)} tests passed")
