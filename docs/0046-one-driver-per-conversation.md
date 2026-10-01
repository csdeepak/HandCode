---
Number:        0046
Title:         One Driver Per Conversation
Type:          DECISION
Status:        ACCEPTED
Created:       2026-10-01
Supersedes:    —
Superseded-by: —
Depends-on:    0016, 0038, 0042, 0045
---

# 0046 — One Driver Per Conversation

`docs/0042` I-02, built. This completes Phase 1 of `0043`.

**The rule.** Only one live process may drive a conversation.
- A crashed holder is taken over automatically.
- A live holder is refused and named, unless `--takeover` is given.
- A superseded holder cannot start an effect.

---

## 1. The defect

Three gaps added up to two drivers of one conversation:

| Gap | Where | Effect |
|---|---|---|
| The lease was never renewed | `renew()` had no callers; TTL 60 s | Any tool call longer than a minute let the lease lapse, and another process took it silently |
| `--resume` always stole it | `takeover=bool(resume)` in `runner.py` | A second terminal took over from a run that was still working |
| Fresh intents were not fenced | `write_intent` checked the fence only when a record already existed | A superseded holder's new call executed and committed (probe P2) |

`0042` §8.2 established that the SDK does not prevent this either. Its only
cross-process lock is per event append, and its state writes are unguarded. So
the two drivers would interleave a single event history.

This mattered more after `0044` §3 showed `agentctl run --resume` working
live: easy resume is easy double-driving.

## 2. What changed

| Where | Change |
|---|---|
| `store.write_intent` | Also checks the **lease table's** current fence. A superseded holder raises `StaleFence` before any record exists, and the gate turns that into BLOCK |
| `store.LeaseHeartbeat` | A daemon thread on its own connection renews every TTL/4. It renews only while it still holds the lease, so it cannot resurrect one it lost. A crash stops it with the process |
| `Guard.close()` | Stops the heartbeat and **releases** the lease, on success and on the runner's error path. The next resume needs no takeover. Idempotent |
| `runtime/lease.py` | Holders are named `run@<host>:<pid>`. `claim()` decides what a resume may do: dead holder → take over; live or unknowable → refuse and name it; `--takeover` → override, saying the holder is ALIVE if it is |
| `pid_alive` | Win32 `OpenProcess` + `GetExitCodeProcess`; POSIX `os.kill(pid, 0)`. **Never `os.kill` on Windows**, where it calls TerminateProcess. A test enforces that |
| `agentctl run --takeover` | New. Not needed after a crash on this machine |
| `protect(holder=None, heartbeat=True)` | The default holder is unique per process. The old default, `"agentctl"`, was shared by every embedder |

**Unknowable counts as alive.** That covers a holder on another host, or one
named in the pre-0046 `run-<pid>` format. Waiting is slow; stealing from a live
run is the failure.

## 3. Found on the way: opening a ledger its holder was killed holding

E-02's first run failed with `sqlite3.OperationalError: disk I/O error`. The
failure was at the open just **after** the holder was hard-killed: the
crash-then-resume path.

**Measured.**
- A holder with a heartbeat, a read by another process while it was alive,
  then kill, then open.
- 5 of 8 trials failed on the first attempt.
- Every one succeeded about 50 ms later.

Windows releases a killed process's locks on the WAL `-shm` file
asynchronously, and SQLite's recovery trips over them.

**Fix.** `store._open` retries `disk I/O error` and `database is locked` with
backoff for up to 3 s, logs the retry, and re-raises anything else
immediately. After the fix, 8 of 8 trials opened at the first call. Two tests
cover it: a transient error is retried, and a real one is not.

This predates the heartbeat. Any run killed mid-write could leave it. The
heartbeat only made a mid-write kill likelier, which is how the test found it.

## 4. Evidence

**Unit and process tests.** `tests/test_one_driver.py`, 23 tests:
- P2 as a permanent test, plus the zombie's gate failing closed;
- the heartbeat outliving its TTL, then lapsing once stopped, and never
  resurrecting a lost lease;
- liveness: this process, an exited one, and unknowable holders;
- every `claim` branch;
- the runner no longer contains `takeover=bool(resume)`;
- **E-02 with real processes.** A holder outlives twice its TTL and resume is
  refused. Then it is killed hard, and resume takes over at once.

**Mutation.** Dropping the lease check from `write_intent` fails both P2
tests.

**Suite.** 713 passed, 1 skipped. `verify.py` 10/10.

**Live, the `0041` rule.** Run A was a real `agentctl run` on
`gemini-3.6-flash` with a four-function task.

| Step | Result |
|---|---|
| B: `--resume` while A works | **Refused**, exit 1: *"being driven by run@Deepak:34836; its lease has 51s left and renews while it runs … If it is gone: add --takeover"*. A unaffected |
| A killed hard | — |
| C: `--resume` at once, no flag | **"the run that held it (run@Deepak:34836) is gone; taking over"**, fence 1 → 2 |
| C hits Gemini's per-minute quota | It released its lease on the error path |
| D: `--resume` 65 s later | No takeover needed (fence 3). Same quota error |
| Ledger across A, C and D | One non-replay-safe intent repeated: `python -m pytest -q`, three times, all OBSERVED (`0045`'s loop). No commit, so no duplicate |

The pid in the refusal is not the pid that was killed. A venv's `python.exe`
on Windows is a launcher that runs the real interpreter as a child, which
dies with it. Detection followed the real process.

**Not shown live:** the task finishing.
`GenerateRequestsPerMinutePerProject` refused both resumes. The lease
behaviour, which is the subject here, was shown; completion was not.

## 5. Left open

- **Multi-host.** A holder on another machine is refused until its TTL
  lapses, or `--takeover` is given. Correct, but nothing tests two hosts.
- **The zombie's BLOCK reason** reads *"gate error, failing closed:
  StaleFence …"*. It is accurate, but the wording is for a developer. Phase 3's
  vocabulary map should name it.
- **Phase 2 of `0043` is next**: the install path, `agentctl init`, and the
  managed proxy.
