"""The agent's markdown prompts and skill folders load and match real tools."""

from airport_agent.agent.agent import ANSWER_NUDGE, PROMPTS, SKILLS, SYSTEM, _answer_prompt, _tool_message
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
        assert "Key uncertainty" in skill["body"]  # the answer's one uncertainty line comes from here


def test_model_does_not_see_the_assumption_list():
    out = {"result": {"headline": ["SFO: 1.8M"], "x": 1}, "assumptions": ["Delay figures cover one month."]}
    message = _tool_message(out)
    assert "SFO: 1.8M" in message and "one month" not in message


def test_answer_prompt_adds_only_the_skills_that_ran():
    prompt = _answer_prompt(["unmet_demand", "unmet_demand", "live_status"])
    assert prompt.startswith(ANSWER_NUDGE)
    assert prompt.count(SKILLS["unmet_demand"]["body"]) == 1
    assert SKILLS["route_mix"]["body"] not in prompt
    assert _answer_prompt([]) == ANSWER_NUDGE
