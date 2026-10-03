# Quickstart

You need Python 3.12 or newer, `git`, and one API key. A free OpenRouter or
Gemini key works.

## 1. Install

**Windows** (PowerShell), in a short path such as `C:\src`:

```powershell
git clone https://github.com/csdeepak/HandCode
cd HandCode
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[openhands]"
```

**macOS / Linux:**

```bash
git clone https://github.com/csdeepak/HandCode
cd HandCode
python3 -m venv .venv          # Ubuntu: sudo apt install python3.12-venv first
source .venv/bin/activate
pip install -e ".[openhands]"
```

## 2. See what it is for (no key, no cost)

```bash
agentctl demo
```

An agent commits, its process is killed in the middle, and the run is resumed.
Without agentctl the commit happens twice. With it, once. This takes about a
minute, and uses a scripted model, so it needs no key and no network.

## 3. Set up one key

```bash
agentctl init
```

It uses a key you already have in your environment, or asks you to paste one;
the key is not shown on screen. It stores it in `~/.agentctl/keys.env`, outside
every repository. Then it sends **one** tiny request to check the key, and
remembers the model that answered.

## 4. Run a task

In any git repository:

```bash
cd your-project
agentctl run "the date parser rejects ISO dates with a Z suffix; fix it" --accept "python -m pytest -q"
```

`--accept` is your test command. agentctl runs it itself when the agent is done,
and the report says PASS or FAIL. Without it, the report says `not checked`.

The run ends with a report, like this one:

```
  outcome     PASS   `python -m pytest -q` exited 0
  changed     2 files  +14 -3
  agent said  "Fixed the Z suffix handling and added a test."
  used        11 requests · 50.3K tokens · $0.00 (free-tier model) · 28s
  actions     16 actions: 9 commands, 6 reads, 1 file write
  needs you   nothing
```

## 5. When a run stops

```bash
agentctl status       # recent runs and what needs you
agentctl resume       # continue the last run here
```

- Pressed Ctrl-C? It paused after the current step. `agentctl resume`.
- Terminal closed or laptop slept? The run shows as `died`. `agentctl resume`.
- Rate limited? Add `--wait 30m` and it waits and resumes on its own.
- A dangerous action is waiting for approval? `agentctl approve <id>`, then
  `agentctl resume`.

## 6. More than one provider (optional)

With keys for several providers, route through a pool, so that a daily cap or
an outage at one provider does not stop the run:

```bash
agentctl run "<task>" --pool
```

The first time, this sets up the pool's own environment (a few minutes). After
that it starts in seconds. `agentctl proxy status` and `agentctl proxy down`
manage it.
