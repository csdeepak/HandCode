# Security

agentctl runs a coding agent's shell commands on your machine and spends your
API keys. A security problem here can mean someone else's commands running, or
someone else's bill. Please report one privately.

## Reporting

Use GitHub's private vulnerability reporting: on the repository, open
**Security → Report a vulnerability**. Please do not open a public issue.

Include what you ran, what happened, and `agentctl --version`. A reproduction
that runs against the local mock provider (no key) is ideal.

## What counts

Examples of what we want to hear about:

- a way for an effect to run **twice** across a crash and resume, or to run
  at all after being refused or denied;
- an API key that is printed, logged, written into a ledger, recording or
  telemetry file, or sent anywhere other than its provider;
- a way around the confirmation for a dangerous action, or for a write
  outside the workspace;
- a prompt-injection path that gets the agent to act on a repository's
  contents, an issue or a tool's output in a way the gate should have
  stopped.

## What is a known limit, not a vulnerability

These are documented, and reports of them are still welcome as improvements:

- **agentctl is not a sandbox.** An allowed command runs with your
  permissions. Use the container image for untrusted tasks
  (`guide/quickstart.md` §6): there it reaches only the mounted repository.
  A way out of *that* boundary, through anything this project configures,
  is a vulnerability.
- A command interpreter's arguments (`python -c "..."`) are opaque to the
  classifier, so it is treated as an unrepeatable command, not inspected.
- A remote service that ignores idempotency keys can duplicate an effect,
  and nothing local can detect it.

See [`guide/concepts.md`](guide/concepts.md#what-agentctl-does-not-do).
