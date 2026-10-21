import pytest

from current.llm.base import NoBackendAvailable, extract_json
from current.llm.router import ModelRouter


class Fake:
    def __init__(self, name, *, local, tiers, up=True):
        self.name, self.local, self.tiers, self._up = name, local, frozenset(tiers), up

    def available(self):
        return self._up

    def complete(self, task, system, prompt, *, json_mode=False, context=None):
        return "{}"


def test_personal_data_never_reaches_a_hosted_backend():
    r = ModelRouter([Fake("groq", local=False, tiers={"small"})])
    with pytest.raises(NoBackendAvailable):
        r.backend_for("triage", "personal")
    assert r.backend_for("triage", "public").name == "groq"


def test_no_silent_fallback_when_the_local_backend_is_down():
    r = ModelRouter([
        Fake("ollama", local=True, tiers={"small"}, up=False),
        Fake("groq", local=False, tiers={"small"}),
    ])
    with pytest.raises(NoBackendAvailable):
        r.backend_for("triage", "personal")


def test_small_tier_first_and_large_for_drafting():
    small = Fake("s", local=True, tiers={"small"})
    large = Fake("l", local=True, tiers={"large"})
    r = ModelRouter([small, large])
    assert r.backend_for("triage", "personal").name == "s"
    assert r.backend_for("draft", "personal").name == "l"
    assert r.backend_for("score", "personal", tier="large").name == "l"


def test_draft_falls_back_to_small_when_large_is_missing():
    r = ModelRouter([Fake("s", local=True, tiers={"small"})])
    assert r.backend_for("draft", "personal").name == "s"


def test_extract_json_tolerates_prose_and_fences():
    assert extract_json('Sure! ```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json("no json here") is None
    assert extract_json("{broken") is None
