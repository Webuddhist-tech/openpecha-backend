# Text Operations API Specification

This document specifies the operation-based text editing API for the OpenPecha backend, including the endpoint design, span adjustment algorithms, and edge case handling.

---

## Overview

The text operations API allows clients to modify edition content through atomic operations (insert, delete, replace) while automatically adjusting all associated span-based annotations.

### API Endpoint

```
PATCH /v2/editions/{edition_id}/content
```

### Operations

| Operation | Description | Required Fields |
|-----------|-------------|-----------------|
| **INSERT** | Insert text at a position | `position`, `text` |
| **DELETE** | Delete text in a range | `start`, `end` |
| **REPLACE** | Replace text in a range | `start`, `end`, `text` |

---

## Request Format

### Insert

```json
{
    "type": "insert",
    "position": 15,
    "text": "new text"
}
```

### Delete

```json
{
    "type": "delete",
    "start": 10,
    "end": 20
}
```

### Replace

```json
{
    "type": "replace",
    "start": 10,
    "end": 20,
    "text": "replacement text"
}
```

---

## Entity Types and Span Behavior

### Categories

| Entity Type | Category | Relationship Path |
|-------------|----------|-------------------|
| Segment | **Continuous** | `Segment → Segmentation → Manifestation` |
| Page | **Continuous** | `Page → Volume → Pagination → Manifestation` |
| Note | Annotation | `Note → Manifestation` |
| Mark | Annotation | `Mark → Manifestation` |
| BibliographicMetadata | Annotation | `BibMeta → Manifestation` |
| Attribute | Annotation | `Attribute → Manifestation` |
| TableOfContentsSection | Annotation | `TableOfContentsSection → TableOfContents → Manifestation` |

### Behavior Summary

| Operation | Continuous (Segment/Page) | Annotation (Note/Mark/BibMeta/Attribute/TableOfContentsSection) |
|-----------|---------------------------|------------------------------------------------|
| Insert at start boundary | **Shift**† | **Shift** |
| Insert at end boundary | **Expand** | **Unchanged** |
| Insert inside | **Expand** | **Expand** |
| Delete encompassed | **Delete** | **Delete** |
| Replace exact match | **Preserve** (resize) | **Delete** |
| Replace encompasses | Keep first, delete others | **Delete** |

†Special case: Insert at position 0 on first span (start=0) **expands** instead of shifts.

---

## DELETE Behavior Matrix

| Overlap Type | Condition | Result |
|--------------|-----------|--------|
| **Before** | `del_end <= start` | Shift left by `del_len` |
| **After** | `del_start >= end` | Unchanged |
| **Fully encompasses** | `del_start <= start && del_end >= end` | **Delete** |
| **Overlaps start** | `del_start <= start < del_end < end` | `(del_start, end - del_len)` |
| **Overlaps end** | `start < del_start < end <= del_end` | `(start, del_start)` |
| **Inside span** | `start < del_start && del_end < end` | `(start, end - del_len)` |

---

## REPLACE Behavior Matrix

| Overlap Type | Continuous | Annotation |
|--------------|------------|------------|
| **Before** (`rep_end <= start`) | Shift by delta | Shift by delta |
| **After** (`rep_start >= end`) | Unchanged | Unchanged |
| **Exact match** | Preserve (resize) | **Delete** |
| **Fully encompasses** | Keep first, delete others | **Delete** |
| **Overlaps start** | Trim start + shift | Trim start + shift |
| **Overlaps end** | Trim end | Trim end |
| **Inside span** | Adjust by delta | Adjust by delta |

---

## Validation Rules

| Operation | Rule | Error |
|-----------|------|-------|
| INSERT | `position >= 0` | 400 Bad Request |
| INSERT | `position <= text_length` | 400 Bad Request |
| INSERT | `text` non-empty | 400 Bad Request |
| DELETE | `start >= 0` | 400 Bad Request |
| DELETE | `end <= text_length` | 400 Bad Request |
| DELETE | `start < end` | 400 Bad Request |
| REPLACE | Same as DELETE | 400 Bad Request |
| REPLACE | `text` required and non-empty | 400 Bad Request |

**Note**: Use DELETE for removing text. REPLACE with empty text is rejected.

---

## Edge Cases

### 1. Insert at Position 0

**Problem**: If first segment starts at 0 and we insert at position 0, shifting would leave new content uncovered.

**Solution**: Special case - if `insert_pos == 0` and `start == 0`, expand instead of shift.

```
Before: S1 [0, 10), S2 [10, 20)
Insert "Hello " at position 0
After:  S1 [0, 16), S2 [16, 26)  ✓ (S1 expanded to cover new content)
```

### 2. Insert at Segment Boundary

**Problem**: Insert at exact boundary between adjacent segments could cause overlap.

**Solution**: Insert at `position == start` shifts the segment.

```
Before: S1 [0, 10), S2 [10, 20)
Insert "XX" at position 10
After:  S1 [0, 12), S2 [12, 22)  ✓ (S1 expanded at end, S2 shifted)
```

### 3. Replace Encompasses Multiple Segments

**Problem**: Multiple segments would all adjust to the same span, causing overlap.

**Solution**: Keep first encompassed segment, delete others.

```
Before: S1 [0, 10), S2 [10, 20), S3 [20, 30)
Replace [5, 25) with "XXX"
After:  S1 [0, 5), S2 [5, 8), S3 [8, 13)  ✓ (S2 kept, others adjusted)
```

### 4. Replace with Empty String

**Problem**: Creates invalid span `[n, n)` where `start == end`.

**Solution**: Reject replace with empty text. Use DELETE operation instead.

### 5. Delete Creates Gap in Segmentation

**Scenario**: Delete exactly matches a segment.

**Result**: Segment is deleted, adjacent segments shift to maintain continuity.

```
Before: S1 [0, 10), S2 [10, 20), S3 [20, 30)
Delete [10, 20)
After:  S1 [0, 10), S3 [10, 20)  ✓ (S2 deleted, S3 shifted)
```

### 6. Multiple Segmentations

Different segmentations on the same edition are adjusted independently.

```
Segmentation A: [0, 20), [20, 40)
Segmentation B: [0, 10), [10, 20), [20, 40)

Replace [5, 15) with "XXX" (delta = -7)

Segmentation A: [0, 13), [13, 33)  ✓
Segmentation B: [0, 8), [8, 13), [13, 33)  ✓
```