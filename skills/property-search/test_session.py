import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from session import getSession, clearSession, handleMessage


def check(label, condition):
    print(f"{'PASS' if condition else 'FAIL'}: {label}")
    return condition


results = []


def is_question(reply: str) -> bool:
    return reply.strip().endswith("?")


# --- handbook's example conversation, turn by turn ---
clearSession("demo-user")
reply1 = handleMessage("demo-user", "Find homes in Irvine")
results.append(check("turn 1 asks for budget (city known, price missing)", "budget" in reply1.lower()))

reply2 = handleMessage("demo-user", "Under $1.2M")
results.append(check("turn 2 asks for property type", "condo" in reply2.lower() or "type" in reply2.lower() or "single family" in reply2.lower()))

reply3 = handleMessage("demo-user", "Single family with at least 3 beds")
results.append(check("turn 3 returns results, not another question", not is_question(reply3)))
results.append(check("turn 3 results respect the accumulated filters", "Irvine" in reply3))

session = getSession("demo-user")
results.append(check("session recorded all three turns", session["conversationStep"] == 3))
results.append(check("session merged city/maxPrice/beds/type from all turns", (
    session["city"] == "Irvine"
    and session["maxPrice"] == 1_200_000
    and session["beds"] == 3
    and session["type"] == "SingleFamilyResidence"
)))

# --- refinement: once results exist, a new message re-searches immediately ---
reply4 = handleMessage("demo-user", "actually make it under $900,000")
results.append(check("refinement turn returns results, not a question", not is_question(reply4)))
results.append(check("refinement updated the session's maxPrice", getSession("demo-user")["maxPrice"] == 900_000))

# --- a single message with every filter present skips straight to results ---
clearSession("one-shot-user")
reply = handleMessage("one-shot-user", "3-bedroom condos in Irvine under $1.5M with a pool")
results.append(check("fully-specified single message skips the Q&A", not is_question(reply)))
results.append(check("result card includes a photo count", "photos" in reply))

# --- sessions are isolated per user ---
clearSession("user-a")
clearSession("user-b")
handleMessage("user-a", "Find homes in Pasadena")
handleMessage("user-b", "Find homes in Malibu")
results.append(check(
    "two users' sessions don't leak into each other",
    getSession("user-a")["city"] == "Pasadena" and getSession("user-b")["city"] == "Malibu",
))

print(f"\n{sum(results)}/{len(results)} tests passed")
