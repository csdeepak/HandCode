import sys, tempfile, os
sys.path.insert(0, r"C:\Users\csdee\openhands")
from agentctl.kernel.gate import EffectGate
from agentctl.kernel.ledger.store import LedgerStore
from agentctl.kernel.ledger.models import ToolCall
d = tempfile.mkdtemp(dir=os.environ["S"]); p = os.path.join(d, "l.db")
zombie = LedgerStore(p, holder="run-1"); fz = zombie.acquire("conv")
recovery = LedgerStore(p, holder="run-2"); fr = recovery.acquire("conv", takeover=True)
print("fences", fz, fr)
gz = EffectGate(zombie, fence=fz)
c = ToolCall("call_fresh", "conv", "t9", "execute_bash", {"command": "git commit -am zombie"})
dec = gz.guard(c); print("zombie guard on a FRESH id:", dec.verdict.value, dec.reason)
gz.record_success(c, b"{}"); print("zombie commit state:", zombie.lookup("call_fresh").state.value)
