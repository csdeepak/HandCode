"""The documentation site (`website/build.py`). docs/0054.

The link check runs here as well as in the site workflow, so a guide page that
links to a heading someone renamed fails the ordinary test run.
"""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("handcode_site", ROOT / "website" / "build.py")
site = importlib.util.module_from_spec(_spec)
sys.modules["handcode_site"] = site          # dataclasses look the module up
_spec.loader.exec_module(site)


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("site")
    pages = site.build(out)
    return out, pages


def test_every_guide_page_is_on_the_site():
    on_site = {src for src, _, _ in site.PAGES}
    for md in (ROOT / "guide").glob("*.md"):
        assert f"guide/{md.name}" in on_site, f"guide/{md.name} is not in website/build.py PAGES"


def test_every_link_between_pages_resolves(built):
    out, _ = built
    for page in out.glob("*.html"):
        text = page.read_text(encoding="utf-8")
        for href in re.findall(r'href="([^"]+)"', text):
            if re.match(r"^[a-z]+:", href) or href.endswith(".css"):
                continue
            name, _, frag = href.partition("#")
            target = out / (name or page.name)
            assert target.exists(), f"{page.name}: {href}"
            if frag:
                assert f'id="{frag}"' in target.read_text(encoding="utf-8"), \
                    f"{page.name}: {href} has no such heading"


def test_no_link_still_points_at_a_markdown_file_on_the_site(built):
    out, _ = built
    for page in out.glob("*.html"):
        for href in re.findall(r'href="([^"]+)"', page.read_text(encoding="utf-8")):
            if not href.startswith("http"):
                assert ".md" not in href, f"{page.name}: {href}"


def test_the_readmes_links_to_the_guide_stay_on_the_site(built):
    out, _ = built
    home = (out / "index.html").read_text(encoding="utf-8")
    assert 'href="quickstart.html"' in home
    assert "blob/main/guide/" not in home
    # The home page is the README's first part; the reference stays on GitHub.
    assert "Reference" not in re.findall(r"<h1[^>]*>(.*?)</h1>", home)


def test_anything_else_in_the_repository_links_to_github():
    assert site.rewrite("../examples/handcode.yml", "guide/github-action.md")[0] == \
        site.BLOB + "examples/handcode.yml"
    assert site.rewrite("INDEX.md", "CHANGELOG.md")[0] == site.BLOB + "INDEX.md"
    with pytest.raises(ValueError):
        site.rewrite("../../elsewhere.md", "guide/faq.md")


def test_headings_get_githubs_anchors():
    seen = {}
    assert site.github_slug("6. Run it in a container (recommended)", seen) == \
        "6-run-it-in-a-container-recommended"
    assert site.github_slug("`outcome     FAIL`", seen) == "outcome-----fail"
    assert site.github_slug("FAQ", seen) == "faq"
    assert site.github_slug("FAQ", seen) == "faq-1"


def test_a_broken_anchor_fails_the_build():
    a = site.Page("guide/a.md", "a.html", "A", anchors={"there"},
                  links=[("b.html#gone", "b.html", "gone"), ("c.html", "c.html", "")])
    b = site.Page("guide/b.md", "b.html", "B", anchors={"here"})
    broken = site.check([a, b])
    assert len(broken) == 2
    assert "no heading #gone" in broken[0] and "no page c.html" in broken[1]


def test_a_docs_reference_becomes_a_link(built):
    out, _ = built
    concepts = (out / "concepts.html").read_text(encoding="utf-8") + \
        (out / "github-action.html").read_text(encoding="utf-8")
    assert re.search(r'href="https://github.com/csdeepak/HandCode/blob/main/docs/\d{4}-[^"]+\.md"><code>docs/\d{4}</code></a>',
                     concepts)
