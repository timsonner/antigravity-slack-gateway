import os
import sys
import logging
import subprocess
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
WORKSPACE_ROOT = os.environ.get("ANTIGRAVITY_WORKSPACE_ROOT", r"C:\Users\admin")

if not SLACK_BOT_TOKEN or not SLACK_APP_TOKEN:
    logger.error("Missing SLACK_BOT_TOKEN or SLACK_APP_TOKEN in environment variables.")
    sys.exit(1)

# Initialize Slack Bolt App
app = App(token=SLACK_BOT_TOKEN)

# In-memory session routing table (maps Slack thread timestamp to a workspace / session config)
# In production, this can be persisted to a SQLite database
sessions = {}

def get_workspace_for_thread(thread_ts, channel_id):
    """
    Resolves or initializes a workspace directory for a given Slack thread.
    """
    session_key = f"{channel_id}_{thread_ts}"
    if session_key not in sessions:
        # Create a unique project workspace under the workspace root
        folder_name = f"slack_project_{thread_ts.replace('.', '_')}"
        workspace_path = os.path.join(WORKSPACE_ROOT, "slack_workspaces", folder_name)
        os.makedirs(workspace_path, exist_ok=True)
        sessions[session_key] = {
            "workspace": workspace_path,
            "session_id": session_key,
        }
        logger.info(f"Initialized new workspace for session {session_key} at {workspace_path}")
    return sessions[session_key]["workspace"]

@app.event("app_mention")
def handle_app_mentions(event, say, client):
    """
    Handles cases where the user mentions @Antigravity in a channel.
    """
    user = event.get("user")
    text = event.get("text", "")
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")
    
    logger.info(f"Received mention from user {user} in channel {channel}: {text}")
    
    # Strip the bot mention from the text
    cleaned_text = text.replace(f"<@{event.get('bot_id')}>", "").strip()
    
    # Resolve the workspace directory mapping
    workspace = get_workspace_for_thread(thread_ts, channel)
    
    # Send an immediate acknowledgement
    say(
        text=f"Hi <@{user}>! I received your request. Running in workspace: `{workspace}`. Working on it... ⚙️",
        thread_ts=thread_ts
    )
    
    # Execute agentic response generation (mock/placeholder for Phase 2 integration)
    # This will hook into the local CLI / API runner
    response_text = execute_agent_task(cleaned_text, workspace)
    
    # Respond in the thread with the output
    say(
        text=response_text,
        thread_ts=thread_ts
    )

@app.event("message")
def handle_message_events(event, say):
    """
    Handles direct messages to the bot.
    """
    # Only respond to DMs (direct messages have channel IDs starting with D)
    channel = event.get("channel", "")
    if not channel.startswith("D"):
        return
        
    # Ignore messages sent by bots (including ourselves)
    if event.get("bot_id") or event.get("subtype") == "bot_message":
        return

    user = event.get("user")
    text = event.get("text", "")
    thread_ts = event.get("thread_ts") or event.get("ts")
    
    logger.info(f"Received DM from user {user}: {text}")
    
    workspace = get_workspace_for_thread(thread_ts, channel)
    
    say(
        text=f"Direct Message received. Active workspace: `{workspace}`. Thinking... 🤔",
        thread_ts=thread_ts
    )
    
    response_text = execute_agent_task(text, workspace)
    say(
        text=response_text,
        thread_ts=thread_ts
    )

def execute_agent_task(prompt, workspace):
    """
    Executes a task using the Antigravity agent engine.
    For Phase 1/2, this is a placeholder returning a structured response,
    ready to be integrated with the CLI/subagent runner interface.
    """
    logger.info(f"Executing agent task: '{prompt}' in {workspace}")
    
    # Placeholder response demonstrating interactive session setup.
    # In Phase 2, this will run a command like:
    # python C:\Users\admin\antigravity-hermes-collab\harness.py --task "prompt" --workspace "workspace"
    
    success_response = (
        f"🤖 *Antigravity Agent Workspace Report*\n\n"
        f"📂 *Workspace:* `{workspace}`\n"
        f"📝 *Prompt received:* \"{prompt}\"\n\n"
        f"✅ I initialized the workspace. In the next phase, we'll hook this up to run tasks "
        f"directly inside your project via local subprocess execution."
    )
    return success_response

if __name__ == "__main__":
    logger.info("Starting Antigravity Slack Gateway in Socket Mode...")
    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
