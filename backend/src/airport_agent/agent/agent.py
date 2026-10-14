"""The conversational agent: deterministic entity resolution → LLM tool choice → tools → grounded answer.

Where the LLM is used (and where it isn't):
* Entity resolution (airport / city / region → codes) is deterministic (registry).
* The LLM (Ollama) chooses which tool to call and with which arguments; if it fails to call
  one, a keyword router picks a tool deterministically so the user still gets data.
* Every number comes from a tool; the LLM only explains it.
* Sources and assumptions shown under each answer are appended deterministically, not generated.
* The model's instructions are markdown files in prompts/: the system prompt, the answer rules, and one
  skill folder (skills/<name>/SKILL.md) per kind of question, loaded only when that tool runs.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from airport_agent.agent import llm
from airport_agent.agent.tools import SCHEMAS, TOOLS
from airport_agent.analytics.features import features
from airport_agent.data.registry import Resolution, registry

PROMPTS = Path(__file__).parent / "prompts"


def _skill(path: Path) -> dict:
    """A skill's SKILL.md: frontmatter (name, description) between '---' lines, then markdown instructions."""
    _, meta, body = path.read_text().split("---", 2)
    fields = dict(line.split(":", 1) for line in meta.strip().splitlines())
    return {key.strip(): value.strip() for key, value in fields.items()} | {"body": body.strip()}


SYSTEM = (PROMPTS / "system.md").read_text().strip()
ANSWER_NUDGE = (PROMPTS / "answer.md").read_text().strip()
# One folder per skill, skills/<name>/SKILL.md; skill "unmet-demand" guides the answer for tool unmet_demand.
SKILLS = {s["name"].replace("-", "_"): s for s in map(_skill, sorted((PROMPTS / "skills").glob("*/SKILL.md")))}


def _answer_prompt(tools: list[str]) -> str:
    """Answer rules plus the SKILL.md of each tool that ran."""
    guides = [f"Skill {SKILLS[t]['name']}: {SKILLS[t]['description']}\n{SKILLS[t]['body']}" for t in dict.fromkeys(tools) if t in SKILLS]
    return "\n\n".join([ANSWER_NUDGE, *guides])


OFF_TOPIC = (
    "I answer questions about US airports: traffic and growth, congestion, route mix, unmet demand and which "
    "airports are strong candidates for terminal expansion. Name an airport (SFO), a city (Santa Ana) or a "
    "region (New England) to get started."
)
DOMAIN_WORDS = re.compile(
    r"airport|flight|airline|runway|terminal|gate|passeng|enplan|congest|delay|capacit|demand|route|hub|cargo|"
    r"aviation|invest|expan|scor|rank|load factor|long[\s-]?haul|faa|bts|method|weight|kpi|travel",
    re.IGNORECASE,
)


@dataclass
class Session:
    history: list[dict] = field(default_factory=list)  # prior user/assistant turns (answers without footers)
    focus_airports: list[str] = field(default_factory=list)
    focus_region: str = ""
    last_tool: str = ""


def _hint(res: Resolution, session: Session) -> str:
    reg = registry()
    parts = []
    if res.airports:
        parts.append("airports " + ", ".join(reg.get(c).label() if reg.get(c) else c for c in res.airports))
    if res.regions:
        parts.append("region " + ", ".join(res.regions) + f" (states {', '.join(res.states)})")
    if session.focus_airports or session.focus_region:
        prev = ", ".join(session.focus_airports) or session.focus_region
        tool = f" using {session.last_tool}" if session.last_tool else ""
        parts.append(f"previous turn was about {prev}{tool}" + ("" if parts else " — this is a follow-up about it"))
    parts += res.notes
    return "; ".join(parts) if parts else "no airport or region recognised"


def route(question: str, res: Resolution, session: Session) -> list[tuple[str, dict]]:
    """Deterministic fallback: choose tool calls from keywords + resolved entities."""
    q = question.lower()
    airports = res.airports or ([] if res.regions else session.focus_airports)
    region = ", ".join(res.regions) or (session.focus_region if not res.airports else "")
    congestion = bool(re.search(r"congest|delay|busy|crowd|bottleneck", q))
    metric = "congestion" if congestion else "terminal_expansion"
    if re.search(r"method|weight|how do you score|scoring|kpi", q):
        return [("methodology", {})]
    follow_up_compare = re.search(r"compar|\bvs\b|versus|than|relative", q) and len(res.airports) == 1 and session.focus_airports
    if follow_up_compare:
        pair = list(dict.fromkeys(session.focus_airports + res.airports))
        if session.last_tool in {"unmet_demand", "route_mix", "live_status", "airport_profile"}:
            return [(session.last_tool, {"airport": a}) for a in pair[:3]]
        return [("compare_airports", {"airports": pair, "metric": metric})]
    if airports and re.search(r"long[\s-]?haul|distance|route|destination", q):
        return [("route_mix", {"airport": airports[0]})]
    if airports and re.search(r"unmet|spill|latent|demand", q):
        return [("unmet_demand", {"airport": a}) for a in airports[:2]]
    if airports and re.search(r"right now|currently|today|live|ground stop", q):
        return [("live_status", {"airport": airports[0]})]
    if len(airports) >= 2:
        investment = re.search(r"expan|rank|candidate|invest|terminal", q)
        return [("compare_airports", {"airports": airports, "metric": metric if congestion or investment else "congestion"})]
    if region and not res.airports:
        return [("rank_airports", {"region": region, "metric": metric})]
    if airports:
        return [("airport_profile", {"airport": airports[0]})]
    return []


def _run(name: str, args: dict, res: Resolution, session: Session) -> dict:
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    args = {k: v for k, v in (args or {}).items() if v not in (None, "", [])}
    try:
        return fn(**args)
    except (ValueError, TypeError) as exc:  # ToolError is a ValueError; bad argument values raise either
        # Repair obviously bad arguments with the deterministically resolved entities, then retry once.
        fixed = dict(args)
        airports = res.airports or session.focus_airports
        if "airport" in fixed or name in {"airport_profile", "route_mix", "unmet_demand", "live_status"}:
            if airports:
                fixed["airport"] = airports[0]
        if name == "compare_airports" and len(airports) >= 2:
            fixed["airports"] = airports
        if name == "rank_airports" and (res.regions or session.focus_region):
            fixed["region"] = ", ".join(res.regions) or session.focus_region
        if fixed != args:
            try:
                return fn(**fixed)
            except (ValueError, TypeError):
                pass
        return {"error": str(exc)}


def _tool_message(out: dict) -> str:
    """Tool result as the LLM sees it: KEY FACTS first (small models anchor on what comes first), then details.
    Sources are left out — they go in the deterministic footer instead."""
    result = dict(out.get("result", {})) if isinstance(out.get("result"), dict) else out.get("result")
    headline = result.pop("headline", None) if isinstance(result, dict) else None
    facts = [headline] if isinstance(headline, str) else (headline or [])
    text = ""
    if facts:
        text += "KEY FACTS:\n" + "\n".join(f"- {f}" for f in facts) + "\n\n"
    if "error" in out:
        text += f"ERROR: {out['error']}\n"
    # Assumptions are left out too: given the full list, a small model repeats the wrong one in every answer.
    # The answer takes its uncertainty line from the skill file; the footer lists every assumption.
    details = {"details": result} if result is not None else {}
    return text + "DETAILS: " + json.dumps(details, ensure_ascii=False)


def _remember(session: Session, calls: list[tuple[str, dict]], res: Resolution) -> None:
    if res.airports:
        session.focus_airports, session.focus_region = res.airports, ""
    elif res.regions:
        session.focus_region, session.focus_airports = ", ".join(res.regions), []
    for name, args in calls:
        session.last_tool = name
        codes = args.get("airports") or ([args["airport"]] if args.get("airport") else [])
        if codes and not res.airports:
            session.focus_airports = [c.upper() for c in codes if isinstance(c, str)]
        if args.get("region") and not res.regions:
            session.focus_region = args["region"]


def _footer(results: list[dict]) -> dict:
    sources, assumptions = [], []
    for r in results:
        sources += [s for s in r.get("sources", []) if s not in sources]
        assumptions += [a for a in r.get("assumptions", []) if a not in assumptions]
    lines = []
    if sources:
        lines += ["", "---", "**Data sources**"] + [f"- {s}" for s in sources]
    if assumptions:
        lines += ["", "**Assumptions & uncertainty**"] + [f"- {a}" for a in assumptions]
    return {"type": "footer", "text": "\n".join(lines), "sources": sources, "assumptions": assumptions}


def ask(question: str, session: Session) -> Iterator[dict]:
    """Answer one question. Yields events: status / tool / token / footer / error / done."""
    features()  # make sure the KPI table (and traffic-aware registry) is loaded
    res = registry().resolve(question)
    hint = _hint(res, session)
    yield {"type": "status", "text": f"Resolved: {hint}"}

    if res.empty() and not (session.focus_airports or session.focus_region) and not DOMAIN_WORDS.search(question):
        # Nothing about airports here: don't let the model invent an analysis.
        yield {"type": "token", "text": OFF_TOPIC}
        session.history += [{"role": "user", "content": question}, {"role": "assistant", "content": OFF_TOPIC}]
        yield {"type": "done"}
        return

    messages = [{"role": "system", "content": SYSTEM}, *session.history[-6:],
                {"role": "user", "content": f"{question}\n\n[Resolved: {hint}]"}]

    try:
        reply = llm.chat(messages, tools=SCHEMAS)
    except llm.LLMUnavailable as exc:
        reply = {"content": "", "tool_calls": []}
        yield {"type": "status", "text": f"LLM unavailable ({exc}); using the deterministic router."}

    calls = [(c["function"]["name"], c["function"].get("arguments") or {}) for c in reply.get("tool_calls") or []]
    chosen_by = "LLM"
    if calls and res.airports and session.focus_airports and re.search(r"compar|\bvs\b|versus|than|relative", question.lower()):
        # Follow-up comparison ("how does that compare to LAX?"): make sure the earlier airport is included too.
        extra = [c for c in route(question, res, session) if c not in calls]
        if extra:
            calls += extra
            chosen_by = "LLM + router (added earlier airport for the comparison)"
    if not calls:
        calls = route(question, res, session)
        chosen_by = "router (LLM made no tool call)"
    if not calls:
        # General question with no data needed (or nothing recognised): let the model reply directly.
        answer = reply.get("content") or "Which airport or region should I look at? (e.g. 'SFO', 'Santa Ana', 'New England')"
        yield {"type": "token", "text": answer}
        session.history += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        yield {"type": "done"}
        return

    results = []
    messages.append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": n, "arguments": a}} for n, a in calls]})
    for name, args in calls[:3]:
        yield {"type": "tool", "text": f"{name}({json.dumps(args)}) — chosen by {chosen_by}",
               "name": name, "args": args, "chosen_by": "router" if chosen_by.startswith("router") else "llm"}
        out = _run(name, args, res, session)
        results.append(out)
        messages.append({"role": "tool", "tool_name": name, "content": _tool_message(out)})
    _remember(session, calls, res)

    if all("error" in r for r in results):
        # Every analysis failed: report it plainly instead of letting the model improvise an answer.
        answer = ("That analysis couldn't run: " + "; ".join(r["error"] for r in results)
                  + " Try naming an airport (SFO), a city (Santa Ana) or a region (New England).")
        yield {"type": "token", "text": answer}
        session.history += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        yield {"type": "done"}
        return

    ran = [name for (name, _), out in zip(calls, results) if "error" not in out]
    messages.append({"role": "user", "content": _answer_prompt(ran)})
    answer = ""
    try:
        for token in llm.stream(messages):
            answer += token
            yield {"type": "token", "text": token}
    except llm.LLMUnavailable:
        answer = "LLM unavailable — raw tool results:\n```json\n" + json.dumps([r.get("result", r) for r in results], indent=1, ensure_ascii=False) + "\n```"
        yield {"type": "token", "text": answer}

    yield _footer(results)
    session.history += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
    yield {"type": "done"}
