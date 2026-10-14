"""Fallback router: the tool and metric chosen when the LLM makes no tool call."""

import pytest

from airport_agent.agent.agent import Session, route
from airport_agent.data.registry import registry


@pytest.mark.parametrize(
    "question, metric",
    [
        ("Why is Bangor ranked above Boston?", "terminal_expansion"),
        ("Is Bradley a better investment candidate than Providence?", "terminal_expansion"),
        ("Compare LA and Santa Ana airport congestion levels.", "congestion"),
        ("How does Logan compare to Bradley?", "congestion"),
    ],
)
def test_compare_metric(question, metric):
    calls = route(question, registry().resolve(question), Session())
    assert [(name, args["metric"]) for name, args in calls] == [("compare_airports", metric)]
