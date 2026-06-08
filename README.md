# Antigravity Slack Gateway

This is the independent Slack Gateway for **Antigravity**, connecting the agent directly to Slack via Socket Mode. It enables real-time project collaboration, automated agent coding, and interactive tool execution approvals directly in Slack threads.

## Features

- **Socket Mode Connection:** Connects securely to the Slack Cloud API without requiring public HTTPS endpoints, reverse-proxy tunnels (like ngrok), or local port exposure.
- **Thread-to-Workspace Mapping:** Automatically maps individual Slack threads to unique local project directories.
- **Multi-Agent CLI Integration Hook:** Ready to execute commands and scripts locally via subprocess execution of the Antigravity/Gemini agent engine.

---

## Getting Started

### 1. Prerequisites

Make sure you have Python 3.8+ installed.

### 2. Installation

Clone or locate this directory, and install the required dependencies:

```bash
pip install -r requirements.txt
```

### 3. Slack App Setup

To register your gateway with Slack:

1. Go to the [Slack App Console](https://api.slack.com/apps).
2. Click **Create New App** -> **From an app manifest**.
3. Select your workspace, and paste the contents of the JSON manifest: [slack-manifest.json](slack-manifest.json) (located in the root of this repository).
4. Go to **Basic Information** -> **App-Level Tokens** and generate a token with the `connections:write` scope. This is your `SLACK_APP_TOKEN`.
5. Go to **OAuth & Permissions** and click **Install to Workspace**. Copy the generated `Bot User OAuth Token`. This is your `SLACK_BOT_TOKEN`.

### 4. Configuration

Copy the example environment file and fill in your keys:

```bash
cp example.env .env
```

Edit the newly created `.env` file:

```env
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_APP_TOKEN=xapp-your-app-token
SLACK_ALLOWED_USERS=                         # Comma-separated list of Slack Member IDs
SLACK_HOME_CHANNEL=                          # Default channel ID for system messages (optional)
SLACK_HOME_CHANNEL_NAME=general
```

### 5. Running the Gateway

Start the gateway listener service:

```bash
python gateway.py
```

Once running, you can mention `@Antigravity` in any authorized Slack channel or DM the bot directly to start orchestrating!

## Sending Messages to Slack from CLI / Agent

The gateway includes a CLI utility `send_slack.py` that allows agents or shell users to send messages directly to the configured Slack workspace.

### Usage

```bash
# Send a message to the default home channel (e.g. #general)
python send_slack.py "Hello from the CLI!"

# Send a message to a specific channel (by name or ID)
python send_slack.py --channel "random" "Hello random channel!"

# Reply to a specific thread in a channel
python send_slack.py --channel "general" --thread "1780829722.426309" "Thread reply"

# Pipe content to a channel
cat logs.txt | python send_slack.py
```

## Interactive Tool Execution Approvals

The gateway features a robust, fully automated interactive tool approval system. When Antigravity attempts to run shell commands in any thread (and YOLO mode is disabled), it triggers a synchronous `BeforeTool` hook that prompts you with Approve/Deny buttons directly in the Slack thread:

1. **How it works:**
   * Antigravity invokes a tool (e.g., `run_command` with a shell script).
   * A global hook (`slack_approval_hook.py`) intercepts the action and pauses execution.
   * It logs a pending transaction inside `session_store.json` and posts an interactive message to Slack.
   * Clicking **Approve 🟢** allows the command to run; clicking **Deny 🔴** blocks execution.

2. **YOLO Mode:**
   * You can dynamically bypass approval prompts on a per-thread basis using the `/ag-yolo` or `!yolo` command in Slack.
   * When enabled, the hook immediately auto-approves all command executions.
   * When disabled, the hook forces interactive Slack card approvals with a 5-minute safety timeout fallback.

3. **Registering the Hook (`hooks.json`):**
   To register the Slack approval hook globally for the Antigravity agent CLI, create or edit `~/.gemini/config/hooks.json` (or your workspace's `.agents/hooks.json`) and configure a `PreToolUse` hook. 

   To avoid hardcoding absolute user paths, you can use environment variables (like `%USERPROFILE%` on Windows, or `$HOME` on Linux/macOS) in the command:

   * **Windows Configuration:**
     ```json
     {
       "slack-approval-gate": {
         "enabled": true,
         "PreToolUse": [
           {
             "matcher": "*",
             "hooks": [
               {
                 "type": "command",
                 "command": "python %USERPROFILE%\\antigravity-slack-gateway\\slack_approval_hook.py"
               }
             ]
           }
         ]
       }
     }
     ```

   * **macOS / Linux Configuration:**
     ```json
     {
       "slack-approval-gate": {
         "enabled": true,
         "PreToolUse": [
           {
             "matcher": "*",
             "hooks": [
               {
                 "type": "command",
                 "command": "python3 $HOME/antigravity-slack-gateway/slack_approval_hook.py"
               }
             ]
           }
         ]
       }
     }
     ```

---

## Dynamic CLI Wrapper Script & Dynamic Session Mappings

The gateway includes an interceptor wrapper script `antigravity_wrapper.py` that provides dynamic conversation mapping, abstracting the raw 36-character UUID hashes generated by the core `agy.exe` engine behind human-friendly, developer-defined aliases.

### "Zero Binary, Zero Batch" Architecture

To satisfy strict security constraints regarding executable hash matching (only using official developer-compiled binaries) and local script policy restrictions (banning `.bat` scripts), the system runs on a **pure Python execution model**:
* **Official Engine Only:** All commands execute using the official, developer-compiled `agy.exe` binary.
* **Python Invocation:** The Slack Gateway and shell profile configurations execute the Python wrapper script `antigravity_wrapper.py` directly using the system Python interpreter (`sys.executable`), eliminating the need for custom compiled `.exe` launchers or `.bat` batch wrappers.

### Key Features of the Wrapper

1. **Parameter Interception:** Intercepts the `--conversation` argument to translate friendly aliases (e.g. `!alias main-session`) or directory names into active workspace UUIDs.
2. **Implicit Workspace Context Resolution:** If a command is called inside a project folder without specifying a conversation ID, the wrapper automatically looks up the active conversation context mapping from global and local caches.
3. **Dynamic Alias Management:** Supports creating maps dynamically:
   ```bash
   agy alias my-session [optional_uuid]
   ```

### Shell Integration Setup

To run `agy` or `antigravity` commands directly from your local terminal using the wrapper:

* **For Windows PowerShell (add to your `$PROFILE`):**
  ```powershell
  function antigravity {
      python <path-to-repo>\antigravity_wrapper.py @args
  }
  function agy {
      python <path-to-repo>\antigravity_wrapper.py @args
  }
  ```

* **For Git Bash / Unix Shell (add to your `~/.bash_profile` or `~/.bashrc`):**
  ```bash
  alias agy="python /c/<path-to-repo>/antigravity_wrapper.py"
  alias antigravity="python /c/<path-to-repo>/antigravity_wrapper.py"
  ```
