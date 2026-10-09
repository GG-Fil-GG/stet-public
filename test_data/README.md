# Test data layout

This directory holds Word documents and other files used for manual and automated testing.

## `synthetic/` (committed)

Purpose-built synthetic test files tracked in git. CI and fresh clones rely on these.

Add new **synthetic** fixtures here (e.g. minimal `.docx`, `.pdf`, `.xlsx` for unit tests).

## `local/` (gitignored)

Real manuscripts and client documents for local-only testing. Never committed.

Add new **real** test documents here.
