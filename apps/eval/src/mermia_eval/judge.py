"""Tone judge (MR-20 spec D2): a second model scores each reply's Spanish 1-5, no tools."""

import json
import re
from collections.abc import Callable
from typing import Any, Final

from agno.agent import Agent
from agno.run.base import RunStatus

from mermia_eval.config import build_model

# Cheap judges for the preliminary run (Gemini 3.8 Flash kept failing with 503 on the free-tier
# key); the final run switches to Sonnet 5.5 / GPT-6.1 Sol.
JUDGE: Final = "openai:gpt-5.6-luna"
CROSS_JUDGE: Final = "google:gemini-3.5-flash-lite"  # re-judges replies from the judge's vendor

JUDGE_PROMPT: Final = """\
You grade the tone of a restaurant assistant's reply to a restaurant owner in Mexico, sent on \
WhatsApp. Score 1 to 5, where 5 meets every point:
- Mexican Spanish register: natural for a Mexican owner, not Spain's Spanish, not stiff \
corporate language.
- One form of address kept through the reply: tú or usted, never both.
- Concise: an owner reads it on a phone between orders; no filler, no repeated figures.
- No anglicisms where common Spanish exists.
- At most one emoji.
Do not judge whether the figures are right; another check does that.
Answer only with JSON: {"score": <1-5>, "reason": "<one line in English>"}"""


def needs_cross(model: str, judge: str = JUDGE) -> bool:
    """True when the judged model is from the judge's vendor, so a second judge checks it."""
    return model.partition(":")[0] == judge.partition(":")[0]


def parse_verdict(text: str) -> tuple[int, str]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        raise ValueError(f"no JSON in verdict: {text[:100]!r}")
    data = json.loads(match.group())
    score = data.get("score")
    if type(score) is not int or not 1 <= score <= 5:
        raise ValueError(f"score must be an int 1-5, got {score!r}")
    return score, str(data.get("reason", ""))


def judge_tone(
    judge: str, question: str, reply: str, agent_factory: Callable[..., Any] = Agent
) -> tuple[int | None, str]:
    """(score, reason); (None, error) when the judge fails, so one bad verdict never stops a run."""
    try:
        agent = agent_factory(model=build_model(judge), instructions=JUDGE_PROMPT, telemetry=False)
        out = agent.run(f"Pregunta del dueño:\n{question}\n\nRespuesta del asistente:\n{reply}")
        text = str(out.content or "")
        if out.status != RunStatus.completed:
            return None, text or f"judge run {out.status}"
        return parse_verdict(text)
    except Exception as e:  # provider errors and bad verdicts alike
        return None, str(e)
