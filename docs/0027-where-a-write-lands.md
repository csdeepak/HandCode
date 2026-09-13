---
Number:        0027
Title:         Where a Write Lands Is Not What Kind of Write It Is
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-13
Supersedes:    —
Superseded-by: —
Depends-on:    0025, 0026
---

# 0027 — Where a Write Lands Is Not What Kind of Write It Is

`echo x > ~/.bashrc` classified `IDEMPOTENT_WRITE` and no confirmation fired.
The classification was **correct**. The gap was somewhere else entirely.

**305 tests passing** (was 264). Code: `kernel/paths.py`.

---

## 1. The hole

`docs/0026` fixed the classifier and, in doing so, showed its limit. Running
the corpus surfaced this pair:

```
echo x > ~/.bashrc          IDEMPOTENT_WRITE    no prompt
cat a.txt > b.txt           IDEMPOTENT_WRITE    no prompt
```

Identical class, and rightly so — replacing a file's whole contents *is*
idempotent, whichever file it is. But one of those writes a scratch file in the
workspace and the other rewrites the operator's shell startup script.

`agentctl run` sets the subprocess `cwd` to the workspace, which stops nothing:
an absolute path, a `~`, or `../..` walks straight out. **The agent could write
anywhere on the filesystem and the gate had no opinion about it.**

## 2. The fix I did not make

The quick version is to escalate the class — make a write outside the root
`DESTRUCTIVE` so the existing prompt fires. One line, and wrong.

`EffectClass` is what the **ledger** consults to decide whether replaying an
effect is safe. `DESTRUCTIVE` means *this cannot be safely repeated*. But
`cp a.txt /tmp/b.txt` repeats perfectly well; it is simply none of the agent's
business. Escalating it would have taught the ledger something false, and a
resume that should have replayed cleanly would have started failing closed.

It would also have collapsed the distinction `0025` §4 went out of its way to
draw:

```
the gate         stops an effect happening TWICE      -- replay safety
confirmation     stops it happening AT ALL unasked    -- authorization
```

**Where a write lands is an authorization question.** It says nothing about
whether the write can be repeated. So the effect class stays honest, and the
confirmation layer gained a second, independent reason to ask.

## 3. What counts as a write target

`kernel/paths.py` collects only unambiguous write destinations: the declared
path argument of a structured tool, a shell redirect target (`>`, `>>`, `tee`),
and the operands of commands whose whole purpose is to mutate a named file.

**Read paths are deliberately not collected.** `grep secret /etc/shadow` reads
outside the workspace, which is a real concern and a *different* one —
exfiltration, not authority over the machine. Half-covering it would be worse
than not claiming to.

Two details that a simpler implementation gets wrong:

- **`~` must be expanded first.** Unexpanded, `~/.bashrc` is a relative path
  that joins onto the workspace and looks perfectly safe. That is the exact
  case that prompted this document.
- **Containment is `PurePath.relative_to`, not `str.startswith`.** `/work` and
  `/work-evil` share a string prefix but not a path.
- **`cp` and `mv` write only their last operand.** Collecting every operand
  would flag `cp /etc/hosts ./local` — a read from outside, copied *in* — as an
  unauthorised write. By §5's own argument that is a bug, not a safe default.

## 4. Lexical resolution, on purpose

`Path.resolve()` follows symlinks, and for this check that is the wrong
direction to be wrong in:

| | `resolve()` | lexical |
|---|---|---|
| link inside → outside | reported | reported |
| link outside → **back inside** | **waved through** | reported |

A symlink planted outside the workspace that points back in would satisfy a
resolving check while the write still lands wherever the link says. Lexical
normalisation cannot be tricked that way. The cost is that a benign symlink
inside the workspace reads as an escape — the safe error.

## 5. Over-prompting is a security bug

Half the tests assert that ordinary work is **not** flagged: `cat a.txt > b.txt`,
`echo x >> notes.md`, `mkdir -p build`, `ls 2>&1`.

That is not politeness. An operator who is asked to confirm `du -sh .` learns
to answer `y` without reading, and at that point the confirmation has been
disabled by a mechanism nothing in the system can observe. The same reasoning
put 15 inspection commands on the read list in `0026` §5.

A prompt that is always right is worth less than a prompt that is rare.

## 6. Still open

- **Reads are not covered.** By design, per §3 — but an agent that can read
  `~/.aws/credentials` and then make an `EXTERNAL` call has exfiltrated them,
  and nothing here notices.
- **Regex, not a shell parser.** Inherited from `0026` §6, same fix
  (`bashlex`), same limitation.
- **An interpreter is opaque.** `python -c "open('/etc/x','w')"` reports no
  write target. Only a sandbox answers this.
- **The workspace is the only boundary.** There is no notion of a path inside
  the workspace being more sensitive than another — `.git/config` is treated
  like any other file.

## 7. Consequences

- `0025` §4 → the replay/authorization split is now load-bearing, not
  descriptive: it is why the class is not escalated.
- `0026` §6 → "no sandbox" keeps its place as the first-listed limitation; this
  narrows it without closing it.
- `runtime/runner.py` → `--confirm-destructive` asks on two grounds, and the
  prompt says which.
