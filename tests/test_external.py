"""EXTERNAL effects and the idempotency-key probe. `docs/0020`.

A remote API cannot be fingerprinted — the world in question is somebody else's
server. So the probe does not ask "did it land?"; it asks whether sending again
is *safe*, and the answer is yes exactly when the call carries a stable key.

The test that matters is `test_retry_after_a_crash_charges_once`: a real HTTP
server that really deduplicates, driven through a real crash. Everything else
is plumbing around it.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agentctl.kernel.classify import Classifier
from agentctl.kernel.gate import EffectGate
from agentctl.kernel.ledger.models import EffectClass, ToolCall, Verdict
from agentctl.kernel.ledger.store import LedgerStore
from agentctl.kernel.reconcile import IdempotencyProbe, ProbeRegistry
from agentctl.kernel.reconcile.base import INCONCLUSIVE, SAFE_TO_RETRY

MATRIX = {
    "version": 1,
    "defaults": {"unknown_tool": "EXTERNAL"},
    "tools": {
        "http_post": {"class": "EXTERNAL", "idempotency_key": "idempotency_key"},
        "send_email": {"class": "EXTERNAL"},          # no key mechanism
    },
}


# ══ a server that actually deduplicates ═══════════════════════════════
class _Charges(BaseHTTPRequestHandler):
    charges: dict[str, dict] = {}
    attempts: int = 0
    lock = threading.Lock()

    def log_message(self, *_):
        pass

    def do_POST(self):                                   # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        key = self.headers.get("Idempotency-Key") or body.get("idempotency_key")

        with _Charges.lock:
            _Charges.attempts += 1
            if key and key in _Charges.charges:
                charge, code = _Charges.charges[key], 200   # replayed
            else:
                charge = {"id": f"ch_{len(_Charges.charges) + 1}",
                          "amount": body.get("amount")}
                if key:
                    _Charges.charges[key] = charge
                code = 201

        raw = json.dumps(charge).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture
def api():
    _Charges.charges, _Charges.attempts = {}, 0
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Charges)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/charges"
    srv.shutdown()
    srv.server_close()


def post(url: str, payload: dict) -> dict:
    import urllib.request
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Idempotency-Key": payload.get("idempotency_key") or ""})
    return json.loads(urllib.request.urlopen(req).read())


# ══ fixtures ══════════════════════════════════════════════════════════
@pytest.fixture
def gate(tmp_path):
    store = LedgerStore(tmp_path / "l.db", holder="test")
    clf = Classifier(matrix=MATRIX)
    g = EffectGate(store, clf,
                   probes=ProbeRegistry(IdempotencyProbe(clf.idempotency_fields())),
                   fence=store.acquire("conv_1"))
    yield g
    store.close()


def charge_call(url: str, cid="tc_1", key: str | None = None) -> ToolCall:
    args = {"url": url, "amount": 4200}
    if key is not None:
        args["idempotency_key"] = key
    return ToolCall(cid, "conv_1", "turn_1", "http_post", args)


# ══ THE PROOF ═════════════════════════════════════════════════════════
def test_retry_after_a_crash_charges_once(api, gate):
    """The whole point: crash after the POST, retry, one charge exists.

    This is the EXTERNAL equivalent of the nine-point suite's guarantee, and it
    holds for a completely different reason -- not because we detected the
    effect, but because the remote refused to repeat it.
    """
    probe = IdempotencyProbe(Classifier(matrix=MATRIX).idempotency_fields())

    # Seam C stamps the key the kernel computes. Model that here.
    bare = charge_call(api)
    key = probe.key_for(bare)
    call = charge_call(api, key=key)

    # --- run 1: gate admits, we POST, then the process dies -----------
    assert gate.guard(call).verdict is Verdict.EXECUTE
    first = post(api, call.args)
    assert first["id"] == "ch_1"
    # crash here: no commit, ledger left at INTENT

    # --- run 2: resume ------------------------------------------------
    decision = gate.guard(call)
    assert decision.verdict is Verdict.EXECUTE, decision.reason
    assert "retry is safe" in (decision.reason or "")

    second = post(api, call.args)

    assert second["id"] == first["id"], "the remote returned a different charge"
    assert len(_Charges.charges) == 1, "the customer was charged twice"
    assert _Charges.attempts == 2, "the retry really was sent"


def test_without_a_key_the_same_scenario_charges_twice(api):
    """Why the key is the mechanism and not a detail.

    Same crash, same retry, no idempotency key: two charges. This is what the
    gate is protecting against, and what it must refuse to allow.
    """
    post(api, {"url": api, "amount": 4200})
    post(api, {"url": api, "amount": 4200})
    assert len(_Charges.charges) == 0    # unkeyed charges are not deduped
    assert _Charges.attempts == 2


def test_an_external_effect_without_a_key_fails_closed(gate):
    """send_email declares no key field, so a retry can never be made safe."""
    call = ToolCall("tc_mail", "conv_1", "t", "send_email",
                    {"to": "a@b.c", "body": "hi"})
    assert gate.guard(call).verdict is Verdict.EXECUTE       # first sighting
    d = gate.guard(call)                                     # crash, resume
    assert d.verdict is Verdict.BLOCK
    assert d.effect_class is EffectClass.EXTERNAL


# ══ probe behaviour ═══════════════════════════════════════════════════
@pytest.fixture
def probe():
    return IdempotencyProbe(Classifier(matrix=MATRIX).idempotency_fields())


def _rec(store, call, pre):
    return store.write_intent(call, EffectClass.EXTERNAL, 1,
                              json.dumps(pre) if pre else None)


def test_key_is_stable_across_a_crash(probe):
    """Two ToolCalls with identical content must yield the same key."""
    a = charge_call("http://x/1")
    b = charge_call("http://x/1")
    assert probe.key_for(a) == probe.key_for(b)
    assert probe.key_for(a) != probe.key_for(charge_call("http://x/2"))


def test_stamping_the_key_does_not_change_the_key(probe):
    """The circularity bug: the key must not be derived from itself.

    Deriving it from arguments that include the key field means stamping it
    changes the args, which changes the key, so the retry sends a different
    one and the probe correctly but uselessly declines.
    """
    bare = charge_call("http://x/1")
    key = probe.key_for(bare)
    stamped = charge_call("http://x/1", key=key)
    assert probe.key_for(stamped) == key


def test_declines_when_the_tool_has_no_key_field(probe):
    call = ToolCall("t", "c", "t", "send_email", {"to": "a@b.c"})
    assert not probe.handles(call)
    assert probe.capture(call) is None


def test_recognises_a_conventional_key_argument(probe):
    """A tool already using `request_id` needs no matrix entry."""
    call = ToolCall("t", "c", "t", "some_api", {"request_id": "abc"})
    assert probe.handles(call)


def test_no_key_went_out_means_inconclusive(tmp_path, probe):
    """The decisive check: an unstamped call must NOT be declared safe.

    Without Seam C nothing stamps, so the remote has nothing to deduplicate
    against and a retry would be a second effect.
    """
    store = LedgerStore(tmp_path / "l.db")
    call = charge_call("http://x/1")                 # no key at all
    rec = _rec(store, call, probe.capture(call))
    assert probe.probe(call, store.lookup(rec.tool_call_id)) == INCONCLUSIVE
    store.close()


def test_a_changed_key_means_inconclusive(tmp_path, probe):
    """A different key on the retry is a fresh request, not a replay."""
    store = LedgerStore(tmp_path / "l.db")
    sent = charge_call("http://x/1", key="key-A")
    rec = _rec(store, sent, probe.capture(sent))
    retried = charge_call("http://x/1", key="key-B")
    assert probe.probe(retried, store.lookup(rec.tool_call_id)) == INCONCLUSIVE
    store.close()


def test_a_model_supplied_key_is_good_enough(tmp_path, probe):
    """We do not need to have chosen the key -- only for it to be the same."""
    store = LedgerStore(tmp_path / "l.db")
    call = charge_call("http://x/1", key="caller-chosen-key")
    rec = _rec(store, call, probe.capture(call))
    assert probe.probe(call, store.lookup(rec.tool_call_id)) == SAFE_TO_RETRY
    store.close()


def test_safe_to_retry_when_the_key_matches(tmp_path, probe):
    store = LedgerStore(tmp_path / "l.db")
    bare = charge_call("http://x/1")
    call = charge_call("http://x/1", key=probe.key_for(bare))
    rec = _rec(store, call, probe.capture(call))
    assert probe.probe(call, store.lookup(rec.tool_call_id)) == SAFE_TO_RETRY
    store.close()


def test_no_fingerprint_means_inconclusive(tmp_path, probe):
    store = LedgerStore(tmp_path / "l.db")
    call = charge_call("http://x/1", key="k")
    rec = _rec(store, call, None)
    assert probe.probe(call, store.lookup(rec.tool_call_id)) == INCONCLUSIVE
    store.close()


def test_matrix_declares_the_key_field():
    fields = Classifier(matrix=MATRIX).idempotency_fields()
    assert fields == {"http_post": "idempotency_key"}
