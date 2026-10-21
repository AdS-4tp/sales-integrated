"""Deterministic offline backend so the whole app runs, and tests pass, without a model.

It reads the structured ``context`` the agent passes alongside the prompt, so it
never has to parse prose. It is a stand-in, not a quality baseline.
"""
from __future__ import annotations

import json
import re
from typing import Any

DECISION_ROLES = ("owner", "founder", "director", "manager", "gm", "ceo", "head", "partner")
CLAIM_WORDS = ("guarantee", "double", "triple", "#1", "best in", "proven to", "award-winning")
NEGATIVE = ("not interested", "no thanks", "no thank", "not relevant", "already have")
UNSUB = ("unsubscribe", "remove me", "stop emailing", "stop contacting", "do not contact", "don't contact")
OOO = ("out of office", "on vacation", "on holiday", "auto-reply", "automatic reply")
POSITIVE = ("yes", "interested", "let's talk", "lets talk", "call", "thursday", "tomorrow", "send me", "sounds good")


def _stem(w: str) -> str:
    return w.lower().strip(".,;:()").rstrip("s")


def _tokens(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[A-Za-zÀ-ÿ]{4,}", text or "")}


class MockBackend:
    name = "mock"
    local = True
    tiers = frozenset({"small", "large"})

    def available(self) -> bool:
        return True

    def complete(
        self,
        task: str,
        system: str,
        prompt: str,
        *,
        json_mode: bool = False,
        context: dict[str, Any] | None = None,
    ) -> str:
        ctx = context or {}
        return getattr(self, f"_{task}")(ctx)

    # -- tasks ---------------------------------------------------------------

    def _score(self, ctx: dict) -> str:
        icp = _tokens(ctx["profile"].get("icp", "")) - {"with", "that", "from"}
        cand = ctx["candidate"]
        overlap = icp & _tokens(cand.get("description", ""))
        score = 40 + min(len(overlap), 3) * 15
        if any(r in (cand.get("role") or "").lower() for r in DECISION_ROLES):
            score += 10
        if "independent" in icp and "chain" in _tokens(cand.get("description", "")):
            score -= 35
        reason = (
            f"Matches your ideal client on: {', '.join(sorted(overlap))}."
            if overlap
            else "Little overlap with your ideal client."
        )
        return json.dumps({"score": min(score, 100), "confidence": 0.8 if overlap else 0.5, "reason": reason})

    def _classify(self, ctx: dict) -> str:
        return self._triage(ctx)

    def _triage(self, ctx: dict) -> str:
        t = (ctx.get("text") or "").lower()
        if any(k in t for k in UNSUB):
            label = "unsubscribe"
        elif any(k in t for k in OOO):
            label = "out_of_office"
        elif any(k in t for k in NEGATIVE):
            label = "negative"
        elif any(k in t for k in POSITIVE):
            label = "positive"
        elif "?" in t:
            label = "question"
        else:
            label = "other"
        return json.dumps({"label": label, "confidence": 0.9})

    def _guard_review(self, ctx: dict) -> str:
        proof = (ctx.get("proof") or "").lower()
        flagged = []
        for sentence in re.split(r"(?<=[.!?])\s+", ctx.get("text") or ""):
            s = sentence.lower()
            has_claim = any(w in s for w in CLAIM_WORDS) or re.search(r"\d+\s*%", s)
            if has_claim and not any(n in proof for n in re.findall(r"\d+", s)):
                flagged.append(sentence.strip())
        return json.dumps({"unsupported": flagged})

    def _plan(self, ctx: dict) -> str:
        p = ctx["profile"]
        words = sorted(_tokens(p.get("icp", "") + " " + p.get("offer", "")))
        return json.dumps({"keywords": words[:8], "summary": f"Find {p.get('icp', 'ideal clients')}."})

    def _draft(self, ctx: dict) -> str:
        p, lead = ctx["profile"], ctx["lead"]
        first = (lead.get("name") or "").split(" ")[0] or "there"
        if ctx.get("kind") == "response":
            slots = " or ".join(ctx.get("slots") or ["a time this week"])
            return json.dumps({
                "subject": "Re: " + (ctx.get("subject") or ""),
                "body": (
                    f"Hi {first},\n\nThanks for getting back to me. I have {slots}, whichever suits you. "
                    "It's a short call to hear what you want to achieve, with no pitch deck.\n\n"
                    f"{p.get('sender_name', '')}"
                ),
            })
        obs = (lead.get("description") or "").rstrip(".")
        proof = (p.get("proof") or "").rstrip(".")
        proof_line = f"Some of my recent work: {proof}. " if proof else ""
        return json.dumps({
            "subject": f"A thought on {lead.get('org')}",
            "body": (
                f"Hi {first},\n\n"
                f"I'm {p.get('sender_name', '')}, {p.get('offer', 'a freelancer')}. "
                f"I came across {lead.get('org')}: {obs[:1].lower() + obs[1:]}.\n\n"
                f"{proof_line}I can share two short case studies if useful. "
                "If it isn't relevant, there's no need to reply and you won't hear from me again.\n\n"
                f"{p.get('sender_name', '')}"
            ),
        })
