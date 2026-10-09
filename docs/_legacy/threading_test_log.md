# Threading Test Log

This log tracks all threading tests performed to validate `word_threading_specification.md`.

## Test Configuration Variables

| Variable | Description |
|----------|-------------|
| **Reply ID** | The `w:id` assigned to the new reply comment |
| **ID Strategy** | "sequential" (max+1), "random", or "renumbered" (Word-style) |
| **`<w:sz>` elements** | Whether sizing elements are added to the comment reference run |
| **`proofErr` handling** | Whether proofErr elements are removed or left alone |
| **Source document** | Which document the test was based on |

---

## Tests Performed

### Round 1: spec_validation (2026-02-16)

These tests used `spec_validation_test.py`.

| File | Source | Reply ID | ID Strategy | `<w:sz>` | proofErr | Threaded? | Notes |
|------|--------|----------|-------------|----------|----------|-----------|-------|
| test_baseline.docx | test.docx | 4 | sequential | Yes | Left alone | **No** | sz on reply only, proofErr in range |
| test_no_sz.docx | test.docx | 4 | sequential | No | Left alone | **?** | Need to re-verify |
| test_sequential_id.docx | test.docx | 4 | sequential | No | Left alone | **?** | Need to re-verify |
| dummy_baseline.docx | dummy.docx | 5 | sequential | Yes | Left alone | **?** | Need to re-verify |
| dummy_no_sz.docx | dummy.docx | 5 | sequential | No | Left alone | **Yes** | User reported worked |
| dummy_minimal.docx | dummy.docx | 5 | sequential | No | Left alone | **?** | Need to re-verify |

### Round 2: validated_threading (2026-02-16)

These tests used `validated_threading_test.py`.

| File | Source | Reply ID | ID Strategy | `<w:sz>` | proofErr | Threaded? | Notes |
|------|--------|----------|-------------|----------|----------|-----------|-------|
| test_with_reply.docx | test.docx | 4 | sequential | No | Left alone | **No** | User reported failed |
| dummy_with_reply.docx | dummy.docx | 5 | sequential | No | Left alone | **No** | User reported failed |
| reply_test_with_reply.docx | reply_test.docx | ? | sequential | No | Left alone | **No** | User reported failed |

---

## Key Observations

### Contradiction Found
- `spec_validation/dummy_no_sz.docx` was reported as **working**
- `validated_threading/dummy_with_reply.docx` was reported as **not working**
- These files are **structurally identical** (same comment ID=5, same threading links, same anchor order)
- Only differences: author name, timestamps, random auxiliary IDs (paraId, textId, rsidR)

### Possible Explanations
1. **Testing error** - one of the results may have been recorded incorrectly
2. **Word version/cache issue** - Word may behave differently between sessions
3. **Something else** - an unknown factor we haven't identified

---

### Round 3: random_id_test (2026-02-16)

These tests use `random_id_test.py` with truly RANDOM IDs.

| File | Source | Existing IDs | Reply ID | `<w:sz>` | Threaded? | Notes |
|------|--------|--------------|----------|----------|-----------|-------|
| test_random_id.docx | test.docx | 0,1,2,3 | **1924** | No | **Yes** | |
| dummy_random_id.docx | dummy.docx | 0,2,4 | **509** | No | **Yes** | |
| reply_test_random_id.docx | reply_test.docx | 1-11 | **4606** | No | **Yes** | Appears as 3rd reply, order preserved |

---

## Tests NOT Yet Performed

| Test Description | Why It Might Matter |
|------------------|---------------------|
| Word-style renumbering | Assign reply ID = parent+1, shift all subsequent IDs |
| Different base documents | Test on documents without track changes |
| Multiple replies to same comment | Test threading chain behavior |

---

## Next Steps

1. **Re-verify spec_validation results** - Open both `dummy_no_sz.docx` and the new `dummy_with_reply.docx` side-by-side to confirm behavior
2. **Test random IDs** - Generate a file with a truly random reply ID (e.g., 999)
3. **Document exact Word version** being used for testing

---

## Word's Native Behavior (Reference)

When Word adds a reply to comment ID=0 in dummy.docx:
- Reply gets ID=**1** (not 5)
- Track change ID 1 → becomes **2**
- Comment ID 2 → becomes **3** 
- Track change ID 3 → becomes **4**
- Comment ID 4 → becomes **5**

This "insert and shift" approach differs from our "append" approach.
