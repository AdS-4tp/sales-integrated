from current.agent import footer
from current.compliance.rules import RulesTable
from current.config import Settings


def table() -> RulesTable:
    return RulesTable.load(Settings().rules_path)


def test_germany_and_austria_are_blocked_even_for_businesses():
    for c in ("DE", "AT"):
        r = table().evaluate(c, "business", strict=False)
        assert r.decision == "block"


def test_unknown_country_needs_review():
    assert table().evaluate("JP", "business", strict=False).decision == "needs_review"


def test_sole_traders_are_not_treated_as_businesses():
    assert table().evaluate("PT", "sole_trader", strict=False).decision == "needs_review"


def test_unreviewed_allow_degrades_when_the_mailer_can_really_send():
    t = table()
    assert t.evaluate("PT", "business", strict=False).decision == "allow"
    assert t.evaluate("PT", "business", strict=True).decision == "needs_review"
    assert not t.signed_off("PT")


def test_spain_and_italy_are_held_for_review():
    for c in ("ES", "IT"):
        assert table().evaluate(c, "business", strict=False).decision == "needs_review"


def test_rule_version_is_reported():
    assert table().evaluate("PT", "business", strict=False).version.startswith("2026")


def test_opt_out_token_round_trips_and_rejects_tampering():
    tok = footer.make_token("k", "A@B.example")
    assert footer.read_token("k", tok) == "a@b.example"
    assert footer.read_token("other", tok) is None
    assert footer.read_token("k", tok[:-2] + "00") is None
    assert footer.read_token("k", "garbage") is None


def test_footer_contains_every_required_element():
    profile = {"sender_name": "Ines Silva", "studio": "Silva Studio", "city": "Porto", "icp": "hotels"}
    lead = {"email": "x@y.example", "org": "Hotel X", "source_name": "Registry", "found_at": "2026-10-14T00:00:00"}
    text = footer.build_footer(profile, lead, "http://t", "k")
    assert footer.missing_parts(text, profile, lead, "http://t", "k") == []
    assert "only message I will send" in text
    assert footer.missing_parts("hello", profile, lead, "http://t", "k") == [
        "sender identity", "data source", "legal basis", "opt-out link"]
