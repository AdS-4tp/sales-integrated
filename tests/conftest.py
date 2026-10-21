from datetime import datetime, timedelta, timezone

import pytest

from current.config import Settings
from current.service import Engine


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 10, 21, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw) -> None:
        self.t += timedelta(**kw)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(db_path=str(tmp_path / "t.db"), base_url="http://test", secret="s3cret", llm="mock")


@pytest.fixture
def engine(settings, clock) -> Engine:
    e = Engine(settings, now=clock)
    e.save_profile(
        offer="brand designer for hotels",
        icp="Independent boutique hotels, 12 to 60 rooms",
        countries=["PT", "FR"], languages=["pt", "fr", "en"],
        proof="14 projects, portfolio link added",
        sender_name="Ines Silva", studio="Silva Studio", city="Porto, Portugal",
        contact_email="ines@silva.example",
    )
    return e
