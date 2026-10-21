import pytest

from current import db, service
from current.agent import footer
from current.service import Engine, PromotionBlocked


@pytest.fixture
def live(settings, clock) -> Engine:
    """An onboarded engine that has been promoted to live (dry-run outbox only)."""
    e = Engine(settings.with_overrides(dev_unlock=True), now=clock)
    e.save_profile(
        offer="brand designer for hotels", icp="Independent boutique hotels, 12 to 60 rooms",
        countries=["PT", "FR"], proof="14 projects, portfolio link added",
        sender_name="Ines Silva", studio="Silva Studio", city="Porto, Portugal",
    )
    e.promote()
    e.promote()
    assert e.mode() == "live"
    return e


def pending_emails(e):
    return [d for d in e.decisions("pending") if d["kind"] == "email"]


def test_cycle_scouts_qualifies_holds_and_drafts(engine):
    n = engine.run_cycle()
    assert n["scouted"] == 16
    assert n["drafted"] == 8
    assert n["held"] == 2  # the two sole traders
    held = {r["org"]: r["hold_reason"] for r in engine.leads() if r["status"] == "held"}
    assert set(held) == {"Studio Hospedagem Mar", "Chambres du Lac"}
    # Leads outside the freelancer's regions are recorded, never drafted.
    assert {r["status"] for r in engine.leads() if r["country"] in ("DE", "ES", "IT", "NL")} == {"rejected"}
    assert len(pending_emails(engine)) == 8


def test_large_chains_do_not_qualify(engine):
    engine.run_cycle()
    estrela = [r for r in engine.leads() if r["org"] == "Grand Hotel Estrela"][0]
    assert estrela["status"] == "rejected"


def test_cycle_is_idempotent(engine):
    engine.run_cycle()
    assert engine.run_cycle()["scouted"] == 0


def test_every_draft_carries_a_valid_footer(engine):
    engine.run_cycle()
    profile = engine.profile()
    for d in pending_emails(engine):
        lead = engine.conn.execute("SELECT * FROM leads WHERE id=?", (d["lead_id"],)).fetchone()
        assert footer.missing_parts(d["footer"], profile, dict(lead), "http://test", "s3cret") == []


def test_german_leads_are_held_not_drafted(engine):
    engine.save_profile(countries=["DE"])
    n = engine.run_cycle()
    assert n["drafted"] == 0 and n["held"] == 2
    assert all("Prior consent" in r["hold_reason"] for r in engine.leads() if r["status"] == "held")


def test_cycle_requires_onboarding(settings):
    with pytest.raises(service.NotOnboarded):
        Engine(settings).run_cycle()


def test_dry_run_approval_sends_nothing(engine):
    engine.run_cycle()
    d = pending_emails(engine)[0]
    out = engine.approve(d["id"])
    assert out.status == "approved_shadow"
    assert engine.conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0
    t = engine.conn.execute("SELECT simulated FROM touches").fetchone()
    assert t["simulated"] == 1


def test_live_approval_goes_through_the_outbox_with_the_footer(live):
    live.run_cycle()
    d = pending_emails(live)[0]
    assert live.approve(d["id"]).status == "sent"
    row = live.conn.execute("SELECT * FROM outbox").fetchone()
    assert row["to_email"].endswith(".example")
    assert "Opt out in one click" in row["body"]
    lead = live.conn.execute("SELECT status FROM leads WHERE id=?", (d["lead_id"],)).fetchone()
    assert lead["status"] == "contacted"


def test_a_second_unsolicited_message_is_blocked(live):
    live.run_cycle()
    d = pending_emails(live)[0]
    live.approve(d["id"])
    live.conn.execute(
        "INSERT INTO decisions(kind,lead_id,subject,body,footer,created_at) "
        "SELECT kind,lead_id,subject,body,footer,created_at FROM decisions WHERE id=?", (d["id"],))
    live.conn.commit()
    again = [x for x in pending_emails(live) if x["lead_id"] == d["lead_id"]][0]
    out = live.approve(again["id"])
    assert out.status == "blocked"
    assert any(c.name == "First contact" for c in out.guard.blocking)


def test_opt_out_link_suppresses_and_cancels_pending_drafts(engine):
    engine.run_cycle()
    d = pending_emails(engine)[0]
    token = footer.make_token("s3cret", d["email"])
    assert engine.opt_out(token) is True
    assert engine.decision(d["id"])["status"] == "cancelled"
    assert engine.approve(d["id"]).status == "ignored"
    assert engine.run_cycle()["scouted"] == 0
    assert engine.opt_out("not-a-token") is False


def test_suppressed_address_is_blocked_by_the_guard(live):
    live.run_cycle()
    d = pending_emails(live)[0]
    live.conn.execute("INSERT INTO suppression(email,reason,at) VALUES(?,?,?)", (d["email"], "test", "x"))
    live.conn.commit()
    out = live.approve(d["id"])
    assert out.status == "blocked"
    assert out.guard.blocking[0].name == "Suppression list"


def test_daily_limit_stops_the_second_send(live):
    live.save_profile(daily_limit=1)
    live.run_cycle()
    a, b = pending_emails(live)[:2]
    assert live.approve(a["id"]).status == "sent"
    out = live.approve(b["id"])
    assert out.status == "blocked"
    assert out.guard.blocking[0].name == "Daily limit"


def test_self_hosted_mailbox_follows_the_warmup_ramp(live, clock):
    live.save_profile(provider="self_hosted", daily_limit=100)
    db.set_json(live.conn, "warmup_started", clock().isoformat())
    assert live.stats()["limit"] == 10
    clock.advance(days=5)
    assert live.stats()["limit"] == 20
    clock.advance(days=100)
    assert live.stats()["limit"] == 40


def test_unsupported_claims_in_an_edited_draft_are_blocked(live):
    live.run_cycle()
    d = pending_emails(live)[0]
    live.edit(d["id"], d["subject"], "Hi,\n\nWe guarantee 300% more bookings. Thanks.")
    out = live.approve(d["id"])
    assert out.status == "blocked"
    assert out.guard.blocking[0].name == "Claims review"


def test_a_missing_footer_is_blocked(live):
    live.run_cycle()
    d = pending_emails(live)[0]
    live.conn.execute("UPDATE decisions SET footer='' WHERE id=?", (d["id"],))
    live.conn.commit()
    out = live.approve(d["id"])
    assert out.status == "blocked"
    assert any(c.name == "Footer" for c in out.guard.blocking)


def test_unhealthy_domain_blocks_sending(live):
    db.set_json(live.conn, "health", {"bounce": 0.09, "complaint": 0.0})
    live.run_cycle()
    out = live.approve(pending_emails(live)[0]["id"])
    assert out.status == "blocked" and out.guard.blocking[0].name == "Domain health"


def test_suggest_level_hands_off_instead_of_sending(live):
    live.set_autonomy("email", 0)
    live.run_cycle()
    assert live.approve(pending_emails(live)[0]["id"]).status == "handed_off"
    assert live.conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0


def test_auto_level_approves_within_the_daily_cap(live, monkeypatch):
    monkeypatch.setattr(service, "AUTO_DAILY_CAP", 3)
    live.set_autonomy("email", 2)
    n = live.run_cycle()
    assert n["auto"] == 3
    assert len(pending_emails(live)) == 5
    assert live.conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 3


def test_default_autonomy_never_sends_without_approval(live):
    live.run_cycle()
    assert live.conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0


def contacted(live):
    live.run_cycle()
    d = pending_emails(live)[0]
    live.approve(d["id"])
    return d["lead_id"]


def test_positive_reply_creates_a_draft_answer_that_can_be_sent(live):
    lead = contacted(live)
    assert live.receive_reply(lead, "Interesting, could we talk Thursday?") == "positive"
    reply = [d for d in live.decisions("pending") if d["kind"] == "reply"][0]
    assert "Thu 11:00" in reply["body"]
    assert live.approve(reply["id"]).status == "sent"
    assert live.conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 2


def test_unsubscribe_reply_suppresses_the_address(live):
    lead = contacted(live)
    assert live.receive_reply(lead, "Please remove me from your list") == "unsubscribe"
    assert live.stats()["suppressed"] == 1
    assert not [d for d in live.decisions("pending") if d["kind"] == "reply"]


def test_negative_reply_closes_the_lead(live):
    lead = contacted(live)
    assert live.receive_reply(lead, "No thanks, not interested") == "negative"
    assert live.conn.execute("SELECT status FROM leads WHERE id=?", (lead,)).fetchone()["status"] == "closed"


def test_replying_to_someone_who_never_replied_is_blocked(live):
    live.run_cycle()
    d = pending_emails(live)[0]
    live.conn.execute("INSERT INTO decisions(kind,lead_id,subject,body,footer,created_at) VALUES('reply',?,?,?,?,?)",
                      (d["lead_id"], "Re", "Hi", d["footer"], "x"))
    live.conn.commit()
    r = [x for x in live.decisions("pending") if x["kind"] == "reply"][0]
    out = live.approve(r["id"])
    assert out.status == "blocked" and out.guard.blocking[0].name == "Follow-up allowed"


def test_stats_count_the_week(live):
    lead = contacted(live)
    live.receive_reply(lead, "yes let's talk")
    live.mark(lead, "booked")
    s = live.stats()
    assert s["booked"] == 1 and s["booked_delta"] == 1
    assert s["funnel"][0] == 16 and s["funnel"][2] == 1 and s["funnel"][3] == 1 and s["funnel"][4] == 1
    assert s["sent_today"] == 1


def test_gate_walks_dry_run_to_shadow_to_live(engine, clock):
    assert engine.mode() == "dry_run" and not engine.gate()["ok"]
    with pytest.raises(PromotionBlocked):
        engine.promote()
    engine.run_cycle()
    for d in pending_emails(engine)[:3]:
        engine.approve(d["id"])
    assert engine.gate()["ok"]
    assert engine.promote() == "shadow"

    g = engine.gate()
    assert not g["ok"]
    names = {c["name"]: c["ok"] for c in g["criteria"]}
    assert names["7 days of shadow drafts reviewed"] is False
    clock.advance(days=8)
    g = engine.gate()
    names = {c["name"]: c["ok"] for c in g["criteria"]}
    assert names["7 days of shadow drafts reviewed"] is True
    # Country rules are unreviewed, so going live stays locked.
    assert names["PT country rules signed off"] is False
    with pytest.raises(PromotionBlocked):
        engine.promote()


def test_shadow_approvals_do_not_carry_over_to_live(settings, clock):
    e = Engine(settings.with_overrides(dev_unlock=True), now=clock)
    e.save_profile(offer="designer", icp="Independent boutique hotels", countries=["PT"],
                   proof="x", sender_name="Ines", studio="S", city="Porto")
    e.run_cycle()
    first = pending_emails(e)[0]["id"]
    e.approve(first)
    assert e.decision(first)["status"] == "approved_shadow"
    e.promote()  # shadow
    e.approve(pending_emails(e)[0]["id"])
    e.promote()  # live
    assert e.decision(first)["status"] == "pending"
    assert e.conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0


def test_reset_keeps_the_suppression_list(engine):
    engine.suppress("someone@x.example", "asked")
    engine.run_cycle()
    engine.reset()
    assert engine.leads() == [] and engine.stats()["suppressed"] == 1
