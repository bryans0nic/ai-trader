#!/usr/bin/env bash
# Runs the trader dashboard permanently on this Mac (starts at login, restarts if it dies), deploys merged PRs
# from origin/main every 2 minutes, and publishes the page to your Tailscale devices over HTTPS.
# Run from the main checkout as your normal user: ./scripts/motley_fool/install-mac.sh   (re-running is safe)
set -euo pipefail

DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$DIR"
PORT=8765
TS_PORT=10443 # 443, 8443 and 9443 are ClaudeOS / SocialOS
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs"
say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }

[ "$(uname -s)" = "Darwin" ] || { echo "This script is for macOS."; exit 1; }
command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/"; exit 1; }

say "Installing packages"
uv sync --frozen

write_plist() { # label, then the plist body
  cat >"$AGENTS/$1.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$1</string>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>$(dirname "$(command -v uv)"):/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>RunAtLoad</key><true/>
$2
</dict></plist>
PLIST
  launchctl bootout "gui/$(id -u)/$1" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$1.plist"
}

say "Starting the dashboard service"
write_plist com.aitrader.dashboard "  <key>ProgramArguments</key><array>
    <string>$DIR/.venv/bin/python</string><string>-u</string>
    <string>$DIR/scripts/motley_fool/dashboard.py</string><string>--port</string><string>$PORT</string>
  </array>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOGS/ai-trader-dashboard.log</string>
  <key>StandardErrorPath</key><string>$LOGS/ai-trader-dashboard.log</string>"

say "Starting auto-deploy (every 2 minutes)"
write_plist com.aitrader.autodeploy "  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>$DIR/scripts/motley_fool/deploy-mac.sh</string>
  </array>
  <key>StartInterval</key><integer>120</integer>
  <key>StandardOutPath</key><string>$LOGS/ai-trader-deploy.log</string>
  <key>StandardErrorPath</key><string>$LOGS/ai-trader-deploy.log</string>"

say "Publishing to your Tailscale devices"
tailscale serve --bg --https="$TS_PORT" "http://127.0.0.1:$PORT"
tailscale serve status | grep -B1 "127.0.0.1:$PORT" || true
