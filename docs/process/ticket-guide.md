# Ticket guide

How we write tickets, titles, branches and labels. Copy this for every sprint. Tickets are dev communication, so they are in English. Anything a customer sees stays in Mexican Spanish.

## 1. The indicator: `MR-<issue number>`

`MR` is short for MermIA. The number is the GitHub issue number and is always present.

| Thing | Format | Example |
|---|---|---|
| Issue title | `MR-<n> <Title>` | `MR-12 Build the Productos vendidos parser` |
| Branch | `MR-<n>-<short-slug>` | `MR-12-productos-vendidos-parser` |
| Commit | `MR-<n>: <what changed>` | `MR-12: parse Productos vendidos xlsx` |
| PR title | same as the issue title | `MR-12 Build the Productos vendidos parser` |
| PR body | `Closes #<n>` | `Closes #12` |

The number is only known after GitHub creates the issue. So: create the issue, then rename its title to add `MR-<n>`.

Branch rules (from `08-mvp-4-week-plan.md`): short branches (1 day), PR to `main`, the other dev reviews the same day, PRs under about 400 lines, squash merge.

## 2. Labels

Every ticket gets exactly one of each group.

| Group | Labels |
|---|---|
| Sprint | `sprint-1`, `sprint-2`, ... |
| Owner | `dev-a` (data), `dev-b` (conversation), `both`, `founders` |
| Week | `week-1`, `week-2`, `week-3`, `week-4` |

## 3. Ticket body: write it for a tired brain

Write it as if talking to someone with ADHD or a kid. Short sentences. One idea per line. Say what to do, not what to think about. No jargon without a plain explanation next to it.

Use these sections, in this order:

```markdown
## 🎯 In one sentence
One sentence. What exists after this ticket that did not exist before.

## 🧩 Why this matters
2-3 short lines. What breaks or waits if we skip it. A small analogy is welcome.

## ✅ Do this
1. One small action per step. Start each with a verb.
2. Name the exact file, command or screen when you know it.
3. Max 7 steps. If you need more, split the ticket.

## 🏁 Done when
- [ ] A thing you can see or run. Not "works well".
- [ ] Include the exact check (command, message, screen).

## 🔗 Connections
- Needs first: MR-x (name)
- Unlocks: MR-y (name)

## ⏱ Time and owner
- Owner: Dev A / Dev B / Both / Founders
- Time: concrete (e.g. "about 3 hours"), never "a bit"
- When: week and day from the plan

## 🌿 Branch
`MR-<n>-<short-slug>`
```

## 4. Rules for good tickets

1. **One ticket = one owner = one to two days max.** Bigger means split.
2. **"Done when" must be checkable** by someone who did not write the code.
3. **Say what is NOT in the ticket** if people might assume it is (one line under "In one sentence").
4. **Time is a number.** "About 2 hours", "about 1 day".
5. **Dependencies are written down** with ticket numbers, so nobody waits in silence.
6. **Contracts first.** Changes to `packages/contracts` need both devs to approve.
7. **Customer-facing text is Spanish (es-MX).** The ticket can say so, but the ticket itself is English.

## 5. Sprint flow

1. Copy the previous sprint's ticket list, drop what is done, add new work.
2. Create the labels for the new sprint.
3. Create issues, then rename titles with `MR-<n>`.
4. Add them to the GitHub Project and set the Sprint field.
5. At the sprint review, move leftovers to the next sprint label.

The issue template lives in `.github/ISSUE_TEMPLATE/ticket.md`.
