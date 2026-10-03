---
Number:        0052
Title:         Installing Software Into Your Environment Asks First
Type:          DECISION
Status:        ACCEPTED
Created:       2026-10-04
Supersedes:    —
Superseded-by: —
Depends-on:    0025, 0027, 0047, 0049, 0051
---

# 0052 — Installing Software Into Your Environment Asks First

`0047` §5 left a hazard open. In a live run the agent ran `pip install pytest`
on the host, unasked. Nothing changed only because pytest was already
installed.

## Why nothing caught it

| Check | Why it missed |
|---|---|
| The effect class | `EXTERNAL`: a command, not `DESTRUCTIVE` |
| `escaping_writes` (`0027`) | It names files a command writes. An install writes into an interpreter's `site-packages`, a global `node_modules` or `/usr/bin`, and the command line names none of them |

It is the same question `0027` answered for `echo x > ~/.bashrc`. It is not
destructive, and it is **none of the agent's business**. So it gets the same
treatment: the effect class stays honest, and the **authorization** layer
asks.

## The rule

`kernel/paths.py::environment_installs`, which is pattern-matching only (no
I/O, so the kernel boundary holds). It flags `pip`/`pip3`/`python -m pip
install`, `uv pip install`, `uv tool install`, `pipx`, global `npm`/`pnpm`,
`yarn global`, `apt`/`apt-get`/`dnf`/`yum`/`apk`/`zypper`, `pacman -S`,
`brew`, `cargo`, `gem`, `conda`/`mamba`, `choco`, `winget`, `scoop` and
`go install`.

**Not flagged**, because the install lands in the repository:
- an installer that lives in the workspace (`.venv/bin/pip`,
  `.venv\Scripts\python.exe -m pip`);
- an explicit destination inside it (`--target ./vendor`, `--prefix`,
  `uv pip install --python .venv/...`);
- a local `npm install`.

Read-only commands (`pip list`, `pip show`) are not flagged either. A wrong
prompt teaches the operator to answer `y` unread.

**What happens when one is flagged:** the same as a write outside the
workspace (`0049`). It asks at a terminal, and **queues** for `approve` /
`deny` without one.

**Inside the container nothing asks** (`HANDCODE_CONTAINER=1` in the
`Dockerfile`). There the install lands in the container and dies with it,
which is the containment the image exists for (`0051` §10), so asking would
be noise.

## Evidence

- **`tests/test_installs.py`, 26 tests.**
  - Fourteen installs that must be flagged; eight commands that must not.
  - A venv outside the workspace that must be flagged.
  - Unattended, a `pip install` is queued.
  - Inside the container it runs.
  - The image declares itself a container.
- **Live (the `0041` rule).** An unattended real run was asked to `pip
  install cowsay`.
  - It printed *"installs into your environment: pip install cowsay"* and
    **queued** the install; the agent was told and did not repeat it.
  - The report listed `agentctl approve call-cd411b0 | agentctl deny
    call-cd411b0`.
  - `cowsay` is installed in **neither** Python on the machine.

## Left open

- **An interpreter can still install anything** (`python -c "import pip;
  ..."`). Interpreter arguments are opaque to the classifier by design
  (README). This closes the plain command line, not every route. The
  container is the answer for the rest.
- **Reads outside the workspace** remain unchecked, as `paths.py` says
  (exfiltration, a different concern). For I-26.
