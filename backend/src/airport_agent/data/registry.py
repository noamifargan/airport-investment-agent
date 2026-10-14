"""Airport registry + deterministic resolver for airport / city / region mentions in free text.

The LLM is never trusted to invent airport codes: every question (and every tool argument) is
passed through :meth:`Registry.resolve`, which maps phrases like "LA", "Santa Ana", "Logan",
"Hartford" or "New England" to IATA codes and state lists using OurAirports metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import pandas as pd

from airport_agent.data.regions import REGION_ALIASES, REGIONS, STATES
from airport_agent.data.sources.ourairports import airports_frame

# Case-sensitive shorthands (only matched exactly as written, so "la" in Spanish names doesn't fire).
CASED_ALIASES = {
    "LA": ["LAX"], "L.A.": ["LAX"], "SF": ["SFO"], "NYC": ["JFK", "LGA", "EWR"],
    "DC": ["DCA", "IAD", "BWI"], "D.C.": ["DCA", "IAD", "BWI"], "DFW": ["DFW"],
}

# Case-insensitive metro / nickname aliases where the obvious answer isn't the municipality match.
CURATED_ALIASES = {
    "los angeles": ["LAX"],
    "santa ana": ["SNA"],
    "orange county": ["SNA"],
    "john wayne": ["SNA"],
    "bay area": ["SFO", "OAK", "SJC"],
    "san francisco": ["SFO"],
    "new york": ["JFK", "LGA", "EWR"],
    "new york city": ["JFK", "LGA", "EWR"],
    "chicago": ["ORD", "MDW"],
    "washington dc": ["DCA", "IAD", "BWI"],
    "washington d.c.": ["DCA", "IAD", "BWI"],
    "dallas": ["DFW", "DAL"],
    "houston": ["IAH", "HOU"],
    "south florida": ["MIA", "FLL", "PBI"],
    "logan": ["BOS"],
    "o'hare": ["ORD"],
    "ohare": ["ORD"],
    "laguardia": ["LGA"],
    "la guardia": ["LGA"],
    "jfk": ["JFK"],
    "kennedy": ["JFK"],
    "dulles": ["IAD"],
    "reagan national": ["DCA"],
    "hartford": ["BDL"],
    "bradley": ["BDL"],
    "anchorage": ["ANC"],
    "honolulu": ["HNL"],
    "las vegas": ["LAS"],
    "vegas": ["LAS"],
    "twin cities": ["MSP"],
    "minneapolis": ["MSP"],
    "philly": ["PHL"],
    "sea-tac": ["SEA"],
    "seatac": ["SEA"],
}

CODE_STOPLIST = {
    "THE", "AND", "FOR", "ARE", "YOU", "NOT", "BUT", "ALL", "ANY", "CAN", "HAS", "WAS", "HOW", "WHY",
    "WHO", "USA", "USD", "KPI", "ROI", "GDP", "CEO", "FAA", "DOT", "BTS", "TSA", "LCC", "IFR", "VFR",
    "ATC", "NAS", "ASV", "PAX", "API", "NEW", "TOP", "LOW", "MAX", "MIN", "AVG", "YOY", "EST", "PDT",
    "PST", "UTC", "GMT", "HUB", "AIR", "OUT", "PER", "VS", "GDP", "MAP", "CAP", "SUM", "ONE", "TWO",
}

WORD_STOPLIST = {
    "mobile", "page", "long", "hope", "rock", "sale", "union", "will", "may", "best", "most", "more",
    "beach", "city", "island", "bay", "lake", "falls", "springs", "state", "north", "south", "east",
    "west", "port", "fort", "new", "saint", "mount", "grand", "hot", "great", "green", "red",
    "white", "black", "center", "central", "county", "valley", "river", "harbor", "point", "rapids",
    "airport", "airports", "international", "regional", "field", "lines", "delta", "frontier",
    "spirit", "united", "american", "alaska", "allegiant", "southwest", "national", "capital",
    "congestion", "capacity", "demand", "terminal", "expansion", "growth", "flight", "flights",
    "compare", "which", "what", "where", "level", "levels", "haul", "candidates", "strong",
    "percentage", "unmet", "should", "invest", "investment", "about", "there", "their", "them",
}

GENERIC_NAME_WORDS = {
    "international", "regional", "municipal", "airport", "airfield", "field", "county", "jetport",
    "memorial", "metropolitan", "metro", "national", "air", "terminal", "base", "station", "the",
    "of", "and", "intl", "int'l", "executive", "district",
}


@dataclass
class Airport:
    iata: str
    name: str
    city: str
    state: str
    lat: float
    lon: float
    type: str
    scheduled: bool

    def label(self) -> str:
        return f"{self.iata} ({self.name}, {self.city}, {self.state})"


@dataclass
class Resolution:
    airports: list[str] = field(default_factory=list)
    regions: list[str] = field(default_factory=list)
    states: list[str] = field(default_factory=list)  # union of states from regions + named states
    matches: list[tuple[str, list[str]]] = field(default_factory=list)  # (phrase, codes or states)
    notes: list[str] = field(default_factory=list)

    def empty(self) -> bool:
        return not (self.airports or self.states)


def _tokens(text: str) -> list[str]:
    text = text.replace("’", "'").replace("‘", "'")
    raw = re.findall(r"[A-Za-z][A-Za-z'.\-]*|\d+", text)
    out = []
    for tok in raw:
        if tok.count(".") >= 2:  # abbreviations like L.A. / D.C. keep their dots
            out.append(tok)
        else:
            out.append(tok.rstrip(".'-").replace("'s", "") if tok.endswith("'s") else tok.rstrip(".'-"))
    return [t for t in out if t]


class Registry:
    def __init__(self, airports: pd.DataFrame, traffic: dict[str, float] | None = None):
        self.df = airports.set_index("iata", drop=False)
        self.by_ident = dict(zip(airports["ident"], airports["iata"]))
        self.traffic = traffic or {}
        self._build_aliases()

    # ----------------------------------------------------------------------------- lookups
    def is_commercial(self, code: str) -> bool:
        if self.traffic:
            return self.traffic.get(code, 0) > 0
        return bool(code in self.df.index and self.df.at[code, "scheduled"])

    def get(self, code: str) -> Airport | None:
        code = code.strip().upper()
        code = self.by_ident.get(code, code)
        if code not in self.df.index:
            return None
        r = self.df.loc[code]
        return Airport(r.iata, r["name"], r.municipality, r.state, r.lat, r.lon, r.type, bool(r.scheduled))

    def in_states(self, states: list[str]) -> list[str]:
        codes = self.df.index[self.df["state"].isin(states)]
        return [c for c in codes if self.is_commercial(c)]

    # ----------------------------------------------------------------------------- aliases
    def _build_aliases(self) -> None:
        commercial = [c for c in self.df.index if self.is_commercial(c) or self.df.at[c, "scheduled"]]
        generated: dict[str, set[str]] = {}

        def add(phrase: str, code: str) -> None:
            phrase = re.sub(r"\s+", " ", phrase.strip().lower())
            if len(phrase) >= 3:
                generated.setdefault(phrase, set()).add(code)

        for code in commercial:
            row = self.df.loc[code]
            for part in re.split(r"[/,;()]", row.municipality):
                if part.strip():
                    add(part, code)
            name_words = [w for w in re.split(r"[\s\-/]+", row["name"]) if w.lower() not in GENERIC_NAME_WORDS]
            if name_words:
                add(" ".join(name_words), code)
            for kw in str(row.keywords).split(","):
                kw = kw.strip()
                if len(kw) >= 4 and not kw.isupper():
                    add(kw, code)

        self.generated = {
            phrase: sorted(codes)
            for phrase, codes in generated.items()
            if not (" " not in phrase and (phrase in WORD_STOPLIST or len(phrase) < 4))
        }
        self.state_names = {name.lower(): code for code, name in STATES.items()}

    def _pick_city_airports(self, codes: list[str]) -> list[str]:
        """A city name can match several airports; keep the meaningful commercial ones."""
        if len(codes) <= 1:
            return codes
        if self.traffic:
            vols = {c: self.traffic.get(c, 0.0) for c in codes}
            top = max(vols.values()) or 1.0
            return [c for c in codes if vols[c] >= 0.2 * top]
        rank = {"large_airport": 0, "medium_airport": 1, "small_airport": 2}
        best = min(rank.get(self.df.at[c, "type"], 9) for c in codes)
        return [c for c in codes if rank.get(self.df.at[c, "type"], 9) == best]

    # ----------------------------------------------------------------------------- resolve
    def resolve(self, text: str) -> Resolution:
        res = Resolution()
        toks = _tokens(text)
        all_lower = text == text.lower()
        used = [False] * len(toks)

        def claim(i: int, n: int) -> None:
            for k in range(i, i + n):
                used[k] = True

        found: list[tuple[int, str, str, list[str]]] = []  # (token position, kind, phrase, codes/states)
        pos = 0

        def add_airports(phrase: str, codes: list[str]) -> None:
            codes = [c for c in codes if c in self.df.index]
            if not codes:
                return
            states = {self.df.at[c, "state"] for c in codes}
            if len(states) > 1 and len(codes) > 1 and phrase.lower() not in CURATED_ALIASES and phrase not in CASED_ALIASES:
                res.notes.append(
                    f"'{phrase}' is ambiguous: matched " + ", ".join(f"{c} ({self.df.at[c, 'state']})" for c in codes)
                )
            found.append((pos, "airport", phrase, codes))

        def add_region(phrase: str, name: str, states: list[str]) -> None:
            found.append((pos, "region:" + name, phrase, states))

        for n in (4, 3, 2, 1):
            for i in range(len(toks) - n + 1):
                if any(used[i : i + n]):
                    continue
                pos = i
                words = toks[i : i + n]
                phrase_cs = " ".join(words)
                phrase = phrase_cs.lower()
                nxt = toks[i + n].lower() if i + n < len(toks) else ""

                if nxt in {"airlines", "airline", "airways"}:  # "Alaska Airlines", "Southwest Airlines"
                    continue
                # "New York state" / "Washington state" -> the state, not the city airports
                if phrase in self.state_names and nxt == "state":
                    add_region(phrase_cs, STATES[self.state_names[phrase]], [self.state_names[phrase]])
                    claim(i, n + 1)
                elif phrase_cs in CASED_ALIASES:
                    add_airports(phrase_cs, CASED_ALIASES[phrase_cs])
                    claim(i, n)
                elif phrase in REGION_ALIASES or (n >= 2 and phrase.title() in REGIONS):
                    name = REGION_ALIASES.get(phrase, phrase.title())
                    add_region(phrase_cs, name, REGIONS[name])
                    claim(i, n)
                elif phrase in CURATED_ALIASES:
                    add_airports(phrase_cs, CURATED_ALIASES[phrase])
                    if phrase == "new york":
                        res.notes.append("'New York' read as the NYC airports; say 'New York state' for statewide.")
                    claim(i, n)
                elif phrase == "washington" and nxt in {"dc", "d.c"}:
                    add_airports("Washington DC", CURATED_ALIASES["washington dc"])
                    claim(i, n + 1)
                elif phrase in self.state_names:
                    code = self.state_names[phrase]
                    add_region(phrase_cs, STATES[code], [code])
                    claim(i, n)
                elif n == 1 and len(words[0]) in (3, 4) and words[0].isupper() and words[0] not in CODE_STOPLIST:
                    code = self.by_ident.get(words[0], words[0])
                    if code in self.df.index:
                        add_airports(words[0], [code])
                        claim(i, n)
                elif phrase in self.generated:
                    # single generic-looking words must be capitalised unless the user types all-lowercase
                    if n == 1 and not (all_lower or words[0][0].isupper()):
                        continue
                    add_airports(phrase_cs, self._pick_city_airports(self.generated[phrase]))
                    claim(i, n)

        for _, kind, phrase, items in sorted(found, key=lambda f: f[0]):
            res.matches.append((phrase, items))
            if kind == "airport":
                res.airports += [c for c in items if c not in res.airports]
            else:
                name = kind.split(":", 1)[1]
                if name not in res.regions:
                    res.regions.append(name)
                res.states += [s for s in items if s not in res.states]
        return res


@lru_cache(maxsize=1)
def _default_registry() -> Registry:
    airports, _ = airports_frame()
    return Registry(airports)


_registry_override: Registry | None = None


def registry() -> Registry:
    """Process-wide registry. The feature pipeline upgrades it with traffic volumes via :func:`set_registry`."""
    return _registry_override or _default_registry()


def set_registry(reg: Registry) -> None:
    global _registry_override
    _registry_override = reg
