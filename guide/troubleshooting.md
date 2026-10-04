# Troubleshooting

Search this page for the exact text agentctl printed.

---

### `ERROR: Could not find a version that satisfies the requirement openhands-sdk`

Your Python is older than 3.12. The error does not say so; it lists a hundred
versions that need `Requires-Python >=3.12`. Check with `python --version`. On
Windows, use `py -3.12 -m venv .venv`.

### `OSError: [Errno 2] No such file or directory` during install, with a hint about *Long Path support*

Windows' 260-character path limit. The install unpacks one file 139
characters deep inside `.venv`, so clone into a short path such as
`C:\src\HandCode`.

### `python: command not found` / `ensurepip is not available` (Ubuntu)

Use `python3`, and install the venv module: `sudo apt install python3.12-venv`.

---

### `no model: no flag, no AGENTCTL_MODEL, no config, and no key to derive one from`

Run `agentctl init`.

### `<provider> cannot serve a request: ...` from `agentctl init`

The key was found, but a test request failed. The message gives the
provider's own reason. A `401` means the key is wrong; copy it again from the
provider's console. Nothing was changed except saving the key.

### `the provider is rate limiting you. This is not an agent error.`

You hit a free-tier limit. The work is saved.
- Wait for the reset, then `agentctl resume`.
- Or start with `--wait 30m`, and agentctl waits and resumes on its own.
- Or add a key at a second provider and use `--pool`.

An OpenRouter `free-models-per-day` cap covers every `:free` model on that
account, so switching model does not help.

### `the provider rejected the request — usually an unknown or unavailable model id.`

The model id no longer exists, or lacks its provider prefix (for example
`openrouter/vendor/model:free`). Run `agentctl init` again: it checks which
model actually answers.

### `the provider says the account is out of credit.`

The account needs credit for this model. Free-tier models do not; run
`agentctl init` to pick one that answers.

---

### `conversation ... is being driven by run@...; its lease has Ns left`

Another process is still running this conversation. Let it finish, or stop it.
If you know it is gone (it ran on another machine, say), add `--takeover`.

### `paused      by you. Continue:  agentctl resume <id>`

You pressed Ctrl-C. Nothing is lost. Run the command it shows.

### `needs you   1 action waiting for your approval:`

A dangerous action was queued because nobody was at a terminal to ask.
`agentctl approve <id>` or `agentctl deny <id>`, then `agentctl resume`. The
agent is told what you decided.

### `!! installs into your environment: pip install ...`

The agent wanted to install software into an environment outside your
repository, usually the Python on your PATH. Say `y` if that is fine. Better
options:
- let it install into a virtual environment *inside* the repository
  (`.venv/bin/pip install ...` does not ask);
- or run the task in the container (`quickstart.md` §6), where installs
  cannot reach your machine.

### `needs you   N action(s) whose outcome is unknown: agentctl blocked`

A crash left an action whose result nobody can confirm. `agentctl blocked`
lists them, and `agentctl show <id>` gives the details. If it happened, run
`agentctl resolve <id> --landed`; if it did not, run `--retry`.

### `<id> is not waiting for approval (BLOCKED). ... answered with agentctl resolve.`

`approve` is for actions that asked permission. This one is an *unknown
outcome*; use `resolve`.

### `outcome     not checked`

You did not pass `--accept "<test command>"`, so agentctl did not check the
result. That is not a failure. It means nothing checked.

### `outcome     FAIL`

Your `--accept` command did not exit 0 after the agent finished. The last lines
of its output are printed under it. The agent believed it was done, so resuming
the same conversation gives it nothing new to do. Start a run that says what is
still wrong instead:
`agentctl run "the tests still fail: <the failing line>" --accept "<same command>"`.

---

### `something not started by agentctl answers on port 4000`

Another program, perhaps a proxy you started by hand, is using the port.
Stop it, or use `agentctl proxy up --port 4001`.

### `no provider can serve right now -- nothing to pool.`

Every key failed its check. `agentctl keys --check` says why, per provider.

### `the proxy exited during startup`

The last lines of its log follow the message. The full log is at
`~/.agentctl/proxy/proxy.log`.

---

### `the demo could not run the ... arm`

The demo's own run failed before it could show anything. That is a broken
install, not a result. Run `agentctl doctor`.

### `The demo did NOT show what it claims`

Please report it, with `agentctl demo --keep` and the folder it prints.

---

### `handcode: refused: ...` (in a GitHub Actions log)

The GitHub Action stopped before the agent started, or before it opened a pull
request. Each refusal says what to change. The table in
[github-action.md](github-action.md#what-it-refuses-and-why) says why each one
exists.

### `the branch is pushed, but GitHub did not let the workflow open the pull request`

The repository does not let workflows open pull requests. Turn on *Settings >
Actions > General > Workflow permissions > "Allow GitHub Actions to create and
approve pull requests"*, or use the link printed below the message.
