# Changelog

What changed for someone using agentctl. The reasons, measurements and
findings behind each item are in the numbered [`docs/`](INDEX.md) stream.

**Versioning.** `0.x` while commands and output may still change. A release
is a git tag; nothing between tags is a release.

## Unreleased

The release that makes it usable by someone other than its author
(`docs/0043` to `docs/0050`).

### Added
- Published on PyPI as **`handcode`** (`agentctl` was taken). The command is
  still `agentctl`, and is also installed as `handcode`; the import package
  is still `agentctl` (`docs/0051` Stage 1).
- `agentctl demo`: a real crash duplicates a commit in plain OpenHands, and
  agentctl prevents it. No key, no network, $0 (`docs/0050`).
- `agentctl init`: one key, checked with one request, and the model that
  answered recorded as your default (`docs/0047`).
- `agentctl run` needs no flags: the model comes from `--model`, then
  `AGENTCTL_MODEL`, then `~/.agentctl/config.toml`, then your first
  provider.
- An end-of-run report: what was checked, what changed, what it used, what
  needs you. `--accept "<command>"` runs your tests after the agent and
  reports PASS or FAIL. The exit code follows the report (`docs/0048`).
- `agentctl status`, `agentctl resume`, and a run index, so follow-up
  commands need no path or id (`docs/0049`). `agentctl dash` reads it too.
- Ctrl-C pauses after the current step; `agentctl resume` continues.
- Approvals without a terminal: a dangerous action is queued, and answered
  with `agentctl approve` / `agentctl deny` (`docs/0049`).
- `--wait 30m` waits out a rate limit and resumes.
- `agentctl run --pool` and `agentctl proxy up|status|down`: a LiteLLM pool
  in an environment of its own; no proxy extra in your install
  (`docs/0047`).
- `agentctl --version`.
- A container image (`Dockerfile`; published to `ghcr.io/csdeepak/handcode`
  with each release). Only the mounted repository is reachable, and the
  pool's environment is built in (`docs/0051` Stage 2).
- A GitHub Action (`csdeepak/HandCode` and `csdeepak/HandCode/publish`): type
  a task in the Actions tab, get a pull request whose description is the
  report. Two jobs, so the one running the agent holds no token that can
  write. Started by a person only, not by issues yet
  (`guide/github-action.md`, `docs/0053`).
- `agentctl run --report-json PATH`: the report, for a program to read.
- A user guide in `guide/`, also built as a website (`website/build.py`),
  published at <https://csdeepak.github.io/HandCode/> (`docs/0054`).

### Changed
- Installing software into your environment (`pip install`, `npm install -g`,
  `apt`, `brew`, …) asks first, or queues when nobody is at a terminal.
  Installs into a venv inside the repository do not, and nothing asks in
  the container (`docs/0052`).
- An identical command the agent re-runs after seeing its result now runs
  (the edit, test, re-test loop). It used to get stale output or be blocked
  (`docs/0045`).
- `--resume` no longer takes over a run that is still alive. A crashed one is
  taken over without asking; `--takeover` overrides (`docs/0046`).
- Costs say what they can be trusted for. Free-tier calls are a known $0, not
  list price and not "unknown"; per-conversation cost works through the pool
  (`docs/0048`).
- A workspace's `.agentctl/` is ignored by git automatically.
- Advice about extra keys points to a second **provider**. Several accounts
  at one provider are unverified as extra quota, and may break that
  provider's terms.

### Fixed
- `doctor` no longer blocks a working install on a package version, and
  `keys --check` no longer reports a working key as unable to serve because
  one model left the catalogue (`docs/0044`).
- `verify.py` skips, rather than fails, the proxy checks when the proxy
  extra is not installed.
- A superseded process can no longer start a new effect (`docs/0046`).
- Opening a ledger right after its holder was killed no longer fails on
  Windows with "disk I/O error" (`docs/0046`).
- `2>/dev/null` no longer asks for confirmation as a write outside the
  workspace (`docs/0047`).

## 0.2.0a0

The correctness core: the effect ledger, the gate, three seams, probes, record
and replay, policy, and the nine-point chaos suite (`docs/0001` to
`docs/0042`). Development snapshot; not released to PyPI.
