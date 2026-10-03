# Contributing

Thank you for looking. This project is small and opinionated, and the opinions
are written down, so this page is mostly pointers to them.

## Set up

```bash
git clone https://github.com/csdeepak/HandCode && cd HandCode
python3 -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev,openhands]"
```

Python 3.12 or newer and `git`. Windows users: clone into a short path; see
[`guide/troubleshooting.md`](guide/troubleshooting.md).

## Check your change

```bash
pytest tests/ -q          # about 3 minutes: the unit suite and the ten-point chaos suite
python verify.py          # about 6 minutes: every end-to-end crash experiment, at no cost
agentctl demo             # about 1 minute: the claim a stranger sees first
```

All three are free: they run against local mock providers, with no key, no
network and no tokens. CI runs the suite on Linux, macOS and Windows, and
`verify.py` with the proxy extra (`--require-proxy`).

## The rules this project holds itself to

These come from things that went wrong. Each one is in [`docs/`](INDEX.md).

1. **A feature that has never run against a real provider is not done**
   (`docs/0041`). Mocks prove the logic; only a real run proves the boundary.
   Say in the pull request what you ran live. "Not run live" is an acceptable
   answer when it is said.
2. **Fail closed.** When the gate cannot tell whether an effect happened, it
   blocks and asks. Never let a bug turn into an unguarded effect
   (`agentctl/kernel/gate.py`: `guard()` must never raise).
3. **The kernel never imports the control plane, the harness, or the network**
   (`tests/test_boundaries.py`). If you need one of those, the code belongs in
   `control/`, `adapters/` or `runtime/`.
4. **Do not print what you did not check.** A report line, a cost or a "ready"
   must come from the same record the precise output uses. The project's worst
   defects were confidently wrong answers (`docs/0039`).
5. **Assert the route, not just the result** (`docs/0024`): a test that passes
   while the code takes the wrong path is a test that cannot fail.

## Code

- Match the surrounding style. Comments explain *why*, and cite the `docs/`
  entry that holds the reason.
- **Line endings are mixed in this repository**: some files are CRLF, most
  are LF. Keep whatever a file already uses; do not renormalise in a feature
  change.
- A user-facing message changed? Update its entry in
  [`guide/troubleshooting.md`](guide/troubleshooting.md), which quotes the CLI
  exactly.

## Documents

- **`docs/`** is the project's memory: numbered, never renumbered, never
  deleted. A decision, an experiment or a finding gets the next number, and
  a row in `INDEX.md` in the same commit. See [`CONVENTIONS.md`](CONVENTIONS.md).
- **`guide/`** is for users, and is edited in place.

## Commits and pull requests

- Commit messages say what changed and why. `docs(NNNN): ...` for a document.
- One concern per pull request. Include what you ran, and how it came out.

## Reporting a security problem

Privately, please: see [`SECURITY.md`](SECURITY.md).
