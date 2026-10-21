"""The send guard: the last gate before anything leaves.

Deterministic checks first (suppression, country rules, one touch, daily limit,
domain health, footer). An LLM review of claims runs last. Every check is
recorded with its reason; nothing is silently dropped.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Callable

from current import db
from current.agent import footer as footer_mod
from current.agent import tasks
from current.compliance.rules import RulesTable
from current.config import Settings
from current.llm.router import ModelRouter

PASS, FAIL, REVIEW, ADJUSTED = "pass", "fail", "review", "adjusted"
PROVIDER_CAPS = {"gmail": 500, "outlook": 300}  # provider-stated daily maximums
WARMUP_START, WARMUP_STEP, WARMUP_CAP = 10, 2, 40  # self-hosted ramp: start, per day, ceiling
BOUNCE_MAX, COMPLAINT_MAX = 0.05, 0.003


@dataclass
class Check:
    name: str
    status: str
    detail: str


@dataclass
class GuardResult:
    checks: list[Check] = field(default_factory=list)
    rules_version: str = ""

    @property
    def passed(self) -> bool:
        return all(c.status in (PASS, ADJUSTED) for c in self.checks)

    @property
    def blocking(self) -> list[Check]:
        return [c for c in self.checks if c.status in (FAIL, REVIEW)]

    def to_dict(self) -> dict:
        return {"checks": [asdict(c) for c in self.checks], "rules_version": self.rules_version}


def start_of_day(now: datetime) -> str:
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def effective_limit(profile: dict, now: datetime, warmup_started: str | None) -> int:
    """The user's limit, capped by the provider's own, or by the warm-up ramp for self-hosted."""
    user = int(profile.get("daily_limit", 60))
    provider = profile.get("provider", "gmail")
    if provider == "self_hosted":
        if not warmup_started:
            return min(user, WARMUP_START)
        days = max(0, (now - datetime.fromisoformat(warmup_started)).days)
        return min(user, WARMUP_START + WARMUP_STEP * days, WARMUP_CAP)
    return min(user, PROVIDER_CAPS.get(provider, 100))


def sent_today(conn: sqlite3.Connection, now: datetime) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM touches WHERE direction='out' AND simulated=0 AND at>=?",
        (start_of_day(now),),
    ).fetchone()[0]


class SendGuard:
    def __init__(self, conn: sqlite3.Connection, rules: RulesTable, router: ModelRouter,
                 settings: Settings, now: Callable[[], datetime], *, strict: bool) -> None:
        self.conn, self.rules, self.router = conn, rules, router
        self.settings, self.now, self.strict = settings, now, strict

    def check(self, decision: sqlite3.Row, lead: sqlite3.Row) -> GuardResult:
        res = GuardResult(rules_version=self.rules.version)
        add = lambda n, s, d: res.checks.append(Check(n, s, d))  # noqa: E731
        profile = db.get_json(self.conn, "profile", {})
        email, kind = lead["email"], decision["kind"]

        # 1. Suppression list
        row = self.conn.execute("SELECT reason FROM suppression WHERE email=?", (email.lower(),)).fetchone()
        add("Suppression list", FAIL if row else PASS, f"suppressed: {row['reason']}" if row else "not listed")

        replied = self.conn.execute(
            "SELECT 1 FROM touches WHERE lead_id=? AND direction='in' AND kind='reply'", (lead["id"],)
        ).fetchone() is not None

        if kind == "email":
            # 2. Country rules
            r = self.rules.evaluate(lead["country"], lead["recipient_type"], strict=self.strict)
            status = {"allow": PASS, "block": FAIL, "needs_review": REVIEW}[r.decision]
            add("Country rules", status, f"{lead['country']}, {lead['recipient_type']}: {r.decision} ({r.reason})")

            # 3. One touch
            prior = self.conn.execute(
                "SELECT at FROM touches WHERE lead_id=? AND direction='out' AND simulated=0 LIMIT 1", (lead["id"],)
            ).fetchone()
            if prior and not replied:
                add("First contact", FAIL, f"already contacted on {prior['at'][:10]}; a second message needs their reply")
            else:
                add("First contact", PASS, "no earlier message to this address")
        elif kind == "reply":
            add("Follow-up allowed", PASS if replied else FAIL,
                "the recipient replied first" if replied else "no reply from this lead; cannot write again")

        if kind in ("email", "reply"):
            # 4. Daily limit
            limit = effective_limit(profile, self.now(), db.get_json(self.conn, "warmup_started"))
            used = sent_today(self.conn, self.now())
            add("Daily limit", PASS if used < limit else FAIL, f"{used} of {limit} used today")

            # 5. Domain health
            health = db.get_json(self.conn, "health", {"bounce": 0.012, "complaint": 0.0})
            ok = health["bounce"] <= BOUNCE_MAX and health["complaint"] <= COMPLAINT_MAX
            add("Domain health", PASS if ok else FAIL,
                f"bounce {health['bounce']:.1%}, complaints {health['complaint']:.1%}")

            # 6. Footer
            miss = footer_mod.missing_parts(decision["footer"] or "", profile, dict(lead),
                                            self.settings.base_url, self.settings.secret) \
                if kind == "email" else \
                ([] if footer_mod.opt_out_url(self.settings.base_url, self.settings.secret, email) in (decision["footer"] or "")
                 else ["opt-out link"])
            add("Footer", FAIL if miss else PASS,
                f"missing: {', '.join(miss)}" if miss else "identity, source, basis and opt-out present"
                if kind == "email" else "opt-out present")

        # 7. Claims review (LLM, advisory input that can block)
        if decision["body"]:
            try:
                bad = tasks.review_claims(self.router, decision["body"], profile.get("proof", ""))
            except Exception as e:  # noqa: BLE001 - no reviewer means no send
                add("Claims review", REVIEW, f"reviewer unavailable: {e}")
            else:
                adjusted = (decision["adjusted"] or "").count("\n") + 1 if decision["adjusted"] else 0
                if bad:
                    add("Claims review", FAIL, f"unsupported claim: {bad[0][:80]}")
                elif adjusted:
                    add("Claims review", ADJUSTED, f"{adjusted} unverifiable claim removed from the draft")
                else:
                    add("Claims review", PASS, "no unsupported claims")
        return res
