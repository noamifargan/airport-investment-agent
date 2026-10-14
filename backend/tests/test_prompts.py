"""The agent's markdown prompts and skill folders load and match real tools."""

from airport_agent.agent.agent import ANSWER_NUDGE, PROMPTS, SKILLS, SYSTEM, _answer_prompt
from airport_agent.agent.tools import TOOLS


def test_prompts_load():
    assert SYSTEM.startswith("You are an aviation investment analyst")
    assert "KEY FACT" in ANSWER_NUDGE


def test_skills_belong_to_tools():
    assert set(SKILLS) == {"rank_airports", "compare_airports", "route_mix", "unmet_demand"}
    assert set(SKILLS) <= set(TOOLS)
    for skill in SKILLS.values():
        assert (PROMPTS / "skills" / skill["name"] / "SKILL.md").is_file()  # folder name = skill name
        assert skill["description"] and skill["body"].startswith("## How to answer")


def test_answer_prompt_adds_only_the_skills_that_ran():
    prompt = _answer_prompt(["unmet_demand", "unmet_demand", "live_status"])
    assert prompt.startswith(ANSWER_NUDGE)
    assert prompt.count(SKILLS["unmet_demand"]["body"]) == 1
    assert SKILLS["route_mix"]["body"] not in prompt
    assert _answer_prompt([]) == ANSWER_NUDGE
