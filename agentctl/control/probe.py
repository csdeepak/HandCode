r"""Does each key actually work? Checked without spending a token.

Every provider exposes a metadata endpoint that authenticates the caller and
returns no completion — listing models, or reporting the key's own status. So
31 credentials can be validated for **zero model tokens and zero quota**, which
matters because the alternative (a one-token completion each) would burn 31 of
a 50-request daily allowance just to ask whether the keys are real.

Two rules this module keeps:

* **The key travels in a header, never a URL.** Gemini accepts
  `?key=` and that would put a live credential into proxy logs, shell history
  and any error message containing the URL. `x-goog-api-key` does the same job
  and leaves no trace.
* **A key is never echoed, including in failures.** An error body can contain
  the key that was rejected, so responses are reduced to a status and a short
  reason before they go anywhere near a terminal.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from .providers import Account, all_accounts

TIMEOUT = 20

# Identify the client honestly. Groq and Cerebras sit behind Cloudflare, which
# refuses Python's default `User-Agent: Python-urllib/3.x` with error 1010 --
# a 403 that looks exactly like a rejected credential. Twelve perfectly good
# keys were reported as broken before this line existed (`docs/0034` §3).
USER_AGENT = "agentctl/0.2 (+https://github.com/csdeepak/HandCode)"

LIVE, BAD_KEY, LIMITED, UNREACHABLE = "live", "rejected", "limited", "unreachable"


@dataclass
class Result:
    account: Account
    status: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        # A rate-limited key is a WORKING key with no allowance left. Reporting
        # it as broken would send someone to rotate a credential that is fine.
        return self.status in (LIVE, LIMITED)


# (url, header builder). Metadata only -- none of these generate tokens.
ENDPOINTS: dict[str, tuple[str, callable]] = {
    "openrouter": ("https://openrouter.ai/api/v1/auth/key",
                   lambda k: {"Authorization": f"Bearer {k}"}),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/models",
               # Header, not `?key=`: a URL leaks into logs and error text.
               lambda k: {"x-goog-api-key": k}),
    "mistral": ("https://api.mistral.ai/v1/models",
                lambda k: {"Authorization": f"Bearer {k}"}),
    "cerebras": ("https://api.cerebras.ai/v1/models",
                 lambda k: {"Authorization": f"Bearer {k}"}),
    "groq": ("https://api.groq.com/openai/v1/models",
             lambda k: {"Authorization": f"Bearer {k}"}),
    "anthropic": ("https://api.anthropic.com/v1/models",
                  lambda k: {"x-api-key": k, "anthropic-version": "2023-06-01"}),
    "openai": ("https://api.openai.com/v1/models",
               lambda k: {"Authorization": f"Bearer {k}"}),
}


def check(account: Account) -> Result:
    """One credential. Never raises, never echoes the key."""
    spec = ENDPOINTS.get(account.provider.name)
    if spec is None:
        return Result(account, UNREACHABLE, "no metadata endpoint known")

    url, headers = spec
    key = account.value
    if not key:
        return Result(account, BAD_KEY, "empty")

    req = urllib.request.Request(url, headers={**headers(key),
                                               "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as fh:
            body = fh.read(20_000)
        return Result(account, LIVE, _describe(account, body))
    except urllib.error.HTTPError as e:
        body = _safe_body(e, key)
        # 403 is NOT automatically a bad key. Cloudflare returns 403 with
        # "error code: 1010" when it dislikes the client, which is a transport
        # problem wearing an authentication problem's clothes.
        if "error code: 101" in body or "cloudflare" in body.lower():
            return Result(account, UNREACHABLE,
                          f"HTTP {e.code} from a CDN, not the API "
                          f"({body[:40]}) — the key was never checked")
        if e.code == 401:
            return Result(account, BAD_KEY, "HTTP 401 unauthorized")
        if e.code == 403:
            return Result(account, BAD_KEY, f"HTTP 403 forbidden ({body[:60]})")
        if e.code == 429:
            return Result(account, LIMITED, "rate limited (the key is valid)")
        return Result(account, UNREACHABLE, f"HTTP {e.code}")
    except Exception as e:                              # noqa: BLE001
        return Result(account, UNREACHABLE, type(e).__name__)


def _describe(account: Account, body: bytes) -> str:
    """Something useful from the response. Never the key."""
    try:
        d = json.loads(body)
    except Exception:                                   # noqa: BLE001
        return "ok"
    if account.provider.name == "openrouter":
        data = d.get("data") or {}
        return "free tier" if data.get("is_free_tier") else "paid"
    for field in ("data", "models"):
        if isinstance(d.get(field), list):
            return f"{len(d[field])} models"
    return "ok"


# ── the one honest quota number (`research/phase-10-3` §2.3, §5.3) ─────
@dataclass
class Quota:
    account: Account
    ok: bool
    checked_at: float
    used: int | None = None
    limit: int | None = None
    remaining: int | None = None
    detail: str = ""


def openrouter_quota(account: Account) -> Quota:
    """`GET /api/v1/key` -- the sibling of `check()`'s `/api/v1/auth/key`,
    same header discipline, same never-echo-the-key rule.

    Every other provider in the registry exposes nothing usable to an
    ordinary inference key (`docs/0038` §5.3, `research/phase-10-3-model-
    selection.md` §2.3): this is the only function in this module that
    returns a quota NUMBER rather than a connectivity verdict, and it exists
    only for `openrouter`. Measured live against six accounts on 2026-09-21:
    `free_model_daily_requests: {"used": 0, "limit": 50, "remaining": 50}`
    for every one of them.

    Callers decide when this runs. Nothing in this module calls it on its
    own, and it must never be polled -- one explicit call per refresh.
    """
    now = time.time()
    key = account.value
    if not key:
        return Quota(account, False, now, detail="empty")

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/key",
        headers={"Authorization": f"Bearer {key}", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as fh:
            body = fh.read(20_000)
    except urllib.error.HTTPError as e:
        detail = _safe_body(e, key) or f"HTTP {e.code}"
        return Quota(account, False, now, detail=detail[:80])
    except Exception as e:                                  # noqa: BLE001
        return Quota(account, False, now, detail=type(e).__name__)

    try:
        d = json.loads(body)
    except Exception:                                       # noqa: BLE001
        return Quota(account, False, now, detail="response was not JSON")

    # The sibling `/api/v1/auth/key` wraps its payload in "data" (see
    # `_describe` above); defend against either shape rather than assume.
    data = d.get("data", d) if isinstance(d, dict) else {}
    fmdr = data.get("free_model_daily_requests") if isinstance(data, dict) else None
    if not isinstance(fmdr, dict):
        return Quota(account, False, now,
                     detail="no free_model_daily_requests in the response "
                            "(paid key, or the shape changed)")
    return Quota(account, True, now, used=fmdr.get("used"),
                limit=fmdr.get("limit"), remaining=fmdr.get("remaining"))


def check_all(accounts: list[Account] | None = None,
              workers: int = 8) -> list[Result]:
    """Every credential, in parallel. Order follows `all_accounts`."""
    accts = accounts if accounts is not None else all_accounts()
    if not accts:
        return []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(check, accts))


def summarise(results: list[Result]) -> dict:
    by = {}
    for r in results:
        by[r.status] = by.get(r.status, 0) + 1
    working = [r for r in results if r.ok]
    return {
        "total": len(results),
        "working": len(working),
        "by_status": by,
        "providers_working": len({r.account.provider.name for r in working}),
    }


def _safe_body(e: urllib.error.HTTPError, key: str) -> str:
    """The error text with the credential stripped.

    An error payload can quote the key that was rejected, and the whole point
    of this module is that a key never reaches a terminal.
    """
    try:
        text = e.read(400).decode("utf-8", "replace")
    except Exception:                                   # noqa: BLE001
        return ""
    return text.replace(key, "<REDACTED>").strip()


NO_CREDIT = "no-credit"
# A paid provider deliberately not called. Not a failure -- a choice.
SKIPPED_PAID = "skipped"


def check_inference(provider_name: str,
                    allow_paid: bool = False) -> Result | None:
    """Can this provider actually COMPLETE, not merely authenticate?

    Metadata endpoints answer "is the credential real". They do not answer "may
    it infer", and the two came apart in practice: six Cerebras keys listed
    models happily and every completion returned *"Payment required to access
    this resource"*. Reporting those as `live` would be a true statement about
    authentication and a false one about usability — the misleading-verdict
    shape this project keeps finding (`docs/0034` §6).

    One call per PROVIDER, not per key, because the tier is an account-level
    property and 31 completions to learn six facts is not a trade worth making.
    """
    import os
    import warnings

    from .providers import BY_NAME, accounts_for

    p = BY_NAME.get(provider_name)
    if p is None or not p.models:
        return None
    accts = accounts_for(p)
    if not accts:
        return None

    # `docs/0002` §5: never silently spend. A diagnostic that bills you is a
    # bad diagnostic, and the first version of this function called Anthropic
    # without being asked. Paid providers are checked only on request.
    if not p.free_tier and not allow_paid:
        return Result(accts[0], SKIPPED_PAID,
                      "paid — not called. Use --check-paid to bill a few tokens.")

    warnings.filterwarnings("ignore")
    os.environ.setdefault("LITELLM_LOG", "ERROR")

    # Ask each ACCOUNT until one serves, and stop there.
    #
    # This used to call `accts[0]` once and rule for the provider, on the
    # reasoning that "the tier is an account-level property" -- which is the
    # argument AGAINST doing that, not for it. A daily cap is account-level
    # too, so one capped key spoke for five working ones and `--verify`
    # dropped all eighteen of that provider's deployments (`docs/0039`).
    #
    # The cost concern behind the original was real and is preserved: a
    # healthy provider still costs exactly one call, because the loop stops
    # at the first success. Only a provider that is actually failing pays for
    # more, which is when you want to know.
    best: Result | None = None
    for acct in accts:
        try:
            import litellm
            litellm.suppress_debug_info = True
            litellm.completion(model=p.default_model, max_tokens=4,
                               api_key=acct.value,
                               messages=[{"role": "user", "content": "ok"}])
            note = f"inference ok ({p.models[0]})"
            if acct is not accts[0]:
                note += f" via {acct.label}"
            return Result(acct, LIVE, note)
        except Exception as e:                          # noqa: BLE001
            best = _worse_of(best, _classify_inference(e, acct, p))
    assert best is not None
    return best


#: Most usable first. A LIMITED provider is still in the pool; a NO_CREDIT one
#: is not, so collapsing the two loses a working provider.
_RANK = (LIMITED, NO_CREDIT, UNREACHABLE)


def _worse_of(a: "Result | None", b: "Result") -> "Result":
    """Keep the most *encouraging* verdict seen across a provider's accounts.

    If one key is rate limited and another has no credit, the provider is
    rate limited -- the capped key will come back. Reporting the bleaker of
    the two would drop a provider that works tomorrow.
    """
    if a is None:
        return b
    rank = {s: i for i, s in enumerate(_RANK)}
    return a if rank.get(a.status, 9) <= rank.get(b.status, 9) else b


def _classify_inference(e: Exception, acct, p) -> "Result":
    """Why a completion failed, from the provider's own words.

    **Rate limiting is checked before payment, and the order is the point.**
    OpenRouter's daily-cap error reads *"Rate limit exceeded:
    free-models-per-day. Add 10 credits to unlock 1000 free model requests
    per day"* -- it contains the word `credits`, so a payment-first match
    classified a temporary cap as a billing failure and removed the provider
    from the pool for the rest of the day. A fifth way a check can lie
    (`docs/0034`).
    """
    msg = str(e).replace(acct.value, "<REDACTED>")
    low = msg.lower()
    if "rate limit" in low or "429" in msg or "quota" in low:
        return Result(acct, LIMITED, "rate limited (usable later)")
    if "payment" in low or "credit" in low or "billing" in low:
        return Result(acct, NO_CREDIT,
                      "authenticates, but inference needs payment")
    if "not found" in low or "404" in msg:
        return Result(acct, UNREACHABLE, f"model id rejected: {p.models[0]}")
    return Result(acct, UNREACHABLE, msg.splitlines()[0][:80])
