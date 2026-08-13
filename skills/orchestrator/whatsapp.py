"""
Week 10: WhatsApp Communication Layer.

Wraps orchestrate() with the two things a real channel needs that a bare
function call doesn't:

  1. A reply shaped for a WhatsApp text bubble (a short intent-tagged
     emoji prefix, per the handbook's formatForWhatsApp example) rather
     than a bare multi-line card dump.
  2. A try/except boundary so a skill-level exception (a dropped DB
     connection, a Gemini timeout, a bad regex edge case) becomes a
     friendly reply instead of a dropped message or a crash.

The WhatsApp session itself -- QR-linked device, actually sending/
receiving messages, the typing indicator -- is OpenClaw's own `whatsapp`
channel plugin (wired in Week 0, `openclaw channels login --channel
whatsapp`). This module is the function OpenClaw's agent calls per
incoming message; see this skill's SKILL.md for how OpenClaw is pointed
at it.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from orchestrate import orchestrate

# WhatsApp text messages don't hard-fail past a certain length the way SMS
# does, but a very long single bubble renders poorly in the app. This is a
# self-imposed safety margin, not a documented WhatsApp/OpenClaw limit --
# same spirit as the handbook's Week 11 "return result sets of <=50 rows"
# guidance, applied to the reply side instead of the query side.
_MAX_REPLY_CHARS = 4000

_INTENT_EMOJI = {
    "search": "🏠",
    "semantic": "🔍",
    "market": "📈",
    "recommend": "✨",
    "knowledge": "📚",
    "mixed": "🧭",
}


def _truncate(text: str, limit: int = _MAX_REPLY_CHARS) -> str:
    """Cut `text` down to `limit` chars on a card boundary (blank line) when
    possible, so a truncated reply doesn't end mid-listing."""
    if len(text) <= limit:
        return text
    cutoff = text.rfind("\n\n", 0, limit)
    if cutoff <= 0:
        cutoff = limit
    return text[:cutoff].rstrip() + "\n\n(showing partial results -- ask a narrower question to see more)"


def format_for_whatsapp(result: dict) -> str:
    """Render an orchestrate() result as a WhatsApp-ready reply: an
    intent-tagged emoji prefix, length-capped for a single text bubble."""
    emoji = _INTENT_EMOJI.get(result["intent"], "")
    prefix = f"{emoji} " if emoji else ""
    return _truncate(f"{prefix}{result['response']}")


def handle_whatsapp_message(user_id: str, message: str) -> str:
    """
    Process one incoming WhatsApp message end to end and return the reply
    text to send back. Never raises -- any skill-level failure becomes a
    user-facing apology instead of a dropped message, matching the
    handbook's onWhatsAppMessage try/except.
    """
    try:
        result = orchestrate(user_id, message)
    except Exception as e:
        print(f"orchestrate() failed for user {user_id!r}: {e.__class__.__name__}: {e}", file=sys.stderr)
        return "Sorry, I hit an issue answering that. Please try again."

    return format_for_whatsapp(result)
