"""The mandatory footer and the signed opt-out token.

Every outbound message carries: who is writing, where the contact data came from,
the legal basis, that this is the only message, and a one-click opt-out.
"""
from __future__ import annotations

import base64
import hashlib
import hmac


def make_token(secret: str, email: str) -> str:
    raw = base64.urlsafe_b64encode(email.lower().encode()).decode().rstrip("=")
    sig = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()[:20]
    return f"{raw}.{sig}"


def read_token(secret: str, token: str) -> str | None:
    """Returns the email the token was issued for, or None if it is not ours."""
    try:
        raw, sig = token.rsplit(".", 1)
    except ValueError:
        return None
    good = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()[:20]
    if not hmac.compare_digest(sig, good):
        return None
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode()
    except (ValueError, UnicodeDecodeError):
        return None


def opt_out_url(base_url: str, secret: str, email: str) -> str:
    return f"{base_url}/optout/{make_token(secret, email)}"


def build_footer(profile: dict, lead: dict, base_url: str, secret: str, *, kind: str = "intro") -> str:
    found = (lead.get("found_at") or "")[:10]
    sender = ", ".join(x for x in (profile.get("sender_name"), profile.get("studio"), profile.get("city")) if x)
    url = opt_out_url(base_url, secret, lead["email"])
    if kind == "response":
        return f"Opt out at any time in one click: {url}"
    return (
        f"Why you're getting this: {sender}. I found {lead.get('org')} in {lead.get('source_name')} "
        f"on {found} and wrote because I work with {profile.get('icp', 'businesses like yours')}. "
        "Basis: legitimate interest in B2B contact relevant to your role. "
        "This is the only message I will send unless you reply. "
        f"Opt out in one click: {url}"
    )


def missing_parts(footer: str, profile: dict, lead: dict, base_url: str, secret: str) -> list[str]:
    """Names of required footer elements that are absent. Empty list means valid."""
    missing = []
    if not profile.get("sender_name") or profile["sender_name"] not in footer:
        missing.append("sender identity")
    if not lead.get("source_name") or lead["source_name"] not in footer:
        missing.append("data source")
    if "legitimate interest" not in footer:
        missing.append("legal basis")
    if opt_out_url(base_url, secret, lead["email"]) not in footer:
        missing.append("opt-out link")
    return missing
