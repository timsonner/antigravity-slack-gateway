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
SLACK_ALLOWED_USERS=U01ABC2DEF3              # Comma-separated list of Slack user IDs
SLACK_HOME_CHANNEL=                          # Default channel for system messages (optional)
SLACK_HOME_CHANNEL_NAME=general
```

### 5. Running the Gateway

Start the gateway listener service:

```bash
python gateway.py
```

Once running, you can mention `@Antigravity` in any authorized Slack channel or DM the bot directly to start orchestrating!
