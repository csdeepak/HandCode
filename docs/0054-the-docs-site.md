---
Number:        0054
Title:         The Documentation Site — The Guide, Built Without a Framework
Type:          DECISION
Status:        DRAFT
Created:       2026-10-04
Supersedes:    —
Superseded-by: —
Depends-on:    0050, 0051, 0053
---

# 0054 — The Documentation Site: The Guide, Built Without a Framework

`0051` Stage 4: publish `guide/` to GitHub Pages, so the project has a URL
that is not a repository page.
- **Built and checked.**
- **Not published.** Turning on Pages is a repository setting, and it makes
  the site public, so it is the owner's (§5).

## 1. What is on it

| Page | From |
|---|---|
| Home | `README.md` up to its `# Reference` heading: what it is, the demo, the quickstart, what it protects you from. The reference half stays on GitHub |
| Quickstart, Concepts, GitHub Action, Troubleshooting, FAQ | `guide/` |
| All pages | `guide/README.md` |
| Changelog | `CHANGELOG.md` |

The numbered `docs/` stream is **not** on the site. It is design memory, not
a manual (`guide/README.md` says the same). A `` `docs/0048` `` reference
in the guide becomes a link to that document on GitHub.

## 2. The decision: no site framework

`website/build.py` is 221 lines, comments included. It uses `markdown-it-py` (CommonMark
plus tables), one HTML template, one stylesheet and a 17-line copy-button
script.

**Why not MkDocs.**
- MkDocs 1.x has gone unmaintained. Its announced successor does not run 1.x
  plugins.
- Material for MkDocs, the theme that makes it pleasant, is in maintenance
  mode, and its authors are moving to a new tool.
- Either choice adopts a migration for six pages.
- `markdown-it-py` is already installed, because `rich` depends on it, and is
  maintained.

**What the build does, which a framework would also need configuring for:**
- **Links work in both places.** The pages stay plain Markdown that reads
  correctly on GitHub.
  - `quickstart.md#x` becomes `quickstart.html#x`.
  - The README's absolute GitHub links into `guide/` become site links.
  - Anything else in the repository (`../examples/handcode.yml`, `INDEX.md`)
    becomes a link to it on GitHub.
  - A link that leaves the repository fails the build.
- **GitHub's heading anchors**, including the `-1` suffix for a repeated
  heading. An anchor written for GitHub therefore works on the site.
- **A broken link fails the build**: a missing page or a missing heading.
  The site workflow runs the build, and so does the ordinary test run.
- Light and dark from the reader's system setting.
  - On a phone, the navigation becomes a scrolling row.
  - Wide tables scroll inside the column, not the page.

## 3. Publishing, only when the owner says so

`.github/workflows/site.yml`:

| Job | Runs | Does |
|---|---|---|
| `build` | every push to `main` and every PR touching the guide | build, link check, upload the Pages artifact |
| `pages-on` | `main` only | asks the API whether Pages deploys from Actions; if not, a notice and `on=false` |
| `deploy` | only when `on=true` | `actions/deploy-pages` into the `github-pages` environment |

The check is a job of its own on purpose. A job that names an environment
**creates** it when it starts, even if all its steps are skipped. So the
workflow never creates `github-pages` before the owner turns Pages on, and
turning it on is the single act that publishes.

## 4. Evidence

- **`tests/test_site.py`, 8 tests.**
  - Every `guide/*.md` is on the site, so a new page cannot be forgotten.
  - Every link between built pages resolves, anchors included.
  - No site link still points at a `.md` file.
  - The README's guide links stay on the site.
  - Other repository files link to GitHub, and a link leaving the
    repository is refused.
  - GitHub's slugs, repeats included.
  - A broken anchor or a missing page fails `check`.
  - `docs/NNNN` becomes a link.
- **Looked at in a browser**, served over HTTP from a local build:
  - the home page and a table-heavy page at desktop width;
  - phone width (375 px), with no horizontal scroll;
  - the deep link `quickstart.html#6-run-it-in-a-container-...` lands at the
    heading, just under the sticky header;
  - all 10 code blocks on the quickstart have a copy button.
- **On GitHub** (`site.yml`, its first run on `0b7599c`):
  - `build` printed *"built 8 pages into _site; every internal link
    resolves"*;
  - `pages-on` printed the notice *"GitHub Pages is not set to deploy from
    Actions ... nothing was published"*;
  - `deploy` was skipped;
  - afterwards the repository's environment list was still empty, so no
    `github-pages` environment was created.

## 5. For the owner

To publish, go to **Settings > Pages > Build and deployment > Source: GitHub
Actions**. Then re-run the `site` workflow, or push to `guide/`.
- The site goes to `https://csdeepak.github.io/HandCode/` and is **public**.
- After that, every change to the guide that reaches `main` is published.

Until then nothing is published, and the `site` workflow's notice says why.
