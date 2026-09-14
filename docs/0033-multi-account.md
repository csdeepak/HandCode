---
Number:        0033
Title:         Many Keys, Many Accounts — and a Guard That Only Existed in a Docstring
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-14
Supersedes:    partially 0032
Superseded-by: —
Depends-on:    0002, 0031, 0032
---

# 0033 — Many Keys, Many Accounts

`docs/0002` asked for *many keys and accounts across providers*. `docs/0032`
built a keys file with **one slot per provider**, which is not that. A
free-tier cap is usually per **account**, so one slot per provider caps the
whole design at one quota per vendor.

**462 tests passing** (was 443). Code: `control/providers.py`,
`control/keys.py`, `control/proxy.py`, `runtime/doctor.py`.

---

## 1. The account is the unit, not the provider

```
OPENROUTER_API_KEY        ->  openrouter
OPENROUTER_API_KEY_2      ->  openrouter#2      a second, separate quota
OPENROUTER_API_KEY_WORK   ->  openrouter#work
```

Any suffix is accepted, so a new account costs one line in the keys file and no
code change. Matching is on the exact name or the name followed by `_`, never a
bare prefix: `ANTHROPIC_BASE_URL` must not be read as an Anthropic credential,
and a stray match would send requests with a URL where a key belongs.

The proxy now builds one deployment per **account × model**. Two OpenRouter
accounts times three models is six ways to keep working, and when one account
hits its daily cap the other three keep serving — which no single-account pool
can do, however many models it lists.

## 2. Four verdicts, because two would overstate it

| accounts | providers | verdict | survives |
|---|---|---|---|
| 0 | 0 | `NONE` | nothing runs |
| 1 | 1 | `SINGLE ACCOUNT` | an outage, not a daily cap |
| 2+ | 1 | `MULTI-ACCOUNT` | a cap, **not** the provider going down |
| 2+ | 2+ | `READY` | both |

`MULTI-ACCOUNT` exists because folding it into `READY` would tell someone with
two OpenRouter keys they are covered against an outage they are not covered
against. That distinction is the entire reason for counting credentials rather
than providers.

## 3. Deployment ids had to be rebuilt

Deriving an id from the account label gave `openrouter-2` (account 1, model 2)
sitting next to `openrouter-2-0` (account 2, model 0). Unique, and unreadable
exactly when you are debugging a fallback map. Ids are now `provider-aN-mI`,
both parts always present and labelled, nothing abbreviated — `openrouter` and
`openai` share a prefix, which had already caused one collision.

## 4. The template

`agentctl keys --init` writes every provider, its console URL, numbered steps, a
live slot and two commented ones showing the convention. It is `chmod 600` where
that means anything, never overwrites a filled file, and **parses to nothing** —
every slot ships empty, so a freshly written template cannot accidentally
configure anything.

## 5. "Outside any repository" was false on the machine that wrote it

`--init` defaults to `~/.agentctl/keys.env`, and `docs/0032` justified that as
being outside any repo: *"a gitignore rule is a promise, a different directory
is a fact."* Checked rather than assumed:

```
C:/Users/csdee/.agentctl   ->   git toplevel: C:/Users/csdee
```

The home directory **is** a repository, with an unrelated remote — the hazard
this project flagged on its first day. The file was not ignored there, and
`--init` had written its ignore rule into the *openhands* repo, which cannot
protect a file that does not live in it.

Two fixes, and the second is the more useful:

- `ensure_ignored` now targets the repository that **contains** the keys file,
  found with `git rev-parse --show-toplevel` from the file's own directory.
- `check_not_tracked` gained a second state. "Tracked" is the accident; **"in a
  repo and not ignored" is the moment before it**, and that is the one worth
  catching. A test that previously asserted an un-ignored file in a repo was
  *fine* now asserts it is flagged — the old test encoded the weaker guarantee.

> A safety claim about the filesystem is a claim about one machine. Assert it,
> do not assume it.

## 6. A guard that existed only in a docstring

`keys.py` documented three guards. The third — *"`doctor` calls the same
check"* — was not wired anywhere. It read as true, it had been written down,
and nothing executed it.

Eighth instance in this repository of the same family: something that looks
like protection and cannot fail, or here, cannot even run. `doctor` now reports
the keys file, and an exposed one is `XX` (blocking), not a warning.

## 7. Consequences

- `docs/0032` §3 is superseded on the location claim and on guard 3.
- `docs/0012` §6 → new rule: a docstring claiming a guard exists is a claim to
  be tested, not documentation to be trusted.
- `agentctl keys`, `dash` and `doctor` all count accounts, never providers.
- Still true, and no code can change it: two accounts at one provider do not
  survive that provider going down.
