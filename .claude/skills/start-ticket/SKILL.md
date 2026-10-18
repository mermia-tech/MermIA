---
name: start-ticket
description: Start work on a MermIA ticket (MR-<n> GitHub issue): read it, check its dependencies, create its branch and write a plan before any code.
argument-hint: "MR-<n> | <n>"
disable-model-invocation: true
---

# start-ticket

Ticket: `$ARGUMENTS` (accept `MR-12`, `mr-12` or `12`; the number is the GitHub issue number in `mermia-tech/MermIA`).

Conventions live in `docs/process/ticket-guide.md`. Follow them.

## 1. Read the ticket

- Fetch the issue and its comments. Use the GitHub MCP tools (`issue_read`) when available, otherwise `gh issue view <n> --comments`.
- If it does not exist or is closed, stop and say so.

## 2. Check what it needs first

- Read the "🔗 Connections → Needs first" line.
- For each `MR-x` listed, check whether that issue is closed (or its PR is merged).
- If any is still open, list them and ask whether to continue against mocks or fixtures (the plan allows this), or to stop.

## 3. Read the context

- Read every doc, section and file the ticket names (for example `docs/kickoff/09-architecture.md` §2.1).
- Look at code already on `main` that this ticket extends. Do not re-read the whole kickoff folder.

## 4. Create the branch

- Branch name: the one in the ticket's "🌿 Branch" section (`MR-<n>-<short-slug>`).
- Branch from an up-to-date `main`: `git fetch origin main && git checkout -b <branch> origin/main`.
- If the branch already exists, check it out instead and say so.
- If the session instructions pin you to a different branch, use that one and tell the user.

## 5. Write the plan, then stop

Reply with:

1. **Goal**: the "🎯 In one sentence" line.
2. **Steps**: each "✅ Do this" step, with the files you expect to create or change.
3. **How we prove it is done**: each "🏁 Done when" item, mapped to the exact test, command or check.
4. **Contract impact**: does this touch `packages/contracts`? If yes, both devs must approve the PR.
5. **Risks and questions**: anything unclear in the ticket, or that conflicts with the docs.
6. **Size**: if the work looks bigger than about 400 lines or 2 days, propose a split.

Wait for the user's go-ahead before writing code. Commits use `MR-<n>: <what changed>`.
