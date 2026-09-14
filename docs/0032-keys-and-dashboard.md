---
Number:        0032
Title:         One Registry, One Keys File, One Screen
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-14
Supersedes:    —
Superseded-by: —
Depends-on:    0001, 0021, 0029, 0031
---

# 0032 — One Registry, One Keys File, One Screen

`docs/0001` is about surviving a rate limit without work stopping. `docs/0031`
§6 found the install had **one** provider key, so there was nowhere to survive
*to*. This is the part that fixes that: somewhere to put many keys, a list of
where to get them, and one screen that says whether failover is real yet.

**443 tests passing** (was 413). New: `control/providers.py`, `control/keys.py`,
`control/dash.py`; `agentctl keys`, `agentctl dash`.

---

## 1. Three provider lists

`doctor` had one. `proxy` had another. Adding a third for the keys file would
have made three copies of the same facts — and `docs/0029` §4 already records
what two copies do: they drift, and drift here means a key you added is checked
by one command and ignored by another.

`control/providers.py` is now the only list. `doctor` and `proxy` derive from
it, and a test asserts their sets match rather than eyeballing it.

## 2. What the registry deliberately does not record

Env var, console URL, model prefix, known-good model ids. Those are stable.

**Not rate limits, token allowances, or whether a card is required.** A survey
of the free-tier landscape in September 2026 turned up, within three months:
Cerebras moving to a card-backed trial, GitHub Models shutting down, Groq
dropping Llama from its free plan, and Together ending trial credit. Two
sources disagreed with each other about Cerebras on the same day, and one
asserted every OpenRouter free model had become paid — which is flatly
contradicted by this project having used one the day before.

Numbers written into source would be confidently wrong within weeks, and a user
planning around a quota that no longer exists is worse off than one who was
told to go and look. A test asserts the registry body contains no
`requests/day` or `tokens/day` string, so this does not quietly erode.

Console URLs were taken from primary documentation, not from the survey posts.

## 3. The keys file, and the guard that actually matters

`agentctl keys --init` writes `keys.env`: every provider, the console URL, the
numbered steps, and a blank to fill in. Every command loads it at startup, an
already-exported variable wins, and **no command ever prints a value** —
`agentctl keys` says `set (73 chars)`.

Display was never the real risk. `git add -A` is.

> **A `.gitignore` entry added after a file is already tracked does nothing.**

That is precisely how keys get published: the rule is present, everyone assumes
it works, and the file was staged before it existed. So there are three
independent guards, and the ordering of the first is deliberate:

1. `--init` writes the ignore rules **before** it writes the file
2. `load()` raises `KeysAreTracked` if the file is tracked by git, and says to
   rotate every key in it because they must now be assumed public
3. `doctor` calls the same check, so the warning surfaces when nobody is
   thinking about keys

The CLI's startup path uses `load_quietly`, which downgrades the refusal to a
loud warning. Refusing to run at all is the safer-feeling reflex and the wrong
one: the key is already exposed, and blocking the user from their own tool does
not un-expose it. Being loud does.

## 4. The parser has no interpolation, on purpose

`KEY=sk-or-v1-$HOME-literal` stores that string. A `$` inside an API key is a
character, and a parser that expanded it would silently mangle a valid key into
an invalid one — a failure that would present as "the provider rejected my key"
and waste an afternoon.

## 5. One screen

`agentctl dash` shows failover verdict, providers, effects, spend and policy;
`--html` writes a self-contained page with no CDN, no fonts and no scripts, so
it opens from `file://` and can be handed to someone.

Every panel is **derived**, and a panel with nothing behind it says so:

```
SPEND
  (none)   no cost ledger at cost.db — run: agentctl ingest <telemetry>
```

not `$0.00`. `docs/0021` §5 is the reason — a zero that means "no data" reads
as good news, which is the direction that costs you something.

The headline is the verdict this project exists to deliver:

```
FAILOVER   SINGLE ACCOUNT
           only openrouter. A per-model limit or a transient outage is
           survivable; an account-wide daily cap is not — there is
           nowhere to go.
```

## 6. Two bugs found while building it

**The `note:` label never rendered.** The template compared wrapped chunks with
`is`, which is identity on strings and was never true, so every note printed
unlabelled. Replaced with an index.

**Deployment ids could collide.** Deriving short ids from a name prefix gave
`openrouter` and `openai` both `op-`. Those ids are what `fallbacks` points at,
so a collision would silently send a failover to the wrong provider. Ids are
now `{provider}-{n}`, and `_validate` asserts uniqueness — with a test proving
that assertion can fire.

## 7. Consequences

- `docs/0031` §6 → the missing half is here: somewhere to put the keys, and a
  screen that says whether you have enough of them yet.
- `docs/0012` §6 → new rule: facts that live in two modules must live in one
  and be derived, with a test asserting they agree.
- `README` → `agentctl keys` and `agentctl dash`.
- Still true: one account survives an outage, not an account-wide daily cap.
  Only a second provider fixes that, and no code in this repository can create
  one for you.
