# The GitHub Action

Type a task in your repository's **Actions** tab and get a pull request back.
Your key stays in your repository's secrets, the commands run on GitHub's
throwaway machines, and nobody, including this project, runs a server.

> **Status.** It runs on a person's say-so only (**Run workflow**), not on
> issues or comments. The tag `@v0` arrives with the first release; until
> then, pin a commit (`csdeepak/HandCode@<sha>`).

## Set it up (five minutes)

1. **Copy the workflow.** Put [`examples/handcode.yml`](../examples/handcode.yml)
   in your repository as `.github/workflows/handcode.yml`.
2. **Set the test command.** Change `accept:` to the command that runs your
   tests. Add the steps that install what they need above the HandCode step,
   where the file says so.
3. **Add your key.** In **Settings > Secrets and variables > Actions**, add
   `OPENROUTER_API_KEY` (or another provider's key, and change the `env:`
   line to match).
4. **Let workflows open pull requests.** Turn on **Settings > Actions > General
   > Workflow permissions > "Allow GitHub Actions to create and approve pull
   requests"**. If you skip this step, the run still pushes a branch and prints
   the link that opens the pull request.
5. **Run it.** Go to **Actions > handcode > Run workflow**, type a task, and
   press the button.

The pull request's description is the end-of-run report: what was checked,
what changed, what it used and what needs you. It is a **draft** unless the
check passed and nothing waits on you.

## Why two jobs

A model reads text that can carry instructions: the task, your code, web
pages, tool output. If those instructions take over the agent, it can read
anything on the machine it runs on, including the environment of every other
process there. So the job that runs the agent holds nothing worth stealing:

| | `run` (the agent) | `pull-request` (publish) |
|---|---|---|
| Holds | your model key, a read-only checkout | a token that can push and open PRs |
| Runs | the agent, then your `accept` command | none of your repository's code |
| Machine | discarded when the job ends | a different one, also discarded |

The `run` job hands over a **git bundle** of the agent's commits and the
report. The publish job treats both as untrusted input:
- it checks that the commits build on the commit the workflow ran for;
- it **refuses a change to `.github/workflows/`**, because a CI change made by an
  agent needs a person;
- it pushes a new branch, `handcode/run-<id>-<attempt>`, and never your base
  branch.

## What it refuses, and why

| You see | Why | Do this |
|---|---|---|
| `triggered by a 'issues' event` | Issue, comment and PR text can come from anyone | Run it from **Run workflow**, `schedule` or `push` |
| `the job's GitHub token is stored in this checkout's git config` | `actions/checkout` leaves the token in `.git/config` by default, where the agent can read it | `persist-credentials: false` on the checkout step |
| `the checkout already has changes` | They would land in the pull request as the agent's work | Commit them, or add them to `.gitignore` |
| `the checkout is at ..., not ...` | The publish job checks the work against the run's commit | Check out the default ref |
| `the change edits a workflow file` | See above | Apply that part by hand from the bundle artifact |

## What else it does for you

- **The agent gets no GitHub token.** `GITHUB_TOKEN`, `GH_TOKEN`, the runner's
  own `ACTIONS_*` tokens and the files that set later steps' environment are
  all removed from the agent's environment. The model key stays, because the
  agent cannot work without it. Use a key with a spending limit.
- **Processes the agent leaves running are stopped** when it finishes, so none
  can wait for a later step's secrets. This needs Linux, and is why the action
  runs on `ubuntu-latest` only.
- **Package installs do not stop to ask** on GitHub's own runners: the machine
  is discarded after the job, as the container is (`docs/0052`). On a
  self-hosted runner they still ask, which means they queue, because nobody
  is at a terminal.

## What to know

- **CI does not run on the pull request by itself.** GitHub does not start
  workflows for a branch pushed with a workflow's own token. The report's
  `--accept` result is the check that ran; push a commit to the branch to run
  CI.
- **The report comes from the agent's machine.** It is honest unless the agent
  was taken over, in which case it can say anything. Read the diff.
- **Artifacts are as readable as the repository.** The hand-over bundle holds the
  agent's commits and the report, the same things the pull request will show.
  It is kept for one day.
- **More `agentctl run` options** go in `args:`, e.g. `args: --wait 30m` to
  wait out a free tier's rate limit, or `--max-budget 0.50`.

## Inputs and outputs

`csdeepak/HandCode` (the run job):

| Input | Default | |
|---|---|---|
| `task` | (required) | What you want done |
| `accept` | none | Your test command. Exit 0 = PASS |
| `model` | your first provider's default | A litellm model id |
| `max-iterations` | 30 | |
| `max-budget` | none | A hard USD ceiling |
| `args` | none | More `agentctl run` arguments |

Outputs: `outcome` (PASS, FAIL, `not checked`, `no report`), `ok`, `commits`,
`conversation-id`.

`csdeepak/HandCode/publish`: inputs `github-token` (the job's own by default)
and `dry-run` (`true` checks everything, prints the pull request and pushes
nothing). Outputs: `pull-request`, `branch`.
