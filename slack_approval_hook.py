import sys
import json
import os
import time
import uuid

# Stderr logging helper
def log(msg):
    print(msg, file=sys.stderr)

def main():
    try:
        # 1. Read input from stdin
        input_data = sys.stdin.read()
        if not input_data:
            # If no input, just allow
            print(json.dumps({"decision": "allow"}))
            return
            
        data = json.loads(input_data)
        log(f"Hook received: {json.dumps(data, indent=2)}")
        
        session_id = data.get("session_id") or data.get("conversationId")
        tool_call = data.get("toolCall", {})
        tool_name = data.get("tool_name") or tool_call.get("name")
        tool_input = data.get("tool_input") or tool_call.get("args") or {}
        
        # Load directories
        gateway_dir = r"C:\Users\admin\antigravity-slack-gateway"
        
        # Check global settings.json as the source of truth for permanent allowlist
        settings_file = os.path.join(os.path.expanduser("~"), ".gemini", "antigravity-cli", "settings.json")
        if os.path.exists(settings_file):
            try:
                with open(settings_file, "r") as f:
                    settings = json.load(f)
                allow_rules = settings.get("permissions", {}).get("allow", [])
                
                if "*" in allow_rules:
                    log("Auto-approving due to global wildcard allow *")
                    print(json.dumps({"decision": "allow"}))
                    return
                    
                if tool_name == "run_command":
                    cmd_line = tool_input.get("CommandLine", "")
                    if f"command({cmd_line})" in allow_rules or "command(*)" in allow_rules:
                        log(f"Auto-approving globally allowed command: {cmd_line}")
                        print(json.dumps({"decision": "allow"}))
                        return
                else:
                    # Check for tool_name(*) or tool_name(target)
                    target = tool_input.get("AbsolutePath") or tool_input.get("TargetFile") or "*"
                    if f"{tool_name}({target})" in allow_rules or f"{tool_name}(*)" in allow_rules:
                        log(f"Auto-approving globally allowed tool: {tool_name}({target})")
                        print(json.dumps({"decision": "allow"}))
                        return
            except Exception as e:
                log(f"Error checking global settings.json: {e}")
        
        # Identify read-only tools to auto-approve (keeps noise low)
        read_only_tools = {"list_dir", "read_file", "search_grep", "get_outline"}
        if tool_name in read_only_tools:
            log(f"Auto-approving read-only tool: {tool_name}")
            print(json.dumps({"decision": "allow"}))
            return
            
        # Format tool details for Slack Block Kit
        if tool_name == "run_command":
            cmd_line = tool_input.get("CommandLine", "")
            tool_details_text = f"📂 *Workspace Cwd:* `{tool_input.get('Cwd', '')}`\n💻 *Command:* `{cmd_line}`"
            fallback_text = f"Antigravity requested permission to run: `{cmd_line}`"
        else:
            args_str = json.dumps(tool_input, indent=2)
            if len(args_str) > 1000:
                args_str = args_str[:1000] + "\n... (truncated)"
            tool_details_text = f"🛠️ *Tool Name:* `{tool_name}`\n📦 *Arguments:*\n```json\n{args_str}\n```"
            fallback_text = f"Antigravity requested permission to use tool: `{tool_name}`"
            
        # Load session store to find the slack thread and session-specific allowlists
        session_store_path = os.path.join(gateway_dir, "session_store.json")
        
        channel_id = None
        thread_ts = None
        skip_permissions = False
        
        if os.path.exists(session_store_path):
            try:
                with open(session_store_path, "r") as f:
                    sessions = json.load(f)
                for key, session_data in sessions.items():
                    if session_data.get("conversation_id") == session_id:
                        # Check session-specific allowed lists first
                        allowed_tools = session_data.get("allowed_tools", [])
                        allowed_commands = session_data.get("allowed_commands", [])
                        
                        if tool_name in allowed_tools:
                            log(f"Auto-approving session-allowed tool: {tool_name}")
                            print(json.dumps({"decision": "allow"}))
                            return
                        if tool_name == "run_command":
                            cmd_line = tool_input.get("CommandLine", "")
                            if cmd_line in allowed_commands:
                                log(f"Auto-approving session-allowed command: {cmd_line}")
                                print(json.dumps({"decision": "allow"}))
                                return
                                
                        skip_permissions = session_data.get("skip_permissions", False)
                        # Extract channel_id and thread_ts from key (e.g. C0B8U3ZGE7L_1780829102.148649)
                        parts = key.split("_")
                        channel_id = parts[0]
                        thread_ts = parts[1] if len(parts) > 1 else None
                        break
            except Exception as e:
                log(f"Error reading session store: {e}")
                
        # If YOLO mode is enabled for this session, auto-approve
        if skip_permissions:
            log("YOLO mode enabled. Auto-approving tool execution.")
            print(json.dumps({"decision": "allow"}))
            return
            
        # If we couldn't find the Slack channel/thread, we can't prompt. Auto-approve or deny?
        # Let's auto-approve as fallback so we don't block CLI runs from terminal.
        if not channel_id:
            log("Could not find Slack channel for session. Auto-approving.")
            print(json.dumps({"decision": "allow"}))
            return
            
        # Otherwise, initiate Slack approval flow!
        approval_id = str(uuid.uuid4())
        
        # 1. Write the pending approval directly inside session_store.json
        if os.path.exists(session_store_path):
            try:
                with open(session_store_path, "r") as f:
                    sessions = json.load(f)
                
                # Find the session key by matching conversation_id
                target_key = None
                for key, session_data in sessions.items():
                    if session_data.get("conversation_id") == session_id:
                        target_key = key
                        break
                        
                if target_key:
                    if "pending_approvals" not in sessions[target_key]:
                        sessions[target_key]["pending_approvals"] = {}
                    sessions[target_key]["pending_approvals"][approval_id] = {
                        "status": "pending",
                        "tool_name": tool_name,
                        "tool_input": tool_input,
                        "decision": None,
                        "created_at": time.time()
                    }
                    with open(session_store_path, "w") as f:
                        json.dump(sessions, f, indent=2)
            except Exception as e:
                log(f"Error writing pending approval to session store: {e}")
            
        # 2. Post interactive message to Slack!
        from dotenv import load_dotenv
        from slack_sdk import WebClient
        
        load_dotenv(os.path.join(gateway_dir, ".env"))
        bot_token = os.environ.get("SLACK_BOT_TOKEN")
        if not bot_token:
            log("Missing SLACK_BOT_TOKEN in env. Auto-approving.")
            print(json.dumps({"decision": "allow"}))
            return
            
        client = WebClient(token=bot_token)
        
        # Build blocks for approval message with three approval modes
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"⚠️ *Antigravity wants to execute a tool:*\n\n{tool_details_text}"
                }
            },
            {
                "type": "actions",
                "block_id": f"approval_block_{approval_id}",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Allow Once 🟢",
                            "emoji": True
                        },
                        "style": "primary",
                        "value": approval_id,
                        "action_id": "approve_once"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Allow for Session ⚡",
                            "emoji": True
                        },
                        "value": approval_id,
                        "action_id": "approve_session"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Allow Permanently 🏆",
                            "emoji": True
                        },
                        "value": approval_id,
                        "action_id": "approve_permanent"
                    },
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "Deny 🔴",
                            "emoji": True
                        },
                        "style": "danger",
                        "value": approval_id,
                        "action_id": "deny_tool"
                    }
                ]
            }
        ]
        
        try:
            post_args = {
                "channel": channel_id,
                "text": fallback_text,
                "blocks": blocks
            }
            if thread_ts:
                post_args["thread_ts"] = thread_ts
                
            res = client.chat_postMessage(**post_args)
            message_ts = res.get("ts")
            log(f"Posted approval message with TS {message_ts}")
        except Exception as se:
            log(f"Failed to post Slack approval message: {se}. Auto-approving.")
            print(json.dumps({"decision": "allow"}))
            return
            
        # 3. Poll for response in session_store.json
        timeout_sec = 300 # 5 minutes timeout
        start_time = time.time()
        decision = "deny"
        reason = "Timeout waiting for approval"
        
        while time.time() - start_time < timeout_sec:
            time.sleep(0.5)
            if os.path.exists(session_store_path):
                try:
                    with open(session_store_path, "r") as f:
                        sessions = json.load(f)
                    
                    # Search all sessions for the approval_id
                    found = False
                    for session_data in sessions.values():
                        pending = session_data.get("pending_approvals", {})
                        if approval_id in pending:
                            entry = pending[approval_id]
                            if entry.get("status") != "pending":
                                decision = entry.get("decision", "deny")
                                reason = "User selection"
                                found = True
                                break
                    if found:
                        break
                except Exception as re:
                    log(f"Error polling session store: {re}")
                    
        # Update slack message to reflect timeout if no decision
        if decision == "deny" and reason == "Timeout waiting for approval":
            try:
                client.chat_update(
                    channel=channel_id,
                    ts=message_ts,
                    text=f"🔴 *Tool Permission Request Timed Out* (ID: `{approval_id}`)\n\n{tool_details_text}",
                    blocks=[
                        {
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"🔴 *Tool Permission Request Timed Out*\n\n{tool_details_text}"
                            }
                        }
                    ]
                )
            except Exception as ue:
                log(f"Failed to update Slack message on timeout: {ue}")
                
        # 4. Output final decision JSON
        log(f"Returning decision: {decision}")
        if decision == "allow":
            print(json.dumps({"decision": "allow"}))
        else:
            print(json.dumps({"decision": "deny", "reason": f"User denied tool execution for tool: {tool_name}."}))
            
    except Exception as e:
        log(f"Fatal error in hook: {e}")
        print(json.dumps({"decision": "allow"})) # Fallback to allow so we don't break execution

if __name__ == "__main__":
    main()