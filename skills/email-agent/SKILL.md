---
name: email-agent
description: Draft-then-approve email workflow for listing alerts, weekly market reports, property summaries, and recommendation digests. Never sends without explicit human approval.
metadata:
  {
    "openclaw":
      {
        "requires":
          {
            "bins": ["python3"],
            "env": ["MYSQL_HOST", "MYSQL_USER", "MYSQL_DATABASE", "EMAIL_USER", "EMAIL_PASSWORD"],
          },
      },
  }
---

# email-agent

Composes and (only with explicit approval) sends emails built from the
other skills' data: listing alerts, weekly market reports, property
summaries, and recommendation digests.

## When to use

Use this skill when the user wants something emailed to them or a
contact -- e.g.:

- "Email me a market report for San Diego"
- "Send a listing alert for 3-bedroom homes in Irvine under $1.5M"
- "Email a summary of that listing to my agent"
- "Send me a digest of homes similar to this one"

It never sends on the first ask. Every request produces a draft; sending
is always a second, separate step that requires the caller to say yes
explicitly.

## Week 11: Email Agents & Safety Guardrails

```bash
cd /Users/lindsaylai/projects/idx-exchange
source venv/bin/activate
python -c "
import sys; sys.path.insert(0, 'skills/email-agent')
from email_agent import draft_market_report, send_approved_email

draft = draft_market_report('buyer@example.com', 'San Diego', months=12)
print(draft)                                    # review it first
# result = send_approved_email(draft, approved=True)   # only after a human says yes
"
```

Or preview each content builder without sending anything:
`python skills/email-agent/chat.py market buyer@example.com 'San Diego'`
(also `listing`, `property`, `recommend` -- see the file's docstring).

### The two-step workflow

| Step | Function | Can it send? |
|---|---|---|
| 1. Draft | `draft_email(to, subject, body)` and the four content builders below | No -- returns a dict tagged `status: "pending_approval"`, nothing else |
| 2. Send | `send_approved_email(draft, approved, transport=...)` | Only if `draft` came from step 1 *and* `approved is True` |

There is no function in this module that goes straight from a request to
a sent email. `send_approved_email()` raises `ApprovalRequiredError` if
either condition in step 2 isn't met -- including a `draft` that wasn't
produced by `draft_email()`, an already-sent draft (no replay), or an
`approved` value that's truthy but not the literal `True` (`"yes"`, `1`,
`"True"` as a string are all refused, on purpose -- see
`test_email_agent.py`).

### Content builders (the handbook's four email use cases)

- `draft_market_report(to, city, months=12)` -- weekly market report, via
  `market-stats`' `format_market_summary()` (Week 5, `california_sold`).
- `draft_listing_alert(to, filters)` -- new-listing alert for a saved
  search, via `property-search`'s `searchActiveListings()` (Week 3,
  `rets_property`).
- `draft_property_summary(to, listing_id)` -- single-listing card with a
  comp-validated price assessment, via `recommendation`'s
  `validate_with_comps()` (Week 7).
- `draft_recommendation_digest(to, listing_id, top_k=5)` -- similar-listings
  digest, via `recommendation`'s `find_similar_listings()` (Week 7).

Each is just `draft_email()` with a pre-built subject/body -- none of them
can send either.

### Safety guardrails (non-negotiable, per the handbook)

| Rule | How it's enforced here |
|---|---|
| Never send without explicit approval | `send_approved_email()`'s two checks above; see "known limitation" below for what this module can't guarantee beyond its own boundary |
| Never expose credentials in logs | `EMAIL_PASSWORD` is read from `.env` and handed straight to `smtplib`; never printed, logged, or included in any exception message this module raises (see `_default_transport`'s missing-credentials error, which names the *variable*, not its value) |
| Never bulk-export MLS data | Every content builder calls into a skill whose query function is capped at `_MAX_ROWS = 50` (`search_listings.py`, `market_stats.py`, `semantic_search.py`, `recommend.py`, `rag.py`) -- and the cap is enforced by clamping `limit`/`top_k` in the function itself, not just a default a caller could override |
| Never operate without human oversight | Same as row 1 -- every outbound path funnels through the same approval gate |

**Known limitation:** `send_approved_email()` guarantees *this module*
never sends without `approved=True` being passed by its caller. It cannot
guarantee that whatever calls it (a future WhatsApp/orchestrator wiring,
a future email-triggered agent loop) only ever passes `approved=True` in
response to a real human "yes" — that trust boundary lives one level up,
in whoever's calling this function. This module's job is to make it
impossible to send *without* that flag; making sure the flag is only ever
set from genuine human confirmation is the caller's responsibility, same
as the handbook's Week 12 capstone demo script treats "draft" and
"approve" as two separate, deliberately non-collapsible turns.

### Testing without ever sending real email

`_default_transport` (real SMTP via Gmail, needs `EMAIL_USER` /
`EMAIL_PASSWORD` in `.env` -- neither is set in this project's `.env` as of
this commit, so the real path can't fire by accident) is swappable:
`send_approved_email(draft, approved=True, transport=my_fake_transport)`.
`test_email_agent.py` uses a spy transport throughout and never imports or
calls real `smtplib` sending code, so the test suite has zero risk of
sending a real email regardless of what's in `.env` when it runs.

### Wired into the orchestrator/WhatsApp (Week 12)

The handbook's Week 12 capstone demo shows an email draft-and-approve flow
happening over WhatsApp via the orchestrator, as two separate turns. As of
Week 12, `orchestrator` (`skills/orchestrator/orchestrate.py`) has an
`email` intent that calls straight into this module's `draft_*` functions
and, on a later "yes" turn, `send_approved_email()` -- see
`skills/orchestrator/SKILL.md`'s "Week 12: email intent" section for the
routing logic and `~/.openclaw/openclaw.json` live-gateway status. This
module's own approval gate is unchanged and still the sole thing standing
between any caller (orchestrator included) and an actual send.

Tests: `python skills/email-agent/test_email_agent.py` (39 checks --
approval-gate enforcement including edge cases like truthy-non-True
approval and draft replay, credential-leak checks, real enforcement of
the <=50-row cap across all five other skills against the live DB/local
indices, and each content builder's draft-only behavior).
