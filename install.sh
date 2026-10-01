#!/bin/bash
# Install agent-sessions as an always-on macOS LaunchAgent.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.agent-sessions.plist"

sed "s|__HOME__|$HOME|g" "$DIR/agent-sessions.plist.template" > "$PLIST"
launchctl load "$PLIST"

echo "loaded com.agent-sessions"
echo "serving on http://0.0.0.0:8485  (reach it over your tailnet, e.g. http://<tailscale-name>:8485)"
echo "logs: /tmp/agent-sessions.log"
