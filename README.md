# sales-integrated

An autonomous client-acquisition agent for freelancers. The agent finds
in-ICP prospects, drafts compliant outreach, and (within limits the user sets)
sends it, triages replies, offers call slots and reports back, for a flat
subscription with no take rate and no ad-spend margin.

Working title for the product: **Current** (placeholder, not final).

## Status

A working vertical slice, **not a product yet**. It runs end to end on a mock
model or on local Qwen via Ollama, but it cannot send real email and finds only
demo prospects. See [What is real and what is stubbed](#what-is-real-and-what-is-stubbed).

| Doc | What it is |
| --- | --- |
| [docs/00-product-decisions.md](docs/00-product-decisions.md) | What was decided in the brainstorm, and what is still open |
| [docs/01-validation-plan.md](docs/01-validation-plan.md) | Concierge test with 5 freelancers: success and kill thresholds |
| [docs/02-architecture-notes.md](docs/02-architecture-notes.md) | Model tiering on a VPS, send guard, compliance engine, autonomy dial |

## Run it

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest                                   # 51 tests

CURRENT_BASE_URL=http://127.0.0.1:8000 python -m current
# open http://127.0.0.1:8000  (the onboarding interview starts on first visit)
```

`CURRENT_BASE_URL` matters: it is the origin written into every opt-out link.

| Variable | Default | Purpose |
| --- | --- | --- |
| `CURRENT_DB` | `./current.db` | SQLite file |
| `CURRENT_LLM` | `mock` | `mock` (offline, deterministic) or `ollama` |
| `OLLAMA_URL` | `http://localhost:11434/v1` | Any OpenAI-compatible endpoint (Ollama, vLLM, llama.cpp) |
| `CURRENT_SMALL_MODEL` / `CURRENT_LARGE_MODEL` | `qwen2.5:7b-instruct` / `qwen2.5:14b-instruct` | Tiers: small for classify/score/triage/review, large for drafting and planning |
| `GROQ_API_KEY` | unset | Hosted fallback. Never receives personal data (see below) |
| `CURRENT_SECRET` | dev value | Signs opt-out links. Change it in any shared deployment |
| `CURRENT_RULES` | `config/rules.yaml` | Country rules table |
| `CURRENT_DEV_UNLOCK` | off | Skips the go-live gate so you can see live mode locally |
| `CURRENT_HOST` / `CURRENT_PORT` | `127.0.0.1` / `8000` | Bind address |

### Try the whole loop

1. Answer the interview, then **Start the dry run**. Eight drafts appear; two sole traders are held back.
2. In **Decisions**, read a draft: footer, and seven send-guard checks.
3. Approve three. In **Funnels**, promote to shadow. Going live stays locked
   (7 days of shadow, and country rules signed off by counsel). Run with
   `CURRENT_DEV_UNLOCK=1` to see live mode.
4. In live mode approved messages land in the **outbox** page, footer included. On
   **Funnels**, simulate a reply: it is classified, an answer with your slots is
   drafted, and "Mark call booked" moves the number on **Today**.

## What is real and what is stubbed

| Area | State |
| --- | --- |
| Onboarding, profile, autonomy dial (suggest / approve first / auto within cap) | Real |
| Send guard: suppression, country rules, one touch, daily limit and warm-up ramp, domain health, footer, claims review | Real, tested |
| Country rules table, signed opt-out links, suppression list | Real. **The rules are a draft and unreviewed by counsel** |
| Dry run -> shadow -> live gate | Real |
| Model router: local-only for personal data, no silent fallback, small-then-large escalation | Real, tested |
| Qwen/Ollama backend | Implemented against the OpenAI-compatible API, **not run against a live Ollama here** (the mock backend is what the tests and demo use) |
| Lead discovery | **Stub**: CSV import and a fictional demo registry. No crawler yet |
| Sending | **Stub**: dry-run outbox only. No Gmail, Outlook or SMTP mailer exists |
| Inbound replies | **Stub**: simulated from the Funnels page. No IMAP |
| Content / social posts, ads | Not started (deferred by decision) |
| Accounts, multi-tenancy, billing | Not started. Single user, no login: do not expose it to a network |
| Footer and drafts in languages other than English | Not started. Required before any non-English send |

## Layout

```
config/rules.yaml        country rules (draft)
src/current/
  service.py             Engine: cycle, approve, autonomy, gate, stats
  guard.py               the send guard
  compliance/rules.py    rules table
  agent/                 tasks (qualify, draft, claims, triage, plan), footer + opt-out tokens
  llm/                   router, OpenAI-compatible backend, mock backend
  scout/sources.py       lead sources (CSV, demo)
  mail/outbox.py         dry-run mailer
  onboarding.py          the interview
  web/                   FastAPI app, templates, CSS, stream geometry
tests/                   51 tests
```

## Principles

1. **An outcome, not a toolbox.** One promise: calls booked with the right people.
2. **Autonomy is a dial, not a switch.** Everything starts at "approve first".
3. **The LLM writes and classifies. It never decides money, rates or compliance.**
4. **Compliance blocks, it does not warn.** EU first, per-country rules.
5. **One living metaphor, one hot accent, huge numerals.** Strong, simple, memorable.
