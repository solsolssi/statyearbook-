#!/bin/zsh
# install.sh로 등록한 자동 시작·백업을 해제한다. 백업 파일과 로그는 지우지 않는다.
set -u

for label in com.statyearbook.server com.statyearbook.ollama com.statyearbook.backup; do
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/$label.plist"
  echo "해제: $label"
done
