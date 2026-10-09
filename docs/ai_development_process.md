# AI-Assisted Development Process

This document describes how Stet is developed using AI coding assistants. It is intended as a working reference for maintaining quality, preventing scope creep, and ensuring robust outcomes across sessions.

---

## Core Principle

**Spec first, code second.** No implementation begins until there is a written specification that has been reviewed and approved. This is the single most important discipline in the process.

---

## The Development Cycle

Every feature or change follows this cycle:

1. **Describe** — The project owner describes what they want in plain language.
2. **Spec** — The AI produces a short specification document covering:
   - What the feature does (user-facing behaviour)
   - What changes to the codebase are needed (files, modules, interfaces)
   - What is explicitly out of scope
   - How it will be tested
3. **Review** — The project owner reviews the spec and approves, pushes back, or asks questions.
4. **Implement** — The AI implements the approved spec, writes tests, and runs the full test suite.
5. **Test** — The project owner tests with real-world documents and reports any issues.
6. **Fix** — The AI investigates and fixes reported issues.
7. **Commit** — Changes are committed with a clear, descriptive message.
8. **Repeat** — Move to the next feature or sub-task.

The critical rule: **never skip from step 1 to step 4.** The spec step (2 + 3) is what keeps the project on track.

---

## Work Units

Large features must be broken into small, atomic pieces. Each piece should be:

- Specifiable in one short document
- Implementable in one session
- Testable independently
- Committable with a clear description

For example, "Add agent loop" is too large. Break it into:

1. Define tool schemas and implement tool functions
2. Implement the agent loop (tool dispatch, multi-step reasoning)
3. Add workspace/project folder support
4. Build the agent chat UI panel
5. Integration testing with a real document

Each gets its own spec, implementation, tests, and commit.

---

## Cursor Rules as Guardrails

Cursor rules (`.cursor/rules/*.mdc`) act as persistent instructions to the AI that survive across sessions. They are the project's "constitution" — constraints that apply even when the project owner forgets to mention them.

Rules should cover:

### Architecture

- All document manipulation must go through the DocumentModel. Never write raw XML outside the serializer.
- All new agent tools must be registered in the tool schema file.
- New dependencies require explicit approval from the project owner.

### Code quality

- All new public functions must have type hints.
- Do not add comments that just narrate what the code does.
- Fix any linter errors introduced by your changes.

### Scope

- Do not refactor existing working code unless the spec explicitly calls for it.
- Do not add features beyond what the current spec describes.
- If you discover a related issue during implementation, report it — do not fix it without approval.

### Testing

- Every new public function must have at least one test.
- Run the full test suite before every commit.
- Integration tests must use real `.docx` files from `test_data/`.

These rules should be added to `.cursor/rules/` as the project evolves.

---

## Testing Strategy

### Automated tests (AI-managed)

- **Unit tests** — Each tool function, each new module, each public method.
- **Integration tests** — Full pipeline: upload a real `.docx`, run the agent, export, verify the output.
- **Regression tests** — Every bug found during real-world testing gets a test case so it never recurs.
- The full test suite runs before every commit. The AI does this automatically.

### Real-world tests (project owner)

- Test with actual medical manuscripts after each feature is complete.
- Maintain a set of reference documents in `test_data/` covering known edge cases (field codes, complex formatting, tables, multi-paragraph comments).
- After each stage, do a manual walkthrough: upload, generate, review, export, open in Word, verify track changes.

The AI can write and run automated tests, but only the project owner can evaluate whether the output works correctly on real documents. The project owner is the quality gate for functional correctness.

---

## Session Management

AI conversations have finite context. To prevent context loss across sessions:

### Persistent artefacts

| Artefact | Location | Purpose |
|----------|----------|---------|
| Roadmap | `docs/agentic_stet_roadmap.md` | Overall direction and stages |
| This document | `docs/ai_development_process.md` | Development process reference |
| Specs | `docs/` (one per feature) | What was planned and approved |
| Cursor rules | `.cursor/rules/` | Architectural constraints |
| Git history | commit messages | What was changed and why |
| Test data | `test_data/` | Reference documents for regression |

### Starting a new session

At the start of each new AI session, provide orientation:

> "Read the roadmap at `docs/agentic_stet_roadmap.md` and the spec at `docs/[current_spec].md`. Here's what I want to work on today: ..."

The AI can then read the relevant docs and `git log` to orient itself quickly.

---

## Project Owner's Role

You do not need to understand every line of code. Your responsibilities are:

1. **Define what you want** — in plain language, as specifically as you can.
2. **Review specs** — does the plan make sense? Does it match your vision?
3. **Approve or reject** — the AI proposes, you decide.
4. **Test with real documents** — you are the domain expert.
5. **Flag problems** — "this doesn't look right" is sufficient; the AI investigates.

What you should not do:

- Review code line-by-line (diminishing returns given your skill level; trust the tests).
- Let the AI proceed without your approval on the spec.
- Skip real-world testing because the automated tests pass.

---

## Artefact Structure

```
docs/
  agentic_stet_roadmap.md              # Overall roadmap
  ai_development_process.md            # This document
  stage1_spec.md                       # Spec for current stage
  stage1_tool_schemas_spec.md          # Sub-task spec
  stage1_agent_loop_spec.md            # Sub-task spec
  ...

.cursor/rules/
  architecture.mdc                     # Architectural constraints
  testing.mdc                          # Testing requirements
  scope.mdc                            # Scope guardrails
  format-toolbar-buttons.mdc           # Existing rule

test_data/
  (reference documents for regression testing)

tests/
  (automated tests, organised by module)
```

---

## Summary

The process is simple and repeating: **describe, spec, review, implement, test, fix, commit.** The spec step is the control point. Cursor rules provide persistent guardrails. Automated tests catch regressions. Real-world testing catches everything else. Small work units keep each cycle manageable and each commit reversible.
