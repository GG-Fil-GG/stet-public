# Stage 1 Specs

This directory holds per-milestone specs and reports for [Stage 1](../stage1_implementation_plan.md).

## Naming convention

| File | Purpose | Created by | Reviewed by |
|------|---------|------------|-------------|
| `stage1_M{N}_spec.md` | What will be built in milestone N | AI, before implementation | Project owner — must approve before coding |
| `stage1_M{N}_report.md` | What was actually built | AI, after implementation | Project owner — approves before next milestone |

`{N}` is the milestone number (0–9) from the implementation plan.

## Spec template

Every spec must cover:

1. **Goal** — one sentence restating the milestone's purpose.
2. **Files to create or modify** — exact paths.
3. **Public API surface** — function signatures, route paths, JSON shapes, config keys (anything other code or future milestones will depend on).
4. **Tests to write** — test file paths and brief case list.
5. **Out of scope for this milestone** — explicit list of things this spec does *not* cover.
6. **Open questions** — anything ambiguous that needs project-owner input before coding. If non-empty, the AI must stop and wait for answers before proceeding.

Specs should be short (half a page to one page is typical). If a spec is growing long, the milestone is probably too large and should be split.

## Report template

Every report must cover:

1. **What was done** — summary, with links to commits.
2. **Files touched** — list of created/modified/deleted files.
3. **Deviations from spec** — anything that differs from the approved spec, with reason. Empty list is the ideal.
4. **New names added to the glossary** — link to entries added in [`stage1_glossary.md`](../stage1_glossary.md).
5. **Decisions made mid-implementation** — link to entries added in [`stage1_decision_log.md`](../stage1_decision_log.md).
6. **Test results** — pass/fail counts, warning count, any skipped tests.
7. **What to watch in the next milestone** — known issues, follow-up items, or context the next session should know.

Reports should be short too. If something complex needs longer discussion, it probably belongs in the decision log.

## Workflow recap

```
User: "Implement Milestone N."
  ↓
AI: writes spec → "Spec ready, review and approve."
  ↓
User: approves or asks for changes.
  ↓
AI: implements per approved spec → runs tests → writes report → commits → pushes.
  ↓
User: reads report, says "OK proceed" or "Hold."
```

See the [implementation workflow](../stage1_implementation_plan.md#implementation-workflow) section of the plan for the full description.
