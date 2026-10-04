"""The GitHub Action: `action.yml` (run) and `publish/action.yml`. docs/0053.

Two jobs on two machines, because the job that runs the agent cannot be
trusted with anything worth stealing. Text the agent reads can carry
instructions (prompt injection), and anything on the agent's machine can read
anything else there that runs as the same user, environment included.

  run      The agent works in the checkout. The job holds the model key and a
           READ-only token, nothing else. Its work leaves as a git bundle plus
           the end-of-run report (`docs/0048`).
  publish  A fresh machine that never runs the repository's code. It checks the
           bundle, pushes it to a new branch, never the base, and opens a pull
           request with the report as its description.

Standard library only, and no `agentctl` import: `publish` runs on the
runner's own python3 with nothing installed.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

#: Events where a person with write access chose the task. Everything else
#: (issues, comments, pull requests from forks, ...) can carry a stranger's
#: text, and the I-26 injection canaries have not run yet (docs/0051 D10).
TRUSTED_EVENTS = frozenset({"workflow_dispatch", "schedule", "push",
                            "repository_dispatch"})

#: Never in the agent's environment. ACTIONS_* carries the runner's own
#: tokens (artifacts, cache, OIDC). The GITHUB_* files set later steps'
#: environment and outputs. INPUT_* are action inputs, the token among them.
_DROP = frozenset({"GITHUB_TOKEN", "GH_TOKEN", "GH_ENTERPRISE_TOKEN",
                   "GITHUB_ENTERPRISE_TOKEN", "HANDCODE_TOKEN",
                   "GITHUB_ENV", "GITHUB_OUTPUT", "GITHUB_PATH", "GITHUB_STATE",
                   "GITHUB_STEP_SUMMARY"})
_DROP_PREFIXES = ("ACTIONS_", "INPUT_")

BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898283+github-actions[bot]@users.noreply.github.com"
RESULT_REF = "refs/handcode/result"
BODY_LIMIT = 60_000                     # GitHub refuses a body over 65,536


class Refusal(Exception):
    """A check failed. The message says what to change; exit 2."""


# ── git ───────────────────────────────────────────────────────────────────
def git(cwd: Path, *args: str, env: dict | None = None, check: bool = True) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        raise Refusal(f"git {' '.join(args[:3])} failed: {p.stderr.strip()[:400]}")
    return p.stdout.strip()


def _safe(scratch: Path) -> list[str]:
    """Options for the git commands run AFTER the agent, in the repository the
    agent could have reconfigured: no hooks, no fsmonitor command."""
    hooks = scratch / "no-hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    return ["-c", f"core.hooksPath={hooks.as_posix()}", "-c", "core.fsmonitor=false"]


# ── the checks before the agent starts ───────────────────────────────────
def check_event(env: dict) -> None:
    name = env.get("GITHUB_EVENT_NAME", "")
    if name and name not in TRUSTED_EVENTS:
        raise Refusal(
            f"refused: this run was triggered by a `{name}` event. Its text can "
            f"come from anyone, and the agent would act on it. For now the "
            f"Action runs on {', '.join(sorted(TRUSTED_EVENTS))} only, where a "
            f"person with write access chose the task (docs/0053).")


def check_credentials(ws: Path) -> None:
    """The agent can read .git/config. actions/checkout leaves the job's token
    there unless told not to, which hands the agent that token."""
    headers = git(ws, "config", "--includes", "--get-regexp",
                  r"^http\..*\.extraheader$", check=False)
    remotes = git(ws, "remote", "-v", check=False)
    if headers or re.search(r"://[^/@\s]+@", remotes):
        raise Refusal(
            "refused: the job's GitHub token is stored in this checkout's git "
            "config, where the agent can read it. Add this to the checkout step:\n"
            "      - uses: actions/checkout@v4\n"
            "        with:\n"
            "          persist-credentials: false")


def check_clean(ws: Path) -> None:
    dirty = git(ws, "status", "--porcelain").splitlines()
    if dirty:
        shown = "\n".join(f"    {l}" for l in dirty[:5])
        more = f"\n    ... and {len(dirty) - 5} more" if len(dirty) > 5 else ""
        raise Refusal(
            "refused: the checkout already has changes, and they would end up in "
            "the pull request as if the agent made them:\n" + shown + more +
            "\n  Commit them, or ignore them in .gitignore, before this step.")


def check_head(ws: Path, env: dict) -> str:
    head = git(ws, "rev-parse", "HEAD")
    want = env.get("GITHUB_SHA")
    if want and head != want:
        raise Refusal(
            f"refused: the checkout is at {head[:12]}, not {want[:12]}, the commit "
            f"this workflow run is for. The publish job checks the agent's work "
            f"against that commit. Check out the default ref.")
    return head


def agent_env(env: dict, runner_environment: str = "") -> dict:
    """The agent's environment: the job's, minus every token GitHub put there.
    The model key stays; the agent cannot work without it."""
    out = {k: v for k, v in env.items()
           if k not in _DROP and not k.startswith(_DROP_PREFIXES)}
    if runner_environment == "github-hosted":
        # The VM is discarded when the job ends, so a package install lands
        # nowhere that lasts: the same containment as the image (docs/0052).
        # A self-hosted runner is somebody's machine, and keeps asking.
        out["HANDCODE_CONTAINER"] = "1"
    out.update(GIT_AUTHOR_NAME=BOT_NAME, GIT_AUTHOR_EMAIL=BOT_EMAIL,
               GIT_COMMITTER_NAME=BOT_NAME, GIT_COMMITTER_EMAIL=BOT_EMAIL,
               GIT_TERMINAL_PROMPT="0")
    return out


# ── leftover processes ────────────────────────────────────────────────────
def become_subreaper() -> bool:
    """Linux: a process the agent leaves running re-parents to US, not to init,
    however it detaches, so `sweep` can find it. Without this, a background
    process could outlive the agent and read what later steps hold."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        return libc.prctl(36, 1, 0, 0, 0) == 0          # PR_SET_CHILD_SUBREAPER
    except (OSError, AttributeError):
        return False


def _descendants(root: int) -> set[int]:
    parent: dict[int, int] = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            stat = Path(f"/proc/{d}/stat").read_text()
        except OSError:
            continue
        # "pid (comm) state ppid ...": comm may hold spaces and parentheses.
        parent[int(d)] = int(stat[stat.rindex(")") + 2:].split()[1])
    found: set[int] = set()
    grew = True
    while grew:
        grew = False
        for pid, pp in parent.items():
            if pid not in found and (pp == root or pp in found):
                found.add(pid)
                grew = True
    return found


def sweep() -> int:
    """Kill every process still descending from this one. Returns how many."""
    if not sys.platform.startswith("linux"):
        return 0
    killed: set[int] = set()
    for _ in range(10):
        left = _descendants(os.getpid()) - killed
        if not left:
            break
        for pid in left:
            try:
                os.kill(pid, signal.SIGKILL)
                killed.add(pid)
            except ProcessLookupError:
                pass
        time.sleep(0.2)
        try:
            while os.waitpid(-1, os.WNOHANG)[0]:
                pass
        except ChildProcessError:
            pass
    return len(killed)


# ── GitHub's files ────────────────────────────────────────────────────────
def set_outputs(env: dict, **values) -> None:
    if path := env.get("GITHUB_OUTPUT"):
        with open(path, "a", encoding="utf-8") as f:
            for k, v in values.items():
                lines = ("" if v is None else str(v)).splitlines()
                f.write(f"{k}={lines[0] if lines else ''}\n")


def add_summary(env: dict, text: str) -> None:
    if path := env.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n")


def fenced(text: str, lang: str = "text") -> str:
    """A code fence longer than any run of backticks inside: the report holds
    what the agent said, which must not be able to close the fence."""
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{lang}\n{text}\n{fence}"


def run_url(env: dict) -> str:
    return (f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/"
            f"{env.get('GITHUB_REPOSITORY', '')}/actions/runs/{env.get('GITHUB_RUN_ID', '')}")


def first_line(task: str) -> str:
    first = next((l.strip() for l in task.splitlines() if l.strip()), "a task")
    return first if len(first) <= 60 else first[:57] + "..."


def title(task: str, report: dict | None) -> str:
    first = first_line(task)
    outcome = (report or {}).get("outcome", "no report")
    tag = "" if (report or {}).get("ok") and outcome == "PASS" else f"[{outcome}] "
    return f"{tag}handcode: {first}"


def render_body(task: str, report: dict | None, meta: dict, env: dict) -> str:
    quoted = "\n".join("> " + l for l in (task.strip() or "(no task)").splitlines())
    parts = [f"**HandCode** ran this task in [workflow run {env.get('GITHUB_RUN_ID', '')}]"
             f"({run_url(env)}):", "", quoted, ""]
    if report:
        parts += [fenced(report.get("text", "")), ""]
    else:
        parts += ["agentctl wrote no report. The run's log says why.", ""]
    if (k := meta.get("swept")):
        parts += [f"{k} process(es) the agent left running were stopped when it "
                  f"finished.", ""]
    parts += [
        "<details><summary>Before you merge</summary>", "",
        "- The agent's job held the model key and a read-only token. This branch "
        "was pushed by a second job that runs none of the repository's code.",
        "- The outcome above comes from `--accept`, run in the agent's job. "
        "GitHub does not run workflows on a branch pushed with the workflow's own "
        "token, so CI has not run here; push a commit or re-run it to get it.",
        "- Review the diff as you would a stranger's. The task text, the "
        "repository and every tool output were input to a model.",
        "", "</details>"]
    body = "\n".join(parts)
    if len(body) > BODY_LIMIT:
        body = body[:BODY_LIMIT - 200] + f"\n\n(cut at {BODY_LIMIT} characters; " \
                                          f"the full report is in the run's log)"
    return body


# ── run: the agent's job ──────────────────────────────────────────────────
def run(env: dict, agentctl: list[str] | None = None) -> int:
    ws = Path(env.get("GITHUB_WORKSPACE") or ".").resolve()
    out = Path(env.get("HANDCODE_OUT") or ws.parent / "handcode-out").resolve()
    out.mkdir(parents=True, exist_ok=True)
    task = env.get("HANDCODE_TASK", "").strip()
    if not task:
        raise Refusal("refused: no task. Set the action's `task` input.")
    check_event(env)
    check_credentials(ws)
    check_clean(ws)
    base = check_head(ws, env)

    cmd = list(agentctl or [env.get("HANDCODE_AGENTCTL") or "agentctl"])
    cmd += ["run", task, "--workspace", str(ws),
            "--report-json", str(out / "report.json")]
    if a := env.get("HANDCODE_ACCEPT", "").strip():
        cmd += ["--accept", a]
    if m := env.get("HANDCODE_MODEL", "").strip():
        cmd += ["--model", m]
    if n := env.get("HANDCODE_MAX_ITERATIONS", "").strip():
        cmd += ["--max-iterations", n]
    if b := env.get("HANDCODE_MAX_BUDGET", "").strip():
        cmd += ["--max-budget", b]
    cmd += shlex.split(env.get("HANDCODE_ARGS", ""))

    reaper = become_subreaper()
    print(f"handcode: running the agent (leftover processes "
          f"{'will be stopped' if reaper else 'are not tracked on this OS'})",
          flush=True)
    rc = subprocess.call(cmd, cwd=ws, env=agent_env(env, env.get("HANDCODE_RUNNER_ENV", "")))
    swept = sweep()
    if swept:
        print(f"handcode: stopped {swept} process(es) the agent left running")

    report = None
    if (out / "report.json").exists():
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))

    # What the agent did not commit, committed for it. These git commands run
    # in a repository the agent may have reconfigured, hence `_safe`, and
    # nothing secret is in this process's environment.
    safe = _safe(out)
    genv = agent_env(env)
    if git(ws, *safe, "status", "--porcelain", env=genv):
        git(ws, *safe, "add", "-A", env=genv)
        git(ws, *safe, "commit", "--no-verify", "-q", "-m",
            f"{first_line(task)}\n\n{task}\n\nRun: {run_url(env)}",
            env=genv)
    head = git(ws, "rev-parse", "HEAD")
    descends = subprocess.run(["git", "merge-base", "--is-ancestor", base, head],
                              cwd=ws, capture_output=True).returncode == 0
    commits = int(git(ws, "rev-list", "--count", f"{base}..{head}")) if descends else 0
    if commits:
        git(ws, "update-ref", RESULT_REF, head)
        git(ws, *safe, "bundle", "create", str(out / "result.bundle"),
            RESULT_REF, f"^{base}", env=genv)
    meta = {"base": base, "head": head, "commits": commits, "descends": descends,
            "agentctl_exit": rc, "swept": swept, "task": task}
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    swept += sweep()                    # anything `git` above was made to start

    add_summary(env, "## HandCode\n\n" + render_body(task, report, meta, env))
    set_outputs(env, outcome=(report or {}).get("outcome", "no report"),
                ok=str(bool((report or {}).get("ok"))).lower(), commits=commits,
                **{"conversation-id": (report or {}).get("conversation_id", "")})
    if not descends:
        print(f"handcode: HEAD ({head[:12]}) no longer descends from {base[:12]}: "
              f"the agent rewrote history, so there is nothing to propose")
    elif not commits:
        print("handcode: no changes, so there is nothing to propose")
    if report is None:
        print(f"handcode: agentctl exited {rc} without a report")
        return rc or 1
    return 0


# ── publish: a fresh machine ──────────────────────────────────────────────
def _auth_env(work: Path, server: str, token: str) -> dict:
    """git's environment for publishing: only config this job wrote (no global,
    no system file), and the token as a header scoped to the server, set
    through the environment rather than a command line or a file."""
    empty = work / "empty.gitconfig"
    empty.write_text("", encoding="utf-8")
    e = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    e.update(GIT_CONFIG_GLOBAL=str(empty), GIT_CONFIG_NOSYSTEM="1",
             GIT_TERMINAL_PROMPT="0")
    if token:
        cred = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        e.update(GIT_CONFIG_COUNT="1",
                 GIT_CONFIG_KEY_0=f"http.{server.rstrip('/')}/.extraheader",
                 GIT_CONFIG_VALUE_0=f"AUTHORIZATION: basic {cred}")
    return e


def github_api(method: str, url: str, token: str, body: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {token}",
                                          "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def publish(env: dict, api=github_api) -> int:
    inp = Path(env.get("HANDCODE_IN") or ".").resolve()
    work = Path(env.get("RUNNER_TEMP") or inp.parent).resolve() / "handcode-publish"
    token = env.get("HANDCODE_TOKEN", "")
    server = env.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    repo = env.get("GITHUB_REPOSITORY", "")
    dry = env.get("HANDCODE_DRY_RUN", "").lower() in ("1", "true", "yes")

    if not (inp / "meta.json").exists():
        raise Refusal(f"refused: no result from the run job in {inp}. Did it fail?")
    meta = json.loads((inp / "meta.json").read_text(encoding="utf-8"))
    report = (json.loads((inp / "report.json").read_text(encoding="utf-8"))
              if (inp / "report.json").exists() else None)
    task = str(meta.get("task", ""))
    ok = bool((report or {}).get("ok"))

    # Everything from the run job is the agent's to forge, so it is checked
    # against what GitHub, not the run job, says this run is for.
    base = env.get("GITHUB_SHA", "")
    ref = env.get("GITHUB_REF", "")
    if not ref.startswith("refs/heads/"):
        raise Refusal(f"refused: {ref or 'this ref'} is not a branch, so there is "
                      f"no branch for a pull request to target.")
    base_branch = ref[len("refs/heads/"):]
    if meta.get("base") != base:
        raise Refusal(f"refused: the run job worked from {str(meta.get('base'))[:12]}, "
                      f"but this workflow run is for {base[:12]}.")
    bundle = inp / "result.bundle"
    if not bundle.exists():
        print("handcode: the agent changed nothing, so there is no pull request")
        set_outputs(env, **{"pull-request": "", "branch": ""})
        return 0 if ok else 1

    work.mkdir(parents=True, exist_ok=True)
    genv = _auth_env(work, server, token)
    url = f"{server}/{repo}.git"
    git(work, "init", "-q", env=genv)
    git(work, "fetch", "-q", "--depth=1", "--no-tags", url, base, env=genv)
    git(work, "bundle", "verify", "-q", str(bundle), env=genv)
    git(work, "fetch", "-q", str(bundle), f"{RESULT_REF}:{RESULT_REF}", env=genv)
    head = git(work, "rev-parse", RESULT_REF, env=genv)
    if subprocess.run(["git", "merge-base", "--is-ancestor", base, head], cwd=work,
                      env=genv, capture_output=True).returncode != 0:
        raise Refusal(f"refused: the agent's work ({head[:12]}) does not build on "
                      f"{base[:12]}.")
    files = git(work, "diff", "--name-only", base, head, env=genv).splitlines()
    workflows = [f for f in files if f.startswith(".github/workflows/")]
    if workflows:
        raise Refusal(
            "refused: the change edits a workflow file (" + ", ".join(workflows[:3]) +
            "). A change to CI made by an agent needs a person, and the "
            "workflow's token cannot push one anyway. The diff is in the bundle "
            "artifact; apply it by hand if you want it.")
    commits = int(git(work, "rev-list", "--count", f"{base}..{head}", env=genv))
    branch = f"handcode/run-{env.get('GITHUB_RUN_ID', '0')}-{env.get('GITHUB_RUN_ATTEMPT', '1')}"
    if branch == base_branch:
        raise Refusal("refused: the new branch would be the base branch")
    body = render_body(task, report, meta, env)
    print(f"handcode: {commits} commit(s), {len(files)} file(s), "
          f"{base[:12]}..{head[:12]} -> {branch}")
    if dry:
        print("handcode: dry run, nothing pushed\n\n" + title(task, report) + "\n\n" + body)
        set_outputs(env, **{"pull-request": "", "branch": branch})
        return 0

    git(work, "push", "-q", "--no-verify", url, f"{head}:refs/heads/{branch}", env=genv)
    pulls = f"{env.get('GITHUB_API_URL', 'https://api.github.com')}/repos/{repo}/pulls"
    pr = {"title": title(task, report), "head": branch, "base": base_branch,
          "body": body, "draft": not ok}
    status, resp = api("POST", pulls, token, pr)
    if status == 422 and pr["draft"] and "draft" in json.dumps(resp).lower():
        pr["draft"] = False                     # a plan without draft PRs
        status, resp = api("POST", pulls, token, pr)
    if status == 403 and "not permitted to create" in json.dumps(resp).lower():
        compare = f"{server}/{repo}/compare/{base_branch}...{branch}?expand=1"
        print("handcode: the branch is pushed, but GitHub did not let the "
              "workflow open the pull request. The repository's owner can allow it:\n"
              "  Settings > Actions > General > Workflow permissions >\n"
              "  \"Allow GitHub Actions to create and approve pull requests\"\n"
              f"Or open it yourself: {compare}")
        add_summary(env, f"Pushed `{branch}`. [Open the pull request]({compare}).")
        set_outputs(env, **{"pull-request": "", "branch": branch})
        return 1
    if status >= 300:
        raise Refusal(f"refused: GitHub answered {status} to opening the pull "
                      f"request: {str(resp.get('message', resp))[:300]}")
    link = resp.get("html_url", "")
    print(f"handcode: opened {link}" + ("" if ok else " as a draft: it needs you"))
    add_summary(env, f"## HandCode\n\nOpened {link}")
    set_outputs(env, **{"pull-request": link, "branch": branch})
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    step = argv[0] if argv else ""
    try:
        if step == "run":
            return run(dict(os.environ))
        if step == "publish":
            return publish(dict(os.environ))
        print("usage: gha.py run|publish", file=sys.stderr)
        return 2
    except Refusal as r:
        print(f"handcode: {r}", file=sys.stderr)
        print(f"::error title=HandCode::{str(r).splitlines()[0]}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
