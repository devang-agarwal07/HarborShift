"""Conservative, rule-based review of advisory titles and summaries."""

from dataclasses import dataclass
import re

from harborshift.models import Port


KEYWORDS = {
    "strike": r"strike|industrial action|work stoppage",
    "congestion": r"congestion|backlog|berthing delays?",
    "severe_weather": r"cyclone|hurricane|typhoon|storm surge|severe weather|tropical storm",
    "equipment_failure": r"equipment failure|crane failure|equipment outage",
}
EXTRA_ALIASES = {
    "P01": ("port of new york and new jersey", "new york harbor"),
    "P05": ("port of durban", "durban harbour"),
    "P11": ("port of mumbai", "mumbai harbour", "bombay harbour"),
}


@dataclass(frozen=True)
class Candidate:
    event_type: str | None
    port_id: str | None
    matched_ports: tuple[str, ...]
    confidence: str
    duration_days: int | None = None
    severity: int | None = None


def extract_candidate(text: str, ports: list[Port]) -> Candidate | None:
    text = " ".join(text.lower().split())
    kinds = [name for name, pattern in KEYWORDS.items()
             if re.search(rf"\b(?:{pattern})\b", text)]
    locations = []
    for port in ports:
        name = port.port_name.lower()
        aliases = (f"port of {name}", f"{name} port", f"{name} harbor", f"{name} harbour",
                   *EXTRA_ALIASES.get(port.port_id, ()))
        if any(re.search(rf"\b{re.escape(alias)}\b", text) for alias in aliases):
            locations.append(port.port_id)
    if not kinds or not (locations or re.search(r"\b(port|harbou?r|terminal|berth|maritime)\b", text)):
        return None
    unique = tuple(sorted(set(locations)))
    return Candidate(
        kinds[0] if len(kinds) == 1 else None, unique[0] if len(unique) == 1 else None, unique,
        "candidate · review required" if len(unique) == len(kinds) == 1 else "ambiguous · review required",
    )
