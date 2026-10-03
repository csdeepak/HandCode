# Concepts, in plain words

## What goes wrong without agentctl

A coding agent runs for minutes or hours and does real things: it writes
files, runs commands, makes commits. Its process can die at any moment: a
crash, a closed laptop, a killed terminal, a provider that stops answering.

When you resume, the agent framework re-runs whatever action was in flight.
If that action had already happened, it now happens **twice**: two commits,
two appended lines, two API calls. `agentctl demo` shows exactly this.

## What agentctl does about it

Every action the agent takes is written to a **ledger** before it runs, and
updated after. The ledger is a small database in your workspace, at
`.agentctl/ledger.db`; git never sees it.

When a resumed run tries an action again, agentctl checks the ledger first:

| What the ledger says | What happens |
|---|---|
| It never ran | It runs |
| It ran, and the agent saw the result | The agent's decision: it runs again (re-running your tests is normal) |
| It ran, but the result was lost in the crash | The agent gets the result back. The action does **not** run again |
| Nobody can tell whether it ran | agentctl asks the world, for example "did HEAD move?" for a commit. If it still cannot tell, it **stops and asks you** |

The last row is the rule underneath everything else. When agentctl cannot tell
whether an action happened, it refuses rather than guesses.

## Kinds of action

agentctl sorts actions by what repeating them would do:

| Kind | Example | Safe to repeat? |
|---|---|---|
| read | `cat`, `ls`, reading a file | yes |
| file write | writing a whole file | yes: the same content again |
| command | `git commit`, `python script.py`, `curl -X POST` | **no**: it might do the thing twice |
| dangerous command | `rm -rf`, `git push --force` | no, and it asks you first |

Interpreters (`python -c ...`) are counted as commands: agentctl cannot see
what they will do.

## Two questions it may ask you

They are different questions, so they use different commands:

- **"May this dangerous action run?"** Asked before an `rm -rf`, a write
  outside your workspace, or installing software into your environment
  (`pip install`, `npm install -g`, `apt install`, `brew install` and the
  like). An install into a virtual environment inside the repository does not
  ask, and nothing asks inside the container, where an install cannot reach
  your machine. With a terminal, it asks there. Without one, the
  action is queued, and you answer with `agentctl approve <id>` or
  `agentctl deny <id>`, then `agentctl resume`.
- **"Did this action happen?"** Asked only when a crash left it truly
  unknown. `agentctl show <id>` tells you everything recorded about it. Then
  answer with `agentctl resolve <id> --landed` (it happened) or `--retry` (it
  did not).

## One driver per conversation

Only one process may drive a conversation at a time. If a run is still going
in another terminal, `agentctl resume` refuses and tells you which process holds
it. If that process is gone, resume takes over without asking.

## What agentctl does not do

Said plainly, because a safety tool that oversells itself is worse than none:

- **It is not a sandbox.** Commands run on your machine. agentctl decides
  whether an action may run *again*, and asks before dangerous ones. It does
  not contain what an allowed command does. Do not point it at a task you
  would not trust a junior developer's shell with, **or run it in the
  container** ([quickstart §6](quickstart.md#6-run-it-in-a-container-recommended-for-tasks-you-would-not-trust-your-shell-with)).
  There, only the mounted repository is reachable.
- **It cannot see inside a remote service.** If a remote API ignores
  idempotency keys, a retry there can duplicate, and nothing local can know.
- **It does not make the model better.** A weak free model still writes weak
  code. `--accept` tells you whether it worked.
