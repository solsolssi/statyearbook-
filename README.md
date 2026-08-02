# 통계연보 검수 보조

통계연보 파일을 구조화하고 합계·비율·오탈자·번역·메타정보 등을 검수하는
React + FastAPI 웹앱입니다. 업로드한 파일의 구조화 데이터와 검수 결과는 선택된
DB에 저장되며, 검수 작업은 연보 ID에 고정된 단계형 워크플로로 실행됩니다.
로컬은 SQLite를 사용하고, Railway는 같은 저장소 계층을 통해 PostgreSQL을
사용합니다.

## 실행

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
.venv/bin/python -m uvicorn app.main:app --app-dir backend --reload
```

```bash
cd frontend
npm install
npm run dev
```

- 프런트엔드: `http://127.0.0.1:5173`
- 백엔드 API: `http://127.0.0.1:8000`
- API 문서: `http://127.0.0.1:8000/docs`

## 업로드와 검수 실행

웹 화면의 `연보 업로드` 버튼은 `.xlsx`, `.hwpx`, `.md`를 받습니다. 업로드
창에서 목록에 표시할 연보 이름을 직접 입력할 수 있습니다. 업로드 단계에서는
다음 작업만 수행합니다.

1. 파일을 형식별 파서로 구조화합니다.
2. 한 트랜잭션에서 연보, 통계표, 셀을 DB에 저장합니다.
3. 업로드한 연보를 목록에 추가합니다.

목록에서 연보를 선택한 뒤 `검수 진행`을 눌러 합계·비율·오탈자·번역·
메타정보·이상치·파란색 표기 중 실행할 항목을 고릅니다. 같은 연도 또는 기준
연보에 구조·메타정보·셀 값이 모두 같은 표가 있으면 해당 표의 검수 결과를
재사용하고, 달라진 표만 새로 검수합니다. 연도만 같고 셀이 다른 표는 재사용하지
않습니다. 언어 후보의 LLM 자동 판정은 검수 창에서 별도로 활성화합니다.

작업 상태는 `report_processing_jobs`와 `report_processing_stages`에 저장됩니다.
업로드 실패 시 성공한 앞 단계는 재사용하고 실패한 단계부터 재시도할 수 있습니다.
동일한 파일·연도·제목·옵션 조합은 SHA-256 해시로 판별해 기존 작업을 재사용합니다.
진행률과 worker lease도 DB에 저장되므로 프로세스가 중단되면 lease 만료 후 다른
worker가 완료된 단계 다음부터 이어서 처리할 수 있습니다.
자세한 내부 흐름은 [자동 검수 아키텍처](docs/automated-validation-workflow.md)를
참고하세요.

전체 시계열 Excel과 당해연도 증분 Excel을 원장에 적재하고 연보별 표시 구간을
생성하는 목표 구조는
[엑셀 시계열 원장 기반 연보 생성](docs/excel-series-yearbook-architecture.md)에
정리되어 있습니다. 원장 적재와 연보 스냅샷을 분리해 기존 HWPX/Markdown 기준
검수 결과를 회귀 기준으로 유지합니다.

현재 원천 시스템의 `표정보·표항목·표데이터` 내보내기는 기존 연보 DB와 분리된
원장 테이블에 적재됩니다. 이 적재는 기존 연보를 교체하거나 검수를 실행하지
않습니다.

웹 화면의 `통계 연보` 목록에는 게시된 2025·2026 연보와 함께 `테스트 연보`가
표시됩니다. 테스트 연보는 기존 연보를 레이아웃 기준으로 사용하고 원장 생성값을
보여줍니다. 생성하지 못한 표도 숨기지 않고 현재 기준 레이아웃, 갱신 방식,
실패 원인을 표시합니다. 검수는 실행하지 않습니다.

데이터 셀은 현재 원장을 정답으로 사용합니다. 기존 연보와 값이 다르면 오류로
덮어쓰지 않고 `원장값 반영`으로 표시하며, 기존 연보 스냅샷은 그대로 보존합니다.

표별 갱신 방식은 `yearbook_table_update_policies`, 연도별 변경 여부는
`yearbook_edition_manifest`에 저장합니다. 최근 N개년 이동, 당해연도 전체 교체,
텍스트 교체, 변경 없음 승계, 고정, 신규, 삭제, 자료 누락을 서로 다른 상태로
처리합니다.
새 기준연도 값이 없을 때 현재 값을 쓰기로 확정한 표는 직전 값을 승계하고,
새 원장값이 들어오면 다시 원장 갱신으로 전환합니다. 의도적으로 미입력 상태를
유지하는 표는 행 제목과 표 구조만 남기고 데이터 셀을 비우는 `빈 값 유지` 상태로
생성합니다.

사용자가 확정한 원장 연결은 자동 제목 매칭과 분리된 승인 레시피로 저장합니다.
복수 원장을 사용하는 표는 각 원장의 실제 보유 기간과 우선순위를 함께 기록하므로,
다음 연도에는 표시 기간에 남아 있는 원장만 선택할 수 있습니다. `통계 원장` 탭에서
연결 대상으로 지정한 원장의 기간·항목·값을 직접 조회할 수 있습니다.

2025 기준 초안 레시피와 셀 비교를 CLI로 다시 만들 수 있습니다.

```bash
PYTHONPATH=backend .venv/bin/python -m app.yearbook_data.bootstrap_recipes \
  --report-id 42

PYTHONPATH=backend .venv/bin/python -m app.yearbook_data.run_reproduction \
  --report-id 42
```

### 업로드 API

브라우저는 파일을 raw body로 전송하고 원본 파일명은 쿼리에 넣습니다.

```bash
curl -X POST \
  --data-binary @2027_통계연보.xlsx \
  "http://127.0.0.1:8000/api/imports?filename=2027_통계연보.xlsx&year=2027"
```

```bash
curl http://127.0.0.1:8000/api/imports/1
curl -X POST http://127.0.0.1:8000/api/imports/1/retry
```

LLM 전수 검수는 비용이 발생하므로 연보 선택 후 `검수 진행` 창에서 명시적으로
켭니다. 새 표의 프로파일을 LLM으로 보강하려면 환경 변수
`PROFILE_LLM_ENABLED=1`도 설정합니다. 이 옵션을 끄더라도 계산 규칙, 승인 사전
및 캐시 기반 검수는 수행됩니다.

## 검수 실행

최신 연보를 규칙과 사전만으로 검수합니다.

```bash
PYTHONPATH=backend .venv/bin/python -m app.validation.run_validations
```

특정 연보를 고정해 검수하거나 LLM을 포함할 수 있습니다.

```bash
PYTHONPATH=backend .venv/bin/python -m app.validation.run_validations \
  --report-id 2 --refresh-profiles --with-llm
```

## LLM 설정

키는 저장소의 `.env`에만 두고 커밋하지 않습니다. 예시는 `.env.example`에
있습니다. `LLM_PROVIDER=auto`는 BizRouter 키가 있으면 BizRouter를 우선하고,
없으면 OpenAI를 사용합니다.

```dotenv
LLM_PROVIDER=bizrouter
LLM_REVIEW_ENABLED=1
BIZROUTER_API_KEY=발급받은_키
BIZROUTER_MODEL=openai/gpt-5-mini

# 새 표 또는 구조 변경 표의 계산 프로파일 보강
PROFILE_LLM_ENABLED=1
PROFILE_LLM_MODEL=gpt-5-mini
```

언어 검수는 `공식 사전 정확 일치 → 동일 문맥 캐시 → LLM` 순서입니다. 한 셀의
오탈자와 번역은 하나의 요청 문맥으로 묶습니다. 용어 제안은 현재 검수 범위에서
제외되어 있습니다. 메타정보는 존재 여부만 계산 규칙으로 확인하며, 주석·출처
본문을 언어 검수 대상으로 보내지 않습니다.

## 배포

현재 배포 기준은 `Vercel 프론트엔드 + Railway 백엔드 + Railway Postgres`입니다.
로컬 개발은 계속 SQLite를 사용하고, Railway 환경에 `DATABASE_URL`이 있으면
백엔드는 자동으로 Postgres를 사용합니다.

### Railway 백엔드

Railway에서 GitHub 저장소를 연결한 뒤 백엔드 서비스를 만듭니다. 저장소 루트의
`railway.json`은 루트 `Dockerfile`로 FastAPI 서버를 빌드하며, 배포 전에 DB
마이그레이션을 실행하고 `/ready`로 DB 연결까지 확인합니다.

필수 환경 변수:

```dotenv
DATABASE_URL=${{Postgres.DATABASE_URL}}
DATABASE_BACKEND=postgres
UPLOAD_DIR=/data/uploads
ALLOWED_ORIGINS=https://your-vercel-project.vercel.app
AUTO_IMPORT_INCLUDE_LLM=0
PROFILE_LLM_ENABLED=0
SOURCE_STORAGE_BACKEND=local
JOB_EXECUTOR_BACKEND=inprocess
```

LLM 검수를 운영에서 자동 실행하려면 아래처럼 명시적으로 켭니다.

```dotenv
LLM_PROVIDER=bizrouter
LLM_REVIEW_ENABLED=1
BIZROUTER_API_KEY=발급받은_키
BIZROUTER_MODEL=openai/gpt-5-mini
AUTO_IMPORT_INCLUDE_LLM=1
```

업로드 원본 파일을 재검수에도 보존하려면 Railway Volume을 `/data`에 연결합니다.
볼륨이 없어도 업로드 직후 DB 저장과 검수는 가능하지만, 재배포 뒤 원본 파일 경로는
유지되지 않을 수 있습니다.

API와 검수 worker를 분리할 때는 두 서비스에 동일한 PostgreSQL과 객체 저장소
설정을 넣습니다.

```dotenv
SOURCE_STORAGE_BACKEND=s3
OBJECT_STORAGE_BUCKET=annual-reports
OBJECT_STORAGE_ENDPOINT=https://<account>.r2.cloudflarestorage.com
OBJECT_STORAGE_REGION=auto
OBJECT_STORAGE_ACCESS_KEY=...
OBJECT_STORAGE_SECRET_KEY=...
JOB_EXECUTOR_BACKEND=worker
JOB_LEASE_SECONDS=300
```

별도 Railway worker의 Start Command는 다음과 같습니다.

```bash
python -m app.workflows.report_worker
```

worker 서비스의 Config File을 `/railway.worker.json`으로 지정하면 Start Command와
재시작 정책이 자동 적용됩니다. API 서비스는 `/railway.json`을 사용하고
`JOB_EXECUTOR_BACKEND=worker`로 설정합니다.

단일 백엔드 서비스만 운영한다면 기존처럼 `SOURCE_STORAGE_BACKEND=local`,
`JOB_EXECUTOR_BACKEND=inprocess`를 사용하면 됩니다.

### Vercel 프론트엔드

Vercel에서 같은 GitHub 저장소를 연결하고 Root Directory를 `frontend`로
설정합니다. `frontend/vercel.json`이 Vite 빌드와 SPA 경로 처리를 담당합니다.

필수 환경 변수:

```dotenv
VITE_API_BASE_URL=https://your-railway-backend.up.railway.app
```

Vercel 배포 URL이 확정되면 Railway의 `ALLOWED_ORIGINS` 값을 그 URL로 갱신한 뒤
백엔드 서비스를 재배포합니다.

작업 실패율, 단계별 처리 시간, LLM 토큰·비용, 원본 파일 보존과 PostgreSQL 백업
설정은 [배포·운영 가이드](docs/deployment-operations.md)를 참고하세요.

## 구조

```text
backend/app/
  api/                    FastAPI 엔드포인트
  core/                   설정, 공용 LLM 전송 계층
  db/                     DB 연결 선택, 공통 스키마, PostgreSQL 어댑터
  ingest/                 Excel/HWPX/Markdown 파서와 저장소
  validation/             프로파일, 규칙 엔진, 언어 검수 단계
  workflows/              업로드부터 검수 완료까지의 작업 오케스트레이션
  services/               조회 모델과 하이라이트 표시 변환
frontend/src/
  api/                    업로드·작업 조회·연보 조회 클라이언트
  components/             목록 및 상세 검수 화면
  utils/                  검수 그룹화·정렬·표시 정책
```

## 검증

```bash
cd backend
../.venv/bin/python -m unittest discover -s tests -q
```

```bash
cd frontend
npm run build
```

## 연보 업로드 테스트 흐름

로컬 환경은 `ANNUAL_STATISTICS_DB_PATH`로 활성 DB를 선택합니다. 현재 테스트용
설정은 `backend/app/db/annual_statistics_test.sqlite`이며, 기존
`annual_statistics.sqlite`는 변경하지 않고 보존합니다. 테스트 DB의 기존
2025·2026 연보는 화면 목록에 노출되지 않는 레이아웃 템플릿으로만 사용됩니다.

화면의 `연보 업로드`에서 다음 세 방식을 선택할 수 있습니다.

1. `완성 연보 새로 업로드`: HWPX/MD/XLSX를 검수 없이 새 스냅샷으로 저장
2. `완성 연보 수정본 반영`: 기준 연보와 표·셀 차이를 저장하고 수정본을 별도 스냅샷으로 저장
3. `기준 연보에 새 연도 원장 추가`: 기준 연보 형식에 증분 원장 3개 파일을 반영하고 다음 연도 스냅샷 생성

세 방식 모두 업로드할 연보 이름을 직접 입력합니다. 업로드가 끝나면 생성된 연보가
자동으로 선택되며, 요약 영역의 `검수 진행`에서 검수 항목과 기존 결과 재사용
여부를 선택합니다.

`연보 비교`에서는 원장 기반 연보와 완성 연보 등 임의의 두 스냅샷을 선택해
일치·변경·추가·삭제 표 수와 셀 차이를 확인할 수 있습니다.

테스트 DB를 다시 만들 때는 기존 테스트 DB를 다른 이름으로 보관한 뒤 다음 명령을
사용합니다. 명령은 대상 파일이 이미 있으면 덮어쓰지 않고 중단합니다.

```bash
PYTHONPATH=backend .venv/bin/python -m app.db.prepare_test_database \
  --source backend/app/db/annual_statistics.sqlite \
  --destination backend/app/db/annual_statistics_test.sqlite
```
