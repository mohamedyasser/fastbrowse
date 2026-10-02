---
name: fastbrowse
description: Fast, DOM-based browser automation in your own Chrome (no screenshots) using a local planner model plus Laya. Use for browser tasks where speed matters, where you are already logged in (LinkedIn, dashboards), or where a step must be blocked before it publishes, sends, likes or follows. Covers reading LinkedIn profile activity, reading a post with its comments, preparing (never posting) a LinkedIn comment, and goal-driven browsing with a pre-execution veto. Triggers - "fastbrowse", "browse fast", LinkedIn activity/engage, slow screenshot-based browsing.
---

# fastbrowse

Run everything from the fastbrowse repo root. Full docs and benchmarks: `README.md`.

It reads the page as a DOM element table (no screenshots), a local model (`qwen3:4b-instruct-2507-q4_K_M` via Ollama) plans, and Laya picks the target. With a browser already open a run takes 0.3 to 0.5 s. When fastbrowse starts and stops its own headless Chrome it takes about 1.7 to 2.3 s.

## Pick the tool

| Task | Use |
|---|---|
| Read someone's recent LinkedIn posts | `activity.py` |
| Read a post and every existing comment on it | `comments.py` (run this BEFORE drafting any comment) |
| Comment on a LinkedIn post | `engage.py` (fills the box, **the user presses Post**) |
| Goal-driven navigation on any site, read-only | `fastbrowse.py` |
| Screenshots, canvas, iframes, shadow DOM, uploads, or a side effect on purpose | NOT fastbrowse: use another browser tool |

## Preflight (once per task)

1. Ollama up and model pulled: `ollama list` shows `qwen3:4b-instruct-2507-q4_K_M`.
2. Laya sidecar up on `http://127.0.0.1:8765`, only needed for `--triage` and the goal-driven chooser.
3. Chrome: use `--isolated --profile ~/.fastbrowse-chrome` (sign in once, quit with Cmd+Q) to avoid the "Allow remote debugging" prompt, or accept that prompt in your own Chrome.
4. `uv sync`, then `uv run pytest -q` (54 tests, no Chrome needed).

## Commands

```bash
uv run python activity.py sara-ali https://www.linkedin.com/in/omar-hassan/ --limit 5 --scrolls 3 --isolated --profile ~/.fastbrowse-chrome
uv run python comments.py <post-url> --isolated --profile ~/.fastbrowse-chrome
uv run python engage.py <post-url> --dry-run
uv run python engage.py <post-url> --text "the exact comment" --isolated --profile ~/.fastbrowse-chrome
uv run python fastbrowse.py --url <url> --goal "Open the pricing page" --title-contains pricing --max-steps 6
```

- `activity.py` prints JSON per profile: author, headline, age, text, reposted_by, reactions, comments (and `relevance` with `--triage`). It waits 8 to 25 s between profiles: never shorten this on a real account.
- `comments.py` prints the parsed post and the raw text of existing comments and replies. Read-only.
- `engage.py` opens the post in a background tab, opens the comment box, types the text and leaves the tab open. **No code path presses Post.** Without `--text` it drafts with the local model (`--angle` steers it). Arabic drafts from small models are weak, so prefer writing the text yourself and passing `--text`.
- `fastbrowse.py`: judge success by the page. Always pass `--title-contains`, `--url-contains` or `--text-contains`. The agent saying DONE alone gives `agent_done` or `done_unverified`, not proof.
- Common flags: `--isolated`, `--headed`, `--port`, `--profile DIR`.

Result reasons: `success`, `agent_done`, `done_unverified`, `vetoed`, `blocked`, `max_steps`, `error`. The exit code is 0 only when `ok`.

## Rules for using it (mandatory)

1. **Read-only by default.** The veto stops the run before the click for labels such as Send, Post, Like, React, Connect, Follow, Message, Comment, Reply, Delete, Buy, Pay, Order, Subscribe, Block, Report (and Arabic equivalents). Never loosen `deny` to get past it. If a real side effect is wanted, do it with another tool after explicit user approval.
2. **Nothing publishes without the user.** Show the user the exact comment text first, run `engage.py`, tell them the tab is ready; they press Post.
3. **First live use on a new site or page shape: one item, watched.**
4. **One run at a time.** The daemon name is fixed. Never run two in parallel.
5. **Never type credentials.** If not signed in, the tool reports an error: tell the user to sign in in that Chrome.
6. **Leave the user's tabs alone.** The tool opens its own background tab.
7. English LinkedIn UI only ("Feed post", "Connect", "Follow", "Like").
8. **Read the thread before writing any public comment or reply.** Run `comments.py <post-url>` first and check how old the post is, who already answered, and what advice was already given. A repeated tip reads as noise. Draft only what adds something new.
9. **Reads use fastbrowse, not screenshots.** Profiles, posts and comments all go through these tools. Only the final send (Connect, comment, DM) needs another tool.
10. **The veto matches labels the chooser can see.** A plain button with only a click handler was not picked in benchmarks, so keep `--max-steps` low.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `daemon default didn't come up` or `already running` | The tool resets the daemon automatically. If stuck: `pkill -f browser_harness`, rerun |
| Attach hangs or is refused | Chrome has not allowed remote debugging. Accept the prompt or use `--isolated --profile` |
| `Document is navigating` | Retried once automatically. If it persists, rerun |
| `reason: vetoed` | Working as intended. Report the blocked label to the user |
| Port 11434 refused | `ollama serve`, confirm the model is pulled |
| `--triage` fails | The Laya sidecar is not running on 8765 |
| `LinkedIn is not signed in in this Chrome` | Ask the user to sign in in that profile |

## After a run

Report what was read or prepared, `reason`, steps and elapsed time. For `engage.py`: the exact text that sits in the box, and that Post is untouched.
