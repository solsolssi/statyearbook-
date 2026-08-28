# 통계연보 검수 보조

통계연보 파일과 원천 통계 Excel을 구조화하고, 합계·비율·증감률·오탈자·번역·메타정보·이상치 등을 검수하는 React + FastAPI 웹앱입니다.  
발표에서는 이 프로젝트를 **연보 업로드 → 표 구조화 → 자동 검수 → 결과 확인 → 원장 기반 다음 연도 연보 생성**까지 이어지는 검수 보조 시스템으로 설명하면 됩니다.


## 프로젝트가 해결하는 문제

통계연보는 한 문서 안에 수백 개의 표가 있고, 각 표마다 합계·비율·증감률·단위·출처·국영문 표기가 다릅니다. 기존 방식은 사람이 엑셀이나 HWP 문서를 열어 값을 대조해야 해서 시간이 많이 걸리고, 같은 오류를 반복해서 놓치기 쉽습니다.

이 프로젝트는 다음 작업을 자동화합니다.

- HWPX, Markdown, Excel 연보 파일을 업로드해 표·셀·메타정보로 구조화합니다.
- 표별 계산 프로파일을 만들고 합계, 비율, 증감률, 이상치를 자동 검수합니다.
- 공식 번역 사전, 지역명 사전, 캐시, 선택적 LLM 검수를 사용해 오탈자와 번역 후보를 검토합니다.
- 기존 연보와 동일한 표는 검수 결과를 재사용하고, 변경된 표만 다시 검수합니다.
- 원천 시스템의 `표정보`, `표항목`, `표데이터` Excel을 원장으로 적재하고 기준 연보 형식에 맞춰 다음 연도 연보를 생성합니다.
- 검수 결과를 표 위치에 하이라이트하고, 필요한 경우 웹에서 표 내용을 수정할 수 있습니다.


## 전체 구조

```text
.
├── backend/                  FastAPI 백엔드
│   ├── app/
│   │   ├── api/              HTTP API 라우터
│   │   ├── application/      API 요청을 서비스로 연결하는 애플리케이션 계층
│   │   ├── core/             환경 설정, 숫자 파싱, LLM 클라이언트
│   │   ├── db/               SQLite/PostgreSQL 연결, 스키마, 마이그레이션
│   │   ├── domain/           파싱 결과와 검수 도메인 모델
│   │   ├── ingest/           HWPX/Markdown/Excel 파서
│   │   ├── models/           API 응답 Pydantic 모델
│   │   ├── services/         연보 조회, 업로드, 수정, 비교, 원장 생성 서비스
│   │   ├── storage/          업로드 원본 보존 로컬/S3 스토리지 추상화
│   │   ├── validation/       검수 프로파일, 규칙 엔진, 언어 검수 파이프라인
│   │   ├── workflows/        업로드·검수 작업 오케스트레이션
│   │   └── yearbook_data/    원천 통계 원장 적재와 연보 재현 로직
│   └── tests/                백엔드 단위/통합 테스트
├── frontend/                 Vite + React 프론트엔드
│   ├── src/
│   │   ├── api/              백엔드 API 클라이언트
│   │   ├── components/       화면 컴포넌트
│   │   ├── hooks/            업로드, 검수, 조회 상태 관리
│   │   ├── styles/           전역 CSS
│   │   └── utils/            검수 결과 표시, 그룹화, 다운로드 유틸
│   └── package.json
├── docs/                     상세 설계와 운영 문서
├── generated/                시뮬레이션·비교 산출물
├── Dockerfile                Railway 백엔드 배포용 이미지
├── railway.json              Railway API 서비스 설정
├── railway.worker.json       Railway worker 서비스 설정
└── vercel.json               루트 Vercel 설정
```

## 기술 스택

- **Frontend:** React 18, TypeScript, Vite, Vitest, lucide-react
- **Backend:** FastAPI, Pydantic, Uvicorn
- **Data:** SQLite 로컬 개발, PostgreSQL 운영 배포
- **Excel/HWP 처리:** openpyxl, xlrd, 자체 HWPX/Markdown 파서
- **Storage:** 로컬 파일 또는 S3 호환 객체 저장소
- **Deployment:** Vercel 프론트엔드, Railway 백엔드/worker, Railway Postgres

## 실행 방법

백엔드 실행:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
.venv/bin/python -m uvicorn app.main:app --app-dir backend --reload
```

프론트엔드 실행:

```bash
cd frontend
npm install
npm run dev
```

접속 주소:

- 프론트엔드: `http://127.0.0.1:5173`
- 백엔드 API: `http://127.0.0.1:8000`
- API 문서: `http://127.0.0.1:8000/docs`
- 상태 확인: `http://127.0.0.1:8000/health`
- DB 준비 확인: `http://127.0.0.1:8000/ready`

## 주요 화면과 기능

### 1. 통계 연보 화면

연보 목록과 표 목록, 선택한 표의 미리보기, 검수 요약을 한 화면에서 확인합니다.

주요 기능:

- 연보 선택
- 표 번호, 제목, 영문 제목 검색
- 정상, 확인 필요, 오류 의심, 이슈 있음 필터
- 검수 유형별 표시/숨김
- 검수 실행
- 연보 삭제
- 표 상세 열기

관련 프론트엔드 파일:

- `frontend/src/App.tsx`
- `frontend/src/components/ReportWorkspace.tsx`
- `frontend/src/components/ReportSummaryPanel.tsx`
- `frontend/src/components/TableList.tsx`
- `frontend/src/components/TablePreview.tsx`

### 2. 표 상세 화면

표 하나를 깊게 확인하는 화면입니다. 표 데이터, 메타정보, 검수 결과, 시각화, 수정 기능이 연결됩니다.

주요 기능:

- 표 데이터를 그리드로 표시
- 검수 결과를 셀·행 단위로 하이라이트
- 같은 계산 방식으로 반복된 검수 결과를 그룹화
- 오류 의심, 확인 필요, 정상 상태를 배지로 표시
- 메타정보 확인
- 표 내용 수정 화면으로 진입
- 표 단위 다운로드 메뉴 제공

관련 파일:

- `frontend/src/components/DetailView.tsx`
- `frontend/src/components/DataGrid.tsx`
- `frontend/src/components/detail/ValidationResultPanel.tsx`
- `frontend/src/components/detail/MetadataGrid.tsx`
- `frontend/src/components/TableEditView.tsx`

### 3. 연보 업로드

상단의 `연보 업로드` 버튼에서 두 가지 업로드 방식을 제공합니다.

| 방식 | 입력 파일 | 설명 |
| --- | --- | --- |
| 완성 연보 새로 업로드 | `.hwpx`, `.md`, `.xlsx` | 이미 완성된 연보 문서를 새 스냅샷으로 저장합니다. |
| 기준 연보에 새 연도 원장 추가 | `표정보`, `표항목`, `표데이터` Excel | 기준 연보의 표 형식에 원장 값을 반영해 새 연도 연보를 생성합니다. |

업로드 후 프론트엔드는 작업 ID를 받아 `/api/imports/{job_id}`를 폴링하고, 완료된 연보를 자동 선택합니다.

관련 파일:

- `frontend/src/components/AppHeader.tsx`
- `frontend/src/hooks/useReportImport.ts`
- `backend/app/api/routes.py`
- `backend/app/application/imports.py`
- `backend/app/workflows/report_processing.py`

### 4. 검수 실행

`검수 진행` 창에서 실행할 검수 항목을 직접 선택합니다.

지원 검수 항목:

| 항목 | 설명 |
| --- | --- |
| 합계 검수 | 계, 합계, 소계, 명시 산식의 산술 결과를 확인합니다. |
| 비율 검수 | 비율, 비중, 잔액율 등 분자/분모 기반 값을 확인합니다. |
| 증감률 검수 | 전년 대비 증감액과 증감률을 확인합니다. |
| 오탈자 검수 | 국문·영문 철자 오류, 문자 깨짐, 숫자 구분기호 오류를 후보로 잡습니다. |
| 번역 검수 | 국문과 영문의 의미 대응과 공식 번역 사전 일치 여부를 확인합니다. |
| 메타정보 검수 | 단위, 기준일, 출처 등 필수 메타정보 누락을 확인합니다. |
| 이상치 검수 | 같은 열 또는 시계열 안에서 통계적으로 튀는 값을 표시합니다. |
| 파란색 표기 확인 | HWPX 원문에서 파란색으로 표시된 검토 대상을 확인합니다. |

검수 실행 옵션:

- **기존 검수 결과 재사용:** 기준 연보 또는 사용자가 선택한 이전 검수 실행에서 구조와 셀 값이 완전히 같은 표의 결과만 복사합니다.
- **언어 후보 LLM 자동 판정:** 오탈자·번역 검수가 선택된 경우, 대기 중인 언어 후보를 LLM으로 판정합니다.
- **선택 검수:** 모든 항목을 돌리지 않고 필요한 검수만 실행할 수 있습니다.

관련 파일:

- `frontend/src/components/ValidationRunDialog.tsx`
- `frontend/src/hooks/useReportValidation.ts`
- `backend/app/application/validation_operations.py`
- `backend/app/services/validation_execution_service.py`
- `backend/app/validation/catalog.py`
- `backend/app/validation/selection.py`

## 백엔드 처리 플로우

### 1. 애플리케이션 시작

`backend/app/main.py`가 FastAPI 앱을 생성합니다.

1. 환경 설정을 읽습니다.
2. 앱 lifespan에서 기본 DB 마이그레이션을 초기화합니다.
3. CORS 설정을 적용합니다.
4. 일반 API 라우터와 운영 API 라우터를 등록합니다.
5. `/health`, `/ready` 상태 확인 엔드포인트를 제공합니다.

### 2. 완성 연보 업로드 플로우

```text
브라우저
  → POST /api/imports
  → ReportImportApplicationService
  → ReportProcessingWorkflow.create_job
  → ReportProcessingWorkflow.run
  → parse_report
  → ReportImportRepository.replace_parsed_report
  → DB 저장
```

핵심 로직:

- 파일 확장자로 `xlsx`, `hwpx`, `markdown` 파서를 선택합니다.
- 표 번호, 제목, 행렬 크기, 셀 좌표 중복 여부를 검증합니다.
- 셀 텍스트와 숫자 값을 함께 저장합니다.
- 업로드 원본은 로컬 또는 S3 호환 스토리지에 보존할 수 있습니다.
- 같은 파일·연도·제목·옵션 조합은 SHA-256 해시로 판별해 작업 재사용이 가능합니다.

### 3. 작업 오케스트레이션

`ReportProcessingWorkflow`는 업로드 후속 작업을 단계로 관리합니다.

```text
import
  → calculation_validation
  → language_validation
  → completed
```

특징:

- 각 단계의 성공·실패·결과를 DB에 저장합니다.
- 실패한 작업은 성공한 단계 다음부터 재시도할 수 있습니다.
- worker lease와 heartbeat를 사용해 중단된 작업을 다른 worker가 이어받을 수 있습니다.
- `JOB_EXECUTOR_BACKEND=inprocess`면 API 프로세스가 백그라운드 작업을 실행합니다.
- `JOB_EXECUTOR_BACKEND=worker`면 별도 worker 프로세스가 큐에서 작업을 처리합니다.

관련 파일:

- `backend/app/workflows/report_processing.py`
- `backend/app/workflows/report_job_repository.py`
- `backend/app/workflows/report_worker.py`
- `backend/app/workflows/job_executor.py`

### 4. 계산 검수 플로우

```text
CalculationValidationWorkflow
  → ValidationProfileRepository.ensure_profiles
  → ValidationEngine.evaluate
  → ValidationRepository.save_run
```

계산 검수는 외부 API 없이 재현 가능한 규칙 엔진으로 실행됩니다.

주요 로직:

- 표 구조를 분석해 검수 프로파일을 생성합니다.
- 사전에 관리되는 curated profile을 우선 사용합니다.
- 필요하면 합계, 비율, 증감률, 이상치 규칙을 자동 생성합니다.
- 선택된 검수 항목만 결과에 남길 수 있습니다.
- 결과는 `validation_runs`, `validation_checks` 계열 테이블에 저장됩니다.

관련 파일:

- `backend/app/validation/calculation_workflow.py`
- `backend/app/validation/profile_repository.py`
- `backend/app/validation/profile_generation/`
- `backend/app/validation/engine.py`
- `backend/app/validation/rules.py`

### 5. 언어 검수 플로우

```text
LanguageValidationWorkflow
  → LanguageReviewPipeline
  → 후보 생성
  → 사전/캐시 재사용
  → 선택적 LLM 판정
  → 검수 결과 동기화
```

언어 검수는 비용과 재현성을 고려해 후보 생성과 LLM 판정을 분리합니다.

판정 순서:

1. 공식 번역 사전과 지역명 사전 확인
2. 동일 문맥 캐시 재사용
3. LLM 자동 판정 옵션이 켜진 경우 외부 모델 호출
4. 미판정 후보는 `대기` 상태로 저장

관련 파일:

- `backend/app/validation/language_workflow.py`
- `backend/app/validation/language_pipeline/`
- `backend/app/validation/translation_glossary.py`
- `backend/app/validation/region_glossary.py`
- `backend/app/validation/llm_translation_review.py`
- `backend/app/validation/blue_review.py`

### 6. 검수 결과 재사용 로직

연보가 매년 반복되는 구조라는 점을 활용해, 바뀌지 않은 표는 기존 검수 결과를 복사합니다.

재사용 조건:

- 기준 연보 계보에 속하거나 사용자가 명시적으로 선택한 검수 실행이어야 합니다.
- 표 번호가 대응되어야 합니다.
- 메타정보와 셀 값이 완전히 같아야 합니다.
- 같은 연도라는 이유만으로는 재사용하지 않습니다.
- 현재 연보에서 검수 후 수동 수정된 표는 이전 결과를 그대로 재사용하지 않습니다.

이 로직 덕분에 새 연도 연보에서 변경된 표만 집중적으로 검수할 수 있습니다.

관련 파일:

- `backend/app/services/validation_execution_service.py`
- `backend/app/services/report_update_service.py`
- `backend/app/validation/report_lineage.py`

## 원장 기반 연보 생성

원천 시스템에서 내려받은 세 종류의 Excel을 별도 원장 테이블에 적재합니다.

- `표정보`: 통계의 기본 정보와 메타데이터
- `표항목`: 행·열 항목 구조
- `표데이터`: 기준시점별 값

`기준 연보에 새 연도 원장 추가`를 실행하면 다음 흐름으로 처리됩니다.

```text
표정보/표항목/표데이터 Excel
  → RelationalSourceDataImporter
  → 원장 테이블 적재
  → LedgerYearbookService.generate
  → 기준 연보 레이아웃과 갱신 정책 적용
  → 새 연도 연보 스냅샷 생성
```

생성 상태 예시:

- 원장값 반영
- 기존 값 승계
- 변경 없음
- 확인 필요
- 신규 통계 임시 표
- 삭제 명세 반영
- 자료 누락

관련 파일:

- `frontend/src/components/SourceStatisticsPage.tsx`
- `backend/app/services/source_statistics_service.py`
- `backend/app/services/ledger_yearbook_service.py`
- `backend/app/services/yearbook_reproduction_service.py`
- `backend/app/yearbook_data/`

## 연보 비교

상단의 `연보 비교` 기능은 두 연보 스냅샷을 선택해 표와 셀 차이를 계산합니다.

비교 결과:

- 일치 표 수
- 변경 표 수
- 추가 표 수
- 삭제 표 수
- 변경 셀 수
- 표별 차이 목록

관련 파일:

- `frontend/src/components/AppHeader.tsx`
- `backend/app/services/report_update_service.py`
- `backend/app/models/report_updates.py`

## 수정 권한과 웹 수정

`수정 권한` 메뉴에서는 연보별·통계표별 수정 비밀번호를 관리합니다. 상세 화면에서 인증을 통과하면 표 번호, 제목, 열, 셀 값을 수정할 수 있습니다.

수정 로직의 특징:

- 비밀번호는 PBKDF2 기반 해시와 salt로 저장합니다.
- 인증 성공 시 bearer token 방식의 편집 세션을 발급합니다.
- 표 번호 중복을 막습니다.
- 수정된 표에는 `edited_after_run_id`가 남아 기존 검수 결과가 오래된 결과인지 판단할 수 있습니다.
- 수정 후에는 다시 검수를 실행해 최신 결과를 만들 수 있습니다.

관련 파일:

- `frontend/src/components/PasswordSettingsPage.tsx`
- `frontend/src/components/TableEditView.tsx`
- `backend/app/services/yearbook_edit_service.py`
- `backend/app/models/yearbook_edits.py`

## 주요 API

| Method | Path | 설명 |
| --- | --- | --- |
| `GET` | `/health` | API 프로세스 상태 확인 |
| `GET` | `/ready` | DB 연결까지 포함한 준비 상태 확인 |
| `GET` | `/api/report/overview` | 연보 요약, 표 목록, 선택 가능한 연보 조회 |
| `GET` | `/api/tables/{table_id}` | 표 상세 조회 |
| `POST` | `/api/imports` | 완성 연보 업로드 작업 생성 |
| `GET` | `/api/imports/{job_id}` | 업로드 작업 상태 조회 |
| `POST` | `/api/imports/{job_id}/retry` | 실패한 업로드 작업 재시도 |
| `POST` | `/api/validation/run` | 선택 검수 실행 |
| `GET` | `/api/validation/catalog` | 검수 항목 카탈로그 조회 |
| `GET` | `/api/validation/reuse-runs` | 재사용 가능한 검수 실행 조회 |
| `GET` | `/api/source-statistics` | 원장 통계 목록과 요약 조회 |
| `POST` | `/api/source-statistics/import` | 원장 Excel 3종 적재 및 연보 생성 |
| `GET` | `/api/source-statistics/{external_id}` | 원장 통계 상세 조회 |
| `POST` | `/api/report-comparisons` | 두 연보 스냅샷 비교 |
| `GET` | `/api/reports/{report_id}/edit-access` | 수정 권한 상태 조회 |
| `PUT` | `/api/reports/{report_id}/tables/{table_id}` | 인증된 표 수정 |

## 데이터 저장 구조

대표 테이블 역할:

- `annual_reports`: 업로드되거나 생성된 연보 스냅샷
- `stat_tables`: 연보 안의 통계표 메타정보
- `stat_table_cells`: 표의 셀 텍스트·숫자 값
- `validation_runs`: 검수 실행 단위
- `validation_checks`: 검수 결과와 표시 정보
- `linguistic_review_candidates`: 오탈자·번역·파란색 표기 후보
- `report_processing_jobs`: 업로드/검수 작업 상태
- `report_processing_stages`: 작업 단계별 실행 이력
- `source_*`: 원천 통계 원장 데이터
- `yearbook_table_update_policies`: 표별 갱신 정책
- `yearbook_edit_passwords`: 수정 비밀번호 정보
- `yearbook_edit_sessions`: 웹 수정 인증 세션

로컬 개발은 SQLite를 사용하고, Railway 운영 환경에서는 `DATABASE_URL`이 있으면 PostgreSQL을 사용합니다.

## LLM 설정

LLM 검수는 비용이 발생할 수 있으므로 기본 자동 실행이 아닙니다. `.env`에 키를 넣고, 화면의 검수 창에서 `언어 후보 LLM 자동 판정`을 선택해야 실행됩니다.

```dotenv
LLM_PROVIDER=bizrouter
LLM_REVIEW_ENABLED=1
BIZROUTER_API_KEY=발급받은_키
BIZROUTER_MODEL=openai/gpt-5-mini

# 새 표 또는 구조 변경 표의 계산 프로파일 보강
PROFILE_LLM_ENABLED=1
PROFILE_LLM_MODEL=gpt-5-mini
```

`LLM_PROVIDER=auto`는 BizRouter 키가 있으면 BizRouter를 우선하고, 없으면 OpenAI 설정을 사용합니다.

## CLI 작업

최신 연보를 규칙과 사전 기반으로 검수:

```bash
PYTHONPATH=backend .venv/bin/python -m app.validation.run_validations
```

특정 연보를 지정하고 LLM까지 포함:

```bash
PYTHONPATH=backend .venv/bin/python -m app.validation.run_validations \
  --report-id 2 --refresh-profiles --with-llm
```

2025 기준 초안 레시피와 셀 비교 재생성:

```bash
PYTHONPATH=backend .venv/bin/python -m app.yearbook_data.bootstrap_recipes \
  --report-id 42

PYTHONPATH=backend .venv/bin/python -m app.yearbook_data.run_reproduction \
  --report-id 42
```

테스트 DB 생성:

```bash
PYTHONPATH=backend .venv/bin/python -m app.db.prepare_test_database \
  --source backend/app/db/annual_statistics.sqlite \
  --destination backend/app/db/annual_statistics_test.sqlite
```

## 검증 방법

백엔드 테스트:

```bash
cd backend
../.venv/bin/python -m unittest discover -s tests -q
```

프론트엔드 빌드:

```bash
cd frontend
npm run build
```

프론트엔드 테스트:

```bash
cd frontend
npm run test
```

## 배포 개요

현재 배포 기준은 `Vercel 프론트엔드 + Railway 백엔드 + Railway Postgres`입니다.

Railway 백엔드 필수 환경 변수 예시:

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

Vercel 프론트엔드 필수 환경 변수:

```dotenv
VITE_API_BASE_URL=https://your-railway-backend.up.railway.app
```

API와 검수 worker를 분리하려면 두 서비스가 같은 PostgreSQL과 객체 저장소를 바라보게 설정합니다.

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

worker 시작 명령:

```bash
python -m app.workflows.report_worker
```

자세한 운영 내용은 `docs/deployment-operations.md`를 참고하면 됩니다.

## 발표에서 강조할 포인트

- **문서 파싱부터 검수까지 한 시스템 안에서 이어집니다.**
- **계산 검수와 언어 검수가 분리되어 재현성과 비용 통제가 가능합니다.**
- **동일한 표의 검수 결과를 재사용해 매년 반복되는 연보 검수 시간을 줄입니다.**
- **원천 통계 원장을 별도로 관리해 기존 연보 스냅샷을 훼손하지 않습니다.**
- **표 상세 화면에서 문제 위치를 바로 확인할 수 있어 담당자 검토가 쉬워집니다.**
- **SQLite와 PostgreSQL을 같은 저장소 계층으로 지원해 로컬 개발과 운영 배포가 연결됩니다.**

## 참고 문서

- `docs/PROJECT_HANDOVER_GUIDE.md`: macOS·Windows 설치, 실행, 수정, 테스트, 배포, 백업, 장애 대응을 포함한 상세 인수인계 가이드
- `exports/통계연보_검수_보조_시스템_프로젝트_인수인계_가이드.pptx`: 인수인계 회의와 신규 담당자 교육용 PowerPoint
- `docs/automated-validation-workflow.md`: 자동 검수 작업 단계와 재시도 구조
- `docs/excel-series-yearbook-architecture.md`: Excel 시계열 원장 기반 연보 생성 구조
- `docs/deployment-operations.md`: Railway/Vercel 운영과 모니터링
- `docs/2026_increment_connection_audit.md`: 2026 증분 원장 연결 감사
