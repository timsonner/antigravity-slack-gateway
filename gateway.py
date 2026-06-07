import os
import sys
import logging
import subprocess
import threading
import time
import uuid
import json
import re
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("gateway.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.environ.get("SLACK_APP_TOKEN")
WORKSPACE_ROOT = os.environ.get("ANTIGRAVITY_WORKSPACE_ROOT", os.path.expanduser("~"))

# Parse allowed users from comma-separated string
SLACK_ALLOWED_USERS = set(
    [u.strip() for u in os.environ.get("SLACK_ALLOWED_USERS", "").split(",") if u.strip()]
)

# Resolve Antigravity binary path
# Default: %LOCALAPPDATA%\agy\bin\agy.exe
DEFAULT_BIN_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Local")),
    "agy", "bin", "agy.exe"
)
ANTIGRAVITY_BIN = os.environ.get("ANTIGRAVITY_BIN", DEFAULT_BIN_PATH)

# Config options for safety / skipping permission dialogs
SKIP_PERMISSIONS = os.environ.get("ANTIGRAVITY_SKIP_PERMISSIONS", "true").lower() == "true"
USE_SANDBOX = os.environ.get("ANTIGRAVITY_SANDBOX", "false").lower() == "true"

SESSION_STORE_FILE = "session_store.json"
active_processes = {}  # session_key -> subprocess.Popen
stopped_processes = set()  # set of process IDs that were explicitly killed/terminated by user /stop

if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
    logger.error("Missing SLACK_BOT_TOKEN or SLACK_APP_TOKEN in environment variables.")
    sys.exit(1)

if not os.path.exists(ANTIGRAVITY_BIN):
    logger.warning(f"Antigravity binary not found at {ANTIGRAVITY_BIN}. Please configure ANTIGRAVITY_BIN in .env if it is installed elsewhere.")

# Initialize Slack Bolt App
app = App(token=SLACK_BOT_TOKEN)

# --- Persistence Helpers ---
def load_sessions():
    if os.path.exists(SESSION_STORE_FILE):
        try:
            with open(SESSION_STORE_FILE, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading session store: {e}")
    return {}

def save_sessions(data):
    try:
        with open(SESSION_STORE_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        logger.error(f"Error saving session store: {e}")

def get_session(channel_id, thread_ts=None):
    # DMs use the channel ID as the session key so conversations are continuous.
    # Channels use channel ID + thread TS if threaded, otherwise just channel ID.
    is_dm = channel_id.startswith("D")
    if is_dm:
        key = channel_id
    elif thread_ts:
        key = f"{channel_id}_{thread_ts}"
    else:
        key = channel_id
        
    sessions = load_sessions()
    if key not in sessions:
        # Generate a unique workspace directory under the workspace root
        unique_id = str(uuid.uuid4())[:8]
        ts_str = str(int(time.time()))
        folder_name = f"proj_{ts_str}_{unique_id}"
        workspace_path = os.path.join(WORKSPACE_ROOT, "slack_workspaces", folder_name)
        os.makedirs(workspace_path, exist_ok=True)
        
        # Unique conversation ID for Antigravity engine
        conv_id = f"slack_{key.replace('.', '_')}"
        
        sessions[key] = {
            "workspace": workspace_path,
            "conversation_id": conv_id,
            "created_at": time.time(),
            "last_active": time.time(),
            "active_task": None,
            "model": "gemini-3.5-flash",
            "skip_permissions": SKIP_PERMISSIONS,
            "use_sandbox": USE_SANDBOX
        }
        save_sessions(sessions)
        logger.info(f"Created new session {key} at {workspace_path} with conversation_id {conv_id}")
        
    return key, sessions[key]

def reset_session_conversation(key):
    sessions = load_sessions()
    if key in sessions:
        # Generate a new unique conversation ID to reset context
        unique_id = str(uuid.uuid4())[:8]
        new_conv_id = f"slack_{key.replace('.', '_')}_{unique_id}"
        sessions[key]["conversation_id"] = new_conv_id
        sessions[key]["last_active"] = time.time()
        save_sessions(sessions)
        logger.info(f"Reset conversation history for session {key}. New conversation_id: {new_conv_id}")
        return new_conv_id
    return None

def update_session_workspace(key, path):
    sessions = load_sessions()
    if key in sessions:
        normalized_path = os.path.abspath(path)
        # Ensure target path directory exists
        os.makedirs(normalized_path, exist_ok=True)
        sessions[key]["workspace"] = normalized_path
        sessions[key]["last_active"] = time.time()
        save_sessions(sessions)
        logger.info(f"Updated workspace for session {key} to {normalized_path}")
        return normalized_path
    raise ValueError("Session not found")

# --- Authorization Gate ---
def check_auth(user_id, say, thread_ts=None):
    if not SLACK_ALLOWED_USERS:
        say(
            text="⚠️ *Security Warning:* No users are authorized to use this bot. Please set `SLACK_ALLOWED_USERS` in the gateway's `.env` configuration file.",
            thread_ts=thread_ts
        )
        return False
        
    if user_id not in SLACK_ALLOWED_USERS:
        logger.warning(f"Unauthorized access attempt by user {user_id}")
        say(
            text=f"❌ *Access Denied:* User <@{user_id}> is not authorized to interact with this agent. Please ask an administrator to add your Member ID to the allowlist.",
            thread_ts=thread_ts
        )
        return False
    return True

# --- Help Text ---
def get_help_text():
    return (
        "⚡ *Antigravity Slack Gateway* ⚡\n\n"
        "I am your autonomous agentic coding assistant, powered by Google Gemini.\n\n"
        "*Commands (Slack Slash commands or thread prefix `!`):*\n"
        "• `/ag-help` or `!help` - Show this usage message\n"
        "• `/ag-new` / `/ag-reset` or `!new` / `!reset` - Reset conversation history for this session\n"
        "• `/ag-status` or `!status` - Show workspace directory, conversation ID, and execution status\n"
        "• `/ag-workspace [path]` or `!workspace [path]` - Map this session to a specific directory (e.g. `/workspace /path/to/project`)\n"
        "• `/ag-stop` or `!stop` - Terminate any active task currently executing in this session\n"
        "• `/ag-model [name]` or `!model [name]` - Switch model (e.g., `gemini-3.5-pro`, `gemini-3.5-flash`)\n"
        "• `/ag-yolo` or `!yolo` - Toggle YOLO mode (skip command safety verification prompts)\n"
        "• `/ag-sandbox` or `!sandbox` - Toggle restricted terminal sandbox mode\n"
        "• `/ag-version` or `!version` - Show the local Antigravity binary version\n\n"
        "*Interaction Rules:*\n"
        "- In channels, `@mention` me or use the `/antigravity <prompt>` command to start a thread. Within that thread, you can reply *without* pings.\n"
        "- In Direct Messages (DMs), simply message me without any mentions.\n"
        "- Since Slack disables slash commands in threads, use the `!` prefix inside threads (e.g., `!status`)."
    )

# --- Agent Subprocess Execution ---
def run_agent_in_background(session_key, prompt, say, thread_ts):
    """
    Runs the agent executable asynchronously to avoid blocking Bolt's main event handler thread.
    """
    sessions = load_sessions()
    if session_key not in sessions:
        say(text="Error: Session not found.", thread_ts=thread_ts)
        return

    session = sessions[session_key]
    workspace = session["workspace"]
    conv_id = session["conversation_id"]
    model = session.get("model", "gemini-3.5-flash")
    skip_perm = session.get("skip_permissions", SKIP_PERMISSIONS)
    sandbox_mode = session.get("use_sandbox", USE_SANDBOX)

    # Build process arguments
    args = [
        ANTIGRAVITY_BIN,
        "--conversation", conv_id,
        "--add-dir", workspace,
        "--model", model,
        "--print", prompt
    ]

    if skip_perm:
        args.append("--dangerously-skip-permissions")
    if sandbox_mode:
        args.append("--sandbox")

    # Update active task state
    sessions[session_key]["active_task"] = prompt
    sessions[session_key]["last_active"] = time.time()
    save_sessions(sessions)

    logger.info(f"Starting agent process: {' '.join(args)} in Cwd: {workspace}")

    try:
        proc = subprocess.Popen(
            args,
            cwd=workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8"
        )
        active_processes[session_key] = proc
        
        try:
            stdout, stderr = proc.communicate(timeout=300)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
            raise Exception("Agent execution timed out after 5 minutes.")

        # Resolve and persist the actual UUID-based conversation ID created by agy.exe
        try:
            cache_path = os.path.join(os.path.expanduser("~"), ".gemini", "antigravity-cli", "cache", "last_conversations.json")
            if os.path.exists(cache_path):
                with open(cache_path, "r", encoding="utf-8") as cache_f:
                    last_convs = json.load(cache_f)
                
                # Normalize workspace path for accurate lookup
                normalized_ws = os.path.abspath(workspace).lower()
                for ws_path, conv_uuid in last_convs.items():
                    if os.path.abspath(ws_path).lower() == normalized_ws:
                        # Update conversation_id in session store so we reuse it on the next turn!
                        sessions = load_sessions()
                        if session_key in sessions:
                            sessions[session_key]["conversation_id"] = conv_uuid
                            save_sessions(sessions)
                            logger.info(f"Successfully mapped and saved persistent conversation ID {conv_uuid} for session {session_key}")
                        break
        except Exception as le:
            logger.error(f"Failed to resolve persistent conversation ID: {le}")

        # Clear active process state
        active_processes.pop(session_key, None)
        
        # Check if the process was explicitly stopped by the user (/stop)
        was_stopped = proc.pid in stopped_processes
        if was_stopped:
            stopped_processes.discard(proc.pid)
        
        sessions = load_sessions()
        if session_key in sessions:
            sessions[session_key]["active_task"] = None
            save_sessions(sessions)

        # Build response
        if proc.returncode == 0:
            formatted_output = stdout.strip()
            if not formatted_output:
                # Attempt to extract the final response directly from the transcript JSONL
                try:
                    transcript_path = os.path.join(
                        os.path.expanduser("~"), 
                        ".gemini", 
                        "antigravity-cli", 
                        "brain", 
                        conv_id, 
                        ".system_generated", 
                        "logs", 
                        "transcript.jsonl"
                    )
                    if os.path.exists(transcript_path):
                        with open(transcript_path, "r", encoding="utf-8") as tf:
                            lines = tf.readlines()
                        # Scan backwards for the latest model response content
                        for line in reversed(lines):
                            try:
                                data = json.loads(line)
                                if data.get("source") == "MODEL" and data.get("content"):
                                    extracted_text = data.get("content").strip()
                                    if extracted_text:
                                        formatted_output = extracted_text
                                        logger.info(f"Successfully extracted final response from transcript.jsonl: {formatted_output[:50]}...")
                                        break
                            except Exception:
                                pass
                except Exception as te:
                    logger.error(f"Failed to parse transcript.jsonl: {te}")

            if not formatted_output:
                # Check the antigravity CLI log for hidden errors (e.g. RESOURCE_EXHAUSTED)
                hidden_error = ""
                cli_log_path = os.path.join(os.path.expanduser("~"), ".gemini", "antigravity-cli", "cli.log")
                if os.path.exists(cli_log_path):
                    try:
                        with open(cli_log_path, "r", encoding="utf-8") as log_f:
                            log_lines = log_f.readlines()
                        # Scan the last 25 lines of the log for error strings
                        for line in reversed(log_lines[-25:]):
                            if "RESOURCE_EXHAUSTED" in line or "quota reached" in line or "Quota reached" in line:
                                hidden_error = "RESOURCE_EXHAUSTED: Individual Gemini API quota reached. Please check Google AI Studio or wait for the quota reset."
                                if "Resets in" in line:
                                    resets_idx = line.find("Resets in")
                                    hidden_error += f" {line[resets_idx:]}"
                                break
                            elif "not logged into Antigravity" in line or "Failed to get OAuth token" in line:
                                hidden_error = "AUTHENTICATION_ERROR: You are not logged into Antigravity. Please run 'agy login' in the host terminal."
                                break
                            elif "E060" in line and "error" in line.lower():
                                # Capture any other severe error log
                                hidden_error = line.strip()
                                break
                    except Exception as le:
                        logger.error(f"Error checking CLI log: {le}")
                
                if hidden_error:
                    say(text=f"❌ *Antigravity Engine Error:* \n```\n{hidden_error}\n```", thread_ts=thread_ts)
                else:
                    say(text="Task completed successfully, but returned no text output.", thread_ts=thread_ts)
            else:
                say(text=formatted_output, thread_ts=thread_ts)
        else:
            # Check if terminated by the user (/stop)
            if was_stopped:
                logger.info(f"Process for session {session_key} was terminated by user /stop.")
            else:
                err_msg = stderr.strip() if stderr.strip() else "Unknown error executing agent."
                say(
                    text=f"❌ *Agent Error (Exit Code {proc.returncode}):*\n```\n{err_msg}\n```",
                    thread_ts=thread_ts
                )

    except Exception as e:
        logger.error(f"Failed to execute agent process: {e}")
        active_processes.pop(session_key, None)
        say(text=f"❌ *Failed to spawn agent process:* `{str(e)}`", thread_ts=thread_ts)

# --- Event/Command Routing Helpers ---
def handle_command_string(command_name, args_str, user_id, channel_id, thread_ts, say):
    """
    Unified parser for commands, supporting both slash commands and '!' prefix text commands.
    """
    session_key, session = get_session(channel_id, thread_ts)
    
    if not check_auth(user_id, say, thread_ts):
        return

    command_name = command_name.lower().strip()

    if command_name == "help":
        say(text=get_help_text(), thread_ts=thread_ts)
        
    elif command_name in ["new", "reset"]:
        new_conv = reset_session_conversation(session_key)
        say(
            text=f"🔄 *Conversation reset.* A new conversation session has been initialized. Workspace: `{session['workspace']}`.",
            thread_ts=thread_ts
        )
        
    elif command_name == "status":
        is_running = session_key in active_processes
        status_text = "🟢 Running active task" if is_running else "⚪ Idle"
        current_model = session.get("model", "gemini-3.5-flash")
        skip_perm = session.get("skip_permissions", SKIP_PERMISSIONS)
        sandbox_mode = session.get("use_sandbox", USE_SANDBOX)
        say(
            text=(
                f"📊 *Antigravity Session Status*\n"
                f"📂 *Workspace:* `{session['workspace']}`\n"
                f"🆔 *Conversation ID:* `{session['conversation_id']}`\n"
                f"🤖 *Active Model:* `{current_model}`\n"
                f"⚡ *YOLO Mode:* `{skip_perm}`\n"
                f"🛡️ *Sandbox Mode:* `{sandbox_mode}`\n"
                f"⚙️ *Status:* {status_text}"
            ),
            thread_ts=thread_ts
        )
        
    elif command_name == "workspace":
        target_path = args_str.strip()
        if not target_path:
            say(text=f"📂 Current workspace path: `{session['workspace']}`", thread_ts=thread_ts)
        else:
            try:
                resolved = update_session_workspace(session_key, target_path)
                say(text=f"📂 Workspace directory updated to: `{resolved}`", thread_ts=thread_ts)
            except Exception as e:
                say(text=f"❌ Failed to set workspace: `{str(e)}`", thread_ts=thread_ts)
                
    elif command_name == "stop":
        proc = active_processes.get(session_key)
        if proc:
            try:
                stopped_processes.add(proc.pid)
                proc.terminate()
                time.sleep(0.5)
                if proc.poll() is None:
                    proc.kill()
                say(text="🛑 *Execution Aborted:* The running task has been stopped.", thread_ts=thread_ts)
            except Exception as e:
                say(text=f"⚠️ Failed to terminate task: `{str(e)}`", thread_ts=thread_ts)
        else:
            say(text="No active task is running in this session.", thread_ts=thread_ts)

    elif command_name == "model":
        target_model = args_str.strip()
        if not target_model:
            current_model = session.get("model", "gemini-3.5-flash")
            say(
                text=(
                    f"🤖 *Current model:* `{current_model}`\n"
                    f"To switch models, run `/model [name]` with one of the following:\n"
                    f"• `gemini-3.5-flash` (default)\n"
                    f"• `gemini-3.5-pro`\n"
                    f"• `gemini-3.5-flash-thinking`"
                ),
                thread_ts=thread_ts
            )
        else:
            valid_models = ["gemini-3.5-flash", "gemini-3.5-pro", "gemini-3.5-flash-thinking"]
            if target_model not in valid_models:
                say(text=f"❌ Invalid model. Please select from: {', '.join(valid_models)}", thread_ts=thread_ts)
            else:
                sessions = load_sessions()
                if session_key in sessions:
                    sessions[session_key]["model"] = target_model
                    save_sessions(sessions)
                    say(text=f"🤖 Model switched to `{target_model}` for this session.", thread_ts=thread_ts)

    elif command_name == "yolo":
        sessions = load_sessions()
        if session_key in sessions:
            current_yolo = sessions[session_key].get("skip_permissions", SKIP_PERMISSIONS)
            new_yolo = not current_yolo
            sessions[session_key]["skip_permissions"] = new_yolo
            save_sessions(sessions)
            status_yolo = "Enabled (agent will skip command approvals)" if new_yolo else "Disabled (agent will prompt for approvals)"
            say(text=f"⚡ *YOLO Mode:* {status_yolo}", thread_ts=thread_ts)

    elif command_name == "sandbox":
        sessions = load_sessions()
        if session_key in sessions:
            current_sandbox = sessions[session_key].get("use_sandbox", USE_SANDBOX)
            new_sandbox = not current_sandbox
            sessions[session_key]["use_sandbox"] = new_sandbox
            save_sessions(sessions)
            status_sandbox = "Enabled (restricted terminal sandbox)" if new_sandbox else "Disabled (unrestricted local access)"
            say(text=f"🛡️ *Sandbox Mode:* {status_sandbox}", thread_ts=thread_ts)

    elif command_name == "version":
        try:
            res = subprocess.run(
                [ANTIGRAVITY_BIN, "--version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                timeout=10
            )
            version_str = res.stdout.strip() if res.returncode == 0 else "Unknown"
            say(text=f"ℹ️ *Antigravity Agent version:* `{version_str}`", thread_ts=thread_ts)
        except Exception as e:
            say(text=f"❌ Failed to fetch version: `{str(e)}`", thread_ts=thread_ts)

    else:
        say(text=f"Unknown command: `{command_name}`. Type `/help` for list of commands.", thread_ts=thread_ts)

# --- Slack Command Handlers (Slash commands) ---
@app.command("/ag-help")
def slash_help(ack, body, say):
    ack()
    handle_command_string("help", "", body.get("user_id"), body.get("channel_id"), body.get("thread_ts"), say)

@app.command("/ag-new")
def slash_new(ack, body, say):
    ack()
    handle_command_string("new", "", body.get("user_id"), body.get("channel_id"), body.get("thread_ts"), say)

@app.command("/ag-reset")
def slash_reset(ack, body, say):
    ack()
    handle_command_string("reset", "", body.get("user_id"), body.get("channel_id"), body.get("thread_ts"), say)

@app.command("/ag-status")
def slash_status(ack, body, say):
    ack()
    handle_command_string("status", "", body.get("user_id"), body.get("channel_id"), body.get("thread_ts"), say)

@app.command("/ag-workspace")
def slash_workspace(ack, body, say):
    ack()
    handle_command_string("workspace", body.get("text", ""), body.get("user_id"), body.get("channel_id"), body.get("thread_ts"), say)

@app.command("/ag-stop")
def slash_stop(ack, body, say):
    ack()
    handle_command_string("stop", "", body.get("user_id"), body.get("channel_id"), body.get("thread_ts"), say)

@app.command("/ag-model")
def slash_model(ack, body, say):
    ack()
    handle_command_string("model", body.get("text", ""), body.get("user_id"), body.get("channel_id"), body.get("thread_ts"), say)

@app.command("/ag-yolo")
def slash_yolo(ack, body, say):
    ack()
    handle_command_string("yolo", "", body.get("user_id"), body.get("channel_id"), body.get("thread_ts"), say)

@app.command("/ag-sandbox")
def slash_sandbox(ack, body, say):
    ack()
    handle_command_string("sandbox", "", body.get("user_id"), body.get("channel_id"), body.get("thread_ts"), say)

@app.command("/ag-version")
def slash_version(ack, body, say):
    ack()
    handle_command_string("version", "", body.get("user_id"), body.get("channel_id"), body.get("thread_ts"), say)

@app.command("/antigravity")
def slash_antigravity(ack, body, say):
    ack()
    user = body.get("user_id")
    text = body.get("text", "").strip()
    channel = body.get("channel_id")
    thread_ts = body.get("thread_ts")
    
    if not text:
        say(text="Please provide a prompt to execute. Example: `/antigravity code a hello-world server`.", thread_ts=thread_ts)
        return
        
    session_key, session = get_session(channel, thread_ts)
    if not check_auth(user, say, thread_ts):
        return
        
    if session_key in active_processes:
        say(text="⚠️ An active task is already executing in this session.", thread_ts=thread_ts)
        return
        
    # say(text=f"🤖 *Task Received.* I am spawning an Antigravity agent in the workspace: `{session['workspace']}`. I'll post the results here shortly! ⚙️", thread_ts=thread_ts)
    t = threading.Thread(
        target=run_agent_in_background,
        args=(session_key, text, say, thread_ts),
        daemon=True
    )
    t.start()

# --- Slack Message Events (Mentions, DMs, Threads) ---
@app.event("app_mention")
def handle_app_mentions(event, say):
    user = event.get("user")
    text = event.get("text", "")
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    
    cleaned_text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    
    # Check if text is an inline command (e.g., @Antigravity !status)
    if cleaned_text.startswith("!"):
        parts = cleaned_text[1:].split(" ", 1)
        cmd_name = parts[0]
        args_str = parts[1] if len(parts) > 1 else ""
        handle_command_string(cmd_name, args_str, user, channel, thread_ts, say)
        return
        
    session_key, session = get_session(channel, thread_ts)
    
    if not check_auth(user, say, thread_ts):
        return

    if session_key in active_processes:
        say(
            text="⚠️ An active task is already executing in this session. Please wait for it to complete or run `/stop` to abort it.",
            thread_ts=thread_ts
        )
        return

    # say(
    #     text=f"🤖 *Task Received.* I am spawning an Antigravity agent in the workspace: `{session['workspace']}`. I'll post the results here shortly! ⚙️",
    #     thread_ts=thread_ts
    # )

    t = threading.Thread(
        target=run_agent_in_background,
        args=(session_key, cleaned_text, say, thread_ts),
        daemon=True
    )
    t.start()

@app.event("message")
def handle_message_events(event, say):
    channel = event.get("channel", "")
    text = event.get("text", "").strip()
    thread_ts = event.get("thread_ts") or event.get("ts")
    user = event.get("user")

    if event.get("bot_id") or event.get("subtype") == "bot_message" or not text:
        return

    is_dm = channel.startswith("D")
    
    session_key = f"{channel}_{event.get('thread_ts')}" if event.get("thread_ts") else None
    sessions = load_sessions()
    is_active_thread_reply = session_key and session_key in sessions

    if not is_dm and not is_active_thread_reply:
        return

    if text.startswith("!"):
        parts = text[1:].split(" ", 1)
        cmd_name = parts[0]
        args_str = parts[1] if len(parts) > 1 else ""
        handle_command_string(cmd_name, args_str, user, channel, thread_ts, say)
        return

    resolved_key, session = get_session(channel, event.get("thread_ts"))
    
    if not check_auth(user, say, thread_ts):
        return

    if resolved_key in active_processes:
        say(
            text="⚠️ An active task is already executing in this session. Please wait for it to complete or run `!stop` to abort it.",
            thread_ts=thread_ts
        )
        return

    # say(
    #     text=f"🤖 *Thinking...* I've started the agent in workspace: `{session['workspace']}`. Response will follow! ⚙️",
    #     thread_ts=thread_ts
    # )

    t = threading.Thread(
        target=run_agent_in_background,
        args=(resolved_key, text, say, thread_ts),
        daemon=True
    )
    t.start()

if __name__ == "__main__":
    logger.info("Starting Antigravity Slack Gateway in Socket Mode...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
