# Validation plan: the riskiest assumption

## What we are testing

> A compliant, one-touch outreach and content engine, run by an AI agent on a
> small local model, books enough qualified calls to justify a subscription,
> while asking the freelancer for no more than about 15 minutes a day.

If this is false, the dashboard and the funnel builder do not matter. So we test
it before building them.

It breaks into five measurable parts:

| # | Sub-assumption | Question |
| --- | --- | --- |
| A1 | Reach | Can the agent find enough in-ICP, legally contactable leads? |
| A2 | Response | Do one-touch emails earn enough positive replies to produce calls? |
| A3 | Quality | Are Qwen-class drafts acceptable with light editing, in the freelancer's language? |
| A4 | Effort | Is the approval workload low enough that people keep doing it? |
| A5 | Economics | Does compute + data cost per active user fit inside a flat subscription? |

## Design: a concierge test

We run the pipeline semi-manually, with scripts and a local Qwen for drafting and
people doing whatever is not built yet. Freelancers approve drafts through a daily
digest (email or chat), which is the same loop the decisions inbox will replace.

- **Participants:** 5 freelancers, 2 to 3 different niches, 2 to 3 EU countries.
  Exclude Germany for cold B2B email in this round.
- **Roles:** the freelancer is the sender of record. Counsel confirms the
  controller/processor arrangement and the data-processing terms first.
- **Cost to them:** free for the test, in exchange for sharing their metrics.

### Timeline

| Week | Work |
| --- | --- |
| 0 | Counsel review of the rules table for the chosen countries. Dedicated sending subdomain, SPF/DKIM/DMARC. Onboarding interview with each freelancer. |
| 1 to 2 | Mailbox warm-up (no cold sends). Lead list building. Content drafts for approval. |
| 3 to 6 | Sending ramp, conservative at first (for example from about 10 a day per mailbox up to about 30 to 40). One touch per prospect. |
| 7 | Readout against the thresholds below. |

Warm-up is why the test needs about seven weeks, not four.

### Expected range (arithmetic, not data)

Assuming about 140 contacted per week for 4 sending weeks (about 560 touches) and
a positive-reply rate of 1 to 3%, that is roughly 5 to 17 positive replies per
freelancer, and about half might book a call: 3 to 8 calls. Every rate in that
sentence is an assumption. Measuring them is the point of the test.

## Metrics and proposed thresholds

Thresholds are **proposed** and should be agreed before the test starts.

| Metric | Target | Kill / rethink |
| --- | --- | --- |
| In-ICP contactable leads found per freelancer per week | 150 or more | under 60 |
| Bounce rate | under 3% | over 5% |
| Spam complaints | under 0.1% | over 0.3% |
| Unsubscribe rate | under 1% | over 2% |
| Positive replies, share of delivered | 1% or more | under 0.3% |
| Booked calls per freelancer over weeks 3 to 6 | 2 or more, in at least 3 of 5 freelancers | under 1 in most |
| Drafts sent without edits | 60% or more | under 30% |
| Freelancer time on approvals | 15 min/day or less | over 30 min/day |
| Compute cost per active user per month | tracked, compared to target price | above 30% of price |

Blind quality check: for a sample of drafts per language, a native speaker rates
the local Qwen output against a larger model's output without knowing which is which.
This decides which tasks must escalate to the larger model.

## What we log on every touch

Lead id, source URL and date, legal basis, rules-table version, send-guard decision
and reasons, model and prompt version used for the draft, edit distance between
draft and sent text, approval timestamp, delivery status, outcome.
This log is also the audit trail the compliance engine will need.

## Decision rules

- **Go:** thresholds met in at least 3 of 5 freelancers. Write the spec, build the dashboard.
- **Iterate:** deliverability and compliance fine, response weak. Change the offer,
  targeting and content engine before touching the product.
- **Pivot:** reach or response persistently under the kill line, or approvals
  consume too much time. Reconsider the channel mix (for example, inbound-first).

## Open items

- Who counsel is, and the budget for the review.
- How freelancers are recruited. Candidate criteria: a clear offer, a reachable ICP
  in the chosen countries, and willingness to share metrics.
- Which self-hosted mailbox provider to use for the test.
