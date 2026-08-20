---
name: orchestrator
description: Classify a free-text message's intent and route it to the specialized skill(s) that handle it -- property-search, semantic-search, market-stats, recommendation, rag-knowledge, or email-agent -- merging results for mixed-intent queries and handling the email draft-then-approve flow as two turns. Also formats replies for WhatsApp and handles the message-in/message-out boundary for that channel.
metadata:
  {
    "openclaw":
      {
        "requires":
          {
            "bins": ["python3"],
            "env": ["MYSQL_HOST", "MYSQL_USER", "MYSQL_DATABASE", "GEMINI_API_KEY", "EMAIL_USER", "EMAIL_PASSWORD"],
          },
      },
  }
---

# orchestrator

The single entry point across all six specialized skills. Classifies each
incoming message's intent and dispatches it -- or, for a mixed-intent
message, dispatches it to more than one skill in parallel and merges the
replies.

## When to use

This is the top-level skill: point WhatsApp (or any other channel) at
`orchestrate(user_id, message)` and it routes to the right specialist
itself. Use the individual skills directly only for isolated testing or
when you already know which one you want.

## Week 9: Multi-Agent Orchestration

```bash
cd /Users/lindsaylai/projects/idx-exchange
source venv/bin/activate
python -c "
import sys; sys.path.insert(0, 'skills/orchestrator')
from orchestrate import orchestrate

result = orchestrate('demo-user', 'Find me affordable homes in Pasadena and tell me whether prices are rising.')
print(result['intent'])
print(result['response'])
"
```

Or drive it interactively: `python skills/orchestrator/chat.py`.

### Agent registry

| Intent | Routes to | Week |
|---|---|---|
| `search` | `property-search` (`session.handleMessage`) | 2-4 |
| `semantic` | `semantic-search` | 6 |
| `market` | `market-stats` | 5 |
| `recommend` | `recommendation` | 7 |
| `knowledge` | `rag-knowledge` | 8 |
| `email` | `email-agent`, as a two-turn draft-then-approve exchange | 11 (wired in here at 12) |
| `mixed` | `property-search` + `market-stats`, run concurrently and merged | 2-4, 5 |

See "Week 12: email intent" below for `email`'s own routing logic --
`emailDraftAgent` from the handbook's Week 9 registry, wired in as part of
the Week 12 capstone integration.

### Functions

- `classify_intent(message)` -- returns one of `search`, `semantic`,
  `market`, `recommend`, `knowledge`, `email`, `mixed`. A keyword/regex
  heuristic (see below), not an LLM call.
- `orchestrate(user_id, message)` -- classifies, routes, and returns
  `{"intent": ..., "response": <display-ready string>}`.

### Why a heuristic classifier, not an LLM

Routing five well-separated skills doesn't need a model call, and it keeps
this project's only paid-API dependency (Gemini) confined to
`rag-knowledge`'s generation step -- consistent with README's Tech Stack
notes (embeddings run locally everywhere; Gemini is the one hosted call).
`classify_intent()` is deliberately built the same way as
`parse_query.parse_property_query()`: layered regex over surface patterns
pulled directly from the handbook's own example queries for each week.

Precedence, evaluated in this order:

0. **email** -- the message mentions "email"/"e-mail" at all. Checked
   before everything else: "email me a market report for San Diego" carries
   market signals too, but the overriding intent is unambiguous. See "Week
   12: email intent" below.
1. **mixed** -- a hard filter or a request-verb-plus-property-noun phrase
   *and* a market signal in the same message (e.g. "Find me affordable
   homes in Pasadena and tell me whether prices are rising").
2. **recommend** -- "similar to", "comparable to", "priced fairly", etc.
3. **market** -- a market signal *and* a place actually named (e.g. "What's
   the average price per sq ft in Pasadena?") -- named-place wins over the
   next check so this doesn't get read as a generic definition question.
4. **knowledge** -- "what is/does/are ... ?", "define", "explain", with no
   place named (e.g. "What is a list-to-close ratio?").
5. **market** -- a market signal with no request phrase and no place.
6. **search** -- a hard filter, or a request-verb-plus-property-noun phrase
   that isn't overridden by rule 7.
7. **semantic** -- a request-verb-plus-property-noun phrase with *no* hard
   filter and a descriptive/vibe cue present (e.g. "Show me quiet
   properties away from the road") reads as semantic, not search, even
   though it uses the same "show me ... properties" shape a real search
   request would.
8. Default: **search** (same fallback a lone `property-search` skill would
   give an unparseable message).

**Known limitations** (documented, not silently papered over): this is a
keyword heuristic, not NLU. It's tuned against the handbook's own example
queries plus this skill's test suite -- open-ended free text will
occasionally land on the wrong branch (e.g. a semantic query that happens
to use market vocabulary). `classify_intent()` is a pure function, so
misroutes are easy to catch and patch by adding a case to
`test_orchestrate.py` and adjusting the relevant regex.

### Mixed-intent routing detail

For `mixed`, the search leg and market leg run concurrently
(`concurrent.futures.ThreadPoolExecutor`) and are joined with a `---`
separator. They use two different city-extraction mechanisms:

- The **market leg** uses this skill's own more lenient `_extract_city()`
  (falls back to a loose "in \<Capitalized word(s)\>" match, then the
  user's session city) specifically so a sentence like "...in Pasadena and
  tell me..." -- which `parse_query.parse_property_query()` can't cleanly
  terminate -- still resolves to a market summary.
- The **search leg** calls `property-search`'s own `session.handleMessage()`
  unmodified, which uses `parse_property_query()`'s stricter city regex on
  its own. Left alone, that regex fails on the same "...in Pasadena and
  tell me..." phrasing property-search's parser was never built to expect,
  and re-asks "What city are you interested in?" on the very message that
  just named one -- a real bug caught rehearsing the Week 12 demo live over
  WhatsApp, not a hypothetical.

**The fix:** before calling `handleMessage()`, `orchestrate()` pre-seeds
`session["city"]` with the market leg's own successful extraction (only if
the session doesn't already have a city). `property-search`'s
`_merge_filters()` only ever *sets* `session["city"]` when its own parse
finds one -- it never clears an already-set value -- so pre-seeding is safe
and doesn't touch `property-search`'s parser at all (still Week 2-4 code,
unmodified, still passes its own test suite standalone). The search leg
then sees a city already on the session and moves straight to asking about
budget instead, same as if the user had stated it in two turns.

This doesn't retire `parse_property_query()`'s stricter regex generally --
only `orchestrate()`'s `mixed` branch pre-seeds around it. A bare `search`
message with the same hard-to-terminate phrasing (no market signal, so it
never reaches this pre-seed) would still hit `property-search`'s original
behavior standalone.

### Recommend: resolving which listing

`recommend` needs a listing id. In order: (1) a bare 6+ digit number in the
message itself, (2) `getSession(user_id)["lastResults"][0]` -- the user's
most recent property-search result, matching the handbook's own
`recommendationAgent(session.lastResults?.[0])`. If neither is available,
it asks instead of guessing or crashing.

### Setup dependency

The `semantic` intent calls `semantic-search`'s `semantic_search()` against
its *default* cached index path (`data/listing_embeddings.npy`) -- run
`semantic-search`'s own `build_index()` at least once locally first (see
its `SKILL.md`), same as `rag-knowledge`'s index needs building before
`knowledge` queries work. `recommend` doesn't need this: it embeds live on
every call instead of reading a cache.

Tests: `python skills/orchestrator/test_orchestrate.py` (37 checks --
`classify_intent()` against one example per intent plus the handbook's own
queries, then `orchestrate()` end to end against the real DB/Gemini/local
embedding model for every intent, including the no-city and no-listing
fallback paths).

## Week 10: WhatsApp Communication Layer

`whatsapp.py` wraps `orchestrate()` with what an actual channel needs on
top of a bare function call: a reply shaped for a WhatsApp text bubble, and
a try/except boundary so a skill-level failure becomes a friendly reply
instead of a dropped message or a crash.

```bash
cd /Users/lindsaylai/projects/idx-exchange
source venv/bin/activate
python -c "
import sys; sys.path.insert(0, 'skills/orchestrator')
from whatsapp import handle_whatsapp_message

print(handle_whatsapp_message('demo-user', 'Is now a good time to buy in San Diego?'))
"
```

Or drive it interactively, seeing exactly what a WhatsApp user would see
(no intent tag, just the reply): `python skills/orchestrator/whatsapp_chat.py`.

### Architecture

```
WhatsApp -> OpenClaw whatsapp channel (Week 0, already linked) -> this
skill's handle_whatsapp_message(user_id, message) -> orchestrate() ->
[routed skill(s)] -> rets_property / california_sold -> formatted reply
-> OpenClaw -> WhatsApp
```

The WhatsApp session itself -- the QR-linked device, actually sending and
receiving messages, the typing indicator -- is OpenClaw's own `whatsapp`
channel plugin, not this skill's Python code. `handle_whatsapp_message()`
is the function OpenClaw's agent is meant to call per incoming message;
wiring OpenClaw's live gateway config to actually do that (registering
this skill, pointing WhatsApp at it) is a separate, deliberately
unautomated step -- see the note at the bottom of this section.

### Functions

- `handle_whatsapp_message(user_id, message)` -- the message handler: calls
  `orchestrate()`, catches any exception and returns a friendly apology
  instead of raising, then runs the result through `format_for_whatsapp()`.
  Never raises.
- `format_for_whatsapp(result)` -- takes an `orchestrate()` result dict and
  returns the reply text: an intent-tagged emoji prefix (🏠 search, 🔍
  semantic, 📈 market, ✨ recommend, 📚 knowledge, 🧭 mixed), then
  length-capped to `_MAX_REPLY_CHARS` (4000, a self-imposed safety margin
  for a single text bubble -- not a documented WhatsApp/OpenClaw limit).

### Why an emoji prefix instead of per-field emoji cards

The handbook's own `formatForWhatsApp` example decorates each field of
each listing individually (🏠 address, 💰 price, 🛏 beds/baths, 📐 sqft, 📅
DOM). This skill's underlying formatters
(`search_listings.format_listing_card`, `market_stats.format_market_summary`,
etc.) already return clean, tested, human-readable multi-line cards used
elsewhere (their own skills' test suites assert on their exact text) --
re-parsing that finished text to re-decorate individual fields per channel
would be fragile string surgery for cosmetic gain. A single intent-level
emoji prefix gets the "this is a WhatsApp-shaped reply" outcome the
handbook is going for without touching those already-tested strings.

### Truncation

`_truncate()` caps a reply at `_MAX_REPLY_CHARS`, preferring to cut on a
blank-line card boundary (so a multi-listing reply doesn't get chopped
mid-card) and appending a note that more results exist. Only matters for
`search`/`semantic`/`recommend` replies with several cards back to back;
`market`/`knowledge` replies are well under the limit in practice.

### Live WhatsApp wiring

This project's OpenClaw gateway is linked to a real WhatsApp account
(Week 0). `~/.openclaw/openclaw.json`'s `skills.entries` now registers
`orchestrator` as the sole skill (replacing the four individually
registered pre-orchestrator entries), so live WhatsApp traffic routes
through `handle_whatsapp_message()` -> `orchestrate()`. If this ever needs
rolling back, a pre-change backup is kept at
`~/.openclaw/openclaw.json.pre-week10-orchestrator-wiring.bak`:
```bash
cp ~/.openclaw/openclaw.json.pre-week10-orchestrator-wiring.bak ~/.openclaw/openclaw.json
launchctl kickstart -k gui/$(id -u)/ai.openclaw.gateway
```

Tests: `python skills/orchestrator/test_whatsapp.py` (17 checks -- emoji
prefixing per intent, truncation behavior, and `handle_whatsapp_message()`
end to end including the exception -> friendly-reply path).

## Week 12: email intent (capstone integration)

Wires `email-agent` (Week 11) into the orchestrator so a WhatsApp user can
ask for something to be emailed, review the draft, and approve or decline
it -- as two separate turns, never one. This is the piece the handbook's
Week 12 demo script calls out as needing "two steps by design":

```bash
cd /Users/lindsaylai/projects/idx-exchange
source venv/bin/activate
python -c "
import sys; sys.path.insert(0, 'skills/orchestrator')
from orchestrate import orchestrate

r1 = orchestrate('demo-user', 'Email you@example.com a market report for San Diego')
print(r1['response'])          # shows the draft, asks for yes/no

r2 = orchestrate('demo-user', 'yes')   # separate turn -- this is what actually sends
print(r2['response'])
"
```

### How a draft gets built

`_handle_email_intent()` picks a content builder using the same signals
the other intents already use, in this order:

1. **recommendation digest** -- "similar to"/"comparable" phrasing
   (`_RECOMMEND_RE`, same regex `recommend` uses). Listing id comes from
   the message, else `session["lastResults"][0]` via the existing
   `_extract_listing_id()`.
2. **listing alert** -- a hard filter (beds/baths/price/type/pool) is
   present. Checked *before* the bare-listing-id case below: a price like
   "$1,500,000" also matches the 6+-digit listing-id regex, and without
   this ordering "email me listings in Irvine under $1,500,000" would get
   misread as "email me listing #1500000".
3. **property summary** -- a bare listing id in the message with no hard
   filter.
4. **market report** -- a named city with no hard filter and no listing id
   (`_extract_city()`, same lenient fallback `market`/`mixed` use --
   broadened in this commit to also recognize "a report **for** San Diego",
   not just "**in** San Diego", since that's how an email request more
   naturally gets phrased).
5. None of the above -- asks what to send instead of guessing.

If no email address is found anywhere in the message (`_EMAIL_ADDRESS_RE`),
it asks for one before building anything.

### The approval turn

The built draft is stashed on the session (`session["pendingEmailDraft"]`)
and previewed in plain text (`_format_draft_preview()` strips the HTML the
content builders produce). `orchestrate()` checks for a pending draft
*before* running `classify_intent()` at all: if one exists and the new
message is a clear yes (`_APPROVE_RE`: "yes", "send it", "approved", "go
ahead", ...) it calls `send_approved_email(draft, approved=True)`; a clear
no (`_DECLINE_RE`: "no", "cancel", "discard", ...) clears it without
sending. Anything else falls through to normal routing and **leaves the
pending draft in place** -- a stray "what does DOM mean?" while a draft is
pending doesn't discard it; a fresh "email ... " request does replace it,
since that's an unambiguous new ask.

This reuses `email-agent`'s own approval gate exactly as built in Week 11
(`send_approved_email` still refuses anything that isn't a real draft with
literal `approved=True`) -- this module only decides *when* to call it,
never bypasses *how* it decides to send.

### Testing without ever sending real email

Every test in `test_orchestrate_email.py` monkeypatches
`orchestrate.send_approved_email` with a spy before running, the same
pattern `test_whatsapp.py` uses for `orchestrate()` itself. No test in this
codebase can place a real outbound call regardless of what's in `.env`.

Tests: `python skills/orchestrator/test_orchestrate_email.py` (29 checks --
`classify_intent()` tagging every email-phrased example, the full
draft/approve/decline cycle, each content builder's routing including the
price-vs-listing-id precedence fix, the missing-address and ambiguous-
request fallbacks, and the pending-draft-survives-an-unrelated-message
case).
