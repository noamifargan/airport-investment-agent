"""Resolver tests against the real OurAirports registry (fetched once, then cached)."""

import pytest

from airport_agent.data.registry import registry


@pytest.fixture(scope="module")
def reg():
    return registry()


@pytest.mark.parametrize(
    "text, airports",
    [
        ("Compare LA and Santa Ana airport congestion levels.", ["LAX", "SNA"]),
        ("What is the percentage of long haul flights out of Anchorage airport?", ["ANC"]),
        ("What is the unmet flight demand in SFO airport and why?", ["SFO"]),
        ("how does logan compare to bradley", ["BOS", "BDL"]),
        ("Is KSFO busier than John Wayne?", ["SFO", "SNA"]),
        ("What about Hartford and Providence?", ["BDL", "PVD"]),
    ],
)
def test_airport_mentions(reg, text, airports):
    assert reg.resolve(text).airports == airports


def test_region(reg):
    res = reg.resolve("Which airports in New England are strong candidates for terminal expansion?")
    assert res.regions == ["New England"] and res.airports == []
    assert sorted(res.states) == ["CT", "MA", "ME", "NH", "RI", "VT"]
    codes = reg.in_states(res.states)
    assert {"BOS", "BDL", "PVD", "MHT", "PWM", "BTV"} <= set(codes)


def test_no_false_positives(reg):
    for text in [
        "Which airports have the most unmet demand and why?",
        "Rank them by growth. What about the top one?",
        "Is Southwest Airlines dominant there?",
    ]:
        res = reg.resolve(text)
        assert res.airports == [] and res.regions == [], (text, res)


def test_state_vs_city(reg):
    assert reg.resolve("airports in California").states == ["CA"]
    assert reg.resolve("New York airports").airports == ["JFK", "LGA", "EWR"]
    assert reg.resolve("New York state airports").states == ["NY"]
