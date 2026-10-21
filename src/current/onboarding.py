"""The onboarding interview: five questions, then who signs the emails."""
from __future__ import annotations

from current import db
from current.service import REGIONS, Engine

QUESTIONS = [
    "Hi, I find clients for freelancers. A few quick questions and I’ll build your first funnel. "
    "What do you do, in one sentence?",
    "Good. Who is the client you’d love ten more of?",
    "Where do you work, and in which languages should I write?",
    "What can I truthfully say about your work? Proof beats adjectives. "
    "I will only ever repeat what you write here.",
    "Last one. How much may I do without asking you first?",
]
OFFERS = ["Brand designer for hotels", "Web developer for clinics", "Copywriter for B2B software"]
ICPS = {
    0: ["Independent boutique hotels, 12 to 60 rooms", "Restaurant groups with 3+ venues", "Wedding venues"],
    1: ["Private dental clinics, 2 to 10 chairs", "Physiotherapy practices", "Veterinary clinics"],
    2: ["Seed-stage SaaS with no content team", "Cybersecurity startups", "Developer tools companies"],
}
AUTONOMY = {"Ask me first (recommended)": 1, "Auto-send within a daily limit": 2, "Suggest only": 0}
SAMPLE_PROOF = "Sample proof, replace later: 14 projects delivered"
TEXT_STEPS = (0, 1, 3)  # steps where the user may type their own answer


def options(step: int, answers: list[str]) -> list[str]:
    if step == 0:
        return OFFERS
    if step == 1:
        return ICPS.get(OFFERS.index(answers[0]) if answers[0] in OFFERS else 0, ICPS[0])
    if step == 2:
        return list(REGIONS)
    if step == 3:
        return [SAMPLE_PROOF]
    if step == 4:
        return list(AUTONOMY)
    return []


def get_answers(engine: Engine) -> list[str]:
    return db.get_json(engine.conn, "onboarding", [])


def answer(engine: Engine, text: str) -> list[str]:
    answers = get_answers(engine)
    step = len(answers)
    text = text.strip()
    if step >= len(QUESTIONS) or not text:
        return answers
    allowed = options(step, answers)
    if step not in TEXT_STEPS and text not in allowed:
        return answers  # region and autonomy must be one of the offered choices
    answers.append(text)
    db.set_json(engine.conn, "onboarding", answers)
    if len(answers) == len(QUESTIONS):
        _apply(engine, answers)
    return answers


def _apply(engine: Engine, answers: list[str]) -> None:
    countries, languages = REGIONS[answers[2]]
    offer = answers[0]
    engine.save_profile(
        offer=offer[:1].lower() + offer[1:], icp=answers[1], countries=countries,
        languages=languages, proof=answers[3],
    )
    level = AUTONOMY[answers[4]]
    engine.set_autonomy("email", level)
    engine.set_autonomy("reply", 1 if level == 2 else level)


def save_identity(engine: Engine, *, sender_name: str, studio: str, city: str,
                  contact_email: str, provider: str) -> None:
    if provider not in ("gmail", "outlook", "self_hosted"):
        provider = "gmail"
    engine.save_profile(sender_name=sender_name.strip(), studio=studio.strip(), city=city.strip(),
                        contact_email=contact_email.strip(), provider=provider)


def restart(engine: Engine) -> None:
    db.set_json(engine.conn, "onboarding", [])
