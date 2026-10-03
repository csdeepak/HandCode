# FAQ

**Does it cost anything?**
agentctl itself is free. What you pay is what your provider charges. With a
free-tier key the report says `$0.00 (free-tier model)`. A list price litellm
attaches to a free call is labelled as such, and not counted as spend.

**Does it send my code anywhere?**
Only to the model provider you configured, which is what any coding agent
does. Your keys stay in `~/.agentctl/keys.env` and are never printed or
logged. The ledger, the run index and recorded conversations stay on your
machine.

**Which model should I use?**
Whatever `agentctl init` recorded is a model that answered. Stronger models
write better code. agentctl does not change that, and `--accept` tells you
whether a run worked.

**Can I use more than one key at the same provider?**
agentctl accepts them, but whether a second key there is a second quota is
**unverified**: OpenRouter's own documentation says extra accounts do not
change rate limits. Pooling several free accounts may also break a provider's
terms. A key at a *second provider* is the reliable way to survive a cap.

**Is it a sandbox?**
No. Commands run on your machine. agentctl asks before dangerous ones and stops
actions from repeating across a crash, but an allowed command does whatever it
does. See [concepts.md](concepts.md).

**What happens if I run two terminals on the same task?**
The second `agentctl resume` refuses and names the process that holds the
conversation. Two drivers of one conversation is the thing agentctl exists to
prevent.

**Why did my test re-run not get blocked?**
Because the agent had already seen the first result, re-running is its
decision. That is the normal edit, test, re-test loop. agentctl only stops an
action from repeating when a crash, not the agent, would repeat it.

**Where is everything kept?**

| What | Where |
|---|---|
| Keys | `~/.agentctl/keys.env` |
| Default model | `~/.agentctl/config.toml` |
| Every run | `~/.agentctl/runs.db` |
| The pool's own environment | `~/.agentctl/proxy-env` |
| A workspace's ledger and conversations | `<workspace>/.agentctl/`, ignored by git |

**How do I check that it works on my machine?**
`agentctl demo` in a minute. `python verify.py` from a clone runs the whole
correctness suite, in about five minutes, at no cost.
