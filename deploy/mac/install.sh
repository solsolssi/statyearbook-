#!/bin/zsh
# 로그인하면 서버·Ollama가 자동으로 켜지고, 매일 새벽 2시에 DB를 백업하도록 launchd에 등록한다.
# 다시 실행해도 안전하다(기존 등록을 바꿔 끼운다). 해제: deploy/mac/uninstall.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$REPO/logs"
mkdir -p "$AGENTS" "$LOGS"
chmod +x "$REPO/deploy/mac/run_server.sh" "$REPO/deploy/mac/backup_db.sh"

write_agent() {
  local label="$1" body="$2"
  cat > "$AGENTS/$label.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
$body
</dict>
</plist>
PLIST
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$label.plist"
  echo "등록: $label"
}

write_agent com.statyearbook.server "
  <key>ProgramArguments</key><array><string>$REPO/deploy/mac/run_server.sh</string></array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$LOGS/server.log</string>
  <key>StandardErrorPath</key><string>$LOGS/server.log</string>"

write_agent com.statyearbook.ollama "
  <key>ProgramArguments</key><array><string>/usr/bin/open</string><string>-g</string><string>-a</string><string>Ollama</string></array>
  <key>RunAtLoad</key><true/>"

write_agent com.statyearbook.backup "
  <key>ProgramArguments</key><array><string>$REPO/deploy/mac/backup_db.sh</string></array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>2</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>$LOGS/backup.log</string>
  <key>StandardErrorPath</key><string>$LOGS/backup.log</string>"
