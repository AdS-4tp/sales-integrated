"""The per-country rules table. Returns a decision; never just a warning."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DECISIONS = ("allow", "block", "needs_review")


@dataclass(frozen=True)
class RuleResult:
    decision: str  # allow | block | needs_review
    reason: str
    version: str


class RulesTable:
    def __init__(self, version: str, rules: list[dict]) -> None:
        self.version = version
        self._rules = {(r["country"].upper(), r["recipient"]): r for r in rules}
        for r in rules:
            if r["decision"] not in DECISIONS:
                raise ValueError(f"bad decision in rules: {r}")

    @classmethod
    def load(cls, path: str | Path) -> "RulesTable":
        data = yaml.safe_load(Path(path).read_text())
        return cls(str(data["version"]), data["rules"])

    def countries(self) -> set[str]:
        return {c for c, _ in self._rules}

    def evaluate(self, country: str | None, recipient_type: str | None, *, strict: bool) -> RuleResult:
        """strict=True means the mailer can really send: unreviewed `allow` rules do not count."""
        key = ((country or "").upper(), recipient_type or "business")
        rule = self._rules.get(key)
        if rule is None:
            return RuleResult("needs_review", f"No rule for {key[0] or 'unknown country'} yet", self.version)
        if rule["decision"] == "allow" and strict and not rule.get("reviewed", False):
            return RuleResult("needs_review", "Rule is waiting for counsel sign-off", self.version)
        return RuleResult(rule["decision"], rule["reason"], self.version)

    def signed_off(self, country: str) -> bool:
        """True when business outreach to this country is allowed by a reviewed rule."""
        r = self._rules.get((country.upper(), "business"))
        return bool(r and r["decision"] == "allow" and r.get("reviewed", False))
