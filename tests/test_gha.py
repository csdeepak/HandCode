"""The GitHub Action's two halves, end to end against a local "remote". docs/0053.

`run` with a stand-in agent, then `publish` from what `run` left, the way the
two jobs hand over through an artifact. The GitHub API is faked; git is real.
"""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from agentctl import gha

ROOT = Path(__file__).resolve().parent.parent

FAKE_AGENT = textwrap.dedent("""
    import json, os, subprocess, sys
    from pathlib import Path
    a = sys.argv[1:]
    report = Path(a[a.index("--report-json") + 1])
    ws = Path(a[a.index("--workspace") + 1])
    mode = os.environ.get("FAKE_MODE", "write")
    leaked = sorted(k for k in ("GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN") if k in os.environ)
    (ws.parent / "agent-saw.json").write_text(json.dumps(leaked))
    if mode in ("write", "fail"):
        (ws / "hello.txt").write_text("hello\\n")
    elif mode == "workflow":
        (ws / ".github" / "workflows").mkdir(parents=True)
        (ws / ".github" / "workflows" / "x.yml").write_text("on: push\\n")
    elif mode == "amend":
        subprocess.run(["git", "commit", "-q", "--amend", "-m", "rewritten"], cwd=ws, check=True)
    ok = mode != "fail"
    report.write_text(json.dumps({"outcome": "PASS" if ok else "FAIL", "ok": ok,
                                  "conversation_id": "c0ffee",
                                  "text": "  outcome     " + ("PASS" if ok else "FAIL")}))
    sys.exit(0 if ok else 1)
""")


def _g(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A remote with one commit on main, a checkout of it, and a job env."""
    for k in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(k, "t")
    for k in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(k, "t@example.invalid")
    remote = tmp_path / "server" / "o" / "r.git"
    remote.parent.mkdir(parents=True)
    _g(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    ws = tmp_path / "ws"
    _g(tmp_path, "clone", "-q", str(remote), str(ws))
    (ws / "README.md").write_text("hi\n")
    _g(ws, "add", "-A")
    _g(ws, "commit", "-q", "-m", "base")
    _g(ws, "push", "-q", "origin", "HEAD:main")
    # A plain path remote, as `persist-credentials: false` leaves it.
    agent = tmp_path / "fake_agent.py"
    agent.write_text(FAKE_AGENT)
    env = {"GITHUB_WORKSPACE": str(ws), "HANDCODE_OUT": str(tmp_path / "out"),
           "HANDCODE_TASK": "Add a hello file\nwith more detail",
           "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_SHA": _g(ws, "rev-parse", "HEAD"),
           "GITHUB_REF": "refs/heads/main", "GITHUB_REPOSITORY": "o/r",
           "GITHUB_SERVER_URL": (tmp_path / "server").as_uri(),
           "GITHUB_RUN_ID": "7", "GITHUB_RUN_ATTEMPT": "1",
           "RUNNER_TEMP": str(tmp_path / "publish-machine"),
           "GITHUB_TOKEN": "ghs_secret", "ACTIONS_RUNTIME_TOKEN": "rt_secret",
           "GITHUB_OUTPUT": str(tmp_path / "outputs.txt")}
    (tmp_path / "publish-machine").mkdir()
    return {"tmp": tmp_path, "ws": ws, "remote": remote, "env": env,
            "agent": [sys.executable, str(agent)]}


def _run(w, mode="write"):
    import os
    os.environ["FAKE_MODE"] = mode
    try:
        return gha.run({**os.environ, **w["env"]}, agentctl=w["agent"])
    finally:
        del os.environ["FAKE_MODE"]


def _publish(w, **over):
    calls = []

    def api(method, url, token, body):
        calls.append((method, url, body))
        return over.get("answer", (201, {"html_url": "https://example/pr/1"}))

    env = {**w["env"], "HANDCODE_IN": str(w["tmp"] / "out"), **over.get("env", {})}
    env.pop("GITHUB_TOKEN")
    return gha.publish(env, api=api), calls


def _outputs(w) -> dict:
    p = Path(w["env"]["GITHUB_OUTPUT"])
    return dict(l.split("=", 1) for l in p.read_text().splitlines()) if p.exists() else {}


# ── before the agent starts ───────────────────────────────────────────────
@pytest.mark.parametrize("event", ["workflow_dispatch", "schedule", "push"])
def test_a_maintainers_event_is_allowed(event):
    gha.check_event({"GITHUB_EVENT_NAME": event})


@pytest.mark.parametrize("event", ["issues", "issue_comment", "pull_request",
                                   "pull_request_target", "discussion"])
def test_an_event_a_stranger_can_write_is_refused(event):
    with pytest.raises(gha.Refusal, match=event):
        gha.check_event({"GITHUB_EVENT_NAME": event})


def test_the_agent_gets_the_model_key_and_no_github_token():
    env = gha.agent_env({"OPENROUTER_API_KEY": "k", "GITHUB_TOKEN": "t", "GH_TOKEN": "t",
                         "ACTIONS_RUNTIME_TOKEN": "t", "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "t",
                         "INPUT_GITHUB-TOKEN": "t", "HANDCODE_TOKEN": "t",
                         "GITHUB_ENV": "/f", "GITHUB_OUTPUT": "/f", "PATH": "/bin"})
    assert env["OPENROUTER_API_KEY"] == "k" and env["PATH"] == "/bin"
    assert not [k for k in env if "TOKEN" in k or k.startswith(("ACTIONS_", "INPUT_"))]
    assert "GITHUB_ENV" not in env and "GITHUB_OUTPUT" not in env


def test_installs_stop_asking_only_on_a_disposable_runner():
    assert gha.agent_env({}, "github-hosted")["HANDCODE_CONTAINER"] == "1"
    assert "HANDCODE_CONTAINER" not in gha.agent_env({}, "self-hosted")


def test_a_checkout_that_kept_its_token_is_refused(world):
    _g(world["ws"], "config", "http.https://github.com/.extraheader",
       "AUTHORIZATION: basic eDp5")
    with pytest.raises(gha.Refusal, match="persist-credentials: false"):
        _run(world)


def test_a_token_in_the_remote_url_is_refused(world):
    _g(world["ws"], "remote", "set-url", "origin", "https://x-access-token:t@github.com/o/r")
    with pytest.raises(gha.Refusal, match="persist-credentials"):
        _run(world)


def test_a_dirty_checkout_is_refused(world):
    (world["ws"] / "stray.txt").write_text("x")
    with pytest.raises(gha.Refusal, match="stray.txt"):
        _run(world)


def test_a_checkout_of_another_commit_is_refused(world):
    world["env"]["GITHUB_SHA"] = "0" * 40
    with pytest.raises(gha.Refusal, match="not 000000000000"):
        _run(world)


# ── end to end ────────────────────────────────────────────────────────────
def test_the_agents_work_becomes_a_pull_request(world):
    assert _run(world) == 0
    saw = json.loads((world["tmp"] / "agent-saw.json").read_text())
    assert saw == [], f"the agent could see {saw}"
    out = _outputs(world)
    assert out["outcome"] == "PASS" and out["commits"] == "1"

    rc, calls = _publish(world)
    assert rc == 0
    (method, url, pr), = calls
    assert url.endswith("/repos/o/r/pulls") and pr["base"] == "main"
    assert pr["head"] == "handcode/run-7-1" and pr["draft"] is False
    assert pr["title"] == "handcode: Add a hello file"
    assert "> Add a hello file" in pr["body"] and "outcome     PASS" in pr["body"]
    # The branch is on the remote with the file; main is untouched.
    assert "hello" in _g(world["remote"], "show", "handcode/run-7-1:hello.txt")
    assert _g(world["remote"], "rev-parse", "main") == world["env"]["GITHUB_SHA"]
    assert _outputs(world)["pull-request"] == "https://example/pr/1"


def test_a_failed_check_opens_a_draft_and_fails_the_job(world):
    assert _run(world, "fail") == 0             # the run job hands over regardless
    rc, calls = _publish(world)
    assert rc == 1
    assert calls[0][2]["draft"] is True
    assert calls[0][2]["title"].startswith("[FAIL] handcode:")


def test_no_changes_means_no_pull_request(world):
    assert _run(world, "none") == 0
    rc, calls = _publish(world)
    assert rc == 0 and calls == []


def test_an_edit_to_a_workflow_is_refused(world):
    _run(world, "workflow")
    with pytest.raises(gha.Refusal, match="workflow file"):
        _publish(world)


def test_rewritten_history_has_nothing_to_propose(world):
    assert _run(world, "amend") == 0
    assert not (world["tmp"] / "out" / "result.bundle").exists()
    rc, calls = _publish(world)
    assert calls == []


def test_a_result_for_another_commit_is_refused(world):
    _run(world)
    meta = world["tmp"] / "out" / "meta.json"
    m = json.loads(meta.read_text())
    meta.write_text(json.dumps({**m, "base": "1" * 40}))
    with pytest.raises(gha.Refusal, match="worked from 111111111111"):
        _publish(world)


def test_a_dry_run_pushes_nothing(world):
    _run(world)
    rc, calls = _publish(world, env={"HANDCODE_DRY_RUN": "true"})
    assert rc == 0 and calls == []
    assert "handcode/run-7-1" not in _g(world["remote"], "branch", "--list")


def test_when_actions_may_not_open_prs_it_says_which_setting(world, capsys):
    _run(world)
    rc, _ = _publish(world, answer=(403, {"message": "GitHub Actions is not "
                                          "permitted to create or approve pull requests."}))
    assert rc == 1
    said = capsys.readouterr().out
    assert "Allow GitHub Actions to create and approve pull requests" in said
    assert "compare/main...handcode/run-7-1" in said


# ── the pieces ────────────────────────────────────────────────────────────
def test_the_agents_words_cannot_close_the_fence():
    body = gha.fenced("```\n# injected heading\n```")
    fence = body.splitlines()[0][:-len("text")]
    assert len(fence) == 4 and body.endswith("\n" + fence)


def test_a_huge_report_is_cut_to_fit_a_pr():
    body = gha.render_body("t", {"text": "x" * 100_000}, {}, {})
    assert len(body) <= gha.BODY_LIMIT


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux subreaper")
def test_a_process_the_agent_leaves_running_is_stopped():
    assert gha.become_subreaper()
    subprocess.run(["sh", "-c", "setsid sleep 300 >/dev/null 2>&1 &"], check=True)
    assert gha.sweep() >= 1
    assert not gha._descendants(__import__("os").getpid())


def test_the_run_job_is_never_handed_a_token():
    run_action = (ROOT / "action.yml").read_text(encoding="utf-8")
    for leak in ("github.token", "secrets.", "HANDCODE_TOKEN", "GITHUB_TOKEN"):
        assert leak not in run_action
    # Inputs reach a script through env, never pasted into a `run:` line.
    for line in run_action.splitlines():
        if line.strip().startswith("run:"):
            assert "${{" not in line, line
    assert "HANDCODE_TOKEN" in (ROOT / "publish" / "action.yml").read_text(encoding="utf-8")
    example = (ROOT / "examples" / "handcode.yml").read_text(encoding="utf-8")
    run_job = example.split("pull-request:")[0]
    assert "persist-credentials: false" in run_job
    assert "contents: read" in run_job and "write" not in run_job


def test_a_real_run_writes_the_report_the_action_reads(tmp_path):
    """The real `agentctl run`, a scripted model, `--accept` and
    `--report-json`: what the run job hands to the publish job. No key."""
    import os
    from scripted_model import serve

    srv, url = serve()
    home = tmp_path / "home"
    home.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    _g(ws, "init", "-q")
    env = {k: v for k, v in os.environ.items()
           if not k.endswith("_API_KEY") and k not in ("AGENTCTL_MODEL", "AGENTCTL_BASE_URL")}
    env.update(HOME=str(home), USERPROFILE=str(home), AGENTCTL_HOME=str(home / ".agentctl"),
               OPENHANDS_SUPPRESS_BANNER="1", PYTHONIOENCODING="utf-8")
    accept = f'"{sys.executable}" -c "import pathlib,sys; sys.exit(0 if pathlib.Path(\'hello.txt\').read_text().strip() == \'hello\' else 1)"'
    try:
        p = subprocess.run([sys.executable, "-m", "agentctl.cli", "run", "write hello.txt",
                            "--workspace", str(ws), "--model", "openai/scripted",
                            "--base-url", url, "--accept", accept,
                            "--report-json", str(tmp_path / "out" / "report.json")],
                           env=env, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=300)
    finally:
        srv.shutdown()
    assert p.returncode == 0, p.stdout[-3000:] + p.stderr[-3000:]
    r = json.loads((tmp_path / "out" / "report.json").read_text(encoding="utf-8"))
    assert r["outcome"] == "PASS" and r["ok"] is True
    assert r["files"] == ["hello.txt"] and r["accept"]["exit"] == 0
    assert "outcome     PASS" in r["text"] and r["conversation_id"]
