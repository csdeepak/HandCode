r"""A recorded LLM session, and the rule for matching a request to a response.

The point of M6 (`docs/0012` §7): **re-run a real session offline at zero
cost.** No API key, no network, no tokens, and — the part that matters —
no sampling. The same code produces the same run every time.

## The matching rule is the whole design

A cassette is keyed by a fingerprint of what actually determines the response:

    model + messages + tool schemas

and deliberately *not* by `temperature`, `max_tokens`, `api_key`, `base_url`,
request id, or timestamp. Those either do not change the mapping or change on
every run, and folding them in would mean a cassette that never hits twice.

A **miss is the product, not a failure.** Replaying a recorded session against
changed code and getting a miss means the agent asked something different —
which is precisely the regression signal M6 exists to produce. So a miss is
reported with the turn number and a diff of what changed, rather than being
papered over.

## What determinism hides

Replay pins `tool_call_id`, because the recorded response carries the one the
model minted. That is convenient and it is also a trap: `docs/0023` found that
`tool_call_id` is **not** stable across a real model pool, and a suite that
only ever ran under replay would never have found it. Replay is for testing
*our* logic against fixed inputs. It cannot test how the world varies.

## Cassettes contain prompts

Every recorded request holds the full message history — source code, file
contents, whatever the agent was working on. Credentials are never recorded
(they live in headers, which this never sees), but a cassette is as sensitive
as the workspace it was recorded in. Treat it like a log, not like a fixture.
"""
from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

# THE list. It decides both what the recorder captures and what the
# fingerprint is built from, and it is one list on purpose.
#
# It began as two: an allow-list in the recorder and a deny-list here. They
# drifted, and a cassette recorded from a Python callback could never match the
# same request arriving as HTTP, because the wire carries fields the callback
# never saw -- `prompt_cache_key` (the conversation id, different every run by
# definition) and `usage: {include: true}`. Every replay missed on turn 0.
#
# A deny-list cannot work here. The two sides are different representations of
# one call, and any provider may add a field to the wire form at any time; a
# deny-list would have to predict them all. An allow-list is closed, and the
# cost of being closed is explicit: **a field outside this list is asserted not
# to determine the response.** Adding a sampling parameter that does would
# produce a wrong match rather than a miss, so the list is short and additions
# belong in review.
SIGNIFICANT_FIELDS = ("model", "messages", "tools", "tool_choice",
                      "response_format", "functions", "function_call")


def fingerprint(request: dict) -> str:
    """Stable hash of the parts of a request that decide the response."""
    return hashlib.sha256(canonical(request).encode("utf-8")).hexdigest()


def canonical(request: dict) -> str:
    """The exact text that gets hashed. Exposed so a miss can be diffed."""
    kept = {k: request[k] for k in SIGNIFICANT_FIELDS
            if request.get(k) is not None}
    return json.dumps(kept, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class Turn:
    """One request and the response it produced."""
    index: int
    fingerprint: str
    request: dict
    response: dict
    model: str = ""
    usage: dict = field(default_factory=dict)
    # What the CALLER configured, e.g. "openrouter/vendor/model:free".
    # `model` is what litellm passed on after stripping the provider prefix,
    # and that stripped form is what the request carries and what the
    # fingerprint is built from. Replay needs the routable name to reconfigure
    # the run; matching needs the stripped one. They are not the same string
    # and using one for both breaks replay (`docs/0029` §3).
    provider_model: str = ""
    # The environment the recording was made in. A cassette is NOT portable:
    # the SDK builds a platform-dependent system prompt -- a Windows recording
    # says "powershell" in message 0 -- so a cassette recorded on one OS misses
    # on turn 0 everywhere else. Recording this is what lets a replay say so
    # instead of looking like a behaviour change (`docs/0029` §6).
    env: dict = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "index": self.index, "fingerprint": self.fingerprint,
            "model": self.model, "provider_model": self.provider_model,
            "usage": self.usage, "env": self.env,
            "request": self.request, "response": self.response,
        }, default=str)

    @classmethod
    def from_json(cls, line: str) -> "Turn":
        d = json.loads(line)
        return cls(index=d["index"], fingerprint=d["fingerprint"],
                   request=d["request"], response=d["response"],
                   model=d.get("model", ""), usage=d.get("usage") or {},
                   provider_model=d.get("provider_model", ""),
                   env=d.get("env") or {})


@dataclass
class Miss:
    """A replayed request that the cassette has no recording for."""
    turn: int
    request: dict
    nearest: Turn | None = None
    recorded_turns: int = 0

    def describe(self) -> str:
        """Say what diverged, not merely that something did."""
        if self.nearest is None:
            return (f"turn {self.turn}: the recording ended after "
                    f"{self.recorded_turns} turns — this run wanted more")
        want = _messages(self.nearest.request)
        got = _messages(self.request)
        if len(want) != len(got):
            return (f"turn {self.turn}: {len(got)} messages, recorded run had "
                    f"{len(want)} — the conversation took a different shape")
        for i, (a, b) in enumerate(zip(want, got)):
            if a != b:
                return (f"turn {self.turn}: message {i} ({b.get('role')}) "
                        f"differs from the recording")
        return f"turn {self.turn}: same messages, different tools or model"


def current_env() -> dict:
    """What this machine is, for the parts a recording depends on."""
    import platform
    try:
        from importlib.metadata import version
        sdk = version("openhands-sdk")
    except Exception:                                   # noqa: BLE001
        sdk = "?"
    return {"platform": sys.platform, "python": platform.python_version(),
            "openhands_sdk": sdk}


def incompatible(cassette: "Cassette") -> str | None:
    """Why this cassette cannot replay here, or None if it can.

    Only `platform` is fatal, and it is fatal for a concrete reason rather than
    caution: the SDK writes the shell name into the system prompt, so message 0
    differs and every turn misses. The SDK version is reported when it differs
    but not refused -- a prompt change would show up as an honest miss.
    """
    if not cassette.turns:
        return "the cassette is empty"
    rec = cassette.turns[0].env or {}
    here = current_env()
    if rec.get("platform") and rec["platform"] != here["platform"]:
        return (f"recorded on {rec['platform']}, replaying on "
                f"{here['platform']} -- the SDK puts the shell name in the "
                f"system prompt, so turn 0 cannot match")
    return None


def _messages(request: dict) -> list[dict]:
    m = request.get("messages")
    return m if isinstance(m, list) else []


class Cassette:
    """Recorded turns, addressed by fingerprint.

    Duplicate fingerprints are kept in order and served in order: an agent that
    genuinely asks the same question twice must get both recorded answers, not
    the first one twice.
    """

    def __init__(self, turns: list[Turn] | None = None):
        self.turns: list[Turn] = list(turns or [])
        self.misses: list[Miss] = []
        self._served: set[int] = set()
        self._index: dict[str, list[int]] = {}
        for i, t in enumerate(self.turns):
            self._index.setdefault(t.fingerprint, []).append(i)

    # ── recording ──────────────────────────────────────────────────────
    def append(self, request: dict, response: dict, *, model: str = "",
               usage: dict | None = None, provider_model: str = "",
               env: dict | None = None) -> Turn:
        t = Turn(index=len(self.turns), fingerprint=fingerprint(request),
                 request=request, response=response, model=model,
                 usage=usage or {}, provider_model=provider_model,
                 env=env if env is not None else current_env())
        self.turns.append(t)
        self._index.setdefault(t.fingerprint, []).append(t.index)
        return t

    # ── replaying ──────────────────────────────────────────────────────
    def match(self, request: dict) -> Turn | None:
        """The recorded response for this request, or None on a divergence."""
        fp = fingerprint(request)
        for i in self._index.get(fp, ()):
            if i not in self._served:
                self._served.add(i)
                return self.turns[i]

        self.misses.append(Miss(turn=len(self._served), request=request,
                                nearest=self._nearest(),
                                recorded_turns=len(self.turns)))
        return None

    def _nearest(self) -> Turn | None:
        """The turn the recorded run would have been at by now.

        Not a similarity search -- just position. It is what makes a miss
        legible: 'at this point the recording asked X, you asked Y'.
        """
        n = len(self._served)
        return self.turns[n] if n < len(self.turns) else None

    @property
    def exhausted(self) -> bool:
        return len(self._served) >= len(self.turns)

    def unplayed(self) -> list[Turn]:
        """Recorded turns never reached. A short run is a divergence too."""
        return [t for i, t in enumerate(self.turns) if i not in self._served]

    # ── storage ────────────────────────────────────────────────────────
    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8", newline="\n") as fh:
            for t in self.turns:
                fh.write(t.to_json() + "\n")
        return p

    @classmethod
    def load(cls, path: str | Path) -> "Cassette":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"no cassette at {p}")
        turns = [Turn.from_json(line) for line in _lines(p)]
        return cls(turns)

    def __len__(self) -> int:
        return len(self.turns)

    def __iter__(self) -> Iterator[Turn]:
        return iter(self.turns)


def _lines(p: Path) -> Iterator[str]:
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield line


def summarise(cassette: Cassette) -> dict[str, Any]:
    """What a replay run actually did. The evaluator's output."""
    return {
        "turns_recorded": len(cassette.turns),
        "turns_replayed": len(cassette.turns) - len(cassette.unplayed()),
        "misses": len(cassette.misses),
        "unplayed": len(cassette.unplayed()),
        "diverged": bool(cassette.misses) or bool(cassette.unplayed()),
        "first_divergence": (cassette.misses[0].describe()
                             if cassette.misses else None),
    }
