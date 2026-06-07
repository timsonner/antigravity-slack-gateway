import os
import sys
import json
import subprocess

# Define paths
AGY_REAL_EXE = r"C:\Users\admin\AppData\Local\agy\bin\agy.exe"
GEMINI_DIR = os.path.join(os.path.expanduser("~"), ".gemini")
ALIASES_DIR = os.path.join(GEMINI_DIR, "antigravity")
ALIASES_FILE = os.path.join(ALIASES_DIR, "session_aliases.json")
LAST_CONVS_FILE = os.path.join(GEMINI_DIR, "antigravity-cli", "cache", "last_conversations.json")

def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_json(path, data):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception as e:
        sys.stderr.write(f"Error saving {path}: {e}\n")
        return False

def get_current_workspace_conv_id():
    # Try current working directory
    cwd = os.getcwd().lower()
    last_convs = load_json(LAST_CONVS_FILE)
    
    # 1. Exact match
    for ws_path, conv_id in last_convs.items():
        if os.path.abspath(ws_path).lower() == os.path.abspath(cwd).lower():
            return conv_id
            
    # 2. Substring match
    for ws_path, conv_id in last_convs.items():
        if cwd in ws_path.lower() or ws_path.lower() in cwd:
            return conv_id
            
    # 3. Fallback to latest registered in last_conversations.json
    if last_convs:
        # Since JSON insertion order is preserved in Python 3.7+, return the last item
        return list(last_convs.values())[-1]
        
    return None

def resolve_alias_or_slug(name):
    # 1. Try aliases first
    aliases = load_json(ALIASES_FILE)
    if name in aliases:
        return aliases[name]
        
    # 2. Treat as workspace folder/slug (Option C)
    last_convs = load_json(LAST_CONVS_FILE)
    name_lower = name.lower()
    
    # Fuzzy match on workspace folder paths (e.g., if user inputs "proj_1780829102_a0999e83" or "a0999e83")
    for ws_path, conv_id in last_convs.items():
        folder_name = os.path.basename(ws_path).lower()
        if name_lower in folder_name or name_lower in ws_path.lower():
            return conv_id
            
    return None

def handle_alias_command(args):
    # Command: agy alias <name> [conv_id]
    if len(args) < 2:
        print("Usage: agy alias <name> [conv_id]")
        # List existing aliases
        aliases = load_json(ALIASES_FILE)
        if aliases:
            print("\nCurrent aliases:")
            for k, v in aliases.items():
                print(f"  {k} -> {v}")
        else:
            print("\nNo aliases configured.")
        return 0
        
    name = args[1]
    conv_id = args[2] if len(args) > 2 else get_current_workspace_conv_id()
    
    if not conv_id:
        print("Error: Could not automatically resolve a conversation ID for the current workspace.")
        print("Please provide the conversation UUID explicitly: agy alias <name> <conv_id>")
        return 1
        
    aliases = load_json(ALIASES_FILE)
    aliases[name] = conv_id
    if save_json(ALIASES_FILE, aliases):
        print(f"Success: Aliased '{name}' to conversation '{conv_id}'")
        return 0
    else:
        print("Error: Failed to save alias.")
        return 1

def main():
    args = sys.argv[1:]
    
    # Handle direct alias sub-command
    if len(args) > 0 and args[0] == "alias":
        sys.exit(handle_alias_command(args))
        
    # Intercept --conversation
    modified_args = []
    i = 0
    while i < len(args):
        if args[i] == "--conversation" and i + 1 < len(args):
            conv_name = args[i+1]
            resolved = resolve_alias_or_slug(conv_name)
            if resolved:
                modified_args.append("--conversation")
                modified_args.append(resolved)
            else:
                modified_args.append("--conversation")
                modified_args.append(conv_name)
            i += 2
        else:
            modified_args.append(args[i])
            i += 1
            
    # Forward execution to real agy.exe
    if not os.path.exists(AGY_REAL_EXE):
        sys.stderr.write(f"Error: Real agy.exe not found at {AGY_REAL_EXE}\n")
        sys.exit(1)
        
    try:
        proc = subprocess.run([AGY_REAL_EXE] + modified_args)
        sys.exit(proc.returncode)
    except Exception as e:
        sys.stderr.write(f"Error running agy.exe: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()
