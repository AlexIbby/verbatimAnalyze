
# Requirements Pack (v2) – Survey Feedback Categorizer

## 1  Project Overview  

**Goal** A Flask SPA that digests an uploaded survey file, helps the user craft 5–6 comment categories, auto‑classifies every verbatim, and returns:
- a **clean CSV** (original rows + `Comment Category` column)  
- a **concise on‑screen report** (counts & sample quotes)  
- an optional **PDF download** of that report  

### Key additions vs v1

| Area | Change |
|------|--------|
| **Input formats** | Accept legacy **`.xls`** as well as `.xlsx`. Pandas can handle both once the `xlrd` (≤ 1.2) dependency is added; fall back to `openpyxl` for modern workbooks. |
| **IRM / sensitivity labels** | The sample is IRM‑labelled; we ignore those XML parts—the libraries strip them automatically once the sheet loads. |
| **Header detection** | Extra guard: if the exact header list (“How can we improve this service”, etc.) is **not** found, drop to a three‑step strategy: ① look for any column whose average cell length > 25 chars, ② look for keywords *improve/service/comment*, ③ ask GPT‑4o. |
| **Manual override UI** | Add a **dropdown** that lets the user manually select the verbatim column if auto‑detect guesses wrong. |
| **Output formats** | In addition to CSV + PDF, expose a **JSON summary endpoint** (`/summary/<id>.json`) so downstream tools can reuse the numbers. |

---

## 2  User Stories (updated)

U2 and U6 now mention “legacy Excel” and “manual column picker”. All other stories remain unchanged.

---

## 3  Functional Requirements (delta only)

### 3.1 File Handling  

* **Dependencies**  
  ```bash
  pip install pandas openpyxl==3.1.2 xlrd==1.2.0
  ```
* **`POST /upload`**  
  * Detect extension; choose engine accordingly.  
  * If engine fails because of IRM, return  
    ```json
    {"error":"IRM‑protected. Please remove protection or supply a non‑protected copy."}
    ```

### 3.2 Header / Verbatim Column Detection  

```python
def detect_verbatim_col(df):
    # 1. strict match
    strict = [c for c in df.columns if c.strip().lower() == "how can we improve this service"]
    if strict:
        return strict[0], True

    # 2. heuristic: long free‑text
    long_cols = [c for c in df.columns if df[c].astype(str).str.len().mean() > 25]
    keyword_cols = [c for c in df.columns if re.search(r"(improve|comment|feedback|verbatim)", c, re.I)]
    candidates = long_cols or keyword_cols
    if len(candidates) == 1:
        return candidates[0], False

    # 3. LLM fallback
    col = llm_pick_verbatim(df.head(200))
    return col, False
```

* Front‑end shows detection result with a ✓ or ⚠ and a dropdown for override.

### 3.6 Outputs  

* **`/summary/<id>.json`** returns  
  ```json
  {
    "total_rows": 812,
    "categories": [
      {"title":"Wait Times","count":294},
      ...
    ]
  }
  ```

---

## 4  Non‑Functional Requirements (new points)

| Concern | Requirement |
|---------|-------------|
| **Library footprint** | Capped to three Excel engines. |
| **Max file size** | **5 MB** for legacy `.xls` uploads (they compress poorly). |
| **Temp retention** | Shortened to **30 min** in `/tmp` via `apscheduler`. |

---

## 5  Updated Route Map

```text
/routes
   ├─ upload.py
   ├─ suggest.py
   ├─ classify.py
   ├─ summary.py          # NEW
   └─ download.py
/static/main.js  # now also polls verbatim‑col detection status
```

---

## 6  LLM Prompt Snippets (unchanged from v1)

### 6.1 Category Suggestion
```text
SYSTEM: You are a research assistant.
USER: Here’s a sample of survey comments (--- delimited).  
Generate 5–6 *distinct* categories (≤4 characters each) that cover all feedback.  
Return JSON list [{"title":"", "description":""}].  
---
{sample_comments}
```

### 6.2 Row Classification
```text
SYSTEM: You label comments.
RULES:
1. Choose ONE of the following categories exactly: {category_titles}.
2. Output only that category title.
USER: {comment_text}
```

---

## 7  Open Items

1. Any other legacy formats (`.csv`, LibreOffice `.ods`) to accept?  
2. Should IRM‑protection errors be surfaced in a dedicated banner?  

---

### Deliverable (for Claude)

> **Claude, implement v2 above**, starting from the existing Flask skeleton.  
> Prioritise robustness of the upload → classify pipeline; front‑end can be minimal but must surface every status event.

---
