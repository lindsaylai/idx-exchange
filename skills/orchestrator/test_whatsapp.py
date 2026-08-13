import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "property-search"))

import whatsapp
from whatsapp import handle_whatsapp_message, format_for_whatsapp, _truncate, _MAX_REPLY_CHARS
from session import clearSession


def check(label, condition):
    print(f"{'PASS' if condition else 'FAIL'}: {label}")
    return condition


results = []

# --- format_for_whatsapp: intent-tagged emoji prefix ---
results.append(check(
    "search reply gets the house emoji",
    format_for_whatsapp({"intent": "search", "response": "123 Main St"}).startswith("🏠 "),
))
results.append(check(
    "market reply gets the chart emoji",
    format_for_whatsapp({"intent": "market", "response": "Oakland: ..."}).startswith("📈 "),
))
results.append(check(
    "mixed reply gets the compass emoji",
    format_for_whatsapp({"intent": "mixed", "response": "..."}).startswith("🧭 "),
))
results.append(check(
    "unknown intent falls back to no prefix rather than crashing",
    format_for_whatsapp({"intent": "nonsense", "response": "hi"}) == "hi",
))

# --- _truncate: caps length, prefers a card-boundary cutoff, always fits ---
short = "short reply"
results.append(check("short text passes through untouched", _truncate(short) == short))

long_text = "\n\n".join(f"Listing {i}: some card text here" for i in range(500))
truncated = _truncate(long_text)
results.append(check("long text is cut down to the limit (plus the truncation note)", len(truncated) < len(long_text)))
results.append(check("truncated text stays within a reasonable bound of the limit", len(truncated) <= _MAX_REPLY_CHARS + 100))
results.append(check("truncated text says more results exist", "ask a narrower question" in truncated))
results.append(check("truncation doesn't cut a card in half", not truncated.split("\n\n(showing")[0].endswith(":")))

# --- handle_whatsapp_message: end-to-end through orchestrate() ---
clearSession("wa-user")
search_reply = handle_whatsapp_message("wa-user", "Find homes in Irvine under $1.5M")
results.append(check("search reply is a non-empty string", isinstance(search_reply, str) and len(search_reply) > 0))
results.append(check("search reply is emoji-prefixed", search_reply.startswith("🏠")))

market_reply = handle_whatsapp_message("wa-user-2", "Is now a good time to buy in San Diego?")
results.append(check("market reply names the city", "San Diego" in market_reply))
results.append(check("market reply is emoji-prefixed", market_reply.startswith("📈")))

knowledge_reply = handle_whatsapp_message("wa-user-3", "What does DOM mean?")
results.append(check("knowledge reply cites sources", "Sources:" in knowledge_reply))
results.append(check("knowledge reply is emoji-prefixed", knowledge_reply.startswith("📚")))

# --- handle_whatsapp_message: a skill-level exception becomes an apology, not a crash ---
_original_orchestrate = whatsapp.orchestrate


def _boom(user_id, message):
    raise RuntimeError("simulated DB outage")


whatsapp.orchestrate = _boom
try:
    error_reply = handle_whatsapp_message("wa-user-4", "Find homes in Irvine")
    results.append(check("an orchestrate() exception doesn't propagate", True))
    results.append(check("the caller gets a friendly apology instead", "issue" in error_reply.lower()))
finally:
    whatsapp.orchestrate = _original_orchestrate

print(f"\n{sum(results)}/{len(results)} tests passed")
