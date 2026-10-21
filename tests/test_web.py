import re

import pytest
from fastapi.testclient import TestClient

from current import onboarding
from current.agent import footer
from current.service import Engine
from current.web import viz
from current.web.app import create_app


@pytest.fixture
def fresh(settings, clock):
    eng = Engine(settings, now=clock)
    return eng, TestClient(create_app(eng), follow_redirects=False)


@pytest.fixture
def client(fresh):
    eng, c = fresh
    for text in ("Brand designer for hotels", "Independent boutique hotels, 12 to 60 rooms",
                 "Portugal and France · PT, FR, EN", "Ten hotel rebrands in 2025", "Ask me first (recommended)"):
        assert c.post("/onboarding/answer", data={"text": text}).status_code == 303
    c.post("/onboarding/identity", data={"sender_name": "Ines Silva", "studio": "Silva Studio",
                                         "city": "Porto, Portugal", "provider": "gmail"})
    return c


def test_unonboarded_visitors_are_sent_to_the_interview(fresh):
    _, c = fresh
    for path in ("/", "/decisions", "/funnel"):
        r = c.get(path)
        assert r.status_code == 303 and r.headers["location"] == "/onboarding"


def test_onboarding_walks_through_to_a_ready_funnel(fresh):
    eng, c = fresh
    page = c.get("/onboarding")
    assert page.status_code == 200 and "What do you do" in page.text
    assert not eng.onboarded()
    for text in ("Brand designer for hotels", "Independent boutique hotels, 12 to 60 rooms",
                 "Portugal and France · PT, FR, EN", "Ten hotel rebrands in 2025", "Ask me first (recommended)"):
        c.post("/onboarding/answer", data={"text": text})
    assert "Who signs the emails" in c.get("/onboarding").text
    c.post("/onboarding/identity", data={"sender_name": "Ines Silva", "provider": "self_hosted"})
    p = eng.profile()
    assert eng.onboarded() and p["countries"] == ["PT", "FR"] and p["provider"] == "self_hosted"
    assert p["proof"] == "Ten hotel rebrands in 2025"
    assert "Nothing is sent until you say so" in c.get("/onboarding").text


def test_region_and_autonomy_only_accept_the_offered_choices(fresh):
    eng, c = fresh
    c.post("/onboarding/answer", data={"text": "Designer"})
    c.post("/onboarding/answer", data={"text": "Hotels"})
    c.post("/onboarding/answer", data={"text": "Germany · DE"})  # not an offered region
    assert len(onboarding.get_answers(eng)) == 2


def test_every_page_renders_after_a_cycle(client):
    client.post("/cycle", data={"next": "/"})
    for path in ("/", "/decisions", "/funnel", "/outbox", "/healthz"):
        assert client.get(path).status_code == 200, path
    today = client.get("/").text
    assert "Next best move" in today and "Approve" in today


def test_decision_page_shows_footer_and_guard_checks(client):
    client.post("/cycle", data={"next": "/"})
    html = client.get("/decisions").text
    assert "Why you&#39;re getting this" in html or "Why you're getting this" in html
    for name in ("Suppression list", "Country rules", "First contact", "Daily limit", "Domain health", "Footer", "Claims review"):
        assert name in html


def test_approving_in_the_ui_follows_the_dry_run_rules(client, fresh):
    eng, _ = fresh
    client.post("/cycle", data={"next": "/"})
    first = eng.decisions("pending")[0]["id"]
    r = client.post(f"/decisions/{first}/approve")
    assert r.status_code == 303
    assert eng.decision(first)["status"] == "approved_shadow"
    assert eng.conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0] == 0


def test_opt_out_link_works_and_a_bad_link_does_not(client, fresh):
    eng, _ = fresh
    client.post("/cycle", data={"next": "/"})
    d = eng.decisions("pending")[0]
    url = re.search(r"/optout/\S+", d["footer"]).group(0)
    assert client.get(url).status_code == 200
    assert eng.conn.execute("SELECT 1 FROM suppression WHERE email=?", (d["email"],)).fetchone()
    assert client.get("/optout/nonsense").status_code == 404
    assert client.post(url).status_code == 200  # RFC 8058 style one-click POST


def test_autonomy_form_updates_the_setting(client, fresh):
    eng, _ = fresh
    client.post("/autonomy", data={"kind": "email", "level": "2"})
    assert eng.autonomy()["email"] == 2
    client.post("/autonomy", data={"kind": "bogus", "level": "2"})
    assert "bogus" not in eng.autonomy()


def test_funnel_promote_is_locked_until_the_checks_pass(client, fresh):
    eng, _ = fresh
    r = client.post("/funnel/promote")
    assert r.status_code == 303 and "Checks%20have%20not%20passed" in r.headers["location"]
    assert eng.mode() == "dry_run"


def test_stream_geometry_narrows_and_stays_in_the_viewbox():
    s = viz.stream([1284, 312, 140, 5, 3, 1])
    assert s["band"].startswith("M0,") and s["band"].endswith("Z")
    nums = [float(n) for n in re.findall(r"-?\d+\.?\d*", s["band"])]
    ys = nums[1::2]
    assert min(ys) >= 0 and max(ys) <= 260
    assert [l["id"] for l in s["lanes"]] == ["a", "b", "c"]
    halves = viz._halves([1284, 312, 140, 5, 3, 1])
    assert halves == sorted(halves, reverse=True) and halves[0] == viz.MAX_HALF and min(halves) >= viz.MIN_HALF


def test_stream_handles_an_empty_funnel():
    s = viz.stream([0, 0, 0, 0, 0, 0])
    assert "nan" not in s["band"].lower()
    with pytest.raises(ValueError):
        viz.stream([1, 2])
