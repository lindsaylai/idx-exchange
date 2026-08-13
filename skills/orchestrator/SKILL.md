---
name: orchestrator
description: Classify a free-text message's intent and route it to the specialized skill(s) that handle it -- property-search, semantic-search, market-stats, recommendation, or rag-knowledge -- merging results for mixed-intent queries. Also formats replies for WhatsApp and handles the message-in/message-out boundary for that channel.
metadata:
  {
    "openclaw":
      {
        "requires":
          {
            "bins": ["python3"],
            "env": ["MYSQL_HOST", "MYSQL_USER", "MYSQL_DATABASE", "GEMINI_API_KEY"],
          },
      },
  }
---

# orchestrator

The single entry point across all five specialized skills. Classifies each
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
| `mixed` | `property-search` + `market-stats`, run concurrently and merged | 2-4, 5 |

`emailDraftAgent` from the handbook's Week 9 registry isn't included --
that's Week 11 and isn't built yet (see `docs/architecture.md`'s roadmap).

### Functions

- `classify_intent(message)` -- returns one of `search`, `semantic`,
  `market`, `recommend`, `knowledge`, `mixed`. A keyword/regex heuristic
  (see below), not an LLM call.
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
separator. They use two different city-extraction paths on purpose:

- The **search leg** calls `property-search`'s own `session.handleMessage()`
  unmodified, which uses `parse_query.parse_property_query()`'s stricter
  city regex -- so on a first turn it may ask a clarifying question
  ("What city are you interested in?") rather than search immediately, same
  as `property-search` would standalone.
- The **market leg** uses this skill's own more lenient `_extract_city()`
  (falls back to a loose "in \<Capitalized word(s)\>" match, then the
  user's session city) specifically so a sentence like "...in Pasadena and
  tell me..." -- which `parse_property_query()` can't cleanly terminate --
  still resolves to a market summary.

This asymmetry is intentional: it reuses `property-search`'s already-tested
parser as-is rather than loosening it (which could change Week 2-4
behavior), while still making the flagship mixed example work end-to-end.

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

### Live WhatsApp wiring (not done by this commit)

This project's OpenClaw gateway is already linked to a real WhatsApp
account (Week 0) and `~/.openclaw/openclaw.json` already registers
`property-search`, `market-stats`, `semantic-search`, and `recommendation`
as live skills (`skills.entries`) -- confirmed working over WhatsApp before
`orchestrator` existed. Actually pointing that live config at this skill
(so WhatsApp messages route through `handle_whatsapp_message()` instead of
OpenClaw picking among the individual skills itself) means editing that
config -- a change to shared, already-working personal infrastructure, not
this repo. That edit is intentionally left for a separate, explicit step
rather than done automatically as part of this commit.

Tests: `python skills/orchestrator/test_whatsapp.py` (17 checks -- emoji
prefixing per intent, truncation behavior, and `handle_whatsapp_message()`
end to end including the exception -> friendly-reply path).
