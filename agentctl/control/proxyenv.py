"""A LiteLLM proxy that agentctl installs, starts and stops for you.

`docs/0043` Phase 2, part B. Before this, the pool took three commands and two
flags (`proxy --out`, `start.sh` or `start.ps1`, then `--model openai/pool
--base-url ...`), plus a two-step install, because `litellm[proxy]` declares
`mcp<2` and the README said the SDK needed `mcp>=2` (`docs/0028`).

The proxy is a separate PROCESS already, so it can have a separate
ENVIRONMENT, and then the conflict cannot exist:

    ~/.agentctl/proxy-env/     a venv holding litellm[proxy] and a COPY of
                               agentctl's pure-Python package (the hook needs
                               its kernel), and never the OpenHands SDK
    ~/.agentctl/proxy/         config, hook, pid file, log

The user's own install never contains `litellm[proxy]`. Nothing is put on the
proxy's PYTHONPATH: the generated start scripts used to point it at the main
environment's site-packages, which would bring every package -- and the
conflict -- back in (`docs/0047`).

    agentctl proxy up        create the env if needed, verify, start, wait
    agentctl proxy status    is it running, and does it answer
    agentctl proxy down      stop it
    agentctl run --pool      `up` if needed, then route through it
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

LITELLM_SPEC = "litellm[proxy]>=1.100.0"
DEFAULT_PORT = 4000


def home() -> Path:
    return Path(os.environ.get("AGENTCTL_HOME") or Path.home() / ".agentctl")


def env_dir() -> Path:
    return home() / "proxy-env"


def run_dir() -> Path:
    return home() / "proxy"


def _env_python() -> Path:
    d = env_dir()
    return d / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def _env_litellm() -> Path:
    d = env_dir()
    return d / ("Scripts/litellm.exe" if sys.platform == "win32" else "bin/litellm")


def _say(msg: str) -> None:
    print(f"  {msg}", flush=True)


# ── the environment ────────────────────────────────────────────────────
def ensure_env(log=_say) -> Path:
    """Create the proxy's own venv, install litellm[proxy], copy agentctl in.

    The first call downloads litellm and its proxy extras, which takes
    minutes; later calls only refresh the agentctl copy, which takes well
    under a second and keeps the hook in step with the CLI that started it.
    """
    py = _env_python()
    if not py.exists():
        log(f"creating the proxy environment at {env_dir()} (once)")
        r = subprocess.run([sys.executable, "-m", "venv", str(env_dir())],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(
                f"could not create a venv for the proxy:\n{r.stderr.strip()[-600:]}\n"
                f"  on Ubuntu: sudo apt install python3-venv")
    if not _env_litellm().exists():
        log(f"installing {LITELLM_SPEC} into it -- a few minutes, once")
        r = subprocess.run([str(py), "-m", "pip", "install", "-q",
                            "--disable-pip-version-check", LITELLM_SPEC],
                           capture_output=True, text=True)
        if r.returncode != 0 or not _env_litellm().exists():
            raise SystemExit(f"installing {LITELLM_SPEC} failed:\n"
                             f"{(r.stdout + r.stderr).strip()[-1200:]}")
    _copy_agentctl(py)
    return py


def _copy_agentctl(py: Path) -> Path:
    """Put this exact agentctl package into the proxy env's site-packages.

    A copy, not a PYTHONPATH entry and not a pip install: the hook must be the
    same code as the CLI that generated its config, it must come without the
    main environment's other packages, and it must work whether agentctl was
    installed from PyPI, from a wheel, or editable from a clone.
    """
    import agentctl

    src = Path(agentctl.__file__).resolve().parent
    purelib = subprocess.run(
        [str(py), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        capture_output=True, text=True, check=True).stdout.strip()
    dst = Path(purelib) / "agentctl"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dst


# ── the process ────────────────────────────────────────────────────────
def _pidfile() -> Path:
    return run_dir() / "proxy.json"


def _read_pid() -> dict | None:
    try:
        return json.loads(_pidfile().read_text(encoding="utf-8"))
    except Exception:                                   # noqa: BLE001
        return None


def url(port: int = DEFAULT_PORT) -> str:
    return f"http://127.0.0.1:{port}"


def answers(port: int, timeout: float = 2.0) -> bool:
    """Does a proxy on this port answer its unauthenticated liveness check?"""
    try:
        with urllib.request.urlopen(f"{url(port)}/health/liveliness",
                                    timeout=timeout) as r:
            return r.status == 200
    except Exception:                                   # noqa: BLE001
        return False


def status() -> dict:
    """{'state': 'running' | 'stopped' | 'dead' | 'foreign', ...}

    `foreign` is something answering on the port that agentctl did not start
    (a proxy you ran by hand, say). It is reported, never stopped.
    """
    from agentctl.runtime.lease import pid_alive

    rec = _read_pid()
    port = (rec or {}).get("port", DEFAULT_PORT)
    alive = bool(rec) and pid_alive(int(rec["pid"]))
    up = answers(port)
    if rec and alive:
        state = "running" if up else "starting"
    elif rec:
        state = "dead"
    else:
        state = "foreign" if up else "stopped"
    return {"state": state, "port": port, "pid": (rec or {}).get("pid"),
            "answers": up, "log": str(run_dir() / "proxy.log"),
            "env": str(env_dir())}


def up(port: int = DEFAULT_PORT, verify: bool = True, log=_say,
       wait_s: float = 120.0) -> dict:
    """Start the managed proxy, or reuse it if it is already running."""
    s = status()
    if s["state"] in ("running", "starting"):
        if s["port"] == port:
            log(f"proxy already running (pid {s['pid']}) at {url(port)}")
            return s
        raise SystemExit(f"a managed proxy is running on port {s['port']}, "
                         f"not {port}. `agentctl proxy down` first.")
    # Only the port being asked for matters. `status()` with no pid file
    # probes the DEFAULT port, and refusing port N because something answers
    # on 4000 was a bug a live proxy on 4000 exposed in the tests.
    if answers(port):
        raise SystemExit(f"something not started by agentctl answers on port "
                         f"{port}. Stop it, or use --port.")

    ensure_env(log)

    from agentctl.control.proxy import available, write

    only, drop = None, set()
    if verify:
        from agentctl.control.providers import BY_NAME
        from agentctl.control.proxy import verified_providers

        log("verifying providers (one completion per model id; paid skipped) ...")
        only, report = verified_providers()
        for name, r in sorted(report.items()):
            log(f"  {'ok' if name in only else '--'}  {name:<11} {r.status}")
        drop = {f"{BY_NAME[n].prefix}{m}" for n, r in report.items() for m in r.gone}
        for m in sorted(drop):
            log(f"  left out   {m}  (the provider no longer serves it)")
    entries = [e for e in available()
               if (only is None or _provider_name(e[0]) in only)
               and e[1] not in drop]
    if not entries:
        raise SystemExit("no provider can serve right now -- nothing to pool.\n"
                         "  `agentctl keys --check` says why.")
    log(f"{len(entries)} deployment(s) in the pool")

    d = run_dir()
    d.mkdir(parents=True, exist_ok=True)
    cfg, _hook = write(d, only=only, drop_models=drop)

    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
           "AGENTCTL_TELEMETRY": str(d / "hook_telemetry.json")}
    env.pop("PYTHONPATH", None)            # never the main env's packages
    logf = open(d / "proxy.log", "ab")
    kw: dict = {"stdout": logf, "stderr": subprocess.STDOUT, "env": env,
                "cwd": str(d), "stdin": subprocess.DEVNULL}
    # The env's own python, not the `litellm.exe` console-script wrapper:
    # launched DETACHED, the wrapper exited during startup with 0xC000013A
    # (STATUS_CONTROL_C_EXIT) and an empty log (`docs/0047`).
    argv = [str(_env_python()), "-c", "from litellm import run_server; run_server()",
            "--config", str(cfg), "--port", str(port)]
    if sys.platform == "win32":
        # No window, its own group, and OUT of the launcher's job object, so
        # it outlives the `agentctl` process that started it. A job that does
        # not allow breakaway refuses the flag; then it runs without it.
        base = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            p = subprocess.Popen(argv, creationflags=base | 0x01000000, **kw)
        except OSError:
            p = subprocess.Popen(argv, creationflags=base, **kw)
    else:
        p = subprocess.Popen(argv, start_new_session=True, **kw)
    logf.close()
    _pidfile().write_text(json.dumps({"pid": p.pid, "port": port,
                                      "started": time.time()}), encoding="utf-8")

    log(f"starting litellm (pid {p.pid}) on {url(port)} ...")
    deadline = time.time() + wait_s
    while time.time() < deadline:
        if p.poll() is not None:
            _pidfile().unlink(missing_ok=True)
            raise SystemExit(f"the proxy exited during startup (code {p.returncode}). "
                             f"Last lines of {d / 'proxy.log'}:\n"
                             + _tail(d / "proxy.log"))
        if answers(port):
            log(f"proxy up at {url(port)}")
            return status()
        time.sleep(1)
    raise SystemExit(f"the proxy did not answer within {wait_s:.0f}s; it is "
                     f"still running (pid {p.pid}). See {d / 'proxy.log'}")


def _provider_name(env_var: str) -> str:
    """`OPENROUTER_API_KEY_2` -> `openrouter`."""
    from agentctl.control.providers import BY_KEY
    return BY_KEY[env_var.split("_API_KEY")[0] + "_API_KEY"].name


def down(log=_say) -> bool:
    """Stop the managed proxy. True if something was stopped."""
    from agentctl.runtime.lease import pid_alive

    rec = _read_pid()
    if not rec:
        log("no managed proxy is running")
        return False
    pid = int(rec["pid"])
    if pid_alive(pid):
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True)
        else:
            import signal
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except ProcessLookupError:
                pass
        for _ in range(20):
            if not pid_alive(pid):
                break
            time.sleep(0.25)
    _pidfile().unlink(missing_ok=True)
    log(f"proxy stopped (pid {pid})")
    return True


def _tail(p: Path, n: int = 15) -> str:
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join("    " + l for l in lines[-n:])
    except Exception:                                   # noqa: BLE001
        return "    (no log)"
