# fastbrowse

Fast, DOM-based browser automation that runs in your own Chrome, with no screenshots. It reads the page as an element table, a local model plans each step, and Laya picks the target. A step takes 1 to 5 seconds instead of a screenshot loop.

It is read-first by design: any button that would publish, send, like, connect or follow is stopped before it is pressed.

## Contents

1. [How it works](#how-it-works)
2. [Usage vs consumption](#usage-vs-consumption)
3. [Benchmark](#benchmark)
4. [Requirements](#requirements)
5. [Install](#install)
6. [Chrome setup](#chrome-setup)
7. [Usage: commands](#usage-commands)
8. [Usage from Python](#usage-from-python)
9. [Safety model](#safety-model)
10. [Result format](#result-format)
11. [Troubleshooting](#troubleshooting)
12. [Known limits](#known-limits)
13. [File layout](#file-layout)
14. [Tests](#tests)

## How it works

| Part | Role |
|---|---|
| Chrome | The real browser, driven over CDP |
| `browser_harness` | Connects Python to Chrome |
| `laya-ultrafast` | Turns the page into an element table and picks the element for the goal |
| Ollama + `qwen3:4b-instruct-2507-q4_K_M` | Local model that plans the next step |
| `DENY` regex | The veto that stops dangerous buttons before execution |

Each step:

1. Read the page as an element table.
2. The model picks the element that serves the goal.
3. The element's label is checked against the veto list.
4. Safe: it runs. Dangerous: the run stops with `reason: vetoed`.
5. Success is decided by the page itself, not by the model's word.

## Usage vs consumption

**Usage** is what you do: commands, options, steps. See [Usage: commands](#usage-commands).

**Consumption** is what the tool costs your machine while it runs. Figures are approximate and vary by hardware.

| Resource | Consumption | Note |
|---|---|---|
| API cost | Zero | The model is local, no keys, no bills |
| Tokens | Zero to any external provider | All planning runs on your Ollama |
| Memory | Roughly the model size while loaded (not measured) | Ollama keeps it resident for a while after a run |
| Disk | 2.5 GB for the model | One time, at `ollama pull` |
| Local planner tokens | About 480 per run (see [Benchmark](#benchmark)) | One planner call per run, measured |
| Run time | 0.3 to 0.5 s with a browser already open, about 1.7 to 2.3 s when it starts and stops Chrome each run | See [Benchmark](#benchmark) |
| Network | Only the page load itself | No data is sent to any service |
| Chrome | One background tab | The tool opens its own tab and never touches yours |
| Delay between profiles | 8 to 25 seconds, randomized | Deliberately slow to protect the account, do not shorten |

| | Usage | Consumption |
|---|---|---|
| Question | How do I run it | What does it cost me |
| Answer | Commands and options | RAM, disk, time, zero money |
| Where | Commands section | Table above |

Compared with screenshot-based automation: that approach sends an image of every step to a vision model, which burns tokens and time. Here the page becomes small text, so steps are faster and free.

## Benchmark

`bench.py` runs three tasks against a small local site (no internet, no logins) in six browser situations. A local proxy sits between the planner and Ollama and sums the `usage` field of every response, so token numbers are measured, not guessed. Raw rows: `bench_results.json`.

Measured on 2026-10-02, model `qwen3:4b-instruct-2507-q4_K_M`, local Laya sidecar, macOS. All modes ran 10 times per task. Every run passed (the veto task passes only when the run ends with `reason: vetoed` and no click was made).

Terms:

- **Cold**: fastbrowse starts Chrome, runs the task, then shuts everything down, on every run. This is what `--isolated` does when you run a command.
- **Warm**: Chrome is already running and the run only attaches to it. This is the case when you keep a Chrome open (your own, or a long-lived `--isolated --profile` Chrome kept up by your own script).
- **Headless / headed**: no window / a visible window.
- **New tab / same tab**: fastbrowse opens a fresh background tab per run (library default) / reuses one tab and only navigates it (the benchmark patches the library to measure this).

All times are medians of the full run, including browser start and shutdown where they apply.

| Situation | one-hop | two-hop | veto | Of which open + close |
|---|---|---|---|---|
| Cold, headless | 1.68 s | 1.86 s | 1.62 s | about 0.9 s |
| Cold, headed | 2.20 s | 2.28 s | 2.17 s | about 1.4 s |
| Warm, headless, new tab | 0.30 s | 0.51 s | 0.28 s | 0 |
| Warm, headed, new tab | 0.30 s | 0.49 s | 0.28 s | 0 |
| Warm, headless, same tab | 0.28 s | 0.47 s | 0.27 s | 0 |
| Warm, headed, same tab | 0.27 s | 0.47 s | 0.27 s | 0 |

First run (the first task after the situation starts, so it pays one-time setup):

| Situation | First run |
|---|---|
| Cold, headless | 2.38 s |
| Cold, headed | 1.94 s |
| Warm, headless, new tab | 1.77 s |
| Warm, headed, new tab | 0.84 s |
| Warm, headless, same tab | 1.82 s |
| Warm, headed, same tab | 1.14 s |
| Warm, headless, Ollama model unloaded first (1 run) | 4.18 s, then 0.52 s and 0.34 s |

What the numbers say:

- **Opening and closing the browser costs about 1 to 1.5 s.** Cold runs take 1.6 to 2.3 s, warm runs 0.3 to 0.5 s. Chrome starts in about 0.3 s, and the rest of the open/close time is stopping the daemon (0.6 s) and the first tab setup.
- **A 15 s teardown was found and fixed.** Before the fix, cold runs took about 17 s: `restart_daemon()` waits 15 s (75 polls of 0.2 s) for the browser-harness daemon to exit, and the daemon never exits by itself. `reset_daemon()` now sends SIGTERM to the daemon (PID taken from the daemon's own answer, not a PID file), waits up to 0.5 s, then SIGKILL. Measured teardown went from 15.3 s to 0.6 s. Closing Chrome first did not help (still 15.25 s), so the order was not the cause.
- **Headless vs headed:** no meaningful difference when warm (0.30 s vs 0.30 s). Cold headed was about 0.5 s slower (2.20 s vs 1.68 s).
- **New tab vs same tab:** reusing the tab saves about 0.02 to 0.04 s per run. The library opens a background tab each run, and that is cheap, so it is not worth patching.
- **First run:** warm first runs are 0.8 to 1.8 s because of one-time warmup. If Ollama had unloaded the model, the first run took 4.18 s to load it again (one measurement, not a statistic). Cold first runs were 1.9 to 2.4 s.
- **Tokens:** the local model is called once per run, about 455 prompt and 26 to 31 completion tokens (median 479 / 488 total). Each step's element choice is made by the local Laya sidecar, so extra steps did not add LLM tokens. External API tokens: 0.

### fastbrowse vs Claude in Chrome

Same fixture site, same two tasks, same machine, 2026-10-02. Claude in Chrome was driven by an agent with its screenshot path (screenshot at 0.5 scale, click by coordinates, verify with `get_page_text`) in an already open Chrome. Raw rows: `bench_claude_in_chrome.json`.

The closest comparison for Claude in Chrome is the warm case, because its Chrome was already open. The cold column adds fastbrowse's own Chrome start and stop.

| | fastbrowse warm | fastbrowse cold | Claude in Chrome |
|---|---|---|---|
| one-hop, median time | 0.30 s (10 runs) | 1.68 s (10 runs) | 7.33 s (3 runs) |
| two-hop, median time | 0.51 s (10 runs) | 1.86 s (10 runs) | 10.80 s (3 runs) |
| one-hop, tool calls / model turns | in-process, 1 planner call | same | 4 calls / 2 turns |
| two-hop, tool calls / model turns | in-process, 1 planner call | same | 6 calls / 3 turns |
| one-hop, tokens | 479 local, 0 external | same | about 542 in tool results (estimate), billed |
| two-hop, tokens | 488 local, 0 external | same | about 951 in tool results (estimate), billed |
| Pass rate | 10/10 and 10/10 | 10/10 and 10/10 | 3/3 and 3/3 by screenshot path |
| Stops dangerous clicks before they happen | Yes (veto) | Yes | No built-in veto |

Speed when both browsers are already open: fastbrowse was about 24x faster on one-hop and about 21x on two-hop. When fastbrowse starts and stops its own headless Chrome every run, it was still about 4x faster on one-hop (1.68 s vs 7.33 s) and about 6x on two-hop (1.86 s vs 10.80 s).

How to read the token rows:

- fastbrowse tokens are measured at the Ollama proxy and are local, so they cost nothing per call.
- Claude in Chrome tokens are an estimate from tool-result sizes: images at width x height / 750 (a 784x340 screenshot is about 355 tokens), text at characters / 4. They exclude the agent's own output tokens and the re-reading of earlier turns, so real billed usage is higher than shown.
- The two columns measure different things. One is local planner tokens with no bill, the other is external input that is billed.

What the Claude in Chrome runs showed beyond the numbers:

- The `find` plus click-by-`ref` path reported "Clicked" twice and the page did not navigate either time (0 of 2). One read in the middle of that failed because the extension disconnected. The coordinate path from a screenshot worked every time (6 of 6 timed runs).
- A click result does not confirm the navigation. The tab info in the result was stale, so every run needed a separate read to verify.

Fairness notes:

- Claude in Chrome time includes the agent's model round trips, which is what an agent loop really costs. fastbrowse plans in-process.
- 10 runs vs 3 runs, on a tiny local page. Treat the ratios as an order of magnitude, not a precise figure.
- Claude in Chrome is the better tool when you need screenshots, complex pages, uploads or a side effect on purpose. fastbrowse is for fast, read-first, vetoable work.

To reproduce the Claude in Chrome side: serve the fixture with `uv run python -c "import bench,time; bench.serve(bench.Site,8791); time.sleep(900)"`, then run each task through the Claude in Chrome tools while stamping `date +%s%N` before and after.

Limits of this benchmark:

- The fixture site is tiny. Real pages have far more elements, so planner prompts and step times grow.
- In trial runs, a plain `<button>` with a click handler was never picked by the chooser (0 of 4 runs), while a link labelled Subscribe was and got vetoed. Do not rely on the veto for buttons the chooser cannot see.
- Three tasks is a smoke benchmark, not a statistical study. The model-unloaded first run is a single measurement.
- Memory use was not measured.

Reproduce it:

```bash
uv run python bench.py --runs 10
uv run python bench.py --runs 1 --modes warm-headless --unload-model
```

The first command runs all six situations and writes `bench_results.json` (about 3 minutes in total). The second measures the first run after unloading the model. Requirements: Ollama running with the model pulled, the Laya sidecar on port 8765, and Chrome installed.

## Requirements

| Needed | Why |
|---|---|
| macOS | The Chrome path is hardcoded for Mac |
| Google Chrome | At `/Applications/Google Chrome.app` |
| Python 3.12 or newer | Required by `pyproject.toml` |
| `uv` | Manages the environment and dependencies |
| Ollama | Local planning and suggested comment drafts |
| Git | To fetch `laya-ultrafast` from GitHub |

Optional:

| Needed | Why |
|---|---|
| Laya sidecar on port 8765 | Only for `--triage` in `activity.py` |

The sidecar is not part of this repo. Skip `--triage` if you do not run one.

## Install

```bash
git clone git@github.com:mohamedyasser/fastbrowse.git
cd fastbrowse
brew install uv
uv sync
```

Pull the local model:

```bash
ollama pull qwen3:4b-instruct-2507-q4_K_M
```

Sanity check (no Chrome needed, tests only):

```bash
uv run pytest -q
```

## Chrome setup

Pick one of two ways.

### Option 1: dedicated profile (best for daily use)

No "Allow remote debugging" prompt on every run. The tool launches its own Chrome with a persistent profile.

1. Open the profile once and sign in to the site you need (LinkedIn for example):

```bash
open -na "Google Chrome" --args --user-data-dir=$HOME/.fastbrowse-chrome https://www.linkedin.com/feed/
```

2. After signing in, quit Chrome with Cmd+Q. Do not use `pkill`: a hard kill right after login can lose the session.
3. Add these flags to any command:

```bash
--isolated --profile ~/.fastbrowse-chrome
```

Rules:

- Only one Chrome per profile. Quit the one you opened before running anything.
- Running without `--headed` is headless and the most stable.

### Option 2: your current Chrome

1. Open `chrome://inspect/#remote-debugging`.
2. Accept the "Allow remote debugging" prompt when Chrome asks.
3. Run the command without `--isolated`.

The prompt appears on every new connection. If attach fails, accept the prompt once and do not retry in a loop.

### `--isolated` without a profile

Launches a throwaway Chrome with no logins, deleted after the run. Good for public sites.

## Usage: commands

Run everything from the repo root. Options shared by all commands:

| Option | Meaning |
|---|---|
| `--isolated` | Throwaway Chrome instead of yours |
| `--headed` | With `--isolated`: show the window. It may time out on the new tab, so prefer headless |
| `--port` | Debug port, default 9333 |
| `--profile DIR` | With `--isolated`: keep the profile between runs |

A leading `--` is ignored, so both forms work.

### 1. General goal-driven browsing: `fastbrowse.py`

```bash
uv run python fastbrowse.py --url https://example.com --goal "Open the pricing page" --title-contains pricing --max-steps 6
```

| Option | Meaning |
|---|---|
| `--url` | Starting page (required) |
| `--goal` | The goal as one sentence (required) |
| `--url-contains` | Success check: URL contains this text |
| `--title-contains` | Success check: title contains this text |
| `--text-contains` | Success check: page text contains this text |
| `--max-steps` | Step cap, default 10 |

The three `--*-contains` options can be repeated. If you pass any, success is decided by the page. If you pass none, success relies on the model saying `DONE`, which is weaker.

Exit code is 0 only when `ok`.

### 2. Read LinkedIn profile activity: `activity.py`

```bash
uv run python activity.py sara-ali https://www.linkedin.com/in/omar-hassan/ --limit 5 --scrolls 3 --isolated --profile ~/.fastbrowse-chrome
```

| Option | Meaning |
|---|---|
| `profiles` | One or more slugs or `linkedin.com/in/...` URLs |
| `--limit` | Posts kept per profile, default 5 |
| `--scrolls` | Scroll count, default 3 |
| `--triage` | Add a relevance label per post (needs the sidecar) |
| `--sidecar` | Sidecar address, default `http://127.0.0.1:8765` |
| `--min-pause` / `--max-pause` | Wait between profiles, 8 and 25 seconds |

Output is JSON per profile: author, headline, age, text, reposted_by, reactions, comments. With `--triage` it also adds `relevance` and `confidence`.

### 3. Read a post and all its comments: `comments.py`

```bash
uv run python comments.py https://www.linkedin.com/feed/update/urn:li:activity:123/ --isolated --profile ~/.fastbrowse-chrome
```

Output: the parsed post plus the text of existing comments and replies. Read-only.

Run it before drafting any comment. Check the post age, who already answered and what advice was given, so you do not repeat it.

### 4. Prepare a comment: `engage.py`

```bash
uv run python engage.py <post-url> --dry-run
uv run python engage.py <post-url> --text "the exact comment" --isolated --profile ~/.fastbrowse-chrome
```

| Option | Meaning |
|---|---|
| `url` | Post URL |
| `--text` | Fill exactly this text (preferred) |
| `--angle` | Steer the model when it drafts |
| `--model` | Ollama model for the draft |
| `--dry-run` | Print the draft only, do not touch the comment box |

What happens:

1. Opens the post in a background tab.
2. Opens the comment box.
3. Types the text.
4. Leaves the tab open in front of you.
5. **You press Post.** No code path presses it.

Tip: small local models are weak at Arabic. Use `--text` with your own text, it fills in under a second. Automatic drafts are a starting point only.

Maximum comment length is 600 characters.

The automatic draft uses a prompt written for Flowfy in the `SYSTEM` constant in `engage.py`. Edit it before using the draft for anything else.

## Usage from Python

```bash
uv run python - <<'PY'
from fastbrowse import browse, contains, chrome_session
with chrome_session(isolated=False):
    r = browse("https://example.com", "Open the pricing page",
               success=contains(title=["pricing"]), max_steps=6)
print(r)
PY
```

Signature:

```python
browse(url, goal, *, success=None, max_steps=10, retries=1, deny=DENY)
```

| Parameter | Meaning |
|---|---|
| `success` | Function that checks the page. Use `contains(url=, title=, text=)` |
| `max_steps` | Step cap |
| `retries` | Retry once on "Document is navigating" |
| `deny` | A regex or `callable(action, page) -> bool`, checked before each click |

For read-only DOM work without the agent: `open_page(url)`, then `settle(browser)`, then `browser.evaluate(js)`. See `activity.py` for a full example.

## Safety model

1. **Read-only by default.** The veto stops the run before the click when the label matches: send, post, publish, like, react, connect, follow, unfollow, message, comment, reply, delete, remove, buy, pay, purchase, checkout, order, apply, subscribe, block, report, plus their Arabic equivalents.
2. **Never loosen `deny`.** If you really need a side effect, do it with another tool and with your explicit approval.
3. **Nothing publishes without a human.** `engage.py` has exactly one click, on the button that opens the comment box, and a test asserts it.
4. **`DONE` is not proof.** Pass a success check so the page decides.
5. **The veto matches labels.** An unlabeled icon button can slip through, so keep `--max-steps` low.
6. **No credentials.** If you are not signed in, the tool reports an error and never types login details.
7. **Human pacing.** 8 to 25 seconds between profiles. Do not shorten this on a real account.
8. **One run at a time.** The daemon name is fixed.

## Result format

`fastbrowse.py` prints JSON:

| Field | Meaning |
|---|---|
| `ok` | Succeeded or not |
| `reason` | Why, values below |
| `steps` | Number of steps |
| `elapsed_ms` | Total time |
| `agent_ms` | Agent time |
| `url` | Final URL |
| `trail` | Actions in order |
| `error` | Error message, or the label of the vetoed button |

`reason` values:

| Value | Meaning |
|---|---|
| `success` | The page met the success check |
| `agent_done` | The agent said done and there was no success check |
| `done_unverified` | The agent said done but the page did not match the check |
| `vetoed` | Stopped before a dangerous click. The label is in `error` |
| `blocked` | The agent got stuck |
| `max_steps` | Hit the step cap |
| `error` | Runtime error |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `daemon default didn't come up` or `already running` | The tool restarts the daemon automatically. If stuck: `pkill -f browser_harness`, then rerun |
| Attach hangs or is refused | Chrome has not allowed remote debugging yet. Accept the prompt, or use `--isolated --profile` |
| `Document is navigating` | Retried once automatically. If it persists, rerun |
| `reason: vetoed` | Working as intended. The tool stopped before a dangerous button |
| Port 11434 refused | Run `ollama serve` and confirm the model is pulled |
| `--triage` fails | The sidecar is not running on 8765 |
| `LinkedIn is not signed in in this Chrome` | Sign in inside the profile you are using |
| "No results found" though results exist | The page was still loading. The tool waits for it to settle, try again |
| Chrome will not start with `--profile` | Another Chrome is using that profile. Quit it with Cmd+Q |
| `Runtime.evaluate` times out with `--headed` | Run without `--headed` |

## Known limits

- English LinkedIn UI only ("Feed post", "Connect", "Follow", "Like").
- The activity parser and the comment-box recipe were verified against LinkedIn-shaped fixtures. Make the first live use one profile and one post, watched.
- Out of scope: shadow DOM, iframes, canvas, file uploads. Use another tool for those.
- The Chrome path is macOS-only.
- LinkedIn company search: location words in `keywords=` are ignored. Filter with `companyHqGeo` using these IDs: Saudi Arabia 100459316, Egypt 106155005, UAE 104305776.

## File layout

| File | Role |
|---|---|
| `fastbrowse.py` | Core: goal-driven browsing, veto, Chrome sessions |
| `activity.py` | Read LinkedIn profile activity |
| `comments.py` | Read a post and its comments |
| `engage.py` | Prepare a comment without posting it |
| `linkedin.py` | LinkedIn text parser |
| `bench.py` | Benchmark: speed, pass rate, measured token consumption |
| `bench_results.json` | Output of the last fastbrowse benchmark run |
| `bench_claude_in_chrome.json` | Measured Claude in Chrome runs on the same tasks |
| `test_*.py` | Tests (no Chrome needed) |
| `pyproject.toml`, `uv.lock` | Pinned dependencies |

## Tests

```bash
uv run pytest -q
```

The tests need neither Chrome nor Ollama.
