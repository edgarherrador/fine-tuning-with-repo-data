# Project Context: Fine-Tuning Dataset for ProjectSight

## Objective

Build a fine-tuning dataset for **Qwen3-35B-A22B** (open-source base model) focused on the
**ProjectSight** (Trimble Construction) codebase.

**Root problem:** ProjectSight is an enterprise system with ~1,500+ developers that uses
non-standard patterns (.NET/C# backend + Angular frontend following an MVC/Razor-style pattern
that current LLMs do not know). Off-the-shelf models cannot reliably help with this codebase
because they are unaware of the project's conventions.

**Solution:** Instead of feeding static code, reproduce the real development process using
Git history and Pull Requests as a supervised fine-tuning dataset.

---

## Approach: PR-Based Fine-Tuning

### Why PRs instead of static code

- **Approved PRs** already encode the project's implicit business rules
- PR descriptions document the reasoning behind each change
- Review comments are **explicit corrections** with very high training signal
- PRs with 8–20 review comments are the most valuable (contain the team's implicit reasoning)

### Training example structure

```json
{
  "messages": [
    {
      "role": "system",
      "content": "You are an expert in the ProjectSight codebase (Trimble Construction)..."
    },
    {
      "role": "user",
      "content": "# PR #1234: Fix site export\n[PR description]\n[reviewer feedback]\n[code BEFORE the change]"
    },
    {
      "role": "assistant",
      "content": "```diff\n[exact diff that implements the change]\n```"
    }
  ]
}
```

---

## Repository & Credentials

| Field | Value |
|-------|-------|
| GitHub repository | `Trimble-Construction/projectsight` (private) |
| Local clone path | `C:\Users\eherrad\source\repos\projectsight` |
| GitHub PAT | `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` |
| Org enforcement | SAML SSO — token must be explicitly authorized |
| Target model | Qwen3-35B-A22B |

### Token blocker (SAML SSO)

The `Trimble-Construction` org enforces SAML SSO. The PAT needs explicit authorization
before any API calls will work:

1. Go to `https://github.com/settings/tokens`
2. Find the token → **Configure SSO** → **Authorize** for `Trimble-Construction`

You will get a 403 with a SAML message in the body if this step is skipped.
The script `01_fetch_prs.py` detects this and prints clear instructions.

---

## Project Stack (ProjectSight)

| Layer | Technology | Key convention |
|-------|-----------|----------------|
| Backend | .NET / C# / ASP.NET MVC | No ORM — only `IDBHelper` + named stored procedures |
| Database | SQL Server | No inline SQL — every DB operation via named stored procedures |
| Frontend | Angular | No `HttpClient` — use `RxJS ajax()` via `APIBase / APIFactory` |
| Subscriptions | Angular | `DestroyRef` + `subscribeTo()` — no manual `Subscription` arrays |
| Styles | CSS | No hardcoded hex colors — only CSS variables from `Default.css` |
| API codegen | C# | Adding/removing `[UseInAPI]` triggers `APIClientComponentGenerator` on build |
| SQL delta | SQL | `delta_procs.sql` is auto-generated from `base_procs.sql` — never edit directly |

---

## Phase Plan

### Phase 1 — PoC (current)
- **Scope:** 46 open PRs
- **Goal:** Validate the pipeline end-to-end
- **Config:** `PR_STATE = "open"`, `PR_LIMIT = 200`

### Phase 2 — Full dataset
- **Scope:** 10,000+ merged PRs
- **Config:** `PR_STATE = "closed"`, `PR_LIMIT = None`
- **Estimate:** ~2–4 hours to download, ~10,000–18,000 clean examples

---

## Pipeline — Scripts

All scripts live in `C:\Users\eherrad\source\repos\projectsight\scripts\dataset\`.

### File inventory

| File | Role |
|------|------|
| `config.py` | Central config: token, paths, quality thresholds, system prompt |
| `01_fetch_prs.py` | GitHub API → `output/raw/pr_*.json` (paginated, auto rate-limit retry) |
| `02_build_examples.py` | Crosses API data with local git, builds BEFORE/AFTER, computes quality score |
| `03_generate_dataset.py` | Final JSONL output + train/eval split + token statistics |
| `requirements.txt` | `requests`, `tqdm`, `tiktoken` |
| `README.md` | Usage instructions |
| `CONTEXT.md` | This file |

### How to run

```bash
cd C:\Users\eherrad\source\repos\projectsight\scripts\dataset

pip install -r requirements.txt

python 01_fetch_prs.py        # ~5–10 min for 46 PRs
python 02_build_examples.py   # ~2–5 min
python 03_generate_dataset.py
```

### Output structure

```
output/
  raw/
    _index.json          # Index of all downloaded PRs
    pr_NNNN.json         # Raw JSON per PR (metadata + diff + reviews + comments)
  examples/
    pr_NNNN.json         # Processed example with quality score
  dataset.jsonl          # Full dataset
  dataset_train.jsonl    # 90% for training
  dataset_eval.jsonl     # 10% for evaluation
  stats.json             # Token stats, score distribution, PR type breakdown
```

---

## What Script 01 Extracts (per PR)

- Metadata: title, description, labels, author, dates, base/head branch, SHAs
- List of changed files (with per-file patch)
- Reviews: state (APPROVED / CHANGES_REQUESTED), body, author, date
- Review comments: inline comments tied to specific lines of code
- Issue comments: general PR thread discussion
- Full PR diff

---

## Quality Scoring (Script 02)

Only examples with **score ≥ 40 / 100** are included in the dataset.

| Criterion | Points |
|-----------|--------|
| Description ≥ 200 chars | +30 |
| Description ≥ 80 chars | +15 |
| ≥ 2 reviewers approved | +20 |
| ≥ 1 reviewer approved | +10 |
| Has inline review comments | +20 |
| Has PR thread comments | +10 |
| Draft PR | −20 |
| Placeholder description ("fix", "wip", "update") | −15 |
| Diff < 5 lines | discarded outright |
| Diff > 800 lines | truncated (not discarded) |
| Example > 28,000 tokens | discarded (exceeds model context) |

---

## Model System Prompt

The system prompt injects the project's critical conventions into every training example:

```
You are an expert in the ProjectSight codebase (Trimble Construction).
The project uses .NET/C# on the backend with ASP.NET MVC/Razor and Angular on the frontend.

Critical project rules (never violate):
- Backend: Never use ORM (Entity Framework, Dapper). Only IDBHelper with named stored procedures.
- Backend: All DB operations go through named stored procedures. No inline SQL ever.
- Frontend: Never use Angular HttpClient. Use RxJS ajax() via APIBase / APIFactory.
- Frontend: Use DestroyRef + subscribeTo() for subscriptions — NO manual Subscription arrays.
- Frontend: Never hardcode hex color values. Use CSS variables from Default.css.
- Do not edit delta_procs.sql directly — it is auto-generated from base_procs.sql.
- Adding or removing [UseInAPI] on a property triggers APIClientComponentGenerator on build.
```

---

## Design Decisions

| Decision | Rationale |
|----------|-----------|
| JSONL messages format | Compatible with Qwen3, OpenAI fine-tuning API, and Unsloth without conversion |
| BEFORE state via `git show base_sha:file` | Uses local repo — faster and more accurate than the API |
| Fallback to patch when SHA missing locally | Preserves the example rather than discarding it |
| Truncate large diffs instead of discarding | Keeps training signal; truncation is explicit and labeled |
| Token estimation with tiktoken (cl100k_base) | Good approximation for Qwen3; no model load required |
| Incremental downloads | Skips already-downloaded PRs on restart — safe to interrupt |
| Score-based filtering | Automated quality gate; avoids training on bot PRs, cherry-picks, WIP branches |

---

## Next Steps

- [ ] Authorize the PAT for SAML SSO on Trimble-Construction
- [ ] Run Phase 1 pipeline against the 46 open PRs
- [ ] Review `output/stats.json` — validate token distribution and score spread
- [ ] Tune `MIN_SCORE` and `MAX_DIFF_LINES` in `config.py` if needed
- [ ] Fine-tune Qwen3-35B-A22B with Unsloth on the generated dataset
- [ ] Phase 2: scale to 10,000 merged PRs with `PR_STATE = "closed"`, `PR_LIMIT = None`
