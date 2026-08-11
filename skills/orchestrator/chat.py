"""
Interactive REPL for manually exercising the Week 9 orchestrator end to end:
type a message, see which intent it's classified as and which skill(s)
answered -- same purpose as property-search/chat.py and rag-knowledge/ask.py.

Usage:
    cd /Users/lindsaylai/projects/idx-exchange
    source venv/bin/activate
    python skills/orchestrator/chat.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from orchestrate import orchestrate
from session import clearSession

USER_ID = "cli-user"


def main():
    print("orchestrator chat — type a message, 'reset' to start over, 'quit' to exit.\n")
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

        result = orchestrate(USER_ID, message)
        print(f"Agent [{result['intent']}]: {result['response']}\n")


if __name__ == "__main__":
    main()
