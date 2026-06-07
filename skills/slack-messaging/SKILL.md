---
name: slack-messaging
description: Send a message or notification to a Slack channel or thread using the gateway's configured tokens.
version: 1.0.0
author: Timsonner
license: MIT
metadata:
  hermes:
    tags: [slack, gateway, messaging, notifications, multi-agent]
    related_skills: [multi-agent-coordination, cli-wrapper-design-and-debugging]
---

# Slack Messaging Skill

This skill provides guidelines and tools to send messages, notifications, or replies to Slack channels and threads from the local command-line or agent context.

## When to use this skill
- Use when the user requests to send a message, status update, or notification to Slack.
- Use when you need to post a status report or automated feedback to a specific Slack channel.
- Use when responding to a specific Slack thread.

## How to use this skill
1. Ensure the gateway's `.env` configuration file exists and has `SLACK_BOT_TOKEN`.
2. Execute the CLI script `send_slack.py` located at the root of the repository:
   ```bash
   python send_slack.py "Your message text here"
   ```

### Commands

#### Send message to default home channel (typically #general)
```bash
python send_slack.py "Message content"
```

#### Send message to a specific channel (by name or ID)
```bash
python send_slack.py --channel "random" "Hello random channel!"
python send_slack.py --channel "C0B8U40L6PL" "Hello custom channel ID!"
```

#### Reply to a thread in a channel
```bash
python send_slack.py --channel "general" --thread "1780829722.426309" "Thread reply message"
```

#### Pipe stdin contents
```bash
cat build_output.log | python send_slack.py
```

### Mentioning Users and Bots

When sending messages via the API, plain text mentions like `@Hermes` or `@Antigravity` will not trigger notifications or gateway events. You must use the Slack Member ID in the `<@MEMBER_ID>` format:
- To mention **Hermes**, use: `<@U0B8CNSPWB1>`
- To mention **Antigravity**, use: `<@U0B8SBAFB8W>`

Example of thread reply:
```bash
python send_slack.py --channel "C0B8U3ZGE7L" --thread "1780831489.381079" "<@U0B8SBAFB8W> Hello Antigravity!"
```

## Multi-Agent Collaboration & Authorization

When initiating agent-to-agent communication (e.g., Hermes invoking Antigravity in a Slack thread), keep the following in mind:

### 1. The Authorization Gate (`SLACK_ALLOWED_USERS`)
The Slack gateway filters incoming messages by user ID to enforce authorization. By default, it blocks messages from unauthorized bots and users.
- If **Hermes** needs to send a message to trigger **Antigravity**, Hermes' Member ID (`U0B8CNSPWB1`) must be added to the comma-separated `SLACK_ALLOWED_USERS` list inside the gateway's `.env` file.
- **Example configuration:**
  ```env
  SLACK_ALLOWED_USERS=U0B8CKH5SVD,U0B8CNSPWB1
  ```
- **Gateway Restart Required:** If `.env` is modified, the gateway listener process (`gateway.py`) must be restarted to load the updated list.

### 2. Identifying Active Processes
To find or manage running gateway processes on the Windows host, use PowerShell commands from the terminal:
- **List running gateways:**
  ```bash
  powershell -Command "Get-CimInstance Win32_Process -Filter \"CommandLine LIKE '%gateway.py%'\" | Select-Object CommandLine, ProcessId"
  ```
- **Force-stop a gateway process:**
  ```bash
  powershell -Command "Stop-Process -Id <ProcessId> -Force"
  ```

### 3. Interactive Tool Approvals (YOLO Mode)
When Antigravity attempts to run shell commands in any thread (and YOLO mode is disabled), it triggers a synchronous `BeforeTool` hook that prompts you with Approve/Deny buttons directly in Slack.
- **Enable YOLO Mode (Disable prompts):** Run `!yolo` inside the Slack thread.
- **Disable YOLO Mode (Enable prompts):** Run `!yolo` again.
- **Handling Requests:** Click **Approve 🟢** to let the tool execute, or **Deny 🔴** to reject it.