from types import SimpleNamespace
from typing import Any

import pytest
from agno.run.agent import RunOutput
from agno.run.base import RunStatus

from mermia_eval.judge import JUDGE, JUDGE_PROMPT, judge_tone, needs_cross, parse_verdict

QUESTION, REPLY = "¿Cuánto vendí ayer?", "Ayer vendiste $26,550.00 en Centro."


def _factory(content: str | Exception, seen: list[str] | None = None) -> Any:
    def run(message: str) -> RunOutput:
        if seen is not None:
            seen.append(message)
        if isinstance(content, Exception):
            raise content
        return RunOutput(content=content, status=RunStatus.completed)

    return lambda **_: SimpleNamespace(run=run)


def test_parse_plain_json() -> None:
    assert parse_verdict('{"score": 4, "reason": "ok"}') == (4, "ok")


def test_parse_json_inside_prose() -> None:
    assert parse_verdict('Claro.\n{"score": 5, "reason": "bien"}\nSaludos') == (5, "bien")


@pytest.mark.parametrize("text", ['{"score": 0}', '{"score": 6}', '{"score": "4"}', "sin json"])
def test_parse_rejects(text: str) -> None:
    with pytest.raises(ValueError):
        parse_verdict(text)


def test_judge_tone_ok() -> None:
    seen: list[str] = []
    verdict = judge_tone(JUDGE, QUESTION, REPLY, _factory('{"score": 4, "reason": "ok"}', seen))
    assert verdict == (4, "ok")
    assert QUESTION in seen[0] and REPLY in seen[0]


def test_judge_tone_never_raises() -> None:
    score, reason = judge_tone(JUDGE, QUESTION, REPLY, _factory(RuntimeError("boom")))
    assert score is None and "boom" in reason
    assert judge_tone(JUDGE, QUESTION, REPLY, _factory("no sé"))[0] is None


def test_judge_tone_failed_run_is_no_score() -> None:
    failed = lambda **_: SimpleNamespace(  # noqa: E731
        run=lambda m: RunOutput(content="rate limit", status=RunStatus.error)
    )
    assert judge_tone(JUDGE, QUESTION, REPLY, failed) == (None, "rate limit")


def test_rubric_names_the_criteria() -> None:
    for word in ("tú", "usted", "emoji", '"score"', '"reason"'):
        assert word in JUDGE_PROMPT


def test_needs_cross() -> None:
    assert needs_cross("openai:gpt-5.6-luna") is True
    assert needs_cross("google:gemini-3.5-flash-lite") is False
    assert needs_cross("anthropic:claude-haiku-5-5") is False
