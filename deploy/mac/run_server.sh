#!/bin/zsh
# 사내 Mac 한 대에서 화면과 API를 함께 서비스한다 (http://<이 Mac의 IP>:8000).
# caffeinate로 서버가 도는 동안 Mac이 잠자기에 들어가지 않게 한다.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO"

export FRONTEND_DIST_DIR="$REPO/frontend/dist"
PORT="${STATYEARBOOK_PORT:-8000}"

if [[ ! -f "$FRONTEND_DIST_DIR/index.html" ]]; then
  echo "frontend/dist가 없습니다. 먼저 빌드하세요: cd frontend && VITE_API_BASE_URL=/ npm run build" >&2
  exit 1
fi

exec /usr/bin/caffeinate -i -s "$REPO/.venv/bin/python" -m uvicorn app.main:app \
  --app-dir backend --host 0.0.0.0 --port "$PORT"
