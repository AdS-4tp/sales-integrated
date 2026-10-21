# Product decisions

Status: agreed in brainstorm. Items marked **proposed** were recommended by
the assistant and accepted as defaults; they should be re-confirmed before the spec is frozen.

## 1. Positioning

- An **acquisition agent with a cockpit**, not a general sales platform. It does
  not try to replace HubSpot, Buffer, Zapier and Meta Ads Manager at once.
- Customer: freelancers, niche-agnostic. The agent builds the funnel itself
  from an onboarding interview (offer, ideal client, proof points, region).
- Business model: flat subscription. No take rate, no ad-spend margin, no
  per-lead fee. Ad spend (later) goes straight from the user to the ad platform.
- Hosting: SaaS, EU-hosted, models run on our own infrastructure.

## 2. Autonomy

- Per action type, three levels: **suggest**, **draft and wait for approval**,
  **auto-run within limits**.
- Default for every action type is *draft and wait for approval*. Users unlock autonomy.
- The centre of the UX is a **decisions inbox** that can be cleared in about two minutes.

## 3. AI

- Stack: Qwen served locally. Ollama for development; vLLM or llama.cpp server for
  multi-tenant production. All behind one OpenAI-compatible endpoint and a role router.
- The LLM drafts, classifies, scores and summarises. **Budget, rate limits and
  compliance are deterministic.** The LLM only explains them.
- Small model first, escalate to a larger one on low confidence. Agent work is
  asynchronous, so queued/overnight batches are acceptable.
- Groq is hosted in the US. **Proposed:** non-personal data only, or explicit opt-in.
- Details in [02-architecture-notes.md](02-architecture-notes.md).

## 4. Channels in v1

| Channel | v1 | Notes |
| --- | --- | --- |
| Outbound email | Yes | One touch per prospect, see section 6 |
| Content (social drafts) | Yes, publishing partial | Drafts + approval; platform publishing added as API access is approved |
| Landing / booking page | Yes | Needed as the destination for every channel |
| Paid ads | No | Later upgrade. Typical freelancer budgets are too small for ad tests to learn |
| LinkedIn automation | **Never** | Platform bans automation; the account is the freelancer's livelihood |

## 5. Funnel building

- The AI builds the funnel autonomously. The visual builder is an **optional,
  advanced** view, not the main path.
- A funnel moves through **dry run -> shadow run -> live**. Dry run touches
  nothing. Shadow run produces real drafts and decisions but sends nothing.

## 6. Email and compliance (EU first)

- Gmail/Outlook accounts: enforce the provider's stated sending limits.
- Self-hosted mailboxes: no provider cap, but **reputation caps** (warm-up ramp,
  per-domain limits), always from a **dedicated sending subdomain**, never the main domain.
- **Send guard** before every send: deterministic checks first (suppression list,
  country rules, rate, domain health), then an LLM review (spammy phrasing,
  unverifiable claims, tone). Both must pass.
- Every message carries: who is writing, where the contact data came from, the
  legal basis, and a one-click opt-out.
- **One touch only.** No second unsolicited message unless the lead interacts.
- **Interaction = a reply.** **Proposed (tightened from the brainstorm):** page visits are
  counted in aggregate only, with no per-lead tokens, no pixels, no redirect tracking,
  so they can never trigger a follow-up. Revisit with counsel.
- Compliance is a **per-country rules table that blocks sends**, not one global policy.
  Germany (consent for B2B email) is expected to be blocked in v1. Sole traders count
  as natural persons in several countries.
- Permanent, platform-wide suppression list.
- Lead discovery: public sources, company registries, own crawler respecting
  robots.txt. No scraping of platforms whose terms forbid it.
- Needs counsel review before any real send: controller/processor roles
  (the freelancer is expected to be the sender and controller), DPA, Art. 14 notice
  content, legal basis per country.

## 7. Identity and UI

- One metaphor: a **living stream** (pipeline as a current that narrows stage by stage).
- One hot accent colour on a near-black ground. Huge numerals. A command bar.
- The hero of the dashboard is one number: *calls booked this week*, plus a
  *next best move* card.
- The onboarding interview is where the product's personality lives.

## Open questions

1. Product name (Current is a placeholder).
2. Which social platforms get publishing in the first release after v1.
3. Pricing and fair-use limits per plan, pending the cost model in the validation plan.
4. Languages supported at launch (depends on Qwen draft quality per language).
5. Self-hosted mailbox provider and IP strategy.
