"""
Week 10: simulates the actual WhatsApp experience end to end -- unlike
orchestrator/chat.py (which prints the raw intent tag for debugging),
this shows exactly what a WhatsApp user would see: just the emoji-prefixed
reply text, nothing else.

Usage:
    cd /Users/lindsaylai/projects/idx-exchange
    source venv/bin/activate
    python skills/orchestrator/whatsapp_chat.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from whatsapp import handle_whatsapp_message
from session import clearSession

USER_ID = "whatsapp-cli-user"


def main():
    print("WhatsApp simulator — type a message, 'reset' to start over, 'quit' to exit.\n")
    clearSession(USER_ID)
    while True:
        try:
            message = input("You: ").strip()
        except EOFError:
            break
        if not message:
            continue
        if message.lower() in ("quit", "exit"):
            break
        if message.lower() == "reset":
            clearSession(USER_ID)
            print("Agent: (session cleared, starting over)\n")
            continue

        reply = handle_whatsapp_message(USER_ID, message)
        print(f"Agent: {reply}\n")


if __name__ == "__main__":
    main()
