"""The engine: orchestrates scouting, drafting, guarding, approving and reporting.

One Engine owns one SQLite connection. Public methods take a lock so the web
layer can call them from a thread pool.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from current import db
from current.agent import footer as footer_mod
from current.agent import tasks
from current.compliance.rules import RulesTable
from current.config import Settings
from current.guard import GuardResult, SendGuard, effective_limit, sent_today, start_of_day
from current.llm.router import ModelRouter, build_router
from current.mail.outbox import DryRunMailer
from current.scout.sources import DemoRegistrySource, LeadSource

DEFAULT_PROFILE = {
    "offer": "", "icp": "", "countries": [], "languages": [], "proof": "",
    "sender_name": "", "studio": "", "city": "", "contact_email": "",
    "provider": "gmail", "daily_limit": 60,
}
DEFAULT_AUTONOMY = {"email": 1, "reply": 1, "post": 1, "schedule": 0}  # 0 suggest, 1 approve first, 2 auto
DEFAULT_SLOTS = ["Thu 11:00", "Thu 15:30"]
AUTO_DAILY_CAP = 30
QUALIFY_THRESHOLD = 60
SHADOW_DAYS_REQUIRED = 7
WARMUP_DAYS_REQUIRED = 21
EDIT_RATE_MAX = 0.40
MODES = ("dry_run", "shadow", "live")

REGIONS = {
    "Portugal and France · PT, FR, EN": (["PT", "FR"], ["pt", "fr", "en"]),
    "Netherlands · NL, EN": (["NL"], ["nl", "en"]),
    "Italy · IT, EN": (["IT"], ["it", "en"]),
}


class NotOnboarded(RuntimeError):
    pass


class PromotionBlocked(RuntimeError):
    pass


@dataclass
class Outcome:
    status: str
    guard: GuardResult | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Engine:
    def __init__(self, settings: Settings, *, router: ModelRouter | None = None,
                 rules: RulesTable | None = None, now: Callable[[], datetime] | None = None,
                 mailer=None) -> None:
        self.s = settings
        self.router = router or build_router(settings)
        self.rules = rules or RulesTable.load(settings.rules_path)
        self.now = now or _utcnow
        self.mailer = mailer or DryRunMailer()
        self.conn = db.connect(settings.db_path)
        self.lock = threading.RLock()

    # -- small helpers ---------------------------------------------------------

    @property
    def strict(self) -> bool:
        return bool(self.mailer.can_send)

    def _iso(self) -> str:
        return self.now().isoformat()

    def log(self, text: str) -> None:
        self.conn.execute("INSERT INTO events(at,text) VALUES(?,?)", (self._iso(), text))
        self.conn.commit()

    def events(self, limit: int = 8) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def _guard(self) -> SendGuard:
        return SendGuard(self.conn, self.rules, self.router, self.s, self.now, strict=self.strict)

    # -- profile, autonomy, mode -------------------------------------------------

    def profile(self) -> dict:
        return {**DEFAULT_PROFILE, **db.get_json(self.conn, "profile", {})}

    def onboarded(self) -> bool:
        p = self.profile()
        return bool(p["sender_name"] and p["icp"] and p["countries"])

    def save_profile(self, **fields) -> dict:
        with self.lock:
            p = {**self.profile(), **fields}
            db.set_json(self.conn, "profile", p)
            return p

    def autonomy(self) -> dict:
        return {**DEFAULT_AUTONOMY, **db.get_json(self.conn, "autonomy", {})}

    def set_autonomy(self, kind: str, level: int) -> None:
        if kind not in DEFAULT_AUTONOMY or level not in (0, 1, 2):
            raise ValueError("bad autonomy setting")
        with self.lock:
            a = self.autonomy()
            a[kind] = level
            db.set_json(self.conn, "autonomy", a)

    def mode(self) -> str:
        return db.get_json(self.conn, "mode", "dry_run")

    def slots(self) -> list[str]:
        return db.get_json(self.conn, "slots", DEFAULT_SLOTS)

    # -- the cycle: scout -> qualify -> hold or draft -------------------------------

    def run_cycle(self, source: LeadSource | None = None, limit: int = 20) -> Counter:
        with self.lock:
            if not self.onboarded():
                raise NotOnboarded("Finish onboarding first")
            profile = self.profile()
            source = source or DemoRegistrySource()
            n: Counter = Counter()
            for c in source.fetch(profile, limit, self._iso()):
                cand = c.as_dict()
                if self.conn.execute("SELECT 1 FROM leads WHERE email=?", (c.email.lower(),)).fetchone():
                    continue
                if self.conn.execute("SELECT 1 FROM suppression WHERE email=?", (c.email.lower(),)).fetchone():
                    n["suppressed"] += 1
                    continue
                lead_id = self._insert_lead(cand)
                n["scouted"] += 1
                if c.country.upper() not in profile["countries"]:
                    self._set_lead(lead_id, "rejected", hold_reason="Outside your regions")
                    continue
                q = tasks.qualify(self.router, profile, cand)
                self.conn.execute("UPDATE leads SET fit_score=?, fit_reason=? WHERE id=?",
                                  (q["score"], q["reason"], lead_id))
                if q["score"] < QUALIFY_THRESHOLD:
                    self._set_lead(lead_id, "rejected", hold_reason=f"Low fit ({q['score']})")
                    continue
                n["qualified"] += 1
                rule = self.rules.evaluate(c.country, c.recipient_type, strict=self.strict)
                if rule.decision != "allow":
                    self._set_lead(lead_id, "held", hold_reason=f"{c.country}: {rule.reason}")
                    n["held"] += 1
                    continue
                lead = dict(self.conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone())
                d = tasks.draft(self.router, profile, lead)
                body, removed = tasks.sanitize(self.router, d["body"], profile["proof"])
                self.conn.execute(
                    "INSERT INTO decisions(kind,lead_id,subject,body,footer,adjusted,model,created_at) "
                    "VALUES('email',?,?,?,?,?,?,?)",
                    (lead_id, d["subject"], body,
                     footer_mod.build_footer(profile, lead, self.s.base_url, self.s.secret),
                     "\n".join(removed) or None, d["model"], self._iso()),
                )
                self._set_lead(lead_id, "drafted")
                n["drafted"] += 1
            self.conn.commit()
            self.log(
                f"Scouted {n['scouted']}, qualified {n['qualified']}, drafted {n['drafted']}"
                + (f", held back {n['held']} by country rules" if n["held"] else "")
                + "."
            )
            n["auto"] = self.autopilot()
            return n

    def _insert_lead(self, c: dict) -> int:
        cur = self.conn.execute(
            "INSERT INTO leads(name,org,role,email,country,recipient_type,description,source_name,"
            "source_url,found_at,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (c["name"], c["org"], c["role"], c["email"].lower(), c["country"].upper(), c["recipient_type"],
             c["description"], c["source_name"], c["source_url"], c["found_at"], "new", self._iso()),
        )
        return cur.lastrowid

    def _set_lead(self, lead_id: int, status: str, hold_reason: str | None = None) -> None:
        self.conn.execute("UPDATE leads SET status=?, hold_reason=? WHERE id=?", (status, hold_reason, lead_id))

    # -- decisions --------------------------------------------------------------------

    def decision(self, decision_id: int) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT d.*, l.org, l.name AS lead_name, l.email, l.country FROM decisions d "
            "LEFT JOIN leads l ON l.id=d.lead_id WHERE d.id=?", (decision_id,)
        ).fetchone()

    def decisions(self, status: str | None = None) -> list[sqlite3.Row]:
        q = ("SELECT d.*, l.org, l.name AS lead_name, l.email, l.country FROM decisions d "
             "LEFT JOIN leads l ON l.id=d.lead_id")
        order = " ORDER BY CASE d.kind WHEN 'reply' THEN 0 WHEN 'email' THEN 1 ELSE 2 END, d.id"
        if status:
            return self.conn.execute(q + " WHERE d.status=?" + order, (status,)).fetchall()
        return self.conn.execute(q + order).fetchall()

    def approve(self, decision_id: int, *, actor: str = "user") -> Outcome:
        with self.lock:
            d = self.conn.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
            if d is None or d["status"] != "pending":
                return Outcome("ignored")
            lead = self.conn.execute("SELECT * FROM leads WHERE id=?", (d["lead_id"],)).fetchone()
            guard = self._guard().check(d, lead)
            gjson = json.dumps(guard.to_dict())
            now = self._iso()

            def finish(status: str) -> Outcome:
                self.conn.execute(
                    "UPDATE decisions SET status=?, guard=?, decided_by=?, decided_at=? WHERE id=?",
                    (status, gjson, actor, now, decision_id),
                )
                self.conn.commit()
                return Outcome(status, guard)

            if not guard.passed:
                why = "; ".join(f"{c.name}: {c.detail}" for c in guard.blocking)
                self.log(f"Blocked a message to {lead['org']}. {why}")
                return finish("blocked")
            if self.autonomy().get(d["kind"], 1) == 0:
                return finish("handed_off")  # suggest-only: the user sends it themselves

            kind = "intro" if d["kind"] == "email" else "response"
            simulated = 0 if self.mode() == "live" else 1
            if not simulated:
                full = d["body"] + "\n\n-- \n" + (d["footer"] or "")
                self.mailer.send(self.conn, decision_id=decision_id, to_email=lead["email"],
                                 subject=d["subject"], body=full, at=now)
                self._set_lead(lead["id"], "contacted" if kind == "intro" else "offered")
            self.conn.execute(
                "INSERT INTO touches(lead_id,direction,kind,body,at,rules_version,guard,simulated) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (lead["id"], "out", kind, d["body"], now, guard.rules_version, gjson, simulated),
            )
            return finish("sent" if not simulated else "approved_shadow")

    def preview_guard(self, decision_id: int) -> GuardResult | None:
        """Run the guard on a pending decision without changing anything."""
        with self.lock:
            d = self.conn.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
            if d is None or d["status"] != "pending":
                return None
            lead = self.conn.execute("SELECT * FROM leads WHERE id=?", (d["lead_id"],)).fetchone()
            return self._guard().check(d, lead)

    def approve_all(self, kind: str) -> Counter:
        n: Counter = Counter()
        for d in self.decisions("pending"):
            if d["kind"] == kind:
                n[self.approve(d["id"]).status] += 1
        return n

    def skip(self, decision_id: int) -> None:
        with self.lock:
            self.conn.execute(
                "UPDATE decisions SET status='skipped', decided_by='user', decided_at=? "
                "WHERE id=? AND status='pending'", (self._iso(), decision_id))
            self.conn.commit()

    def edit(self, decision_id: int, subject: str, body: str) -> None:
        with self.lock:
            self.conn.execute(
                "UPDATE decisions SET subject=?, body=?, edited=1 WHERE id=? AND status='pending'",
                (subject.strip(), body.strip(), decision_id))
            self.conn.commit()

    def autopilot(self) -> int:
        """Approve pending items for action types set to 'auto', within the daily cap."""
        with self.lock:
            aut, done = self.autonomy(), 0
            used = self.conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE decided_by='auto' AND decided_at>=?",
                (start_of_day(self.now()),)).fetchone()[0]
            for d in self.decisions("pending"):
                if aut.get(d["kind"]) != 2 or used + done >= AUTO_DAILY_CAP:
                    continue
                if self.approve(d["id"], actor="auto").status != "ignored":
                    done += 1
            return done

    # -- suppression, replies, outcomes ---------------------------------------------------

    def suppress(self, email: str, reason: str) -> None:
        with self.lock:
            email = email.lower()
            self.conn.execute("INSERT OR IGNORE INTO suppression(email,reason,at) VALUES(?,?,?)",
                              (email, reason, self._iso()))
            lead = self.conn.execute("SELECT id FROM leads WHERE email=?", (email,)).fetchone()
            if lead:
                self._set_lead(lead["id"], "suppressed")
                self.conn.execute(
                    "UPDATE decisions SET status='cancelled' WHERE lead_id=? AND status='pending'", (lead["id"],))
            self.conn.commit()
            self.log(f"Added an address to the suppression list ({reason}).")

    def opt_out(self, token: str) -> bool:
        email = footer_mod.read_token(self.s.secret, token)
        if not email:
            return False
        self.suppress(email, "opted out via link")
        return True

    def receive_reply(self, lead_id: int, text: str) -> str:
        """Record an inbound reply, classify it, and act on the label."""
        with self.lock:
            lead = self.conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
            if lead is None:
                raise KeyError(lead_id)
            self.conn.execute(
                "INSERT INTO touches(lead_id,direction,kind,body,at) VALUES(?,?,?,?,?)",
                (lead_id, "in", "reply", text, self._iso()))
            label = tasks.triage(self.router, text)
            if label == "unsubscribe":
                self.suppress(lead["email"], "asked to stop")
            elif label == "negative":
                self._set_lead(lead_id, "closed")
                self.conn.execute("UPDATE decisions SET status='cancelled' WHERE lead_id=? AND status='pending'", (lead_id,))
                self.log(f"{lead['org']} said no. Closed, no further contact.")
            elif label in ("positive", "question"):
                self._set_lead(lead_id, "replied")
                profile = self.profile()
                subj = (self.conn.execute(
                    "SELECT subject FROM decisions WHERE lead_id=? AND kind='email' ORDER BY id LIMIT 1",
                    (lead_id,)).fetchone() or {"subject": ""})["subject"]
                d = tasks.draft(self.router, profile, dict(lead), kind="response", slots=self.slots(), subject=subj)
                self.conn.execute(
                    "INSERT INTO decisions(kind,lead_id,subject,body,footer,model,created_at) "
                    "VALUES('reply',?,?,?,?,?,?)",
                    (lead_id, d["subject"], d["body"],
                     footer_mod.build_footer(profile, dict(lead), self.s.base_url, self.s.secret, kind="response"),
                     d["model"], self._iso()))
                self.log(f"Positive reply from {lead['org']}. Drafted an answer with two slots.")
            self.conn.commit()
            self.autopilot()
            return label

    def mark(self, lead_id: int, outcome: str) -> None:
        if outcome not in ("booked", "won"):
            raise ValueError(outcome)
        with self.lock:
            self.conn.execute("INSERT INTO touches(lead_id,direction,kind,at) VALUES(?,?,?,?)",
                              (lead_id, "sys", outcome, self._iso()))
            self._set_lead(lead_id, outcome)
            self.conn.commit()

    def leads(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()

    # -- stages and the go-live gate -------------------------------------------------------

    def gate(self) -> dict:
        mode, p = self.mode(), self.profile()
        decided = self.conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE kind='email' AND status IN ('approved_shadow','sent','skipped')"
        ).fetchone()[0]
        edited = self.conn.execute("SELECT COUNT(*) FROM decisions WHERE kind='email' AND edited=1").fetchone()[0]
        crit: list[dict] = []
        nxt = None
        if mode == "dry_run":
            nxt = "shadow"
            drafted = self.conn.execute("SELECT COUNT(*) FROM decisions WHERE kind='email'").fetchone()[0]
            blocked = self.conn.execute("SELECT COUNT(*) FROM decisions WHERE status='blocked'").fetchone()[0]
            crit = [
                {"name": "The dry run produced drafts", "ok": drafted > 0, "detail": f"{drafted} drafts"},
                {"name": "No draft was blocked by the send guard", "ok": blocked == 0, "detail": f"{blocked} blocked"},
                {"name": "You reviewed at least 3 drafts", "ok": decided >= 3, "detail": f"{decided} reviewed"},
            ]
        elif mode == "shadow":
            nxt = "live"
            start = db.get_json(self.conn, "shadow_started")
            days = (self.now() - datetime.fromisoformat(start)).days if start else 0
            rate = edited / decided if decided else 0.0
            crit = [
                {"name": f"{SHADOW_DAYS_REQUIRED} days of shadow drafts reviewed", "ok": days >= SHADOW_DAYS_REQUIRED,
                 "detail": f"day {min(days + 1, SHADOW_DAYS_REQUIRED)} of {SHADOW_DAYS_REQUIRED}"},
                {"name": "Your edit rate is under 40%", "ok": decided > 0 and rate < EDIT_RATE_MAX,
                 "detail": f"{rate:.0%} so far" if decided else "no reviews yet"},
            ]
            if p["provider"] == "self_hosted":
                w = db.get_json(self.conn, "warmup_started")
                wd = (self.now() - datetime.fromisoformat(w)).days if w else 0
                crit.append({"name": "Mailbox warm-up finished", "ok": wd >= WARMUP_DAYS_REQUIRED,
                             "detail": f"day {min(wd + 1, WARMUP_DAYS_REQUIRED)} of {WARMUP_DAYS_REQUIRED}"})
            for c in p["countries"]:
                ok = self.rules.signed_off(c)
                crit.append({"name": f"{c} country rules signed off", "ok": ok,
                             "detail": "reviewed" if ok else "waiting for legal review"})
        return {"mode": mode, "next": nxt, "criteria": crit,
                "ok": bool(crit) and all(c["ok"] for c in crit)}

    def promote(self) -> str:
        with self.lock:
            g = self.gate()
            if g["next"] is None:
                raise PromotionBlocked("Already live")
            if not g["ok"] and not self.s.dev_unlock:
                raise PromotionBlocked("Checks have not passed")
            db.set_json(self.conn, "mode", g["next"])
            if g["next"] == "live":
                # An approval given while nothing could be sent does not authorise a real send.
                self.conn.execute(
                    "UPDATE decisions SET status='pending', decided_by=NULL, decided_at=NULL, guard=NULL "
                    "WHERE status='approved_shadow'")
                self.conn.commit()
            if g["next"] == "shadow":
                db.set_json(self.conn, "shadow_started", self._iso())
                if self.profile()["provider"] == "self_hosted" and not db.get_json(self.conn, "warmup_started"):
                    db.set_json(self.conn, "warmup_started", self._iso())
            self.log(f"Funnel moved to {g['next'].replace('_', ' ')}.")
            return g["next"]

    def reset(self) -> None:
        """Wipe funnel data. Keeps the profile, autonomy settings and suppression list."""
        with self.lock:
            for t in ("outbox", "touches", "decisions", "leads", "events"):
                self.conn.execute(f"DELETE FROM {t}")
            self.conn.commit()
            db.set_json(self.conn, "mode", "dry_run")

    def node_values(self) -> list[str]:
        """One line per funnel step, from real data, for the funnel view."""
        c = self.conn

        def one(sql: str, *a) -> int:
            return c.execute(sql, a).fetchone()[0]

        live = self.mode() == "live"
        sent = one("SELECT COUNT(*) FROM decisions WHERE kind='email' AND status='sent'")
        shadow = one("SELECT COUNT(*) FROM decisions WHERE kind='email' AND status='approved_shadow'")
        skipped = one("SELECT COUNT(*) FROM decisions WHERE kind='email' AND status='skipped'")
        edited = one("SELECT COUNT(*) FROM decisions WHERE kind='email' AND edited=1")
        blocked = one("SELECT COUNT(*) FROM decisions WHERE status='blocked'")
        held = one("SELECT COUNT(*) FROM leads WHERE status='held'")
        passed = sent + shadow
        waiting = one("SELECT COUNT(*) FROM leads WHERE status='contacted'")
        found = one("SELECT COUNT(*) FROM leads")
        matched = one("SELECT COUNT(*) FROM leads WHERE fit_score>=?", QUALIFY_THRESHOLD)
        drafts = one("SELECT COUNT(*) FROM decisions WHERE kind='email'")
        answers = one("SELECT COUNT(*) FROM decisions WHERE kind='reply'")
        booked = one("SELECT COUNT(*) FROM touches WHERE kind='booked'")
        return [
            f"{found} found",
            f"{matched} matched",
            f"{drafts} drafts",
            f"{passed + skipped} reviewed" + (f", {edited} edited" if edited else ""),
            f"{passed} passed" + (f", {blocked} blocked" if blocked else "") + (f", {held} held" if held else ""),
            f"{sent} sent" if live else "0 sent, by design",
            f"{waiting} waiting" if live else "—",
            f"{answers} answers drafted",
            f"{booked} booked",
        ]

    # -- numbers for the dashboard ---------------------------------------------------------------

    def stats(self) -> dict:
        c, now = self.conn, self.now()
        since, before = (now - timedelta(days=7)).isoformat(), (now - timedelta(days=14)).isoformat()
        mode = self.mode()
        sim = 0 if mode == "live" else 1

        def one(sql: str, *a) -> int:
            return c.execute(sql, a).fetchone()[0]

        booked = one("SELECT COUNT(*) FROM touches WHERE kind='booked' AND at>=?", since)
        booked_prev = one("SELECT COUNT(*) FROM touches WHERE kind='booked' AND at>=? AND at<?", before, since)
        funnel = [
            one("SELECT COUNT(*) FROM leads WHERE created_at>=?", since),
            one("SELECT COUNT(*) FROM leads WHERE created_at>=? AND fit_score>=?", since, QUALIFY_THRESHOLD),
            one("SELECT COUNT(DISTINCT lead_id) FROM touches WHERE direction='out' AND kind='intro' "
                "AND simulated=? AND at>=?", sim, since),
            one("SELECT COUNT(DISTINCT lead_id) FROM touches WHERE kind='reply' AND at>=?", since),
            booked,
            one("SELECT COUNT(*) FROM touches WHERE kind='won' AND at>=?", since),
        ]
        p = self.profile()
        limit = effective_limit(p, now, db.get_json(c, "warmup_started"))
        held = c.execute("SELECT hold_reason, COUNT(*) n FROM leads WHERE status='held' GROUP BY hold_reason").fetchall()
        return {
            "mode": mode, "booked": booked, "booked_delta": booked - booked_prev, "funnel": funnel,
            "sent_today": sent_today(c, now), "limit": limit,
            "approved_today_sim": one("SELECT COUNT(*) FROM touches WHERE direction='out' AND simulated=1 AND at>=?",
                                      start_of_day(now)),
            "health": db.get_json(c, "health", {"bounce": 0.012, "complaint": 0.0}),
            "held": [(r["hold_reason"], r["n"]) for r in held],
            "held_total": sum(r["n"] for r in held),
            "suppressed": one("SELECT COUNT(*) FROM suppression"),
            "pending": one("SELECT COUNT(*) FROM decisions WHERE status='pending'"),
            "weekly_booked": [
                one("SELECT COUNT(*) FROM touches WHERE kind='booked' AND at>=? AND at<?",
                    (now - timedelta(days=7 * (i + 1))).isoformat(), (now - timedelta(days=7 * i)).isoformat())
                for i in reversed(range(8))
            ],
        }
