---
Number:        0053
Title:         The GitHub Action — Two Jobs, and the Agent's Holds Nothing Worth Stealing
Type:          DECISION
Status:        DRAFT
Created:       2026-10-04
Supersedes:    —
Superseded-by: —
Depends-on:    0048, 0049, 0051, 0052
---

# 0053 — The GitHub Action: Two Jobs, and the Agent's Holds Nothing Worth Stealing

`0051` Stage 3 is the "hosted" answer with no host:
- the user's key stays in their repository's secrets;
- commands run on GitHub's throwaway VMs;
- the owner runs nothing.

The plan sketched **one step** that runs the task and opens a pull request.
Building it showed why one step cannot be made safe. This document records the
shape that replaced it.

DRAFT because the `0041` rule is half met:
- it **has** run on GitHub, for real, with a scripted model;
- it **has not** run with a real model, or opened a real pull request.

Both need things only the owner can add (§6).

## 1. Why one job cannot work

A model acts on text that can carry instructions: the task, the repository,
tool output. **Anything the agent's machine holds, a hijacked agent can take.**
On a runner that is more than it looks:

| Where a secret sits | How the agent reaches it |
|---|---|
| `.git/config` | `actions/checkout` stores the job's token there by default (`extraheader`) |
| The step's environment | `GITHUB_TOKEN` if the workflow put it there; `ACTIONS_*` runtime tokens |
| Another process's environment | `/proc/<pid>/environ` is readable for any process of the same user, so a token held by the action's own process is readable too |
| A later step | A process left running in the background outlives the agent and waits |
| The Actions cache | A cache the agent's job saves is restored by other workflows: **cache poisoning** |

So a single job that both runs the agent and holds a token that can write
cannot keep that token. Masking it in logs does nothing here.

## 2. The decision: two jobs, on two machines

| | `run` (`action.yml`) | `publish` (`publish/action.yml`) |
|---|---|---|
| Permissions | `contents: read` | `contents: write`, `pull-requests: write` |
| Secrets | the model key | none but the job's token |
| Runs | the agent, then `--accept` | **none of the repository's code** |
| Hands over | a git bundle of the commits, `report.json`, `meta.json` (one artifact, kept 1 day) | a branch `handcode/run-<id>-<attempt>` and a pull request |

The logic is `agentctl/gha.py`, which uses the standard library only.
- `publish` runs it on the runner's own `python3` with **nothing installed**.
- `run` installs HandCode from the action's own source, so `@<ref>` pins
  both halves.

### What `run` refuses before the agent starts

| Refusal | Why |
|---|---|
| An event other than `workflow_dispatch`, `schedule`, `push`, `repository_dispatch` | Issue, comment and PR text can come from anyone, and I-26 has not run (`0051` D10) |
| A git config or remote URL holding a credential | The `.git/config` row above. The fix is one line, `persist-credentials: false`, so failing closed costs the user one edit |
| A dirty checkout | It would enter the pull request as the agent's work |
| `HEAD` ≠ `GITHUB_SHA` | `publish` checks the work against `GITHUB_SHA` |

### What `run` does around the agent

- **The agent's environment loses** `GITHUB_TOKEN`, `GH_TOKEN`, the enterprise
  variants, every `ACTIONS_*` and `INPUT_*`, and `GITHUB_ENV`, `GITHUB_OUTPUT`,
  `GITHUB_PATH`, `GITHUB_STATE` and `GITHUB_STEP_SUMMARY`, which set later
  steps' environment.
  - The model key stays. The guide says to use one with a spending limit.
- **A subreaper.** On Linux, `prctl(PR_SET_CHILD_SUBREAPER)` re-parents every
  process the agent leaves behind to the action's own process, however it
  detaches.
  - After the agent exits, and again after the action's own git commands, all
    descendants are killed.
  - The action is Linux-only for this reason.
- **The git commands after the agent run in a repository the agent may have
  reconfigured.** They run with hooks pointed at an empty directory,
  `core.fsmonitor=false`, `--no-verify`, and no secret in the environment.
- **On GitHub-hosted runners `HANDCODE_CONTAINER=1`.** The VM is discarded, so
  installs do not ask (`0052`). On a self-hosted runner they still ask.
- **No uv cache**, for the cache-poisoning row in §1.

### What `publish` checks, treating everything from `run` as forged

| Check | Against |
|---|---|
| `meta.base` | `GITHUB_SHA`, from GitHub, not from the run job |
| The bundle verifies, and its head descends from `GITHUB_SHA` | git |
| No path under `.github/workflows/` | A CI change by an agent needs a person, and the job's token cannot push one anyway |
| The base is a branch (`refs/heads/...`) | Something must be there for a pull request to target |

- It fetches the base into a fresh repository it created itself, with
  `GIT_CONFIG_GLOBAL` set to an empty file and `GIT_CONFIG_NOSYSTEM=1`.
- The token goes in through `GIT_CONFIG_*` environment variables as an
  `extraheader` scoped to the server, never on a command line or in a file.
- It pushes a new branch, never the base.
- The pull request is a **draft** unless the report is `ok`, and the job then
  fails, so the run is red when the work is not done.
- If the repository forbids Actions to open pull requests, it says which
  setting changes that and prints the compare link.

`agentctl run --report-json PATH` is new for this: `Report.to_json()`.
- `text` is the report exactly as printed, so the pull request and the
  terminal cannot drift apart.
- It goes into the body inside a fence one backtick longer than any run of
  backticks in the text, so what the agent said cannot close the fence.

## 3. Evidence

**`tests/test_gha.py`: 27 tests, one Linux-only.**
- The refusals each fire.
- The agent's environment holds no GitHub token: a stand-in agent records what
  it can see.
- End to end with real git and a local bare "remote":
  - the work becomes a branch with the file, and `main` is untouched;
  - a FAIL becomes a draft, and the job fails;
  - no change means no pull request;
  - a workflow edit is refused;
  - rewritten history proposes nothing;
  - a forged `meta.base` is refused;
  - a dry run pushes nothing;
  - the 403 names the setting.
- The fence, and the body size cap.
- The subreaper kills a `setsid` daemon (Linux only).
- `action.yml` holds no token and pastes no input into a `run:` line.
- **A real `agentctl run`** against `tests/scripted_model.py`, with `--accept`
  and `--report-json`, gives PASS and `files == ["hello.txt"]`.

**On GitHub, for real** (`action-test.yml`, run 37195364924, first attempt).
Each item was read from the log, not only the job status:

| Step | Result |
|---|---|
| Install from the action's source with uv | 3.4 s; `handcode 0.3.0rc1 … linux` |
| The agent, with the scripted model | `outcome PASS`, `changed 1 file +1 -0`, `needs you nothing`, 10.5 s |
| The subreaper | "leftover processes will be stopped" |
| Hand-over | `outcome=PASS commits=1` |
| A clone given an `extraheader` | **refused** with the `persist-credentials` message |
| `publish`, dry run | `1 commit(s), 1 file(s), 19ce64ee4c7e..1d459535a2f1 -> handcode/run-37195364924-1`, nothing pushed |
| The whole thing | 24 s for the run job, 5 s for publish |

**Found by that run.** `setup-uv` saved a cache at the end of the agent's job
(`cache saved with the key: setup-uv-1-x86_64-…`).
- The cache is now off (the §1 cache-poisoning row), and a test holds it off.
- The re-run (37195611011) saved no cache, still installed in **2.3 s**, and
  passed the same checks.
- The one entry saved earlier came from the scripted model, so it holds
  nothing hostile. GitHub evicts it after 7 days unused.

## 4. Left open

- **Prompt injection is contained, not prevented.**
  - A hijacked agent still holds the model key.
  - It can write anything into the bundle and the report, including a false
    PASS.
  - The guide says: review the diff as a stranger's, use a key with a spending
    limit.
- **CI does not run on the pull request.** GitHub does not start workflows for
  a push made with a workflow's own token. The report's `--accept` is the check
  that ran. A GitHub App token would fix this, and needs an app the owner
  creates.
- **The task guard looks at the event, not where the text came from.** A
  dispatch workflow could still feed in an issue's body. The guide says so.
- **No resume across jobs.** A job that times out starts over. `0051` saw
  persisting `.agentctl/` as the natural fit. But an artifact is readable by
  everyone who can read the repository, so the conversation it holds would be
  as well. That needs a decision before it is built.
- **Issue triggers** wait for I-26 (`0051` D10).

## 5. Not done this way, and why

| Alternative | Why not |
|---|---|
| One container action on the Stage 2 image | The image is unpublished, and one job is §1's problem |
| A reusable workflow (`workflow_call`) | It gives two jobs too, but a called workflow cannot reliably name its own ref, so the code it runs could differ from the workflow. Two composite actions pinned by the same `@ref` do not have this problem |
| Strip the token from `.git/config` and restore it afterwards | The agent runs while it is gone, but the restore puts it back on a machine the agent may still occupy |

## 6. For the owner

1. **A real run.** Add `OPENROUTER_API_KEY` as a repository secret, and the
   self-test can run one real task. That meets the `0041` rule.
2. **A real pull request.** "Allow GitHub Actions to create and approve pull
   requests" is **on**. The owner asked for it to be set through the API on
   2026-10-04, and reading it back gives `can_approve_pull_request_reviews:
   true` with `default_workflow_permissions: read` unchanged.
   - A workflow token still starts read-only; only a job that asks for
     `pull-requests: write` gets it.
   - The setting also lets such a job **approve** a pull request, though
     nothing in HandCode does.
   - Left: run `publish` without `dry-run`, so a real pull request is opened.
3. **`@v0`.** The guide and `examples/handcode.yml` use `csdeepak/HandCode@v0`.
   That tag should move with each `0.x` release. `RELEASING.md` can add it to
   the release steps once the first release is out.
