# Running End-to-End (Local Dev + Live WhatsApp)

A checklist for verifying the whole stack works, in order — from "does
MySQL respond" up through "does a real WhatsApp message get a real
reply." Each step assumes the previous ones passed; if something fails,
fix it before moving on rather than skipping ahead.

## 1. Check the three external dependencies directly

```bash
cd /Users/lindsaylai/projects/idx-exchange
source venv/bin/activate

# MySQL
python3 -c "
import sys; sys.path.insert(0, 'skills/property-search')
from db import get_cursor
with get_cursor() as cur:
    cur.execute('SELECT 1')
    print('MySQL OK:', cur.fetchone())
"

# Gemini
python3 -c "
import os, sys
sys.path.insert(0, 'skills/property-search')
from db import _load_dotenv, _ENV_PATH
_load_dotenv(_ENV_PATH)
from google import genai
client = genai.Client(api_key=os.environ.get('GEMINI_API_KEY'))
r = client.models.generate_content(model='gemini-2.5-flash', contents='say hi in one word')
print('Gemini OK:', r.text)
"

# Email SMTP login (login only -- doesn't send anything)
python3 -c "
import os, sys, smtplib
sys.path.insert(0, 'skills/property-search')
from db import _load_dotenv, _ENV_PATH
_load_dotenv(_ENV_PATH)
with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
    server.login(os.environ['EMAIL_USER'], os.environ['EMAIL_PASSWORD'])
    print('Email login OK')
"
```

All three should print `OK` with no exception. If Gemini 429s here, stop
and see "Gemini rate limits" below -- nothing downstream will be reliable
until that clears or billing is enabled.

## 2. Run the full test suite

```bash
for f in skills/*/test_*.py; do echo "=== $f ==="; python "$f"; done
```

Every file should end in `N/N tests passed`, no `FAIL` lines anywhere.
Confirms the codebase itself is healthy, independent of OpenClaw/WhatsApp.

## 3. Test locally before touching WhatsApp

```bash
python skills/orchestrator/whatsapp_chat.py
```

Try a search, a market question, and an email draft + `yes`. This runs
the exact same code WhatsApp will call, but skips OpenClaw's own
Gemini-based reasoning layer entirely -- so if it's broken here, the bug
is in this repo; if it works here but not on WhatsApp, the problem is on
OpenClaw's/Gemini's side, not this code.

## 4. Check the live gateway config

```bash
python3 -c "
import json
c = json.load(open('/Users/lindsaylai/.openclaw/openclaw.json'))
print('openai plugin enabled (should be False):', c['plugins']['entries']['openai']['enabled'])
print('registered skills (should be just orchestrator):', list(c['skills']['entries'].keys()))
env = c['skills']['entries']['orchestrator']['env']
print('orchestrator env keys (should have all 7):', sorted(env.keys()))
"
```

Expected: `openai` plugin disabled, only `orchestrator` registered under
`skills.entries`, and its `env` has all 7 of `MYSQL_HOST`, `MYSQL_USER`,
`MYSQL_PASSWORD`, `MYSQL_DATABASE`, `GEMINI_API_KEY`, `EMAIL_USER`,
`EMAIL_PASSWORD` -- matching `skills/orchestrator/SKILL.md`'s declared
requirements exactly.

## 5. Check the gateway process is running

```bash
launchctl list | grep ai.openclaw.gateway
```

Should print a PID. If not, or after any config edit above:

```bash
launchctl kickstart -k gui/$(id -u)/ai.openclaw.gateway
```

## 6. Gemini rate limits

The single most common cause of "no response on WhatsApp" during this
project's testing has been Gemini's free-tier rate limit -- both the
daily quota and the per-minute (RPM) limit. OpenClaw's own agent makes a
Gemini call to reason about *every* WhatsApp message that needs
tool-calling (not just `rag-knowledge`'s own calls), so rapid back-to-back
messages trip it fast.

Symptoms: a reply that takes 10-30s longer than usual (Gemini
retry/backoff), or total silence with nothing logged at all (retries
exhausted, or a longer hang).

Fix: enable billing on the `GEMINI_API_KEY` at
[aistudio.google.com](https://aistudio.google.com) -> your key ->
billing. Same key, no code or config change needed -- just raises the
ceiling so a live demo's back-to-back messages don't trip it. Short of
that, pace messages ~15-20s apart while testing.

## 7. Test on real WhatsApp

Send one message, wait for the reply, then send the next -- don't
rapid-fire, especially without step 6 done.

## 8. Reading the live log when something breaks

```bash
tail -n 50 /Users/lindsaylai/Library/Logs/openclaw/gateway.log | python3 -c "
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        obj = json.loads(line)
        print(obj.get('time', ''), '|', obj.get('message', obj))
    except Exception:
        print('RAW:', line[:250])
"
```

Known signatures:
- `auth-profile-failure` right after an inbound message -> a provider
  auth/rate-limit issue (has been Gemini or a since-disabled OpenAI
  plugin with no credits), not this repo's code.
- Total silence for minutes with nothing logged at all -> same category,
  manifesting as a hang instead of a quick failure.
- `config change detected; evaluating reload (...)` / `config hot reload
  applied (...)` -> confirms OpenClaw picked up an `openclaw.json` edit
  live, without needing the `launchctl kickstart` restart (which is still
  worth doing anyway for a clean state).

## Rollback

Backups exist for every live-config edit made while building this out,
each restorable the same way:

```bash
cp ~/.openclaw/openclaw.json.pre-week10-orchestrator-wiring.bak ~/.openclaw/openclaw.json  # before orchestrator was the sole registered skill
cp ~/.openclaw/openclaw.json.pre-openai-plugin-disable.bak ~/.openclaw/openclaw.json        # before the openai plugin was disabled
cp ~/.openclaw/openclaw.json.pre-email-env-fix.bak ~/.openclaw/openclaw.json                # before EMAIL_USER/EMAIL_PASSWORD were added
launchctl kickstart -k gui/$(id -u)/ai.openclaw.gateway
```
