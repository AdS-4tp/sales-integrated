# Architecture notes

Notes, not a spec. They record the shape the brainstorm converged on so the spec
can start from it.

## Components

```
onboarding agent -> funnel planner -> task queue -> workers
                                                    |- scout     (find leads from public sources)
                                                    |- qualify   (score against the ICP)
                                                    |- draft     (emails, content)
                                                    |- triage    (classify replies)
                                                    '- report    (weekly summary)
                          every outbound action -> decisions inbox -> send guard -> provider
```

- **Task queue.** Agent work is asynchronous. Jobs are prioritised, batched and may run
  overnight. This is what makes a modest inference box viable.
- **Decisions inbox.** Every outward-facing action is written here first. The autonomy
  setting for that action type decides whether it waits for the user or proceeds.
- **Send guard.** The last gate before anything leaves, see below.

## Model serving on a VPS

| Tier | Job | Where |
| --- | --- | --- |
| Small (Qwen, about 7 to 8B, quantised) | classify, score, triage, short summaries | CPU is acceptable |
| Larger | long drafts, funnel planning, onboarding interview | shared GPU box |

- Escalate small -> larger only on low confidence, and use a deterministic step wherever one works.
- Serve through one **OpenAI-compatible endpoint**. Ollama for development; vLLM or
  llama.cpp server for production, because they batch concurrent requests far better.
- Host in the EU. "Lead data never leaves the EU and never reaches a third-party
  LLM" is a product claim as well as a compliance fact.
- **Data class on every call.** Calls that contain personal data may only be routed to
  local backends. A hosted fallback (for example Groq) is allowed for non-personal data
  or on explicit opt-in. A guard task must never fall back silently to a weaker backend.
- Test draft quality per launch language before committing to that language.

### Cost model (to fill in during the validation test)

Per active user per month: tokens for onboarding, daily scouting, drafts and triage,
split by tier, converted to GPU-hours. Then check the subscription price covers it at
100 active users, with headroom. This number sets how aggressive the "small first"
routing has to be.

### Reuse note

The existing `therainmaker` repo has a role-based model router
(`src/rainmaker/models/router.py`) that maps roles to an ordered list of configured
backends and refuses to fall back silently for the `decision` role. The pattern fits
here with different roles (`classify`, `draft`, `plan`, `guard_review`) and with the
data-class rule above. It is a pattern to copy, not code to depend on.

## Send guard

Runs on every outbound email, after the autonomy gate.

1. **Deterministic (all must pass):**
   - recipient is not on the suppression list
   - the country rules table allows this contact (country, recipient type, legal basis)
   - this recipient has not been contacted before, unless they replied
   - sender mailbox is inside its limits (provider cap, or warm-up ramp for self-hosted)
   - sending domain health is acceptable (bounce and complaint rates, authentication)
   - mandatory footer present: sender identity, data source, legal basis, one-click opt-out
2. **LLM review (advisory input, can block):** spammy phrasing, unverifiable claims,
   tone mismatch with the freelancer's profile.

A block is recorded with reasons and shown in the dashboard. Nothing is silently dropped.

## Compliance engine

A versioned rules table, keyed by country and recipient type, that returns
`allow`, `block` or `needs_review` with the reason.

```yaml
# illustrative only; real values need counsel review
- country: DE
  recipient: business
  decision: block
  reason: prior consent required for B2B email
- country: FR
  recipient: business
  decision: allow
  conditions: [relevant_to_role, opt_out_in_message, source_disclosed]
```

- Rules version is stored with every touch.
- Sole-trader recipients are treated as natural persons unless a rule says otherwise.
- Suppression list is global and permanent.

## Autonomy dial

Per action type (send email, publish post, change schedule, and later, spend budget):
`suggest` -> `approve first` (default) -> `auto within limits`. Limits are explicit
numbers the user can see, such as a daily send cap. Unlocking auto never removes the
send guard.

## Lead discovery

Public web pages (robots.txt respected), company registries and open data, with the
source URL and date stored per lead. A self-hosted metasearch (for example SearXNG)
keeps queries off third-party APIs. No scraping of platforms whose terms forbid it.
