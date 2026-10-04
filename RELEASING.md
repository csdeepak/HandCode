# Releasing handcode

The distribution on PyPI is **`handcode`**. The command is `agentctl`, also
installed as `handcode`, and the import package is `agentctl`
(`docs/0051` Stage 1).

Publishing uses **PyPI trusted publishing**: GitHub Actions proves to PyPI
which repository and workflow it is, so no API token exists anywhere to leak.
The workflow is [`.github/workflows/release.yml`](.github/workflows/release.yml).

## One-time setup (the owner)

This has to be done from the owner's own accounts. It is the part no
automation should hold credentials for.

1. **TestPyPI** (a separate account from PyPI): <https://test.pypi.org>, then
   *Account settings → Publishing → Add a new pending publisher*:

   | Field | Value |
   |---|---|
   | PyPI project name | `handcode` |
   | Owner | `csdeepak` |
   | Repository name | `HandCode` |
   | Workflow name | `release.yml` |
   | Environment name | `testpypi` |

2. **PyPI**: <https://pypi.org>, the same form, with environment **`pypi`**.

3. **GitHub**: *Settings → Environments → `pypi` → Required reviewers →
   yourself.* Every upload to the real index then waits for you to press
   Approve. The environments are created automatically the first time the
   workflow runs; add the reviewer after that, or create `pypi` first.

## A release

1. Set the version in `pyproject.toml`: `0.3.0rc1` for a candidate, `0.3.0`
   for the release.
2. In `CHANGELOG.md`, move *Unreleased* under a heading for that version.
3. Commit, then tag with **the same version** and push the tag:

   ```bash
   git tag v0.3.0rc1
   git push origin v0.3.0rc1
   ```

4. The workflow builds the package and installs **its own wheel** on Linux,
   macOS and Windows. It runs `handcode demo` from each install, publishes to
   TestPyPI, installs from TestPyPI on all three OS and runs the demo again.
   Only then does it stop at the `pypi` environment for your approval.
5. Approve, and it publishes to PyPI and creates a GitHub release with the
   files attached.
6. **For a final release** (not a candidate), move the GitHub Action's major
   tag to it, since `examples/handcode.yml` uses `csdeepak/HandCode@v0`
   (`docs/0053`):

   ```bash
   git tag -f v0 v0.3.0
   git push -f origin v0
   ```

A tag that does not match `pyproject.toml`'s version fails at the first step.
A version can be uploaded to an index only once, ever, so a failed release
after TestPyPI means bumping to the next `rcN`.

## A dry run

*Actions → release → Run workflow → publish: `none`* builds and tests the
wheel on all three OS, and publishes nothing. `testpypi` goes as far as
TestPyPI. `pypi` asks for approval before the real index.

## After the first PyPI release

Done with `0.3.0rc1` (2026-10-04). `README.md` and `guide/quickstart.md`
install from PyPI:

```bash
uv tool install "handcode[openhands]"
```
