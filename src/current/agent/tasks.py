"""LLM-backed tasks: qualify, draft, claims review, reply triage, planning.

The model writes and classifies. It does not decide money, rates or compliance.
Every call carries personal data, so the router only offers local backends.
"""
from __future__ import annotations

import re

from current.llm.base import extract_json
from current.llm.router import ModelRouter

SYSTEM = (
    "You help a freelancer find clients. Be concrete, short and truthful. "
    "Never claim results, numbers or credentials that are not in the PROOF given. "
    "Reply with JSON only."
)
LABELS = ("positive", "question", "negative", "unsubscribe", "out_of_office", "other")
ESCALATE_BELOW = 0.6


def _ask(router: ModelRouter, task: str, prompt: str, context: dict, *, tier: str | None = None) -> tuple[dict | None, str]:
    """One retry on unparseable output. Returns (parsed or None, backend name)."""
    name = ""
    for _ in range(2):
        text, name = router.complete(
            task, SYSTEM, prompt, data_class="personal", json_mode=True, context=context, tier=tier
        )
        parsed = extract_json(text)
        if parsed is not None:
            return parsed, name
    return None, name


def qualify(router: ModelRouter, profile: dict, cand: dict) -> dict:
    prompt = (
        f"IDEAL CLIENT: {profile.get('icp')}\nOFFER: {profile.get('offer')}\n"
        f"PROSPECT: {cand.get('org')} ({cand.get('country')}), {cand.get('role')}. {cand.get('description')}\n"
        'Return {"score": 0-100, "confidence": 0-1, "reason": "one sentence"}.'
    )
    ctx = {"profile": profile, "candidate": cand}
    out, model = _ask(router, "score", prompt, ctx)
    # Small model first; escalate to the larger one only when it is unsure.
    if out is None or float(out.get("confidence", 0)) < ESCALATE_BELOW:
        try:
            big, big_model = _ask(router, "score", prompt, ctx, tier="large")
            if big is not None:
                out, model = big, big_model
        except Exception:  # noqa: BLE001 - escalation is best effort
            pass
    out = out or {"score": 0, "confidence": 0.0, "reason": "Could not score"}
    return {
        "score": max(0, min(100, int(out.get("score", 0)))),
        "reason": str(out.get("reason", ""))[:240],
        "model": model,
    }


def draft(router: ModelRouter, profile: dict, lead: dict, *, kind: str = "intro",
          slots: list[str] | None = None, subject: str = "") -> dict:
    if kind == "intro":
        brief = (
            "Write a first email under 110 words. One short observation about the prospect, one line of "
            "proof taken only from PROOF, then say no reply is needed if it isn't relevant and that you "
            "won't write again. No hype, no numbers that are not in PROOF."
        )
    else:
        brief = f"Write a short reply to a prospect who answered. Offer these call slots: {', '.join(slots or [])}."
    prompt = (
        f"{brief}\nFREELANCER: {profile.get('sender_name')}, {profile.get('offer')}\n"
        f"PROOF: {profile.get('proof')}\nPROSPECT: {lead.get('name')} at {lead.get('org')}. {lead.get('description')}\n"
        'Return {"subject": "...", "body": "..."}. Do not include a footer or unsubscribe text.'
    )
    ctx = {"profile": profile, "lead": lead, "kind": kind, "slots": slots, "subject": subject}
    out, model = _ask(router, "draft", prompt, ctx)
    if out is None or not out.get("body"):
        raise ValueError("model returned no usable draft")
    return {"subject": str(out.get("subject") or subject), "body": str(out["body"]).strip(), "model": model}


def review_claims(router: ModelRouter, text: str, proof: str) -> list[str]:
    """Sentences that make claims PROOF does not support."""
    prompt = (
        f"PROOF: {proof}\nTEXT: {text}\n"
        'List sentences of TEXT that state results, numbers or credentials not supported by PROOF. '
        'Return {"unsupported": ["sentence", ...]}.'
    )
    out, _ = _ask(router, "guard_review", prompt, {"text": text, "proof": proof})
    return [s for s in (out or {}).get("unsupported", []) if isinstance(s, str) and s.strip()]


def sanitize(router: ModelRouter, body: str, proof: str) -> tuple[str, list[str]]:
    """Drop unsupported claims from a draft. Returns (clean body, removed sentences)."""
    removed = [s for s in review_claims(router, body, proof) if s in body]
    for s in removed:
        body = re.sub(r"\s*" + re.escape(s), "", body, count=1)
    return body, removed


def triage(router: ModelRouter, text: str) -> str:
    prompt = f'Classify this reply: {text}\nReturn {{"label": one of {list(LABELS)}, "confidence": 0-1}}.'
    out, _ = _ask(router, "triage", prompt, {"text": text})
    label = (out or {}).get("label")
    return label if label in LABELS else "other"


def plan(router: ModelRouter, profile: dict) -> dict:
    prompt = (
        f"OFFER: {profile.get('offer')}\nIDEAL CLIENT: {profile.get('icp')}\n"
        'Return {"keywords": [up to 8 search keywords], "summary": "one sentence"}.'
    )
    out, model = _ask(router, "plan", prompt, {"profile": profile})
    out = out or {"keywords": [], "summary": ""}
    return {"keywords": out.get("keywords", [])[:8], "summary": out.get("summary", ""), "model": model}
