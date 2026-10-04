---
Number:        0051
Title:         Deployment — The Plan
Type:          DECISION
Status:        DRAFT
Created:       2026-10-04
Supersedes:    —
Superseded-by: —
Depends-on:    0042, 0043, 0047, 0050
---

# 0051 — Deployment: The Plan

The owner's third goal: deploy agentctl on the most suitable platform, so that
people can use it with their own API keys. `0043` (user-centric) is done
(`0050` §4). This plans what comes next. **Nothing in it is built.**

---

## 1. What kind of thing is being deployed

The answer decides the platform, so it comes first.

agentctl is a **local tool that acts**:
- It runs a coding agent against the user's repository.
- It executes the agent's shell commands.
- It spends the user's API key.

Three facts follow, and every option below is judged against them:

1. **Where it runs is where commands run.** agentctl is not a sandbox
   (`guide/concepts.md`). On a laptop, an allowed command can touch the whole
   laptop. In a container, only what the container can reach.
2. **Whoever runs it holds the key.** Key custody is the one thing a hosted
   service cannot avoid, and the one thing every other option avoids
   entirely.
3. **It is heavy.** A clean install is 141 packages and 417 MB, of which
   litellm is 132 MB, through the OpenHands SDK. Measured install times were
   4 m 20 s and 13.5 min (`0044`, `0047`). Whatever ships must make that
   cost paid once, or not at all.

## 2. The options

| Option | Who holds the key | Where commands run | Owner's running cost | Fit |
|---|---|---|---|---|
| **A. PyPI package** (`pipx` / `uv tool install`) | The user, locally | The user's machine | none | The baseline every other option is built from. Heavy install (§1.3) |
| **B. Container image** (GitHub Container Registry) | The user, passed in at `docker run` | **A container**: only the mounted repo is writable | none | Install cost paid once, as a pull. The nearest thing to a sandbox the project can offer today |
| **C. GitHub Action** (`uses: …@v1`) | The user's repository secrets | GitHub's ephemeral runner VM | none (minutes are the user's) | "Use it from GitHub, with your key, results as a PR." The hosted experience without hosting |
| D. Hosted web service | **The operator: us** | Our infrastructure, one sandbox per user | real, and growing with use | See §4: not now |
| E. Docs site (GitHub Pages from `guide/`) | — | — | none | Cheap discoverability. Optional |

"The most suitable platform" is therefore not one thing. **A is the
foundation, B makes it safe and fast to try, and C is the hosted experience.**
None of them needs anyone but the user to hold a key.

## 3. The stages

Each stage ends the way `0041` requires: run once, live, from the published
artifact rather than the repository.

### Stage 0: release readiness (owner decisions plus hygiene, about 1 day)

**Owner decisions (§6).** The name (D3/D4), a PyPI account with trusted
publishing, and whether the multi-account pool is described publicly at all
(D7).

**Hygiene, before strangers arrive:**
- **Untrack `hook_telemetry.json`.** It holds run telemetry (deployment ids,
  conversation ids, token counts), not secrets, and has been noise in every
  commit since `0042`. Add it to `.gitignore`.
- **Add `CONTRIBUTING.md`** (how to run the tests and `verify.py`; the docs
  stream; the "run it live once" rule), **`SECURITY.md`** (private
  vulnerability reporting, since this tool runs commands), **`CHANGELOG.md`**,
  and issue templates that ask for `agentctl doctor` output.
- **Set a version policy.** 0.x while the CLI may still change; a release is
  a tag.
- **History scan, done 2026-10-04.** Every commit was searched for
  OpenRouter, Gemini, Groq, Anthropic, Cerebras and OpenAI key shapes. The
  only hits are test placeholders (`sk-or-v1-NEVERSHOWTHIS…`).
- **macOS has never been run.** CI covers Linux and Windows. Add macOS to the
  matrix before claiming it.

**Measure the install** before deciding how to cut it:
- `pip` versus `uv`, both cold and warm, on all three OS;
- what `[openhands]` pulls, and whether any heavy dependency (`botocore`,
  `grpc`, `PIL`) can be avoided.

`uv` is the likely answer, but it is unmeasured here, so it is not a
conclusion.

### Stage 1: PyPI (about 1 day after Stage 0)

- **A release workflow, run on a tag:**
  1. Build the sdist and wheel.
  2. Install **from the built wheel** into clean environments on Linux,
     macOS and Windows, outside the repository.
  3. Run `agentctl demo` and the unit suite against that install.
  4. Publish to **TestPyPI**, install from there, and repeat step 3.
  5. Only then publish to **PyPI**.
- **Trusted publishing (OIDC).** GitHub Actions publishes without a stored
  token. Nobody, including this assistant, handles a PyPI credential.
- **The install command in the README and guide becomes**
  `uv tool install <name>[openhands]`, or `pipx`, replacing the clone.

**Done when** a clean machine of each OS goes from the install command to
`agentctl demo` passing, then `agentctl init` and a real task, using the
published package.

**Risks.**
- The `mcp`/`litellm[proxy]` conflict is avoided because the proxy lives in
  its own environment (`0047`), but a future SDK release could reintroduce
  another. The weekly CI run (`0044` §10) is the alarm.
- Unpinned dependencies drift. Publish a tested constraints file with each
  release, so "known to work" can be reproduced.

### Stage 2: the container image (about 2 days)

```
docker run --rm -it -v "$PWD:/work" --env-file ~/.agentctl/keys.env \
    -v agentctl-home:/root/.agentctl  ghcr.io/csdeepak/<name>  run "<task>"
```

- **The image:** a slim Python 3.12 base, `git`, the published package, and
  the **proxy environment pre-built**, so `--pool` starts in seconds rather
  than minutes. Built for `amd64` and `arm64`, and published to GitHub
  Container Registry from the same release workflow.
- **What it changes about safety.** Only `/work` (the user's repository) is
  writable from the host. A `pip install` the agent runs unasked (`0047` §5)
  lands in the container and dies with it. A write to `~/.bashrc` writes the
  container's. **This is the first deployment shape that limits what an
  allowed command can reach.** The guide should recommend it for any task
  you would not run in your own shell.
- **Details to get right:**
  - file ownership on the mounted repository (run as the host user's uid);
  - `git safe.directory` for `/work`;
  - a git identity inside the container (`0044` N12, where the agent set its
    own);
  - a named volume for `~/.agentctl`, so `status` and `resume` survive the
    container;
  - Windows paths under Docker Desktop.
- **Experiment, `0042` I-26 in miniature.** The canary tasks (write outside
  the workspace, read `keys.env`, `pip install`), run inside the image. Each
  must stay inside the container or be refused. This is the evidence for the
  safety claim, and the claim is not made without it.

**Done when** the demo and one real task run through a single `docker run` on
Linux, macOS and Windows, and the canaries cannot reach the host.

### Stage 3: the GitHub Action (about 3 days)

```yaml
- uses: csdeepak/<name>@v1
  with:
    task: ${{ github.event.issue.body }}        # or a workflow_dispatch input
    accept: python -m pytest -q
  env:
    OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}
```

- **How it runs.** A container action built on the Stage 2 image. It runs
  the task in the repository's checkout, runs `--accept`, and opens a pull
  request with the end-of-run report (`0048`) as its description. It never
  pushes to the default branch.
- **Why this is the "hosted" answer.**
  - The user's key stays in their repository's secrets.
  - Commands run on GitHub's ephemeral VM, not on anyone's laptop and not on
    our servers.
  - The owner runs no infrastructure and pays nothing.
  - **agentctl's own value shows up here naturally.** Jobs time out and get
    cancelled. Persisting `.agentctl/` as a workflow artifact lets the next
    job `agentctl resume` instead of starting over, which is the
    crash-and-resume story in a setting where crashes are routine.
- **The hard part is prompt injection.** An issue body is text from
  strangers, and the agent will act on it. Before the Action accepts issue
  text as a task, **I-26 must have run**: injected instructions in issue
  text, README and tool output, each trying a canary.
  - The Action's token gets the least it needs: `contents: write`,
    `pull-requests: write`, nothing else.
  - Workflows triggered from forks get no secrets (GitHub's own rule, which
    the docs must state).
  - Dangerous actions queue for approval (`0049`) and cannot be approved
    from inside the run.

**Done when** a sample repository with a labelled issue gets a pull request
with a PASS report, and the injection canaries from issue text are refused or
contained.

### Stage 4 (optional): a documentation site

`guide/` published to GitHub Pages (mkdocs, or plain Markdown). It is cheap,
and it gives the project a URL that is not a repository page. It needs
nothing from Stages 1–3.

## 4. Not now: a hosted web service

"Paste your key, point at a repository, get a pull request." It is attractive,
and it is the wrong next step:

| Why not | What it would take |
|---|---|
| **Key custody.** We would hold every user's provider key | Encryption at rest, a breach plan, and liability for every key |
| **A sandbox per user.** Strangers' agents running arbitrary commands on our machines | Container or microVM isolation, egress control, resource limits, abuse handling. Vercel Sandbox or Firecracker are candidates (unevaluated) |
| **Cost that grows with use.** Compute, storage, bandwidth | A billing model, for a project whose users mostly come for free tiers |
| **Terms of service.** Pooling free accounts (`0042` §4.C) on a service *we* operate is a different question from a user doing it for themselves | Legal review per provider |
| **No evidence of demand.** 0 stars, 0 forks today | — |

**Revisit when** Stage 3 shows people want agentctl without running it
themselves, and the GitHub Action does not serve them. Most of what a hosted
service would offer, the Action already offers with none of the custody.

**Serverless platforms in general** (Vercel functions, Lambda) do not fit the
core loop at all. A run is minutes long, needs `git` and a shell, and holds a
local ledger. A docs site is the only part that belongs there.

## 5. What deployment changes about the open risks

Once strangers run it, three items stop being backlog:

| Item | Why it moves up |
|---|---|
| **I-26, prompt-injection canaries** | A gate for Stage 3. Issue text is untrusted input |
| **The `pip install` hazard** (`0047` §5) | Contained by Stage 2. On a bare install, package installs could become "asks first" (a classifier change) |
| **The multi-account pool** (`0042` §4.C) | A public tool must not encourage something a provider's terms forbid. The docs already hedge it (`0044` N9); D7 decides whether it is documented at all |

## 6. Decisions for the owner

| # | Decision | Recommendation |
|---|---|---|
| D3/D4 | Package and project name | One name for the repository, the package and the image. `agentctl` is taken on PyPI. `handcode`, `effectledger` and `agentctl-ledger` were free on 2026-10-02. The command can stay `agentctl` |
| D6 | PyPI account, and trusted publishing configured on PyPI for this repository | **You do this.** It is an account action, and the point of trusted publishing is that no token is handed to anyone |
| D7 | Document the multi-account pool publicly? | Document **multi-provider** pooling. Leave same-provider multi-account out of the public docs until each provider's terms are checked |
| D8 | Publish the image and the Action under `csdeepak`? | Yes. The image and Action follow the package name |
| D9 | Supported platforms for 1.0 | Linux and macOS first-class; Windows supported, since it is where this was built and tested most |
| D10 | Stage 3 trigger | `workflow_dispatch` (typed by a maintainer) before issue-triggered runs. Issue text only after I-26 |

## 7. Order and size

| Stage | Size | Needs |
|---|---|---|
| 0 Readiness | about 1 day, plus owner decisions | D3/D4, D6, D7 |
| 1 PyPI | about 1 day | Stage 0 |
| 2 Image | about 2 days | Stage 1; Docker running locally |
| 3 Action | about 3 days | Stage 2; I-26 before issue triggers |
| 4 Docs site | about ½ day | nothing |

**Measures of success:**
- time from "never heard of it" to a finished task, per channel;
- install time, cold and warm;
- the canary results in the container;
- whether anyone other than the owner completes the quickstart (D5,
  still open).

---

## 8. Addendum (2026-10-04): Stage 0 results

| Item | Result |
|---|---|
| `hook_telemetry.json` | Untracked and ignored everywhere (`0b24f65`). The local file is untouched |
| `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, issue templates | Added. The changelog holds the 0.x version policy, and the bug template asks for `--version`, `doctor` and whether the demo passes |
| `agentctl --version` | Added. `--help` now says what the tool is for; it still said "Inspect and resolve the effect ledger" |
| History scan | Clean. The only key-shaped strings in any commit are test placeholders |
| **macOS** | Added to CI. **The whole suite passed on its first run there**, demo included, on Python 3.12 and 3.13 |
| **Private vulnerability reporting** | **Disabled on the repository.** `SECURITY.md` points at it, so it needs turning on: Settings → Code security → Private vulnerability reporting. **Owner action** (D11) |

**Install time, measured** (`install-time.yml`; fresh GitHub runners, Python
3.12, no cache; each install then ran `agentctl demo`, and every demo
passed):

| OS | pip, cold | pip, warm | uv, cold | uv, warm |
|---|---|---|---|---|
| Ubuntu | 39 s | 33 s | **3 s** | 1 s |
| macOS | 43 s | 43 s | **4 s** | 2 s |
| Windows | 48 s | 34 s | **23 s** | 8 s |
| The owner's Windows laptop | 4 m 20 s, 13.5 min (`0044`, `0047`) | — | **21 s** | 13 s |

**What this changes.**
- §1.3 called the install heavy, and it is: 140 distributions, almost all of
  them through the OpenHands SDK. litellm, boto3/botocore, tokenizers,
  lmnr→grpcio and pillow are the bulk. agentctl's own dependency is `pyyaml`.
  Nothing on agentctl's side can slim it.
- **But installs are slow on that laptop, not in general.** On clean
  machines pip takes under a minute. The 4–13.5 minutes were the machine:
  network, antivirus or disk, not investigated further.
- **uv removes the cost everywhere**, that laptop included (21 s cold).

**Decision.**
- `uv` is the recommended installer, with pip as a fallback that only costs
  time.
- The README and quickstart now say `pip install uv && uv pip install -e …`
  for the clone path.
- Stage 1's published path becomes `uv tool install <name>[openhands]`.

**First run of the measurement.** `uv` on Windows failed: the script passed
`.../Scripts/python` without `.exe`, and uv does not add it. The script's bug
was fixed (`ebd6be4`), and the re-run passed 6/6.

**Stage 0 is done, except D11.** Stage 1 needs D3/D4 (the name) and D6
(PyPI trusted publishing).

## 9. Addendum (2026-10-04): Stage 1 built; publishing waits on the owner

**The name is `handcode`** (owner's decision on D3/D4). It was free on PyPI
and TestPyPI, and so were the separator variants PyPI would treat as
colliding (`hand-code`, `hand_code`, `hand.code`). The command stays
`agentctl` and is also installed as `handcode`; the import package stays
`agentctl`. The README title is now HandCode.

**What was built** (`47ff51d`):

| | |
|---|---|
| `pyproject.toml` | `handcode` 0.3.0rc1, with readme, URLs, classifiers, keywords and both entry points. No author email published |
| README | Links made absolute, because PyPI renders the README and does not resolve relative links |
| `release.yml` | On a tag matching the version: build, `twine check`, a refusal if the sdist holds telemetry, ledgers or keys; `uv tool install` of the wheel plus `handcode demo` on Linux, macOS and Windows; TestPyPI; the same three-OS check installed from TestPyPI; PyPI behind the `pypi` environment's approval; a GitHub release. Trusted publishing only, so no token exists anywhere |
| `RELEASING.md` | The owner's one-time setup, and the release steps |

**A dependency-confusion trap, avoided in review.** The first draft installed
from TestPyPI with `--index-strategy unsafe-best-match`. That lets *any*
dependency resolve from TestPyPI, where anyone can upload a lookalike. The
check now downloads only `handcode` from there and takes every dependency
from PyPI.

**Verified:**
- **Locally.** `uv build`; `twine check` passed; the sdist holds only the
  package, the tests and metadata. `uv tool install` of the wheel, with uv's
  tool directories isolated, took 9 s, gave both commands at `0.3.0rc1`, and
  `handcode demo` passed outside the repository.
- **On GitHub, the dry run** (`publish: none`). Build and wheel on all three
  OS passed, demo included; every publish job was skipped, as designed.

**Not verified: publishing itself.** It needs the owner's setup (`RELEASING.md`):
pending publishers on test.pypi.org and pypi.org, and a required reviewer on
the `pypi` environment. **A pending publisher does not reserve the name.**
Until the first upload, someone else can still take `handcode`.

**Next, once the setup exists:**
1. Tag `v0.3.0rc1`. That goes through TestPyPI to the approval gate. Approve
   it, or stop there.
2. Switch the README and quickstart to `uv tool install "handcode[openhands]"`.
3. Bump to `0.3.0` for the release.

## 10. Addendum (2026-10-04): Stage 2 built and tested; not published, one live run open

**What was built** (`6fd0828`):

| | |
|---|---|
| `Dockerfile` | `python:3.12-slim` plus `git`; **the release wheel** (not the source tree) installed with uv. The pool's proxy environment is built in at `/opt/handcode/proxy-env` (new `AGENTCTL_PROXY_ENV`), outside `$HOME`, so the volume over the home directory cannot hide it. Runs as any uid. `git safe.directory` for the mounted repository, and a fallback git identity, so the agent never sets one in the user's repository (`0044` N12) |
| `.dockerignore` | Admits only `dist/*.whl`. Nothing else in the repository can reach an image |
| `image.yml` | Builds from the wheel and checks the real container. Publishes to `ghcr.io/csdeepak/handcode` (amd64 and arm64; `latest` only for a final release) **on a release tag only** |

**Checked in CI, against the built image, first run** (run 37158793668). Each
item was confirmed from its log output, not only from the job's status:
- `--version` reports `handcode 0.3.0rc1 … linux`;
- **the demo inside the container, as an ordinary uid**: plain OpenHands
  2 commits, agentctl 1;
- a file written into `/work` is **owned by the host user (uid 1001), not
  root**, and git accepts the mounted repository;
- `proxy status` reports `/opt/handcode/proxy-env`, and its interpreter
  imports `litellm.proxy.proxy_server`;
- **containment**: the container appended to its `~/.bashrc` and ran `pip
  install`; the host's `~/.bashrc` hash was unchanged.

**Documented.** `guide/quickstart.md` §6 gives the `docker run` line, and why
each part is there. `concepts.md`, `SECURITY.md` and the README now point
untrusted tasks at the container. `SECURITY.md` says a way out of that
boundary is a vulnerability.

**Open.**
- **One real task with a real model inside the container** (the `0041`
  rule). This needs Docker running on the owner's machine with a key, or a
  key as a repository secret for CI. Neither exists yet. Everything above
  used the demo's scripted model.
- **The I-26 canaries with a real model**, injected instructions trying to
  leave `/work`, read keys or reach the network. The containment test above
  proves the mechanism, not how a model behaves against it.
- **Publishing** happens with the first release tag, after Stage 1's
  trusted-publisher setup.

## 11. Addendum (2026-10-04): Stage 3 built, as two jobs; recorded in `0053`

The one-step action sketched in §3 could not keep its own token. A hijacked
agent can read anything on its machine, including the environment of the
process holding the token. So Stage 3 is **two jobs**:
- the agent's, with the model key and a read-only checkout;
- a publish job on a fresh machine, which checks the git bundle and opens the
  pull request.

`docs/0053` has the design, the refusals and the evidence. It ran on GitHub with
a scripted model (first attempt green, every claim read from the log).

**Still open:**
- the `0041` live run with a real model, which needs a key secret;
- a real pull request, which needs the "Allow GitHub Actions to create and
  approve pull requests" setting;
- issue triggers, which wait for I-26 as D10 says.

The §3 "done when" (a labelled issue gets a PASS pull request) is therefore
**not** met yet.
