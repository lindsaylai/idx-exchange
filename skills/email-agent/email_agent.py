"""
Week 11: Email Agents & Safety Guardrails.

A two-step draft-then-approve email workflow. draft_email() and the
content-builders below it (draft_market_report, draft_listing_alert,
draft_property_summary, draft_recommendation_digest) can only ever
produce a pending draft dict -- none of them can place an outbound call.
send_approved_email() is the sole function that can actually send, and it
refuses to unless its `draft` argument came from draft_email() and its
caller explicitly passes approved=True. There is no code path from a
free-text request straight to a sent email.

Per the handbook's non-negotiable Week 11 safety rules:
  - Send emails without explicit user approval  -> NEVER (send_approved_email
    raises ApprovalRequiredError otherwise)
  - Expose API keys/credentials in logs         -> NEVER (EMAIL_PASSWORD is
    read from .env and handed straight to smtplib; never printed or
    interpolated into any message this module raises or prints)
  - Export/bulk-download full MLS datasets      -> NEVER (every content
    builder here calls into skills that already cap result sets at
    <=50 rows -- see search_listings.py, market_stats.py, recommend.py)
  - Operate autonomously without human oversight -> NEVER (every function
    in this module that touches the outside world requires the caller to
    have gone through draft_email() first)
"""

import os
import re
import smtplib
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "property-search"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "market-stats"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "recommendation"))

from db import get_cursor, _load_dotenv, _ENV_PATH
from market_stats import format_market_summary
from search_listings import searchActiveListings, format_listing_card
from recommend import find_similar_listings, format_similar_listing, validate_with_comps

_load_dotenv(_ENV_PATH)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_LISTING_QUERY = """
    SELECT
        L_ListingID, L_Address, L_City, L_SystemPrice,
        L_Keyword2 AS beds, LM_Dec_3 AS baths, LM_Int2_3 AS sqft,
        L_Type_ AS propertyType, PoolPrivateYN, ViewYN, PhotoCount
    FROM rets_property
    WHERE L_ListingID = %s AND L_Status = 'Active'
"""


class ApprovalRequiredError(Exception):
    """Raised when send_approved_email() is asked to send something that
    never went through draft_email(), or wasn't explicitly approved."""


# --- Step 1: draft (never sends) --------------------------------------------

def draft_email(to: str, subject: str, body: str) -> dict:
    """
    Create a pending draft. This is as far as any code path in this module
    can go without an explicit, separate call to send_approved_email(...,
    approved=True) -- the returned dict is meant to be shown to a human for
    review before that second call ever happens.
    """
    if not _EMAIL_RE.match(to):
        raise ValueError(f"Not a valid email address: {to!r}")
    if not subject.strip():
        raise ValueError("Email subject cannot be empty")
    if not body.strip():
        raise ValueError("Email body cannot be empty")

    return {"to": to, "subject": subject, "body": body, "status": "pending_approval"}


# --- Content builders (Week 11's four email use cases, each just a draft) --

def draft_market_report(to: str, city: str, months: int = 12) -> dict:
    """Weekly market report, populated from california_sold via market-stats."""
    summary = format_market_summary(city, months=months)
    return draft_email(to, f"Weekly Market Report: {city}", f"<p>{summary}</p>")


def draft_listing_alert(to: str, filters: dict) -> dict:
    """New-listing alert for a saved search against active rets_property listings."""
    listings = searchActiveListings(filters, page=1, limit=10)
    if not listings:
        body = "<p>No new listings matched your saved search.</p>"
    else:
        cards = "".join(f"<p>{format_listing_card(row).replace(chr(10), '<br>')}</p>" for row in listings)
        body = f"<p>{len(listings)} new listing(s) matching your search:</p>{cards}"
    return draft_email(to, "New Listing Alert", body)


def draft_property_summary(to: str, listing_id) -> dict:
    """Single-listing summary card: address, price, comp-validated assessment."""
    with get_cursor() as cursor:
        cursor.execute(_LISTING_QUERY, (listing_id,))
        listing = cursor.fetchone()
    if listing is None:
        raise ValueError(f"No active listing found for id {listing_id!r}")

    # A handful of listings in this dataset have no L_Address on file --
    # fall back to the listing id rather than emitting "Property Summary: None".
    address = listing["L_Address"] or f"Listing #{listing['L_ListingID']}"
    card = format_listing_card(listing)
    comp = (
        validate_with_comps(listing["L_City"], listing["sqft"], listing["L_SystemPrice"])
        if listing["sqft"]
        else None
    )
    if comp and comp["delta_pct"] is not None:
        comp_line = f"<p>{comp['comp_count']} comps, {comp['flag']} ({comp['delta_pct']:+.1f}% vs. comp price)</p>"
    elif comp:
        comp_line = f"<p>{comp['flag']}</p>"
    else:
        comp_line = ""
    return draft_email(to, f"Property Summary: {address}", f"<p>{card.replace(chr(10), '<br>')}</p>{comp_line}")


def draft_recommendation_digest(to: str, listing_id, top_k: int = 5) -> dict:
    """Personalized digest of listings similar to one the user liked."""
    hits = find_similar_listings(listing_id, top_k=top_k)
    if not hits:
        body = "<p>No similar active listings found.</p>"
    else:
        cards = "".join(f"<p>{format_similar_listing(row).replace(chr(10), '<br>')}</p>" for row in hits)
        body = f"<p>Listings similar to one you liked:</p>{cards}"
    return draft_email(to, "Recommended For You", body)


# --- Step 2: send (only path to an outbound call) ---------------------------

def _default_transport(to: str, subject: str, body: str) -> None:
    """Real SMTP send via Gmail, using EMAIL_USER/EMAIL_PASSWORD from .env.
    Swappable in callers/tests via send_approved_email(..., transport=...)
    so nothing in this codebase's test suite ever sends real email."""
    user = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_PASSWORD")
    if not user or not password:
        raise RuntimeError("EMAIL_USER/EMAIL_PASSWORD not set in .env -- cannot send email.")

    message = MIMEMultipart()
    message["From"] = user
    message["To"] = to
    message["Subject"] = subject
    message.attach(MIMEText(body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(user, password)
        server.sendmail(user, [to], message.as_string())


def send_approved_email(draft: dict, approved: bool, transport=_default_transport) -> dict:
    """
    The only function in this codebase that can place an outbound email.
    Refuses unless BOTH hold:
      1. `draft` is a dict produced by draft_email() and not already sent
         (status == "pending_approval") -- guards against sending an
         arbitrary hand-built dict or double-sending the same draft.
      2. `approved` is the literal value True -- guards against a truthy-
         but-not-explicit value (1, "yes", a non-empty string) being
         mistaken for real human confirmation.
    """
    if draft.get("status") != "pending_approval":
        raise ApprovalRequiredError(
            "This draft didn't come from draft_email() (or was already sent) -- refusing to send."
        )
    if approved is not True:
        raise ApprovalRequiredError("Explicit approval (approved=True) is required to send.")

    transport(draft["to"], draft["subject"], draft["body"])
    return {**draft, "status": "sent"}
