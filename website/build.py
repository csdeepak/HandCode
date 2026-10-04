"""Build the documentation site from the guide. docs/0054.

    python website/build.py                   # -> _site/
    python website/build.py --out DIR

No site framework: markdown-it-py (CommonMark plus tables) and one template.
The pages stay plain Markdown that reads well on GitHub. The build:

  - turns links between pages into links between the site's pages, and links
    to anything else in the repository into links to it on GitHub;
  - gives every heading GitHub's anchor, so a `#section` link works in both
    places;
  - fails on a link to a page or an anchor that does not exist.

It writes only into the output directory.
"""
from __future__ import annotations

import argparse
import html
import posixpath
import re
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
REPO = "https://github.com/csdeepak/HandCode"
BLOB = f"{REPO}/blob/main/"
TREE = f"{REPO}/tree/main/"

#: (source in the repository, page on the site, label in the navigation).
#: The home page is the README up to its "# Reference" heading.
PAGES = [
    ("README.md", "index.html", "Home"),
    ("guide/quickstart.md", "quickstart.html", "Quickstart"),
    ("guide/concepts.md", "concepts.html", "Concepts"),
    ("guide/github-action.md", "github-action.html", "GitHub Action"),
    ("guide/troubleshooting.md", "troubleshooting.html", "Troubleshooting"),
    ("guide/faq.md", "faq.html", "FAQ"),
    ("guide/README.md", "guide.html", "All pages"),
    ("CHANGELOG.md", "changelog.html", "Changelog"),
]
SITE_OF = {src: out for src, out, _ in PAGES}
HOME_STOP = re.compile(r"^# Reference\s*$", re.M)
DOC_REF = re.compile(r"^docs/(\d{4})$")


@dataclass
class Page:
    src: str
    out: str
    label: str
    title: str = ""
    body: str = ""
    anchors: set[str] = field(default_factory=set)
    #: (href as written, the page it points to, its anchor) for the link check
    links: list[tuple[str, str, str]] = field(default_factory=list)


def github_slug(text: str, seen: dict[str, int]) -> str:
    """GitHub's heading anchor: lower case, punctuation dropped except `-` and
    `_`, each space a hyphen, and `-1`, `-2` ... for repeats."""
    s = re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")
    n = seen.get(s, 0)
    seen[s] = n + 1
    return s if n == 0 else f"{s}-{n}"


def _plain(inline) -> str:
    return "".join(c.content for c in (inline.children or [])
                   if c.type in ("text", "code_inline", "html_inline"))


def _doc_files() -> dict[str, str]:
    return {p.name[:4]: p.name for p in (ROOT / "docs").glob("[0-9][0-9][0-9][0-9]-*.md")}


def rewrite(href: str, src: str) -> tuple[str, str | None, str]:
    """(href for the site, the site page it lands on or None, the anchor)."""
    if href.startswith("#"):
        return href, SITE_OF[src], href[1:]
    if href.startswith(BLOB):
        href = "/" + href[len(BLOB):]          # treat as a path from the root
    elif re.match(r"^[a-z]+:", href):
        return href, None, ""
    path, _, frag = href.partition("#")
    if path.startswith("/"):
        target = path.lstrip("/")
    else:
        target = posixpath.normpath(posixpath.join(posixpath.dirname(src), path))
    if target in SITE_OF:
        out = SITE_OF[target]
        return out + (f"#{frag}" if frag else ""), out, frag
    if target.startswith(".."):
        raise ValueError(f"{src}: {href} leaves the repository")
    base = TREE if (ROOT / target).is_dir() else BLOB
    return base + target + (f"#{frag}" if frag else ""), None, ""


def render(src: str, out: str, label: str) -> Page:
    text = (ROOT / src).read_text(encoding="utf-8")
    if src == "README.md":
        m = HOME_STOP.search(text)
        text = text[:m.start()] if m else text
    md = MarkdownIt("commonmark", {"html": True}).enable(["table", "strikethrough"])
    tokens = md.parse(text)
    page = Page(src, out, label)
    seen: dict[str, int] = {}
    docs = _doc_files()
    for i, t in enumerate(tokens):
        if t.type == "heading_open":
            words = _plain(tokens[i + 1])
            slug = github_slug(words, seen)
            t.attrSet("id", slug)
            page.anchors.add(slug)
            if t.tag == "h1" and not page.title:
                page.title = words
        if t.type == "inline":
            kids = []
            for c in t.children or []:
                if c.type == "link_open":
                    new, target, frag = rewrite(c.attrGet("href") or "", src)
                    c.attrSet("href", new)
                    if target:
                        page.links.append((c.attrGet("href"), target, frag))
                    elif new.startswith("http") and not new.startswith(REPO):
                        c.attrSet("rel", "noopener")
                elif c.type == "code_inline" and (m := DOC_REF.match(c.content)) \
                        and m.group(1) in docs:
                    # `docs/0048` in the text becomes a link to that document.
                    from markdown_it.token import Token
                    a = Token("link_open", "a", 1)
                    a.attrSet("href", f"{BLOB}docs/{docs[m.group(1)]}")
                    kids += [a, c, Token("link_close", "a", -1)]
                    continue
                kids.append(c)
            t.children = kids
    page.body = md.renderer.render(tokens, md.options, {})
    # Wide tables scroll inside the column instead of widening the page.
    page.body = page.body.replace("<table>", '<div class="table"><table>') \
                         .replace("</table>", "</table></div>")
    page.title = page.title or label
    return page


def _version() -> str:
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    except OSError:
        return ""


def page_html(p: Page, pages: list[Page], version: str, commit: str) -> str:
    nav = "\n".join(
        f'<li><a href="{q.out}"{" aria-current=page" if q is p else ""}>'
        f"{html.escape(q.label)}</a></li>" for q in pages)
    title = "HandCode" if p.out == "index.html" else f"{html.escape(p.title)} · HandCode"
    edit = f"{BLOB}{p.src}"
    built = f" from <code>{commit}</code>" if commit else ""
    return (HERE / "template.html").read_text(encoding="utf-8").format(
        title=title, nav=nav, body=p.body, version=html.escape(version),
        edit=edit, built=built, repo=REPO)


def check(pages: list[Page]) -> list[str]:
    by_out = {p.out: p for p in pages}
    broken = []
    for p in pages:
        for href, target, frag in p.links:
            if target not in by_out:
                broken.append(f"{p.src}: {href} -> no page {target}")
            elif frag and frag not in by_out[target].anchors:
                broken.append(f"{p.src}: {href} -> no heading #{frag} in {by_out[target].src}")
    return broken


def build(out: Path) -> list[Page]:
    pages = [render(*row) for row in PAGES]
    if broken := check(pages):
        raise SystemExit("broken links:\n  " + "\n  ".join(broken))
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    version, commit = _version(), _commit()
    for p in pages:
        (out / p.out).write_text(page_html(p, pages, version, commit), encoding="utf-8")
    for asset in ("style.css", "site.js"):
        shutil.copy(HERE / asset, out / asset)
    notfound = Page("", "404.html", "Not found", "Not found",
                    '<h1>Not found</h1><p>No page here. <a href="index.html">'
                    "Start from the home page</a>.</p>")
    (out / "404.html").write_text(page_html(notfound, pages, version, commit),
                                  encoding="utf-8")
    (out / ".nojekyll").write_text("")
    return pages


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=ROOT / "_site")
    a = ap.parse_args(argv)
    pages = build(a.out)
    print(f"built {len(pages)} pages into {a.out}; every internal link resolves")
    return 0


if __name__ == "__main__":
    sys.exit(main())
