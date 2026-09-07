"""The architecture's immune system. docs/0012 §1.

If the kernel ever imports the control plane, requirement R2 is dead: the
kernel must keep working when the control plane is unavailable. This test is
cheap and catches that the moment it happens.
"""
import ast
import pathlib

KERNEL = pathlib.Path(__file__).resolve().parent.parent / "agentctl" / "kernel"


def _imports(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_kernel_never_imports_control():
    """R2: the kernel must run when the control plane is dead."""
    offenders = []
    for py in KERNEL.rglob("*.py"):
        bad = {m for m in _imports(py) if "control" in m.split(".")}
        if bad:
            offenders.append((py.name, sorted(bad)))
    assert not offenders, f"kernel imports control plane: {offenders}"


def test_kernel_never_imports_the_harness():
    """R6: nothing structurally couples the kernel to OpenHands."""
    offenders = []
    for py in KERNEL.rglob("*.py"):
        bad = {m for m in _imports(py) if m.split(".")[0] in {"openhands", "litellm"}}
        if bad:
            offenders.append((py.name, sorted(bad)))
    assert not offenders, f"kernel imports a harness: {offenders}"


def test_kernel_makes_no_network_calls():
    """The in-band kernel must not depend on the network (docs/0008 §4)."""
    banned = {"requests", "httpx", "urllib", "urllib3", "socket", "aiohttp"}
    offenders = []
    for py in KERNEL.rglob("*.py"):
        bad = {m for m in _imports(py) if m.split(".")[0] in banned}
        if bad:
            offenders.append((py.name, sorted(bad)))
    assert not offenders, f"kernel imports a network library: {offenders}"
