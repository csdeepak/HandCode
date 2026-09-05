# Repository Conventions

## The numbered document stream

Every durable artifact — architecture, research result, decision, guideline,
experiment report — lives in `docs/` as a numbered Markdown file:

```
docs/NNNN-short-kebab-slug.md
```

**Rules**

1. `NNNN` is a zero-padded 4-digit integer, strictly increasing, never reused,
   never renumbered. **The highest number is always the newest document.**
2. Numbers are allocated across *all* document types in one shared sequence.
   There is no per-category numbering. This is deliberate: one glance at the
   highest number tells you where the project is.
3. A document is never deleted. If it becomes wrong, mark it `SUPERSEDED` in
   its front-matter, add a `Superseded-by:` pointer, and write a new one.
4. A document is never edited in place once its status is `ACCEPTED`, except
   to add a supersession notice. Corrections go in a new numbered document.
   Documents in `DRAFT` or `LIVING` status may be edited freely.
5. Every new document must be added to `INDEX.md` in the same commit.

## Front-matter

Every numbered document starts with this block:

```markdown
---
Number:        0008
Title:         System Architecture v1
Type:          ARCHITECTURE | RESEARCH | DECISION | GUIDELINE | EXPERIMENT | REGISTER
Status:        DRAFT | ACCEPTED | LIVING | SUPERSEDED
Created:       YYYY-MM-DD
Supersedes:    0003 (or —)
Superseded-by: —
Depends-on:    0006, 0007
---
```

## Document types

| Type | Purpose | Typical status |
|---|---|---|
| `ARCHITECTURE` | How the system is structured and why | ACCEPTED, later SUPERSEDED |
| `RESEARCH` | Raw output of a research phase, preserved verbatim | ACCEPTED (frozen) |
| `DECISION` | A choice made, its alternatives, and its consequences | ACCEPTED |
| `GUIDELINE` | A rule we hold ourselves to | LIVING |
| `EXPERIMENT` | A run, its method, its result, what it falsified | ACCEPTED (frozen) |
| `REGISTER` | A continuously updated table (open questions, accounts) | LIVING |

**Research documents are frozen on arrival.** Never edit a research result to
match later understanding — that destroys the audit trail. Write a DECISION
document that reinterprets it instead.

## Directories

```
docs/            The numbered stream. The project's memory.
research/raw/    Unprocessed source material (PDFs, exports, transcripts).
experiments/     Scripts, configs, and logs for reproducible experiments.
issues/          Working notes on open problems. Promoted to docs/ when resolved.
```

Only `docs/` is numbered. Everything else is supporting material.

## Commit messages

```
docs(NNNN): <what changed>
```

One document per commit wherever practical, so the git history and the
document stream stay legible together.

## Guideline: research provenance

Any claim imported from a research phase carries its confidence tier from the
source document — VERIFIED / INFERRED / UNKNOWN. When an architecture document
depends on a claim, cite it as `0006:V1` (document number, claim id). If a
claim is later falsified by an experiment, every document citing it must be
reviewed. This is why claim ids matter.
