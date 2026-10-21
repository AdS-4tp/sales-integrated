"""Where leads come from.

v0 ships two sources: a CSV importer and a fictional demo registry. Real
discovery (public registries, own crawler respecting robots.txt) plugs in behind
the same interface. Every candidate must carry its source name, URL and date,
because the footer discloses them and the audit trail stores them.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Protocol

REQUIRED = ("org", "email", "country", "source_name", "source_url")


@dataclass
class Candidate:
    org: str
    email: str
    country: str
    source_name: str
    source_url: str
    found_at: str = ""
    name: str = ""
    role: str = ""
    recipient_type: str = "business"
    description: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


class LeadSource(Protocol):
    name: str

    def fetch(self, profile: dict, limit: int, found_at: str) -> list[Candidate]: ...


class CsvSource:
    name = "csv"

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def fetch(self, profile: dict, limit: int, found_at: str) -> list[Candidate]:
        out: list[Candidate] = []
        with self.path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if any(not (row.get(k) or "").strip() for k in REQUIRED):
                    continue  # no provenance, no lead
                fields = {k: (v or "").strip() for k, v in row.items() if k in Candidate.__dataclass_fields__}
                fields.setdefault("found_at", found_at)
                if not fields.get("found_at"):
                    fields["found_at"] = found_at
                out.append(Candidate(**fields))
                if len(out) >= limit:
                    break
        return out


# Fictional businesses on the reserved .example domain. They exist to make the
# demo and the tests realistic; none of them is a real company or address.
_DEMO: Iterable[tuple] = (
    ("Hotel Azulejo Norte", "Ana Ferreira", "Owner", "PT", "business", "Independent boutique hotel, 24 rooms, website last updated 2019"),
    ("Casa das Marés", "Rui Almeida", "General manager", "PT", "business", "Independent boutique hotel on the coast, 18 rooms, outdated logo"),
    ("Quinta do Sol", "Marta Ribeiro", "Owner", "PT", "business", "Independent boutique hotel and wine estate, 14 rooms"),
    ("Pousada Rio Verde", "João Costa", "Director", "PT", "business", "Independent hotel, 32 rooms, no recent brand work"),
    ("Hotel Lumière Vieux-Port", "Claire Dubois", "Directrice", "FR", "business", "Independent boutique hotel, 28 rooms, dated website"),
    ("Maison des Pins", "Hugo Lambert", "Owner", "FR", "business", "Independent boutique hotel, 12 rooms, logo not used consistently"),
    ("Hôtel du Canal", "Sophie Martin", "Manager", "FR", "business", "Independent hotel, 40 rooms, website last updated 2018"),
    ("Hotel De Gracht", "Daan de Vries", "Owner", "NL", "business", "Independent boutique hotel, 16 rooms"),
    ("Landhaus Birkenhof", "Katrin Weber", "Owner", "DE", "business", "Independent boutique hotel, 22 rooms, dated website"),
    ("Seehotel Alpenblick", "Lukas Gruber", "Director", "DE", "business", "Independent hotel, 36 rooms"),
    ("Hostal La Ribera", "Carmen Ortiz", "Owner", "ES", "business", "Independent boutique hotel, 20 rooms"),
    ("Villa Rosmarino", "Giulia Conti", "Owner", "IT", "business", "Independent boutique hotel, 15 rooms"),
    ("Studio Hospedagem Mar", "Pedro Nunes", "Owner", "PT", "sole_trader", "Independent guesthouse run by one person, 6 rooms"),
    ("Chambres du Lac", "Éric Moreau", "Owner", "FR", "sole_trader", "Independent guesthouse, 5 rooms"),
    ("Grand Hotel Estrela", "Inês Carvalho", "Operations director", "PT", "business", "Large hotel chain property, 210 rooms"),
    ("Hotel Atlântico Sul", "Tiago Pires", "Owner", "PT", "business", "Independent boutique hotel, 26 rooms, brand refresh planned"),
)


class DemoRegistrySource:
    name = "demo registry"

    def fetch(self, profile: dict, limit: int, found_at: str) -> list[Candidate]:
        out = []
        for i, (org, person, role, country, rtype, desc) in enumerate(_DEMO):
            slug = "".join(c for c in org.lower() if c.isalnum())
            out.append(
                Candidate(
                    org=org, name=person, role=role, country=country, recipient_type=rtype,
                    email=f"info@{slug}.example",
                    description=desc,
                    source_name="demo registry (fictional data)",
                    source_url=f"https://registry.example/{country.lower()}/{i + 1}",
                    found_at=found_at,
                )
            )
        return out[:limit]
