#!/bin/zsh
# 개발 폴더의 코드를 서비스용 복사본(~/statyearbook-server)에 반영한다.
# macOS는 자동 시작 서비스가 '문서' 폴더를 읽지 못하게 막으므로, 서비스는 홈 폴더의 복사본에서 돈다.
#
# 처음 실행: 복사본을 만들고 지금 DB·업로드 파일·.env를 옮긴 뒤 자동 시작을 등록한다.
# 다시 실행: 코드만 덮어쓰고 서버를 재시작한다. DB·업로드·.env·로그·백업은 건드리지 않는다.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="${STATYEARBOOK_SERVER_DIR:-$HOME/statyearbook-server}"
SERVICE_DB="backend/app/db/annual_statistics.sqlite"
first_run=false
[[ -d "$DEST" ]] || first_run=true

if [[ ! -f "$SRC/frontend/dist/index.html" ]]; then
  echo "frontend/dist가 없습니다. 먼저 빌드하세요: cd frontend && VITE_API_BASE_URL=/ npm run build" >&2
  exit 1
fi

mkdir -p "$DEST"
rsync -a --delete \
  --exclude '.git/' --exclude '.venv/' --exclude 'node_modules/' \
  --exclude '.env' --exclude 'logs/' --exclude 'backups/' \
  --exclude 'backend/app/db/*.sqlite*' --exclude 'backend/uploads/' \
  --exclude 'workspace_inputs/' --exclude 'generated/' --exclude 'exports/' --exclude 'references/' \
  --exclude '__pycache__/' --exclude '.pytest_cache/' \
  "$SRC/" "$DEST/"

cd "$DEST"
if [[ ! -x .venv/bin/python ]]; then
  uv venv -q --python 3.12 .venv
fi
uv pip install -q --python .venv/bin/python -r backend/requirements.txt

if $first_run || [[ ! -f .env ]]; then
  # 개발 폴더의 설정을 가져오되 DB는 서비스 전용 파일을 쓴다.
  sed -E "s|^ANNUAL_STATISTICS_DB_PATH=.*|ANNUAL_STATISTICS_DB_PATH=$SERVICE_DB|" "$SRC/.env" > .env
fi
if [[ ! -f "$SERVICE_DB" ]]; then
  src_db="$(grep -E '^ANNUAL_STATISTICS_DB_PATH=' "$SRC/.env" | cut -d= -f2-)"
  /usr/bin/sqlite3 "$SRC/${src_db:-backend/app/db/annual_statistics.sqlite}" ".backup '$DEST/$SERVICE_DB'"
  echo "DB 복사: $SERVICE_DB"
fi
if [[ ! -d backend/uploads && -d "$SRC/backend/uploads" ]]; then
  cp -R "$SRC/backend/uploads" backend/uploads
fi

if launchctl print "gui/$(id -u)/com.statyearbook.server" >/dev/null 2>&1; then
  launchctl kickstart -k "gui/$(id -u)/com.statyearbook.server"
  echo "서버 재시작: $DEST"
else
  "$DEST/deploy/mac/install.sh"
fi
