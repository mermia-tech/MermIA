import dataclasses
import json
from types import SimpleNamespace
from typing import Any

import agno.utils.log as agno_log
import pytest

from mermia_eval import cli
from mermia_eval.cases import load_cases
from mermia_eval.config import Price
from mermia_eval.run import RunResult, run_case
from mermia_eval.score import ToolCall
from mermia_mock_rpc import rpcs

CASE = load_cases()[0]
ANSWER = json.dumps(rpcs.build("get_dish_margin"), ensure_ascii=False)
LUNA, HAIKU = "openai:gpt-5.6-luna", "anthropic:claude-haiku-5-5"


def _ok(
    model: str = LUNA, reply: str = "Margen $37.63 (67.2%), costo $18.40, precio $65.00"
) -> RunResult:
    call = ToolCall("get_dish_margin", {"dish": "tacos al pastor"})
    return RunResult(model, [call], [ANSWER], reply, 1000, 100, 0, 0, 2.0, None, "tid")


def _err(model: str = LUNA) -> RunResult:
    return RunResult(model, [], [], "no credit", 0, 0, 0, 0, 0.1, "no credit", None)


def test_summarize_means_and_counts_errors() -> None:
    results = [_ok(), _ok(reply="Margen $99.99"), _err()]
    (row,) = cli.summarize(results, CASE, {LUNA: Price(1.0, 0.1, 2.0)})
    assert (row["runs"], row["errors"]) == (3, 1)
    assert (row["tool"], row["args"], row["numbers"]) == (1.0, 1.0, 0.5)
    assert row["tokens_in"] == 1000 and row["seconds"] == 2.0
    assert row["cost"] == pytest.approx((1000 * 1.0 + 100 * 2.0) / 1e6)


def test_summarize_all_errors_has_no_scores() -> None:
    (row,) = cli.summarize([_err(), _err()], CASE, {LUNA: None})
    assert row["tool"] is None and row["cost"] is None and row["errors"] == 2


def test_format_table_shows_na_cost_and_dash_scores() -> None:
    rows = cli.summarize([_err()], CASE, {LUNA: None}) + cli.summarize([_ok()], CASE, {LUNA: None})
    table = cli.format_table(rows)
    assert "n/a" in table and "-" in table and LUNA in table


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "setup_tracing", lambda env: None)
    monkeypatch.setattr(cli, "post_scores", lambda *a, **k: None)


def test_exit_code_is_zero_with_low_scores(
    monkeypatch: pytest.MonkeyPatch, no_network: None
) -> None:
    bad = RunResult(LUNA, [], [], "no sé", 10, 5, 0, 0, 1.0, None, None)
    monkeypatch.setattr(cli, "run_case", lambda model, case, tools, **kw: bad)
    assert cli.main(["--models", LUNA]) == 0


def test_exit_code_is_one_when_every_run_errors(
    monkeypatch: pytest.MonkeyPatch, no_network: None
) -> None:
    monkeypatch.setattr(cli, "run_case", lambda model, case, tools, **kw: _err(model))
    assert cli.main(["--models", f"{LUNA},{HAIKU}"]) == 1


def test_one_failing_model_does_not_stop_the_others(
    monkeypatch: pytest.MonkeyPatch, no_network: None, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake(model: str, case: Any, tools: Any, **kw: Any) -> RunResult:
        return _err(model) if model == HAIKU else _ok(model)

    monkeypatch.setattr(cli, "run_case", fake)
    assert cli.main(["--runs", "2", "--models", f"{HAIKU},{LUNA}"]) == 0
    out = capsys.readouterr().out
    assert HAIKU in out and LUNA in out


def test_models_filter_rejects_unknown_id(no_network: None) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--models", "deepseek:v4"])


def test_main_passes_the_backend_failures_to_run_case(
    monkeypatch: pytest.MonkeyPatch, no_network: None
) -> None:
    seen: list[Any] = []

    def fake(model: str, case: Any, tools: Any, **kw: Any) -> RunResult:
        seen.append(kw["failures"])
        return _ok(model)

    monkeypatch.setattr(cli, "run_case", fake)
    cli.main(["--runs", "2", "--models", LUNA])
    assert (
        len(seen) == 2 and seen[0] is seen[1] and seen[0] == []
    )  # one backend list, cleared per run


@pytest.mark.parametrize("value", ["0", "-2", "abc"])
def test_runs_must_be_at_least_one(value: str, no_network: None) -> None:
    with pytest.raises(SystemExit) as stop:
        cli.main(["--runs", value, "--models", LUNA])
    assert stop.value.code == 2


def test_empty_models_is_rejected(monkeypatch: pytest.MonkeyPatch, no_network: None) -> None:
    def never(*a: Any, **k: Any) -> RunResult:
        raise AssertionError("no model may be called")

    monkeypatch.setattr(cli, "run_case", never)
    for bad in ("", ",", f"{LUNA},"):
        with pytest.raises(SystemExit) as stop:
            cli.main(["--models", bad])
        assert stop.value.code == 2


def test_models_are_stripped(monkeypatch: pytest.MonkeyPatch, no_network: None) -> None:
    called: list[str] = []

    def fake(model: str, case: Any, tools: Any, **kw: Any) -> RunResult:
        called.append(model)
        return _ok(model)

    monkeypatch.setattr(cli, "run_case", fake)
    assert cli.main(["--models", f"{LUNA}, google:gemini-3.8-flash"]) == 0
    assert called == [LUNA, "google:gemini-3.8-flash"]


def test_format_table_is_header_plus_rows() -> None:
    rows = cli.summarize([_ok(), _err()], CASE, {LUNA: None})
    expected = "\n".join([cli.format_header(), *(cli.format_row(r) for r in rows)])
    assert cli.format_table(rows) == expected


def test_rows_are_printed_as_each_model_finishes(
    monkeypatch: pytest.MonkeyPatch, no_network: None, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake(model: str, case: Any, tools: Any, **kw: Any) -> RunResult:
        if model == HAIKU:
            raise KeyboardInterrupt
        return _ok(model)

    monkeypatch.setattr(cli, "run_case", fake)
    with pytest.raises(KeyboardInterrupt):
        cli.main(["--models", f"{LUNA},{HAIKU}"])
    out = capsys.readouterr().out
    assert "model" in out and LUNA in out  # header and the finished model's row survive


def test_redact_hides_secret_values() -> None:
    env = {"OPENAI_API_KEY": "sk-abcdef123456", "SHORT_KEY": "abc", "HOME": "/Users/arturo"}
    text = "bad key sk-abcdef123456 at /Users/arturo abc"
    assert cli.redact(text, env) == "bad key *** at /Users/arturo abc"


def _failing(monkeypatch: pytest.MonkeyPatch, message: str) -> None:
    def fake(model: str, case: Any, tools: Any, **kw: Any) -> RunResult:
        return dataclasses.replace(_err(model), error=message)

    monkeypatch.setattr(cli, "run_case", fake)


def test_errors_are_listed_once_per_model_on_stderr(
    monkeypatch: pytest.MonkeyPatch, no_network: None, capsys: pytest.CaptureFixture[str]
) -> None:
    _failing(monkeypatch, "no credit")
    cli.main(["--runs", "2", "--models", LUNA])
    captured = capsys.readouterr()
    assert [ln for ln in captured.err.splitlines() if "no credit" in ln] == [f"{LUNA}: no credit"]
    assert "no credit" not in captured.out


def test_error_line_never_contains_a_secret(
    monkeypatch: pytest.MonkeyPatch, no_network: None, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value-123")
    _failing(monkeypatch, "Incorrect API key sk-secret-value-123")
    cli.main(["--models", LUNA])
    captured = capsys.readouterr()
    assert "sk-secret-value-123" not in captured.err + captured.out
    assert "Incorrect API key ***" in captured.err


def test_missing_langfuse_variables_print_a_warning(
    monkeypatch: pytest.MonkeyPatch, no_network: None, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "run_case", lambda model, case, tools, **kw: _ok(model))
    cli.main(["--models", LUNA])
    assert "LANGFUSE" in capsys.readouterr().err


def test_error_line_is_a_single_line(
    monkeypatch: pytest.MonkeyPatch, no_network: None, capsys: pytest.CaptureFixture[str]
) -> None:
    _failing(monkeypatch, '{\n  "error": {\n    "code": 503\n  }\n}')
    cli.main(["--models", LUNA])
    lines = [ln for ln in capsys.readouterr().err.splitlines() if ln.startswith(LUNA)]
    assert lines == [f'{LUNA}: {{ "error": {{ "code": 503 }} }}']


def test_secret_straddling_the_limit_is_not_printed(
    monkeypatch: pytest.MonkeyPatch, no_network: None, capsys: pytest.CaptureFixture[str]
) -> None:
    key = "sk-secret-value-123456"
    monkeypatch.setenv("OPENAI_API_KEY", key)

    def raiser(**_: Any) -> Any:
        def run(question: str) -> Any:
            raise RuntimeError("x" * 295 + key + "tail")  # the key crosses character 300

        return SimpleNamespace(run=run)

    monkeypatch.setattr(
        cli, "run_case", lambda model, case, tools, **kw: run_case(model, case, tools, raiser, **kw)
    )
    cli.main(["--models", LUNA])
    assert "sk-" not in capsys.readouterr().err  # not even a prefix of the key


def test_redact_covers_password_auth_and_credential_names() -> None:
    env = {
        "DB_PASSWORD": "hunter2hunter2",
        "AUTH_HEADER": "Bearer abc12345",
        "MY_CREDENTIAL": "cred-9999",
    }
    text = "hunter2hunter2 | Bearer abc12345 | cred-9999"
    assert cli.redact(text, env) == "*** | *** | ***"


def test_redact_covers_the_url_encoded_form() -> None:
    env = {"X_API_KEY": "abc/def+ghi123"}
    text = "url=abc%2Fdef%2Bghi123 plain=abc/def+ghi123"
    assert cli.redact(text, env) == "url=*** plain=***"


def test_redact_leaves_short_values_and_other_names() -> None:
    env = {"API_KEY": "short", "HOME": "/Users/arturopo"}
    assert cli.redact("short /Users/arturopo", env) == "short /Users/arturopo"


def test_failures_do_not_leak_into_the_next_run(
    monkeypatch: pytest.MonkeyPatch, no_network: None
) -> None:
    starts: list[list[str]] = []

    def fake(model: str, case: Any, tools: Any, **kw: Any) -> RunResult:
        starts.append(list(kw["failures"]))
        kw["failures"].append("boom")  # a backend failure during this run
        return _ok(model)

    monkeypatch.setattr(cli, "run_case", fake)
    cli.main(["--runs", "2", "--models", f"{LUNA},{HAIKU}"])
    assert starts == [[], [], [], []]


def test_error_summary_survives_ctrl_c(
    monkeypatch: pytest.MonkeyPatch, no_network: None, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake(model: str, case: Any, tools: Any, **kw: Any) -> RunResult:
        if model == HAIKU:
            raise KeyboardInterrupt
        return dataclasses.replace(_err(model), error="no credit")

    monkeypatch.setattr(cli, "run_case", fake)
    with pytest.raises(KeyboardInterrupt):
        cli.main(["--models", f"{LUNA},{HAIKU}"])
    assert f"{LUNA}: no credit" in capsys.readouterr().err


@pytest.fixture(autouse=True)
def agno_loggers_restored(monkeypatch: pytest.MonkeyPatch) -> None:
    # main() replaces Agno's module-level loggers; give them back after every test
    for name in ("logger", "agent_logger", "team_logger", "workflow_logger"):
        monkeypatch.setattr(agno_log, name, getattr(agno_log, name))


def test_agno_errors_go_to_stderr_not_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    cli.route_agno_logs({})
    agno_log.log_error("Error from OpenAI API: boom")  # type: ignore[no-untyped-call]
    captured = capsys.readouterr()
    assert captured.out == "" and "boom" in captured.err


def test_agno_log_lines_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    key = "sk-secret-value-123456"
    cli.route_agno_logs({"OPENAI_API_KEY": key})
    agno_log.log_error(f"Incorrect API key provided: {key}")  # type: ignore[no-untyped-call]
    captured = capsys.readouterr()
    assert key not in captured.out + captured.err and "***" in captured.err


def test_main_routes_agno_logs(monkeypatch: pytest.MonkeyPatch, no_network: None) -> None:
    seen: list[Any] = []
    monkeypatch.setattr(cli, "route_agno_logs", seen.append)
    monkeypatch.setattr(cli, "run_case", lambda model, case, tools, **kw: _ok(model))
    cli.main(["--models", LUNA])
    assert len(seen) == 1


def test_no_cases_is_an_error_not_an_empty_run(
    monkeypatch: pytest.MonkeyPatch, no_network: None, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "load_cases", lambda: [])
    with pytest.raises(SystemExit) as exit_info:
        cli.main([])
    assert exit_info.value.code == 2
    assert "no cases" in capsys.readouterr().err


def test_traces_are_flushed_before_their_scores_are_posted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Spans are exported in the background, so the trace must reach Langfuse before its scores.
    events: list[str] = []
    provider = SimpleNamespace(force_flush=lambda: events.append("flush"))
    monkeypatch.setattr(cli, "setup_tracing", lambda env: provider)
    monkeypatch.setattr(cli, "post_scores", lambda *a, **k: events.append("scores"))
    monkeypatch.setattr(cli, "run_case", lambda model, case, tools, **kw: _ok(model))
    cli.main(["--models", LUNA])
    assert events[:2] == ["flush", "scores"]
