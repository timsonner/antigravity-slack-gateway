#!/usr/bin/env python3
"""
CLI utility to send messages to Slack using the configured bot token.
Usage:
    python send_slack.py "Your message here"
    python send_slack.py -c general "Your message here"
    python send_slack.py -c C0B8U3ZGE7L -t 1234567890.123456 "Thread response"
"""

import os
import sys
import argparse
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

def main():
    parser = argparse.ArgumentParser(description="Send messages to a Slack channel using the Antigravity gateway configuration.")
    parser.add_argument("message", nargs="?", help="The message text to send. Can also be passed via stdin.")
    parser.add_argument("-c", "--channel", help="Channel name (e.g. 'general') or channel ID (e.g. 'C0B8U3ZGE7L'). Defaults to SLACK_HOME_CHANNEL/SLACK_HOME_CHANNEL_NAME in .env.")
    parser.add_argument("-t", "--thread", help="Thread timestamp (ts) to post a reply in a specific thread.")
    
    args = parser.parse_args()

    # Load environment variables
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dotenv_path = os.path.join(base_dir, ".env")
    load_dotenv(dotenv_path)

    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    if not bot_token:
        print("Error: SLACK_BOT_TOKEN not found in environment. Please make sure the .env file exists and is populated.", file=sys.stderr)
        sys.exit(1)

    # Resolve message
    message_text = args.message
    if not message_text:
        # Check if stdin has data
        if not sys.stdin.isatty():
            message_text = sys.stdin.read().strip()
        
    if not message_text:
        print("Error: No message content provided. Either pass it as an argument or pipe it to stdin.", file=sys.stderr)
        parser.print_help()
        sys.exit(1)

    client = WebClient(token=bot_token)

    # Resolve target channel ID
    channel_target = args.channel or os.environ.get("SLACK_HOME_CHANNEL")
    if not channel_target:
        # If SLACK_HOME_CHANNEL is not set, check SLACK_HOME_CHANNEL_NAME
        channel_name = os.environ.get("SLACK_HOME_CHANNEL_NAME", "general").strip()
        if channel_name.startswith("#"):
            channel_name = channel_name[1:]
        
        print(f"Resolving channel ID for #{channel_name}...", file=sys.stderr)
        try:
            response = client.conversations_list(types="public_channel,private_channel")
            for chan in response.get("channels", []):
                if chan.get("name") == channel_name:
                    channel_target = chan.get("id")
                    break
        except SlackApiError as e:
            print(f"Warning: Failed to list channels to resolve name: {e.response['error']}", file=sys.stderr)

    # Default fallback
    if not channel_target:
        channel_target = "C0B8U3ZGE7L" # Default ID for #general if resolution fails

    # Send the message
    try:
        print(f"Posting message to {channel_target}...", file=sys.stderr)
        post_args = {
            "channel": channel_target,
            "text": message_text
        }
        if args.thread:
            post_args["thread_ts"] = args.thread

        response = client.chat_postMessage(**post_args)
        print(f"Success: Message posted successfully. TS: {response['ts']}")
    except SlackApiError as e:
        print(f"Error posting message: {e.response['error']}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
