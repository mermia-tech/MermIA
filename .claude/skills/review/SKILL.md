---
name: review
description: Two-pass pre-PR review for MermIA. Runs the built-in /code-review, then the skeptic-reviewer agent to challenge its findings and check MermIA-specific risks, and returns one merged list.
argument-hint: "[PR number | base ref] [effort: low|medium|high|xhigh|max]"
disable-model-invocation: true
---

# review

Arguments: `$ARGUMENTS`. A number is a PR. Anything else that looks like a ref (for example `origin/main`) is the diff base. A word from low, medium, high, xhigh or max is the effort level. Defaults: the current branch's diff against `origin/main`, effort `high`.

This skill only reports. Do not fix, commit, push or post GitHub comments unless the user asks after seeing the report.

## 1. Set the scope

- Run `git fetch origin main` and look at `git diff --stat <base>...HEAD`, or the PR's files.
- Find the ticket: the `MR-<n>` in the branch name or PR title. Fetch the issue and keep its "🏁 Done when" list.
- If the diff is empty, say so and stop.

## 2. First pass: the reviewer

Invoke the built-in `code-review` skill on the same scope at the chosen effort level, without `--fix` or `--comment`. Keep its findings as a list.

If `code-review` is not available in this session, do one careful correctness pass yourself and use that list instead.

## 3. Second pass: the skeptic

Launch the `skeptic-reviewer` agent with:
- the scope (base ref or PR number),
- the ticket number and its "Done when" list,
- the first-pass findings, numbered.

## 4. Merge and report

Reply with one report:

1. **Verdict**: the skeptic's SHIP / FIX FIRST / NEEDS DISCUSSION.
2. **Fix before PR**: confirmed reviewer findings plus new blocker and major findings. Each with file:line, the problem, and the failure scenario.
3. **Worth a look**: UNSURE items and minor findings.
4. **Dropped**: rejected findings, one line each with the reason.
5. **Ticket check**: the "Done when" checklist.

Then ask whether to fix the "Fix before PR" items.
