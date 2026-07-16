"""
Interactive REPL for manually exercising the Week 2-4 pipeline end to end:
type a message, see the parser -> session -> DB search flow respond live.

Usage:
    cd /Users/lindsaylai/projects/idx-exchange
    source venv/bin/activate
    python skills/property-search/chat.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from session import handleMessage, clearSession

USER_ID = "cli-user"


def main():
    print("property-search chat — type a message, 'reset' to start over, 'quit' to exit.\n")
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
            print("Agent: (session cleared, starting a new search)\n")
            continue

        reply = handleMessage(USER_ID, message)
        print(f"Agent: {reply}\n")


if __name__ == "__main__":
    main()
