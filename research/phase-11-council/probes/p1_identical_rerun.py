# Local, zero-network check: what does the gate do when an agent re-runs an
# identical test command in the same conversation?
import sys, tempfile, os
sys.path.insert(0, r"C:\Users\csdee\openhands")
from agentctl.kernel.classify import Classifier
from agentctl.kernel.gate import EffectGate
from agentctl.kernel.ledger.store import LedgerStore
from agentctl.kernel.ledger.models import ToolCall
c = Classifier()
for cmd in ["python -m pytest -q", "pytest -q", "npm test", "ruff check .", "python app.py",
            "cd src && python -m pytest", "git commit -am wip", "echo x >> log.txt"]:
    print(f"{cmd!r:32} -> {c.classify(ToolCall('x','c','t','execute_bash',{'command':cmd})).value}")
d = tempfile.mkdtemp(dir=os.environ.get("S"))
s = LedgerStore(os.path.join(d, "l.db")); f = s.acquire("conv")
g = EffectGate(s, c, fence=f)
cmd = {"command": "python -m pytest -q"}
a = ToolCall("call_A", "conv", "t1", "execute_bash", cmd)
print("run 1:", g.guard(a).verdict.value)
g.record_success(a, b'{"output":"1 failed"}')      # ran, recorded (as if exit 0)
b = ToolCall("call_B", "conv", "t5", "execute_bash", cmd)   # later turn, after a fix
dec = g.guard(b); print("run 2 (after COMMITTED):", dec.verdict.value, dec.reason, dec.observation)
# failing-first variant
a2 = ToolCall("call_C", "conv", "t1", "execute_bash", {"command": "python -m pytest tests/"})
g.guard(a2); g.record_tool_error("call_C", "exit=1 1 failed")
b2 = ToolCall("call_D", "conv", "t6", "execute_bash", {"command": "python -m pytest tests/"})
dec = g.guard(b2); print("run 2 (after failing run):", dec.verdict.value, "|", dec.reason)
