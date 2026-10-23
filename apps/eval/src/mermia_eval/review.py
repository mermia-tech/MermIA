"""Markdown table of the eval cases, for Dev A to review the expected figures."""

import json

from mermia_contracts.agent_tools import tools_sha256
from mermia_eval.cases import Case, load_cases
from mermia_eval.figures import derived_figures

TODAY = "2026-10-12"  # fixtures/el_guero/expected.json "today"


def _figure(fig: str, case: Case, sources: dict[str, str]) -> str:
    names = ", ".join(n for n, v in sources.items() if v == fig) or "sin fuente"
    pending = "" if fig in case.must_contain else " (pending)"  # the mock cannot return it
    return f"{fig} [{names}]{pending}"


def review_table(cases: list[Case]) -> str:
    sources = derived_figures()
    head = ["id", "category", "question", "tool", "args", "must_contain", "expected_figures"]
    rows = [head, ["---"] * len(head)]
    for c in cases:
        figs = "; ".join(_figure(f, c, sources) for f in c.expected_figures)
        args = json.dumps(c.expected_args, ensure_ascii=False)
        rows.append(
            [
                c.id,
                c.category,
                c.question,
                c.expected_tool or "ninguna",
                args,
                "; ".join(c.must_contain),
                figs,
            ]
        )
    return "\n".join("| " + " | ".join(cell.replace("|", "\\|") for cell in r) + " |" for r in rows)


def main() -> None:
    print(f"tools_sha256: {tools_sha256()} | today: {TODAY}\n")
    print(review_table(load_cases()))


if __name__ == "__main__":
    main()
