"""FastAPI app: server-rendered pages, plain forms, no client-side framework."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from current import onboarding
from current.config import from_env
from current.service import AUTO_DAILY_CAP, Engine, NotOnboarded, PromotionBlocked
from current.web import viz

BASE = Path(__file__).parent
LEVELS = ["Suggest", "Approve first", "Auto within limits"]
AUTONOMY_ROWS = [
    ("email", "Send intro emails", f"Auto means up to {AUTO_DAILY_CAP} a day, one touch each"),
    ("reply", "Answer positive replies", "Auto only offers your calendar slots"),
]
NODES = [
    ("Scout", "Finds prospects in public sources.", "AGENT"),
    ("Qualify", "Scores each against your ideal client.", "AGENT"),
    ("Draft", "Writes one email per prospect.", "AGENT"),
    ("Approve", "You review. Your autonomy setting decides how often.", "YOU"),
    ("Guard", "Suppression, country rules, limits, footer, claims.", "RULES"),
    ("Send once", "One message. No second touch.", "AGENT"),
    ("Wait", "Only a reply opens the next step.", "THEM"),
    ("Offer slots", "Proposes times from your calendar.", "AGENT"),
    ("Book", "The call lands in your calendar.", "BOTH"),
]
STAGES = [
    ("dry_run", "Dry run", "Simulated on sample prospects. Touches nothing real."),
    ("shadow", "Shadow run", "Real prospects and drafts. Nothing is sent, by design."),
    ("live", "Live", "One email per prospect, within the limits you set."),
]
STATUS_LABEL = {
    "pending": "", "sent": "Sent", "approved_shadow": "Approved (shadow)", "blocked": "Blocked",
    "skipped": "Skipped", "handed_off": "Handed off", "cancelled": "Cancelled",
}


def _dview(d) -> dict:
    who = d["lead_name"] or d["org"] or ""
    if d["kind"] == "reply":
        return {"id": d["id"], "kind": "reply", "group": "reply", "type": "REPLY",
                "title": f"{who} replied", "meta": f"{d['org']} · draft answer ready", "status": d["status"]}
    return {"id": d["id"], "kind": "email", "group": "email", "type": "EMAIL",
            "title": f"Intro to {d['org']}", "meta": f"{d['country']} · {who}", "status": d["status"]}


def _hhmm(iso: str) -> str:
    dt = datetime.fromisoformat(iso)
    return dt.strftime("%H:%M") if dt.date() == datetime.now(dt.tzinfo).date() else dt.strftime("%a")


def create_app(engine: Engine | None = None) -> FastAPI:
    eng = engine or Engine(from_env())
    app = FastAPI(title="Current")
    app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
    templates = Jinja2Templates(directory=BASE / "templates")

    def render(request: Request, name: str, active: str, **kw) -> HTMLResponse:
        level = eng.autonomy()["email"]
        return templates.TemplateResponse(request, name, {
            "active": active, "pending": eng.stats()["pending"], "mode": eng.mode(),
            "level": level, "level_label": LEVELS[level], "flash": request.query_params.get("msg"), **kw,
        })

    def back(path: str, msg: str | None = None) -> RedirectResponse:
        sep = "&" if "?" in path else "?"
        return RedirectResponse(path + (f"{sep}msg={quote(msg)}" if msg else ""), status_code=303)

    def gated(request: Request):
        return None if eng.onboarded() else back("/onboarding")

    # -- today ---------------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    def today(request: Request):
        if (r := gated(request)):
            return r
        s = eng.stats()
        pend = [_dview(d) for d in eng.decisions("pending")]
        nxt = None
        if pend:
            first, d0 = pend[0], eng.decision(pend[0]["id"])
            n_email = sum(1 for p in pend if p["kind"] == "email")
            shadow = "" if eng.mode() == "live" else " This funnel is not live, so approving records the decision and sends nothing."
            if first["kind"] == "reply":
                nxt = {"kicker": f"REPLY · {d0['org']}".upper(), "title": f"{d0['lead_name']} wrote back. Send your answer.",
                       "body": "Draft ready with your calendar slots: " + " or ".join(eng.slots()) + "." + shadow,
                       "action": f"/decisions/{first['id']}/approve", "cta": "Send reply", "fields": {"next": "/"}}
            else:
                nxt = {"kicker": f"EMAIL · {n_email} INTRO MESSAGES",
                       "title": f"Approve today’s {n_email} intro emails",
                       "body": "The send guard checks every one again before it leaves. One touch each, with source and opt-out." + shadow,
                       "action": "/decisions/approve-all", "cta": f"Approve {n_email}", "fields": {"kind": "email", "next": "/"}}
        counts = s["funnel"]
        return render(request, "today.html", "today", s=s, stream=viz.stream(counts), particles=viz.PARTICLES,
                      counts=counts, pend=pend[:5], nxt=nxt, events=[(_hhmm(e["at"]), e["text"]) for e in eng.events(7)],
                      pct=int(100 * s["sent_today"] / s["limit"]) if s["limit"] else 0,
                      spark=_spark(s["weekly_booked"]), profile=eng.profile())

    @app.post("/cycle")
    def cycle(next: str = Form("/")):
        try:
            n = eng.run_cycle()
        except NotOnboarded:
            return back("/onboarding")
        msg = f"Scouted {n['scouted']}, drafted {n['drafted']}" + (f", held back {n['held']}" if n["held"] else "")
        return back(next, msg)

    # -- decisions -----------------------------------------------------------------------

    @app.get("/decisions", response_class=HTMLResponse)
    def decisions(request: Request, filter: str = "all", sel: int | None = None):
        if (r := gated(request)):
            return r
        views = [_dview(d) for d in eng.decisions() if d["status"] != "cancelled"]
        shown = [v for v in views if filter == "all" or v["group"] == filter]
        pend = [v for v in shown if v["status"] == "pending"]
        sel_id = sel or (pend[0]["id"] if pend else (shown[0]["id"] if shown else None))
        d = eng.decision(sel_id) if sel_id else None
        detail = checks = None
        if d is not None:
            if d["status"] == "pending":
                g = eng.preview_guard(d["id"])
                checks = g.to_dict()["checks"] if g else []
            else:
                checks = (json.loads(d["guard"]) if d["guard"] else {"checks": []})["checks"]
            detail = {**_dview(d), "d": d, "adjusted": (d["adjusted"] or "").split("\n") if d["adjusted"] else [],
                      "status_label": STATUS_LABEL.get(d["status"], d["status"])}
        a = eng.autonomy()
        return render(request, "decisions.html", "decisions", views=shown, sel=sel_id, filter=filter, detail=detail,
                      checks=checks, pending_n=len(pend),
                      tabs=[("all", "All"), ("email", "Email"), ("reply", "Replies")],
                      autonomy=[(k, label, hint, a[k]) for k, label, hint in AUTONOMY_ROWS], levels=LEVELS,
                      cta=_cta(detail["kind"] if detail else "email", eng.mode()))

    def _next_pending(after: int | None = None) -> str:
        p = eng.decisions("pending")
        return f"/decisions?sel={p[0]['id']}" if p else "/decisions"

    @app.post("/decisions/approve-all")
    def approve_all(kind: str = Form("email"), next: str = Form("/decisions")):
        n = eng.approve_all(kind)
        done = n["sent"] + n["approved_shadow"] + n["handed_off"]
        return back(next, f"Approved {done}" + (f", blocked {n['blocked']} by the send guard" if n["blocked"] else ""))

    @app.post("/decisions/{decision_id}/approve")
    def approve(decision_id: int, next: str = Form("")):
        out = eng.approve(decision_id)
        msg = {"blocked": "Blocked by the send guard: " + "; ".join(f"{c.name}: {c.detail}" for c in out.guard.blocking)
               if out.guard else "Blocked", "sent": "Sent", "approved_shadow": "Approved. Shadow run, nothing sent.",
               "handed_off": "Marked as handed off to you"}.get(out.status)
        return back(next or _next_pending(), msg)

    @app.post("/decisions/{decision_id}/skip")
    def skip(decision_id: int):
        eng.skip(decision_id)
        return back(_next_pending())

    @app.post("/decisions/{decision_id}/edit")
    def edit(decision_id: int, subject: str = Form(""), body: str = Form("")):
        eng.edit(decision_id, subject, body)
        return back(f"/decisions?sel={decision_id}", "Saved. The send guard will check it again.")

    @app.post("/autonomy")
    def autonomy(kind: str = Form(...), level: int = Form(...)):
        try:
            eng.set_autonomy(kind, level)
        except ValueError:
            return back("/decisions", "Not a valid setting")
        return back("/decisions")

    # -- funnel --------------------------------------------------------------------------

    @app.get("/funnel", response_class=HTMLResponse)
    def funnel(request: Request):
        if (r := gated(request)):
            return r
        mode, vals = eng.mode(), eng.node_values()
        order = [k for k, _, _ in STAGES]
        cur = order.index(mode)
        stages = [{"key": k, "name": n, "desc": dsc, "state": "done" if i < cur else "cur" if i == cur else "locked",
                   "tag": "DONE" if i < cur else "IN PROGRESS" if i == cur else "LOCKED", "num": f"0{i + 1}"}
                  for i, (k, n, dsc) in enumerate(STAGES)]
        nodes = [{"num": f"{i + 1:02d}", "name": n, "desc": d, "who": w, "val": vals[i]} for i, (n, d, w) in enumerate(NODES)]
        leads = eng.leads()
        return render(request, "funnel.html", "funnel", stages=stages, nodes=nodes, gate=eng.gate(), leads=leads,
                      profile=eng.profile(), plan=_plan(eng), dev=eng.s.dev_unlock,
                      outbox_n=eng.conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0])

    @app.post("/funnel/promote")
    def promote():
        try:
            to = eng.promote()
        except PromotionBlocked as e:
            return back("/funnel", str(e))
        return back("/funnel", f"Moved to {to.replace('_', ' ')}")

    @app.post("/funnel/reset")
    def reset():
        eng.reset()
        return back("/funnel", "Demo data cleared")

    @app.post("/funnel/reply")
    def reply(lead_id: int = Form(...), text: str = Form(...)):
        label = eng.receive_reply(lead_id, text)
        return back("/funnel", f"Reply classified as {label.replace('_', ' ')}")

    @app.post("/funnel/mark")
    def mark(lead_id: int = Form(...), outcome: str = Form(...)):
        eng.mark(lead_id, outcome)
        return back("/funnel", f"Marked {outcome}")

    @app.get("/outbox", response_class=HTMLResponse)
    def outbox(request: Request):
        rows = eng.conn.execute("SELECT * FROM outbox ORDER BY id DESC").fetchall()
        return render(request, "outbox.html", "funnel", rows=rows)

    # -- onboarding ----------------------------------------------------------------------

    @app.get("/onboarding", response_class=HTMLResponse)
    def onboarding_page(request: Request):
        answers = onboarding.get_answers(eng)
        step = len(answers)
        p = eng.profile()
        asking = step < len(onboarding.QUESTIONS)
        identity = not asking and not p["sender_name"]
        rows = ["What you do", "Ideal client", "Where, which languages", "Proof", "Autonomy"]
        return templates.TemplateResponse(request, "onboarding.html", {
            "step": step, "asking": asking, "identity": identity, "finished": not asking and not identity,
            "question": onboarding.QUESTIONS[step] if asking else "", "options": onboarding.options(step, answers),
            "free": step in onboarding.TEXT_STEPS, "history": list(zip(onboarding.QUESTIONS, answers)),
            "blueprint": [(r, answers[i] if i < len(answers) else None) for i, r in enumerate(rows)],
            "reveal": min(100, round(8 + step * 18.4)), "stream": viz.stream([1284, 312, 140, 5, 3, 1]),
            "profile": p, "ready": eng.onboarded(), "flash": request.query_params.get("msg"),
        })

    @app.post("/onboarding/answer")
    def onboarding_answer(text: str = Form("")):
        onboarding.answer(eng, text)
        return back("/onboarding")

    @app.post("/onboarding/identity")
    def onboarding_identity(sender_name: str = Form(...), studio: str = Form(""), city: str = Form(""),
                            contact_email: str = Form(""), provider: str = Form("gmail")):
        onboarding.save_identity(eng, sender_name=sender_name, studio=studio, city=city,
                                 contact_email=contact_email, provider=provider)
        from current.agent import tasks
        try:
            plan = tasks.plan(eng.router, eng.profile())
            from current import db
            db.set_json(eng.conn, "plan", plan)
        except Exception:  # noqa: BLE001 - the plan is a nicety; onboarding must not fail on it
            pass
        eng.log("Built your first funnel.")
        return back("/onboarding")

    @app.post("/onboarding/restart")
    def onboarding_restart():
        onboarding.restart(eng)
        eng.save_profile(sender_name="")
        return back("/onboarding")

    # -- opt-out and health ----------------------------------------------------------------

    @app.api_route("/optout/{token}", methods=["GET", "POST"], response_class=HTMLResponse)
    def optout(request: Request, token: str):
        ok = eng.opt_out(token)
        return templates.TemplateResponse(request, "optout.html", {"ok": ok}, status_code=200 if ok else 404)

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "mode": eng.mode(), "llm": eng.s.llm}

    app.state.engine = eng
    return app


def _cta(kind: str, mode: str) -> str:
    if mode != "live":
        return "Approve (nothing is sent)"
    return "Send reply" if kind == "reply" else "Approve and send"


def _spark(weekly: list[int]) -> list[dict]:
    top = max(weekly) or 1
    return [{"h": 4 + round(24 * v / top), "hot": i == len(weekly) - 1} for i, v in enumerate(weekly)]


def _plan(eng: Engine) -> dict:
    from current import db
    return db.get_json(eng.conn, "plan", {"keywords": [], "summary": ""})


app = None


def get_app() -> FastAPI:
    global app
    if app is None:
        app = create_app()
    return app
