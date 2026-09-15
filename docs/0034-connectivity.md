---
Number:        0034
Title:         31 Keys, and Four Ways a Check Can Lie
Type:          DECISION
Status:        ACCEPTED
Created:       2026-09-15
Supersedes:    —
Superseded-by: —
Depends-on:    0002, 0032, 0033
---

# 0034 — 31 Keys, and Four Ways a Check Can Lie

31 credentials across 6 providers, every one distinct, every one live. The
charter's premise — *many keys, many accounts* — is true for the first time.

Getting to a truthful answer took four corrections, and every one of them was a
**measurement** that was wrong rather than a key that was.

**480 tests passing** (was 462). New: `control/probe.py`, `tests/conftest.py`.

---

## 1. Count the credentials, not the slots

31 slots were filled. Six per provider, identical lengths within each provider —
which is equally consistent with six accounts and with one key pasted six times,
and those differ completely in what they buy.

Compared by SHA-256 digest rather than by eye: **31 distinct values, no
duplicates.** Never displayed, only hashed.

## 2. Validate for nothing

Every provider has a metadata endpoint that authenticates the caller and
returns no completion. So 31 keys cost **zero tokens and zero quota** to check.
The obvious alternative — a one-token completion each — would have burned 31 of
a 50-request daily allowance to ask whether the keys were real.

## 3. A CDN 403 is not a rejected key

The first run reported all six Cerebras and all six Groq keys as `rejected`,
HTTP 403. A uniform failure across two entire providers, while 19 others
worked, points at the client.

```
HTTP 403   error code: 1010
```

Cloudflare, not authentication. Both providers sit behind it and it refuses
Python's default `User-Agent: Python-urllib/3.x`. **The API never saw those
requests.** Reporting them as bad keys would have sent someone to rotate twelve
working credentials.

Fixed by identifying the client honestly, and by teaching the checker that a
403 whose body names a CDN is a transport failure wearing an authentication
failure's clothes.

## 4. The model list is not the list of models you can call

`gemini-2.5-flash` appears in Gemini's own `/models` response and returns 404
when called:

> *"This model models/gemini-2.5-flash is no longer available to new users.
> Please update your code to use models/gemini-3.6-flash."*

Groq was worse: `llama-3.3-70b-versatile` — the id the registry shipped — is not
in their catalogue at all any more. Every model id is now one that answered a
real completion, not one that appeared in a list.

> A catalogue says what exists. Only a call says what *you* can use.

## 5. Authenticating is not being allowed to infer

Six Cerebras keys list models happily. Every completion returns *"Payment
required to access this resource."* `live` would be a true statement about
authentication and a false one about usability — the misleading-verdict shape
this project keeps finding.

`no-credit` is now its own verdict, and `agentctl proxy --verify` leaves such a
provider out of the pool entirely. Left in, six dead deployments failed ~11% of
requests with an HTTP 402 that litellm does not retry.

## 6. A diagnostic that bills you is a bad diagnostic

The first inference check called **every** provider — including Anthropic,
which is paid. `docs/0002` §5 says never silently spend, and I wrote a command
that did. Cost was a few tokens; the principle is the point. Paid providers are
now skipped unless `--check-paid` is passed.

## 7. Failover comes from the model group, not from `fallbacks`

The generated config had `fallbacks` pointing at `model_info.id` values.
litellm maps model **groups** — its own example is
`[{"azure-gpt-3.5-turbo": "openai-gpt-3.5-turbo"}]` — so those resolved to
nothing.

The fix is not to correct the ids. Every free deployment shares `model_name:
pool`, and *that shared group* is what the router retries across, cooling down
whichever deployment just failed. `fallbacks` is left out entirely, because
`paid` is a group you ask for by name rather than one you arrive at by failing.

48 deployments across 24 verified accounts, in one group. A key that hits its
daily cap is skipped for `cooldown_time` while 47 keep serving.

## 8. The cp1252 banner, for the fifth time

The proxy died on startup with `UnicodeEncodeError` in `click.echo` — the
litellm banner, on a redirected Windows console. `docs/0012` §6 has required
`PYTHONUTF8=1` on redirected subprocesses since M0, and the generated output
did not set it.

`agentctl proxy` now writes `start.sh` and `start.ps1` that force UTF-8 and
embed the absolute path to this interpreter's `litellm` — a launcher that
requires an activated virtualenv is a launcher that fails the first time it is
used, which this one also did.

## 9. The tests were order-dependent

Eight tests failed together and passed individually. `keys.load()` writes into
`os.environ`, and `monkeypatch.delenv` on a variable that never existed has
nothing to restore — so a value written afterwards survived into the next test.

Found by an autouse hook that printed leaked names after each test, not by
reasoning. `tests/conftest.py` now snapshots and restores every
credential-shaped variable.

## 10. A safety sweep that cried wolf, read after the push

The commit for this document ran a grep for key-shaped strings and reported a
match. It was a test placeholder — `sk-or-v1-NEVERSHOWTHIS0000000000` — and a
comparison against all 31 live values confirmed nothing real had leaked.

Two failures there, and the second is the worse one:

* **The sweep matched a shape, not a secret.** A regex for
  `sk-[A-Za-z0-9]{20,}` flags every fixture in every test file. A check that
  cries wolf gets ignored, which is worse than no check because it is mistaken
  for protection.
* **The sweep and the push were the same command**, so its output arrived
  after the push. A check whose result you read afterwards is not a check.

Both are now fixed by the same thing: `agentctl keys --install-hook` writes a
git `pre-commit` hook that compares staged content against **the keys you
actually hold** and refuses the commit. Verified by staging a file containing
a real key:

```
COMMIT BLOCKED: these keys appear in the staged changes:
    OPENROUTER_API_KEY
Remove them, then commit. If one was already pushed, rotate it.
```

The placeholder passes; the real key does not. And it runs *before* the commit
exists, which is the only moment at which the answer is useful.

## 11. Consequences

- `docs/0012` §6 → a generated launcher must set the encoding itself; the rule
  existed and the generator ignored it.
- `docs/0033` → registry model ids are now verified by call, not by catalogue.
- Cerebras is live but cannot infer without payment; it is excluded by
  `--verify` and will return on its own if that changes. No code records the
  tier, because the tier keeps changing.
- `README` → `agentctl keys --install-hook` is the first thing to run after
  filling the file in.
- **Remaining honest gap:** `--verify` tests one account per provider and
  assumes the tier is account-wide. If one of six keys at a provider were
  downgraded individually, this would not notice.
