"""
Interactive CLI for manually exercising the Week 11 email content builders
-- prints a draft for review and stops there. It deliberately does NOT
send anything: there is no command-line path to send_approved_email() here,
matching the handbook's rule that sending requires a separate, explicit,
human-reviewed approval step, not a CLI flag. To actually send a draft
(once EMAIL_USER/EMAIL_PASSWORD are set in .env), call
send_approved_email(draft, approved=True) yourself from Python -- see
this skill's SKILL.md and test_email_agent.py for the exact call shape.

Usage:
    cd /Users/lindsaylai/projects/idx-exchange
    source venv/bin/activate
    python skills/email-agent/chat.py market <to> <city>
    python skills/email-agent/chat.py listing <to> <city> [maxPrice]
    python skills/email-agent/chat.py property <to> <listing_id>
    python skills/email-agent/chat.py recommend <to> <listing_id>
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from email_agent import (
    draft_market_report,
    draft_listing_alert,
    draft_property_summary,
    draft_recommendation_digest,
)


def _print_draft(draft: dict) -> None:
    print(f"\n--- DRAFT ({draft['status']}) ---")
    print(f"To: {draft['to']}")
    print(f"Subject: {draft['subject']}")
    print(f"Body:\n{draft['body']}")
    print("--- end draft: not sent. Review it, then approve separately. ---\n")


def main():
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__)
        return

    command, to, *rest = args

    if command == "market":
        city = rest[0] if rest else "San Diego"
        _print_draft(draft_market_report(to, city))
    elif command == "listing":
        city = rest[0] if rest else "Irvine"
        max_price = int(rest[1]) if len(rest) > 1 else None
        filters = {"city": city, "maxPrice": max_price}
        _print_draft(draft_listing_alert(to, filters))
    elif command == "property":
        listing_id = rest[0] if rest else None
        if not listing_id:
            print("Usage: python skills/email-agent/chat.py property <to> <listing_id>")
            return
        _print_draft(draft_property_summary(to, listing_id))
    elif command == "recommend":
        listing_id = rest[0] if rest else None
        if not listing_id:
            print("Usage: python skills/email-agent/chat.py recommend <to> <listing_id>")
            return
        _print_draft(draft_recommendation_digest(to, listing_id))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
