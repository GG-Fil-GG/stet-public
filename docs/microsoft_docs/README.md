# Microsoft / ECMA Reference Material

This folder holds Microsoft and ECMA reference documentation for the Office Open XML formats (DOCX, XLSX, PPTX). It is **external reference material**, not project documentation, and was saved here largely as downloaded — file names and folder layout reflect the upstream sources.

## Contents

| Item | What it is |
|------|------------|
| `[MS-DOCX].pdf` | Microsoft Open Specifications: DOCX File Format (MS-DOCX) |
| `[MS-OE376].pdf` | Microsoft Open Specifications: Office Implementation Information for ECMA-376 Standards Support (MS-OE376) |
| `[MS-OI29500].pdf` | Microsoft Open Specifications: Office Implementation Information for ISO/IEC 29500 Standards Support (MS-OI29500) |
| `[MS-OREACTXML].pdf` | Microsoft Open Specifications: Office Reactive XML File Format (MS-OREACTXML) |
| `[MS-OTASKXML].pdf` | Microsoft Open Specifications: Office Task XML File Format (MS-OTASKXML) |
| `ecma/ECMA-376-4_5th_edition_december_2016/` | ECMA-376 5th edition schemas — XSD and RELAX NG definitions for WordprocessingML, SpreadsheetML, PresentationML, and DrawingML |

## Purpose

Useful for offline lookup when reasoning about DOCX/XLSX/PPTX behavior — particularly around comments, tracked changes, threading, and formatting. **Nothing in the project's runtime depends on these files.**

## Why these files are not in git

These vendor documents total ~125 MB and never change between project commits. Tracking them in git inflates clone size and history without benefit. Only this README is committed; the actual PDFs and schemas are gitignored (`docs/microsoft_docs/*` with a `!README.md` exception). They live on developers' local machines and are downloaded once from the upstream sources.

## How to populate this folder

To get the reference material on a fresh clone, download the following into this folder:

- **Microsoft Open Specifications** (PDFs): <https://learn.microsoft.com/en-us/openspecs/office_standards/>
  - `[MS-DOCX].pdf`, `[MS-OE376].pdf`, `[MS-OI29500].pdf`, `[MS-OREACTXML].pdf`, `[MS-OTASKXML].pdf`
- **ECMA-376** (Office Open XML schemas): <https://www.ecma-international.org/publications-and-standards/standards/ecma-376/>
  - Place under `ecma/` (matches the structure expected by the project's historical reference layout).

Once downloaded, files are visible locally but git will ignore them.

## Updating

These are vendor documents — do not edit. To refresh, re-download the latest from the sources above.
