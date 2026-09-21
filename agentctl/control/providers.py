r"""One registry of providers. The single source of truth.

`doctor` listed providers. `proxy` listed providers. Two lists, maintained
separately, which is precisely the defect `docs/0029` §4 recorded: they drift,
and drift here means a key you added is checked by one command and ignored by
another. Everything now reads this module.

## What is recorded, and what deliberately is not

Recorded: the env var, the console URL where a key is made, the litellm model
prefix, and a known-good model id. Those are stable.

**Not recorded: rate limits, token allowances, or whether a card is required.**
Those change constantly — a survey in September 2026 found Cerebras had moved
to a card-backed trial, GitHub Models had shut down, and Groq had dropped Llama
from its free plan, all since June. Writing today's numbers into source would
produce a file that is confidently wrong within weeks, and a user trusting it
would plan around a quota that no longer exists.

So the registry says where to get a key and what to call it. What the key is
worth, you find out from the provider, and `agentctl doctor` reports what it
can actually observe.

Sources for the console URLs, checked against primary documentation:
  Gemini    https://ai.google.dev/gemini-api/docs/api-key
  Cerebras  https://inference-docs.cerebras.ai/introduction
  Groq      https://console.groq.com/docs/quickstart
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Provider:
    key: str                     # environment variable
    name: str                    # short name used in output
    console: str                 # where a key is created
    prefix: str                  # litellm model prefix
    models: tuple[str, ...]      # known-good ids, cheapest/freest first
    free_tier: bool              # has offered a no-card free tier
    #: Does a second key here buy a second quota?
    #:
    #: True everywhere except Gemini, and the exception is the point. The
    #: multi-account design assumes a cap is per credential (`docs/0033`), so
    #: a second key is a second allowance. Google bills per PROJECT, and keys
    #: minted in one project share one limit -- measured 2026-09-21 against
    #: this owner's six, all in a single project.
    quota_per_key: bool = True
    note: str = ""
    steps: tuple[str, ...] = field(default_factory=tuple)

    @property
    def configured(self) -> bool:
        return bool(os.environ.get(self.key))

    @property
    def default_model(self) -> str:
        return f"{self.prefix}{self.models[0]}" if self.models else ""


PROVIDERS: tuple[Provider, ...] = (
    Provider(
        key="OPENROUTER_API_KEY", name="openrouter",
        console="https://openrouter.ai/settings/keys",
        prefix="openrouter/",
        # `deepseek/deepseek-chat-v3.1:free` was here and is gone: absent from
        # `/api/v1/models` entirely, and a call returns 404 "This model is
        # unavailable for free. The paid version is available now". Six of the
        # eighteen OpenRouter deployments pointed at it (2026-09-21).
        #
        # Its replacement was chosen by a real completion, not by the
        # catalogue — `thinkingmachines/inkling:free` is listed and 403s,
        # which is `docs/0034`'s "a catalogue is not what you can call"
        # happening again on the same provider.
        models=("nex-agi/nex-n2.5-pro:free",
                "nvidia/nemotron-3-super-120b-a12b:free",
                "nvidia/nemotron-3-ultra-550b-a55b:free"),
        free_tier=True,
        note="One account-wide cap covers every `:free` model, so extra "
             "OpenRouter models add resilience to outages but not to the "
             "daily limit.",
        steps=("Sign in at openrouter.ai (Google/GitHub works).",
               "Open Settings -> Keys.",
               "Create Key, name it `agentctl`, copy it once — it is not "
               "shown again.",
               "Leave the credit limit blank to stay on free models only."),
    ),
    Provider(
        key="GEMINI_API_KEY", name="gemini",
        console="https://aistudio.google.com/apikey",
        prefix="gemini/",
        # Verified by a real completion, not by the model list: `models`
        # still advertises gemini-2.5-flash, and calling it returns "no
        # longer available to new users" (`docs/0034` §5).
        models=("gemini-3.6-flash",),
        # UNVERIFIED FOR THIS ACCOUNT SET, and it matters more here than
        # anywhere else in this file. Google's rate-limit documentation
        # (ai.google.dev/gemini-api/docs/rate-limits, read 2026-09-21) states:
        #
        #     "Rate limits are applied per project, not per API key."
        #
        # Every other provider in this registry bills a quota per KEY, which
        # is the entire premise of the multi-account design (`docs/0033`): a
        # second key at the same provider buys a second quota. For Gemini that
        # premise may simply be false. Six keys minted inside ONE AI Studio
        # project share ONE quota, and `accounts_for()` would then report six
        # where there is one -- overstating failover by 6x on the dashboard
        # and filling the pool with six deployments that all die together.
        #
        # This is not asserted either way, because it is not measured. It
        # depends on how the keys were created, which only the owner can see:
        # aistudio.google.com/apikey lists each key's project. The free tier's
        # per-model numbers are no longer published at all -- the docs now
        # say to read them at aistudio.google.com/rate-limit, which needs a
        # Google sign-in.
        free_tier=True,
        # Six keys, one project, one quota. Confirmed by the owner in AI
        # Studio on 2026-09-21 after Google's docs stated the rule.
        quota_per_key=False,
        note="Independent of OpenRouter's quota, so it survives that outage "
             "— but all keys in ONE Google project share ONE limit, so extra "
             "Gemini keys do not add allowance the way a second key elsewhere "
             "does.",
        steps=("Open aistudio.google.com/apikey and accept the terms.",
               "A default Google Cloud project is created for you.",
               "Create API key, then copy it.",
               "Quotas are per-model; check the console for current limits."),
    ),
    Provider(
        key="MISTRAL_API_KEY", name="mistral",
        console="https://console.mistral.ai/api-keys",
        prefix="mistral/",
        models=("ministral-3b-latest", "mistral-small-latest"),
        free_tier=True,
        note="The free tier has historically required opting in to data "
             "training. Read the consent screen before accepting.",
        steps=("Sign up at console.mistral.ai.",
               "Activate the free/Experiment plan if prompted.",
               "Open API Keys -> Create new key."),
    ),
    Provider(
        key="CEREBRAS_API_KEY", name="cerebras",
        console="https://cloud.cerebras.ai",
        prefix="cerebras/",
        models=("gpt-oss-120b",),
        free_tier=True,
        note="Very fast inference. Whether a card is required has changed at "
             "least once in 2026 — check at signup.",
        steps=("Sign up at cloud.cerebras.ai.",
               "Open API Keys -> Create API Key."),
    ),
    Provider(
        key="GROQ_API_KEY", name="groq",
        console="https://console.groq.com/keys",
        prefix="groq/",
        # Groq no longer serves Llama on this tier; these are what the
        # account actually lists AND answers.
        models=("openai/gpt-oss-20b", "openai/gpt-oss-120b"),
        free_tier=True,
        note="Model availability on the free plan has changed during 2026; "
             "confirm the model id in the console before relying on it.",
        steps=("Sign up at console.groq.com.",
               "Open Keys -> Create API Key."),
    ),
    Provider(
        key="ANTHROPIC_API_KEY", name="anthropic",
        console="https://console.anthropic.com/settings/keys",
        prefix="anthropic/",
        models=("claude-sonnet-5",),
        free_tier=False,
        note="Paid. Listed last everywhere so a fallback degrades toward "
             "slower, never silently toward billed (`docs/0002` §5).",
        steps=("Sign in at console.anthropic.com.",
               "Add billing, then Settings -> API keys -> Create key."),
    ),
    Provider(
        key="OPENAI_API_KEY", name="openai",
        console="https://platform.openai.com/api-keys",
        prefix="openai/",
        models=("gpt-4o-mini",),
        free_tier=False,
        note="Paid.",
        steps=("Sign in at platform.openai.com.",
               "Add billing, then API keys -> Create new secret key."),
    ),
)

BY_KEY = {p.key: p for p in PROVIDERS}
BY_NAME = {p.name: p for p in PROVIDERS}


@dataclass(frozen=True)
class Account:
    """One credential. Not one provider — a provider can have several.

    This is the unit the whole project turns on. `docs/0002` asked for many
    keys across many accounts, and an account-wide daily cap is beaten by a
    second *account*, not by a second model. Counting providers instead of
    credentials would report failover as ready when it is not.
    """
    provider: Provider
    env: str                     # the variable actually holding it
    label: str                   # "openrouter" or "openrouter#2"

    @property
    def value(self) -> str:
        return os.environ.get(self.env, "")


def accounts_for(p: Provider, env: dict | None = None) -> list[Account]:
    r"""Every credential for one provider, in a stable order.

    Recognised shapes, so a second account costs one line in `keys.env` and no
    code change:

        OPENROUTER_API_KEY        -> openrouter
        OPENROUTER_API_KEY_2      -> openrouter#2
        OPENROUTER_API_KEY_WORK   -> openrouter#work

    Matching is on the exact name or the name followed by `_`, never a bare
    prefix: `ANTHROPIC_BASE_URL` must not be mistaken for an Anthropic key, and
    a stray match would send requests with a URL where a credential belongs.
    """
    e = env if env is not None else os.environ
    out: list[Account] = []
    if e.get(p.key):
        out.append(Account(p, p.key, p.name))
    for name in sorted(e):
        if not name.startswith(p.key + "_") or not e.get(name):
            continue
        suffix = name[len(p.key) + 1:].lower()
        out.append(Account(p, name, f"{p.name}#{suffix}"))
    return out


def quotas_for(p: Provider, env: dict | None = None) -> int:
    """Independent allowances behind a provider — not credentials.

    `Account`'s own docstring warns that counting PROVIDERS instead of
    credentials "would report failover as ready when it is not". Gemini is
    that same error one level down: counting credentials reports six
    allowances where the project has one.

    So the unit the project turns on is narrower than a key. It is a quota,
    and only the provider knows which keys share one.
    """
    n = len(accounts_for(p, env))
    return n if p.quota_per_key else min(n, 1)


def all_accounts(env: dict | None = None) -> list[Account]:
    """Every credential, free tiers first, paid last."""
    out: list[Account] = []
    for p in sorted(PROVIDERS, key=lambda x: (not x.free_tier, PROVIDERS.index(x))):
        out.extend(accounts_for(p, env))
    return out


def configured() -> list[Provider]:
    """Providers with at least one key present, free tiers first."""
    got = [p for p in PROVIDERS if p.configured]
    return sorted(got, key=lambda p: (not p.free_tier, PROVIDERS.index(p)))


def missing() -> list[Provider]:
    return [p for p in PROVIDERS if not p.configured]


def accounts(env: dict | None = None) -> int:
    """How many distinct credentials exist. The failover number.

    Counts CREDENTIALS, never providers and never deployments: three models
    behind one key share one quota, and two keys at one provider do not.
    """
    return len(all_accounts(env))
