# Antigravity Slack Gateway

Local Python process that connects a Slack app to the Antigravity agent over Slack Socket Mode. Socket Mode is an outbound connection from this machine, so the gateway does not open a public HTTP port.

In a channel, mention the bot or run `/antigravity` with a prompt. In a thread that already has a session, reply in the thread. In a direct message, message the bot. The gateway keeps one session per direct message, per channel thread, or per channel (when the message is not in a thread). It creates a working directory for that session, runs the agent there, and posts the text result back to Slack.

Tool approval buttons in Slack are handled by the same process. `send_slack.py` can post a message without starting the gateway. `antigravity_wrapper.py` resolves conversation aliases and then runs `agy.exe`.

## Prerequisites

- Python 3.7 or newer. `antigravity_wrapper.py` relies on JSON object order from Python 3.7 onward. The commands in this file were run with Python 3.12.3.
- `pip`, and the standard library `venv` module if you want an isolated install (`python3 -m venv`).
- A Slack app created from [`slack-manifest.json`](slack-manifest.json). That manifest turns on Socket Mode, interactivity, the slash commands this repo implements, and the bot event subscriptions and scopes listed in the file.
- `SLACK_BOT_TOKEN` (bot token from **OAuth & Permissions** after you install the app).
- `SLACK_APP_TOKEN` (app-level token from **Basic Information** with the `connections:write` scope).
- One or more Slack member IDs in `SLACK_ALLOWED_USERS`. An empty list makes the bot refuse every user.
- `agy.exe` for agent runs. `antigravity_wrapper.py` looks for it beside the wrapper, then in the `agy/bin` directory under `LOCALAPPDATA` (or `~/AppData/Local` when that variable is unset).

Create the Slack app at <https://api.slack.com/apps> with **Create New App**, then **From an app manifest**, and paste `slack-manifest.json`.

## Install, build, run, test

There is no compile or package build. The programs are the Python files in the repository root.

From the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
cp example.env .env
```

`requirements.txt` installs `slack-bolt` (which installs `slack_sdk`), `python-dotenv`, and `requests`. The scripts import `slack_bolt`, `slack_sdk`, and `python-dotenv`. None of them import `requests`.

Edit `.env` before starting the gateway. Variable names the code reads:

| Variable | Required | Purpose |
| --- | --- | --- |
| `SLACK_BOT_TOKEN` | yes | Slack bot token. The gateway exits if this is missing. `send_slack.py` and the approval hook use it too. |
| `SLACK_APP_TOKEN` | yes for the gateway | Socket Mode app token. The gateway exits if this is missing. |
| `SLACK_ALLOWED_USERS` | yes, to allow anyone | Comma-separated Slack member IDs. Empty means every caller is refused. |
| `SLACK_HOME_CHANNEL` | no | Channel ID used by `send_slack.py` when `--channel` is omitted. |
| `SLACK_HOME_CHANNEL_NAME` | no | Channel name used by `send_slack.py` when no channel ID is set. Default `general`. A leading `#` is stripped. |
| `ANTIGRAVITY_WORKSPACE_ROOT` | no | Parent directory for session folders. Default is the home directory. Each new session gets `slack_workspaces/proj_<unix-time>_<8-char-id>` under that parent. |
| `ANTIGRAVITY_BIN` | no | Program the gateway runs. Default is `antigravity_wrapper.py` next to `gateway.py`. If that file is missing, the default is `agy/bin/antigravity_wrapper.py` under `LOCALAPPDATA` or `~/AppData/Local`. |
| `ANTIGRAVITY_SKIP_PERMISSIONS` | no | `true` or `false`. Default `true`. New sessions copy this into `skip_permissions`. When that flag is true, the agent command includes `--dangerously-skip-permissions`. |
| `ANTIGRAVITY_SANDBOX` | no | `true` or `false`. Default `false`. New sessions copy this into `use_sandbox`. When that flag is true, the agent command includes `--sandbox`. |

`example.env` also comments on `GEMINI_API_KEY`. `gateway.py` does not read that variable.

Start the listener from the repository root (the process writes `gateway.log` and `session_store.json` in the current directory):

```bash
python3 gateway.py
```

If `SLACK_BOT_TOKEN` or `SLACK_APP_TOKEN` is unset, the process logs `Missing SLACK_BOT_TOKEN or SLACK_APP_TOKEN in environment variables.` and exits with status 1. If `ANTIGRAVITY_BIN` does not exist, it logs a warning and still starts.

This repository has no test suite and no test runner. These checks match the commands that were run against this tree:

```bash
python3 -m py_compile gateway.py send_slack.py slack_approval_hook.py antigravity_wrapper.py
python3 send_slack.py --help
python3 antigravity_wrapper.py alias
printf '' | python3 slack_approval_hook.py
```

`py_compile` only checks syntax. `send_slack.py --help` prints the CLI and exits. `antigravity_wrapper.py alias` prints usage and any saved aliases. Empty stdin to `slack_approval_hook.py` prints `{"decision": "allow"}`.

`python3 antigravity_wrapper.py --version` exits with status 1 when `agy.exe` is not on either search path. That flag is forwarded to `agy.exe` only after the file is found.

## Usage

### Talk to the agent in Slack

The bot accepts a prompt when your member ID is in `SLACK_ALLOWED_USERS` and that session has no agent process already running.

- Channel: mention the bot, or `/antigravity` followed by the prompt. The mention form strips the `<@...>` tag and sends the remaining text.
- Thread that already belongs to a session: reply with the prompt. A leading `!` runs a command instead of a prompt.
- Direct message: send the prompt. The session key is the DM channel ID, so later DMs continue the same session.

The gateway starts `ANTIGRAVITY_BIN` in the session directory. When the path ends in `.py`, it uses the same Python interpreter as the gateway. The arguments are:

```text
--conversation <conversation_id> --add-dir <workspace> --model <model> --print <prompt>
```

`--dangerously-skip-permissions` and `--sandbox` are added only when the session flags say so. The default model is `gemini-3.5-flash`. The process is killed after 300 seconds.

On exit code 0, Slack receives stdout. If stdout is empty, the gateway reads the last `MODEL` entry with `content` from `~/.gemini/antigravity-cli/brain/<conversation_id>/.system_generated/logs/transcript.jsonl`. If that is also empty, it scans the last 25 lines of `~/.gemini/antigravity-cli/cli.log` for a quota message, a not-logged-in or OAuth failure, or a line that contains `E060` and `error`. After a run, a matching workspace entry in `~/.gemini/antigravity-cli/cache/last_conversations.json` replaces the session conversation ID.

A second prompt in a busy session gets a message to wait or stop the task. `/ag-stop` records the process as user-stopped, then terminates it. A user-stopped process does not post an error.

### Slack commands

Slash commands work from the Bolt handlers below. Inside a thread, use the `!` form (`!status`). The same words work after a mention (`@Antigravity !status`).

| Command | `!` form | Effect |
| --- | --- | --- |
| `/ag-help` | `!help` | Post the command list. |
| `/ag-new`, `/ag-reset` | `!new`, `!reset` | Replace the session conversation ID. The workspace path stays. |
| `/ag-status` | `!status` | Workspace, conversation ID, model, YOLO flag, sandbox flag, and whether a task is running. |
| `/ag-workspace` | `!workspace` | No argument: show the path. With a path: create it if needed and store the absolute path. |
| `/ag-stop` | `!stop` | Stop the active agent process for this session. |
| `/ag-model` | `!model` | No argument: show the current model. Accepted names: `gemini-3.5-flash`, `gemini-3.5-pro`, `gemini-3.5-flash-thinking`. |
| `/ag-yolo` | `!yolo` | Toggle `skip_permissions` for this session. |
| `/ag-sandbox` | `!sandbox` | Toggle `use_sandbox` for this session. |
| `/ag-version` | `!version` | Run the agent program with `--version` (10 second timeout). Exit code 0 posts stdout. Any other result posts `Unknown`. |
| `/antigravity <prompt>` |  | Start an agent run with that prompt. |
|  | `!alias <name>` | Store `<name>` to the session conversation ID in `~/.gemini/antigravity/session_aliases.json`. |

### Post a message with send_slack.py

`send_slack.py` loads `.env` from the directory that contains the script. It needs `SLACK_BOT_TOKEN`. The gateway process does not have to be running.

```bash
python3 send_slack.py "Hello from the CLI"
python3 send_slack.py --channel general "Hello general"
python3 send_slack.py -c general -t 1234567890.123456 "Thread reply"
printf '%s\n' "piped text" | python3 send_slack.py
```

`--channel` / `-c` accepts a channel name or a channel ID. `--thread` / `-t` is the thread timestamp. With no message argument, the script reads stdin when stdin is not a terminal.

Channel choice order: `--channel`, then `SLACK_HOME_CHANNEL`, then a single `conversations.list` lookup of `SLACK_HOME_CHANNEL_NAME`, then the channel ID hardcoded in `send_slack.py`. Set `SLACK_HOME_CHANNEL` when you want a known destination.

More notes on this CLI live in [`skills/slack-messaging/SKILL.md`](skills/slack-messaging/SKILL.md).

### Wrapper

`antigravity_wrapper.py` is the default `ANTIGRAVITY_BIN`. It can also be run on its own.

```bash
python3 antigravity_wrapper.py alias
python3 antigravity_wrapper.py alias my-session
python3 antigravity_wrapper.py alias my-session CONVERSATION_ID
python3 antigravity_wrapper.py --conversation my-session --version
```

`alias` with no name prints usage and the contents of `~/.gemini/antigravity/session_aliases.json`. `alias <name>` stores a conversation ID from `~/.gemini/antigravity-cli/cache/last_conversations.json`: an exact current-directory match, then a substring match, then the last value in that file. `alias <name> <conversation_id>` stores the ID you pass.

A `--conversation` value is replaced when it is an alias, or when it matches a workspace folder name or path in that cache. Every other argument is forwarded to `agy.exe`. The wrapper exits with status 1 when `agy.exe` is missing.

### Tool approval hook

`slack_approval_hook.py` reads one JSON object from stdin and prints one JSON decision to stdout. Logs go to stderr. The gateway must be running to receive button clicks. The hook only posts the message and polls `session_store.json`.

Set `gateway_dir` in `slack_approval_hook.py` to the directory that contains this repo's `.env` and `session_store.json`. The hook loads both files from that directory.

These inputs print `{"decision": "allow"}` without posting to Slack:

- Empty stdin.
- A tool name of `list_dir`, `read_file`, `search_grep`, or `get_outline`.
- A matching entry in `~/.gemini/antigravity-cli/settings.json` under `permissions.allow` (`*`, `command(<command line>)`, `command(*)`, `<tool>(<target>)`, or `<tool>(*)`).
- A session whose `conversation_id` matches `session_id` or `conversationId` in the payload, and whose `allowed_tools`, `allowed_commands`, or `skip_permissions` covers the call.
- No matching session channel, a missing `SLACK_BOT_TOKEN`, a failed Slack post, or any uncaught error in the hook.

Otherwise the hook writes a `pending_approvals` entry and posts four buttons:

- **Allow Once** (`approve_once`): mark that approval allowed.
- **Allow for Session** (`approve_session`): also append a `run_command` line to `allowed_commands`, or any other tool name to `allowed_tools`.
- **Allow Permanently** (`approve_permanent`): also append `command(<CommandLine>)` or `<tool>(<AbsolutePath or TargetFile or *>)` to `permissions.allow` when `settings.json` already exists.
- **Deny** (`deny_tool`): mark that approval denied.

The hook polls for up to 300 seconds. On timeout it updates the Slack message and prints `{"decision": "deny", "reason": ...}`.

`!yolo` / `/ag-yolo` flips `skip_permissions` for the current session. New sessions start from `ANTIGRAVITY_SKIP_PERMISSIONS`, which defaults to `true`, so a fresh session auto-approves in this hook until you toggle YOLO off.

## Layout

```text
gateway.py                    Socket Mode app, sessions, slash commands, approval buttons
send_slack.py                 Post one message with the bot token
slack_approval_hook.py        Stdin/stdout tool approval hook
antigravity_wrapper.py        Alias lookup, then agy.exe
slack-manifest.json           Slack app manifest
example.env                   Environment template
requirements.txt              Python dependencies
skills/slack-messaging/SKILL.md   Notes for send_slack.py
```

Runtime files `gateway.log` and `session_store.json` are gitignored, along with `.env`.

## License

This repository has no `LICENSE` file. The frontmatter in `skills/slack-messaging/SKILL.md` lists `MIT` for that skill file.
