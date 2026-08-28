# 통계연보 검수 보조 시스템 인수인계 가이드

> 대상: 이 프로젝트를 처음 받는 개발자·운영자
>
> 기준일: 2026-08-28 (Asia/Seoul)
>
> 기준 브랜치/커밋: `master` / `6292d55` 이후의 로컬 작업 트리
>
> 개발 환경: 기존 담당자 macOS → 다음 담당자 Windows
>
> 목적: 이 문서만 보고도 설치, 실행, 사용, 수정, 테스트, 배포, 백업, 장애 대응까지 할 수 있게 한다.

---

## 0. 가장 먼저 읽을 다섯 문장

1. 이 프로젝트는 **프론트엔드(React)** 와 **백엔드(FastAPI)** 를 각각 실행해야 화면이 정상 동작한다.
2. 소스 코드는 Git으로 전달되지만, 로컬 SQLite DB·업로드 원본·`.env` 비밀값은 Git에 들어가지 않으므로 **별도로 인계해야 한다.**
3. 처음에는 LLM 기능을 끈 채 SQLite 테스트 DB로 실행한다. 기본 계산 검수는 외부 API 없이 동작한다.
4. 백엔드 명령은 항상 저장소 루트에서 실행한다. 그래야 `.env`, DB, 업로드 폴더의 상대 경로가 엉키지 않는다.
5. DB 스키마는 백엔드 시작 시 자동 갱신될 수 있다. 실제 DB로 처음 실행하기 전에 반드시 백업한다.

### 요청한 순서대로 읽는 방법

이 문서는 필요한 내용을 빠르게 다시 찾을 수 있도록 세부 장을 나누어 두었다. 처음 인계받는 사람은 아래 순서를 지키면 된다.

1. **설치 단계:** [2. 15분 빠른 실행](#2-15분-빠른-실행) → [7. macOS 상세 설치](#7-macos-상세-설치) 또는 [8. Windows 상세 설치](#8-windows-상세-설치) → [9. 환경변수 완전 설명](#9-환경변수-완전-설명) → [10. 매일 실행하는 절차](#10-매일-실행하는-절차)
2. **기능 설명:** [3. 이 프로젝트는 무엇을 하는가](#3-이-프로젝트는-무엇을-하는가) → [4. 전체 구조와 데이터 흐름](#4-전체-구조와-데이터-흐름) → [11. 화면 사용 방법](#11-화면-사용-방법)
3. **유지보수와 프로젝트 구조:** [5. 폴더와 파일 지도](#5-폴더와-파일-지도) → [6. 코드·데이터·비밀정보 인계](#6-코드-데이터-비밀정보를-구분해서-인계하기) → [12. 코드 수정](#12-코드를-수정하는-표준-절차)부터 24장까지

컴퓨터 사용이 익숙하지 않다면 먼저 2장의 빠른 실행을 그대로 따라 한다. 화면이 정상적으로 열린 다음 기능 설명을 읽고, 마지막에 유지보수 장을 읽는다. 처음부터 운영 DB, 외부 LLM, Railway 배포를 연결하지 않는다.

---

## 1. 인수인계 완료의 정의

다음 항목을 모두 확인해야 “소스만 넘겨받은 상태”가 아니라 “운영 가능한 상태”다.

- [ ] Git 저장소 접근 권한과 저장소 URL을 받았다.
- [ ] 어떤 브랜치와 커밋이 실제 인계 기준인지 확인했다.
- [ ] 미커밋 변경을 커밋으로 받을지, 패치/압축 파일로 받을지 합의했다.
- [ ] 로컬 SQLite DB가 필요한지, Railway PostgreSQL만 사용할지 결정했다.
- [ ] 필요한 경우 SQLite DB와 `backend/uploads`를 별도 보안 경로로 받았다.
- [ ] `.env`의 **값 자체는 안전한 비밀관리 채널**로 받았다.
- [ ] Vercel, Railway, PostgreSQL, S3/R2, GitHub 권한을 받았다.
- [ ] 운영 프론트엔드 URL과 백엔드 URL을 받았다.
- [ ] LLM 공급자(BizRouter 또는 OpenAI), 모델, 월 비용 한도, 키 소유자를 확인했다.
- [ ] Windows PC에서 프론트엔드와 백엔드를 실행했다.
- [ ] `/health`, `/ready`, 프론트 화면, 테스트 파일 업로드를 확인했다.
- [ ] 프론트엔드 테스트/빌드와 백엔드 테스트 결과를 인계자와 함께 비교했다.
- [ ] DB 백업과 복원 연습을 최소 한 번 했다.
- [ ] 운영 장애 시 연락할 서비스/데이터/계정 담당자를 기록했다.

### 현재 저장소에서 특히 주의할 점

2026-08-28 점검 시점에는 다음 상태였다.

- Git 브랜치: `master`
- 마지막 커밋: `6292d55 feat: llm 보조 기능 및 검수 리포트 추출 기능`
- `git status --short`에 표시되는 변경 항목: 45개
- 위 항목 중 Git이 아직 추적하지 않는 항목: 11개
- 로컬 주 DB: `backend/app/db/annual_statistics.sqlite`, 약 4.1GB
- 로컬 테스트 DB: `backend/app/db/annual_statistics_test.sqlite`, 약 620MB
- 로컬 업로드 원본: `backend/uploads`, 약 1.3GB
- 위 DB와 업로드 폴더는 `.gitignore` 대상이므로 `git clone`만으로는 복원되지 않는다.

따라서 기존 담당자는 인계 직전에 `git status`, 최종 커밋, DB 백업 시각, 업로드 원본 백업 시각을 다시 기록해야 한다. 이 문서의 숫자는 기준일 스냅샷일 뿐 영구적인 값이 아니다.

---

## 2. 15분 빠른 실행

처음에는 **빈 테스트 DB + LLM 비활성화**로 실행한다. 운영 DB를 바로 연결하지 않는다.

### 2.1 공통 준비물

권장 버전은 다음과 같다.

| 도구 | 권장 버전 | 이유 |
| --- | --- | --- |
| Git | 최신 안정 버전 | 저장소 복제와 변경 관리 |
| Python | 3.12.x | Docker 운영 이미지가 Python 3.12 기반 |
| Node.js | 권장 24 LTS | 현재 공식 LTS이며 이 프로젝트의 Vite 8 의존성 범위를 충족 |
| npm | Node.js에 포함된 버전 | `package-lock.json` 기반 설치 |
| 편집기 | VS Code 권장 | Python, TypeScript, PowerShell을 함께 다루기 편함 |
| 브라우저 | Chrome 또는 Edge | 프론트엔드 확인과 개발자 도구 사용 |

설치 파일은 검색 광고나 개인 블로그의 재배포 파일이 아니라 아래 공식 사이트에서만 받는다.

| 프로그램 | 공식 설치 페이지 | 선택할 항목 |
| --- | --- | --- |
| Git | <https://git-scm.com/install/> | 자신의 운영체제용 설치 프로그램 |
| Python | <https://www.python.org/downloads/release/python-31210/> | 이 프로젝트와 같은 3.12 계열. Windows는 64-bit installer, macOS는 universal2 installer |
| Node.js | <https://nodejs.org/en/download> | `LTS`로 표시된 24 계열 설치 프로그램 |
| VS Code | <https://code.visualstudio.com/download> | 자신의 운영체제용 설치 프로그램; 선택 사항 |

Python 3.12.10은 3.12 계열에서 Windows/macOS 바이너리 설치 프로그램이 제공된 마지막 정기 유지보수판이다. 더 높은 `3.12.x`가 패키지 관리자에 이미 설치되어 있으면 그대로 사용해도 된다. Python 3.13/3.14로 임의 변경하기보다 운영 Docker 이미지와 같은 3.12를 먼저 사용한다.

설치 확인:

```text
git --version
python 또는 py --version
node --version
npm --version
```

버전 명령이 `command not found`, `찾을 수 없습니다`라고 나오면 다음 단계로 넘어가지 않는다. 설치 프로그램을 닫은 뒤 터미널 또는 PowerShell을 완전히 닫고 새로 열어 다시 확인한다.

### 2.2 macOS 빠른 실행

터미널을 열고 아래를 한 줄씩 실행한다.

```bash
git clone https://github.com/wtdnrr/statyearbook.git
cd statyearbook
cp .env.example .env
python3.12 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r backend/requirements.txt
cd frontend
npm ci
cd ..
```

터미널 1에서 백엔드를 실행한다.

```bash
cd /프로젝트가/있는/경로/statyearbook
./.venv/bin/python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

터미널 2에서 프론트엔드를 실행한다.

```bash
cd /프로젝트가/있는/경로/statyearbook/frontend
npm run dev
```

브라우저에서 다음 주소를 연다.

- 화면: `http://127.0.0.1:5173`
- API 문서: `http://127.0.0.1:8000/docs`
- 백엔드 생존 확인: `http://127.0.0.1:8000/health`
- DB 준비 확인: `http://127.0.0.1:8000/ready`

### 2.3 Windows 빠른 실행

#### 권장 폴더

OneDrive 동기화 폴더, 바탕 화면, 한글·공백이 매우 긴 경로를 피하고 `C:\work\statyearbook`처럼 짧은 경로를 권장한다. 대용량 DB와 `node_modules`가 동기화/백신 검사에 걸리면 실행이 느려질 수 있다.

PowerShell을 열고 아래를 한 줄씩 실행한다.

```powershell
Set-Location C:\work
git -c core.longpaths=true -c core.autocrlf=false clone https://github.com/wtdnrr/statyearbook.git
Set-Location C:\work\statyearbook
git config core.longpaths true
git config core.autocrlf false
Copy-Item .env.example .env
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
Set-Location frontend
npm ci
Set-Location ..
```

PowerShell 창 1에서 백엔드를 실행한다.

```powershell
Set-Location C:\work\statyearbook
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

PowerShell 창 2에서 프론트엔드를 실행한다.

```powershell
Set-Location C:\work\statyearbook\frontend
npm run dev
```

PowerShell 실행 정책 때문에 `Activate.ps1`이 차단되어도 문제없다. 이 문서처럼 `.venv\Scripts\python.exe`를 직접 실행하면 가상환경 활성화가 필요 없다.

확인 명령:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/ready
```

정상 예시:

```text
status
------
ok

status database
------ --------
ready  sqlite
```

화면 주소는 macOS와 같다.

- `http://127.0.0.1:5173`
- `http://127.0.0.1:8000/docs`

### 2.4 종료 방법

백엔드와 프론트엔드를 실행한 각 터미널에서 `Ctrl+C`를 누른다. 터미널 창을 강제로 닫기 전에 가능하면 `Ctrl+C`로 정상 종료한다.

---

## 3. 이 프로젝트는 무엇을 하는가

통계연보 파일과 원천 통계 Excel을 구조화하고, 사람이 반복하던 검수를 자동으로 보조하는 웹 애플리케이션이다.

주요 기능:

1. 화면에서 완성된 `.hwpx`, `.md` 연보를 업로드한다. 백엔드 API/파서는 `.xlsx`도 지원하지만 현재 화면의 파일 선택창에는 노출하지 않는다.
2. 연보 안의 표, 셀, 제목, 단위, 출처 등 메타정보를 DB에 저장한다.
3. 합계, 비율, 증감률, 오탈자, 번역, 메타정보, 이상치, 파란색 표기를 검수한다.
4. 변경되지 않은 표는 이전 검수 결과를 재사용한다.
5. `표정보`, `표항목`, `표데이터` Excel 원장을 이용해 다음 연도 연보 초안을 만든다.
6. 두 연보를 비교해 추가/삭제/변경 표와 셀을 찾는다.
7. 웹에서 인증 후 표 내용을 수정하고 다시 검수한다.
8. 검수 결과 Excel/ZIP 리포트를 내려받는다.

### 반드시 알아야 하는 용어

| 용어 | 쉬운 설명 |
| --- | --- |
| 연보(report) | 한 해의 통계표들을 묶은 문서 스냅샷 |
| 통계표(table) | 연보 안의 표 하나 |
| 셀(cell) | 표의 한 칸 |
| 검수 run | 특정 연보에 대해 검수를 한 번 실행한 기록 |
| 검수 check | 셀/행/표에 대한 개별 판정 결과 |
| 프로파일(profile) | 특정 표에서 어떤 계산과 규칙을 적용할지 정한 설계 |
| 원장 | `표정보`, `표항목`, `표데이터`로 관리되는 원천 통계 데이터 |
| 기준 연보 | 다음 연도 연보를 만들 때 모양과 구조의 기준이 되는 기존 연보 |
| 증분 연보 | 기준 연보에 새 연도 원장 값을 반영해 만든 초안 |
| 언어 후보 | 오탈자나 번역 문제가 있을 가능성이 있어 확인을 기다리는 항목 |
| worker | API와 별개로 대기 작업을 가져가 처리하는 백그라운드 프로세스 |
| migration | 기존 데이터를 보존하면서 DB 구조/데이터를 새 코드에 맞추는 작업 |

---

## 4. 전체 구조와 데이터 흐름

```text
[사용자 브라우저]
       |
       | HTTP/JSON, 파일 업로드
       v
[React + Vite 프론트엔드 :5173]
       |
       | /api 요청
       v
[FastAPI 백엔드 :8000] ----------------------+
       |                                      |
       | 표/검수/작업 기록                     | 선택적 외부 호출
       v                                      v
[SQLite 로컬 또는 PostgreSQL 운영]      [BizRouter/OpenAI]
       |
       | 업로드 원본 위치/작업 상태
       v
[로컬 backend/uploads 또는 S3/R2]
       ^
       |
[선택적 별도 worker]
```

### 완성 연보 업로드 흐름

```text
업로드
  → 원본 파일 보존
  → 파일 형식별 파서 선택
  → 표/셀/메타정보 구조화
  → DB 저장
  → 필요 시 계산/언어 검수
  → 작업 완료 또는 실패 기록
```

### 검수 흐름

```text
검수 항목 선택
  → 기존 결과 재사용 가능 여부 확인
  → 표별 프로파일 준비
  → 계산 검수
  → 언어 후보 생성
  → 사전/캐시 판정
  → 선택 시 LLM 판정
  → 결과 저장 및 화면 하이라이트
```

### 원장 기반 다음 연도 생성 흐름

```text
표정보.xlsx + 표항목.xlsx + 표데이터.xlsx
  → 원장 테이블 적재
  → 기준 연보와 통계 연결
  → 표별 갱신 정책 적용
  → 새 연도 초안 생성
  → 연결 확인/수정
  → 확정 및 검수
```

---

## 5. 폴더와 파일 지도

```text
statyearbook/
├── .env.example                 백엔드 환경변수 예시
├── README.md                    기능·구조 전체 개요
├── Dockerfile                   Railway 백엔드 이미지
├── railway.json                 Railway API 서비스 설정
├── railway.worker.json          Railway worker 서비스 설정
├── vercel.json                  저장소 루트 기준 Vercel 설정
├── backend/
│   ├── requirements.txt         Python 실행 의존성
│   ├── app/
│   │   ├── main.py              FastAPI 시작점, CORS, health/ready
│   │   ├── api/routes.py        대부분의 HTTP API
│   │   ├── application/         API와 서비스 연결
│   │   ├── core/                .env, 설정, 숫자/LLM 공통 코드
│   │   ├── data/                공식 기관명·지역명·번역 사전 데이터
│   │   ├── db/                  DB 연결, 스키마, migration
│   │   ├── domain/              핵심 도메인 모델
│   │   ├── export/              검수 리포트 Excel/ZIP 생성
│   │   ├── ingest/              HWPX/Markdown/Excel 파서
│   │   ├── models/              API 요청/응답 Pydantic 모델
│   │   ├── operations/          운영 지표와 원본 보존 정리
│   │   ├── services/            주요 업무 로직
│   │   ├── storage/             로컬/S3 업로드 원본 저장
│   │   ├── validation/          검수 규칙, 프로파일, 언어 파이프라인
│   │   ├── workflows/           업로드 작업과 worker 오케스트레이션
│   │   └── yearbook_data/       원장 적재와 연보 재현
│   ├── tests/                   Python unittest 테스트
│   └── uploads/                 로컬 업로드 원본; Git 제외
├── frontend/
│   ├── package.json             npm 명령과 프론트 의존성
│   ├── package-lock.json        정확한 npm 설치 버전
│   ├── vite.config.ts           Vite 개발 서버 설정
│   └── src/
│       ├── App.tsx              최상위 화면/라우팅 상태
│       ├── api/reportApi.ts     백엔드 API 호출
│       ├── components/          화면 단위 컴포넌트
│       ├── hooks/               비동기 상태와 업무 흐름
│       ├── styles/global.css    전역 디자인
│       ├── types.ts             프론트 타입 계약
│       └── utils/               다운로드·표시 유틸
├── docs/                        설계·운영·인수인계 문서
├── generated/                   시연/비교/생성 산출물
├── scripts/                     발표자료·검증 산출물 생성 스크립트
└── exports/                     발표자료와 내보내기 결과
```

### DB 테이블을 기능 묶음으로 보는 법

DB 테이블은 `backend/app/db/schema.py`에 정의되어 있다. 테이블이 많으므로 이름을 하나씩 외우지 말고 다음 기능 묶음으로 이해한다.

| 기능 묶음 | 대표 테이블 | 저장 내용 |
| --- | --- | --- |
| 스키마 버전 | `schema_migrations` | 어떤 migration이 적용되었는지 |
| 연보 본문 | `annual_reports`, `stat_tables`, `stat_table_cells` | 연보, 표, 셀, 메타정보 |
| 검수 | `validation_rule_definitions`, `validation_profiles`, `validation_runs`, `validation_checks`, `validation_jobs` | 규칙 정의, 표별 산식, 실행 결과, 진행/중단 작업 |
| 업로드 작업 | `report_processing_jobs`, `report_processing_stages` | 원본 위치, 작업 단계, 재시도, lease |
| 원천 통계 원장 | `statistical_datasets`, `statistical_dataset_versions`, `statistical_dataset_items`, `statistical_values`, 각 revision/lifecycle 테이블 | 표정보·표항목·표데이터와 변경 이력 |
| 증분 연보 | `report_incremental_*`, `generated_report_table_status`, `yearbook_table_recipes`, `yearbook_table_update_policies` | 기준 연보와 증분 M키 연결, 셀 반영, 생성 상태 |
| 연보 비교 | `report_update_*`, `report_comparison_*` | 표/셀의 추가·삭제·변경 결과 |
| 웹 수정 | `yearbook_edit_passwords`, `yearbook_edit_sessions`, `yearbook_manual_edits` | 비밀번호 해시, 인증 토큰 해시, 수정 감사 기록 |
| 언어·LLM | `translation_glossary*`, `linguistic_review_*`, `glossary_audit_results`, `llm_usage_events`, `report_llm_assistance_decisions` | 공식 사전, 언어 후보/캐시, 사용량과 제안 기록 |

`annual_reports`를 삭제하면 외래키 `ON DELETE CASCADE`에 의해 연결된 표·셀·검수 기록 등이 함께 삭제될 수 있다. 유지보수자가 DB에서 직접 `DELETE`하기 전에 `schema.py`의 외래키를 확인해야 하는 이유다.

### 계층별 책임

```text
frontend component
  → frontend hook
  → frontend api/reportApi.ts
  → backend api/routes.py
  → application service
  → domain/service/workflow
  → repository 또는 db adapter
  → SQLite/PostgreSQL 또는 object storage
```

- 화면 컴포넌트는 표시와 사용자 입력에 집중한다.
- hook은 로딩·실패·폴링·선택 상태를 관리한다.
- API 라우터는 HTTP 입력 검증과 오류 코드를 담당한다.
- service/workflow는 실제 업무 규칙과 여러 단계의 순서를 담당한다.
- repository/DB 코드는 SQL과 저장소 차이를 담당한다.

새 기능이 한 계층에만 억지로 들어가면 테스트하기 어려워진다. 예를 들어 라우터 함수 안에 긴 SQL과 검수 계산을 함께 넣지 않는다.

### 기능을 수정할 때 먼저 볼 파일

| 바꾸려는 것 | 먼저 볼 파일 | 함께 확인할 곳 |
| --- | --- | --- |
| 화면 배치/메뉴 | `frontend/src/App.tsx`, `components/` | `styles/global.css` |
| 백엔드 주소/호출 | `frontend/src/api/reportApi.ts` | `frontend/.env.local` |
| 프론트 타입 | `frontend/src/types.ts` | 백엔드 `models/` |
| API 경로 | `backend/app/api/routes.py` | `application/`, `services/` |
| 업로드 처리 | `backend/app/application/imports.py` | `workflows/report_processing.py`, `ingest/` |
| 계산 검수 | `backend/app/validation/` | `services/validation_execution_service.py` |
| 언어/LLM 검수 | `backend/app/validation/language_pipeline/` | `core/llm_client.py` |
| DB 테이블/열 | `backend/app/db/schema.py` | `db/migrations.py`, 관련 repository/service |
| 원장 기반 생성 | `backend/app/yearbook_data/` | `services/ledger_yearbook_service.py` |
| 업로드 원본 저장 | `backend/app/storage/source_storage.py` | `.env`의 storage 변수 |
| 작업 큐/worker | `backend/app/workflows/` | `railway.worker.json` |

---

## 6. 코드, 데이터, 비밀정보를 구분해서 인계하기

### 6.1 Git으로 전달되는 것

- Python/TypeScript 소스 코드
- 테스트 코드와 고정 fixture
- `requirements.txt`, `package.json`, `package-lock.json`
- `.env.example`
- Docker/Railway/Vercel 설정
- Git이 추적하는 문서와 예시 산출물

### 6.2 Git으로 전달되지 않는 것

- `.env`, `.env.local`과 API 키
- `backend/app/db/*.sqlite`와 백업 DB
- `backend/uploads/`
- `.venv/`
- `frontend/node_modules/`
- `frontend/dist/`
- 로그와 캐시

가상환경과 `node_modules`는 운영 데이터가 아니므로 인계하지 않고 새 PC에서 다시 만든다. 반대로 DB와 업로드 원본은 실제 데이터일 수 있으므로 필요 여부를 확인한 뒤 안전하게 인계한다.

### 6.3 권장 인계 묶음

```text
1_source/       Git 저장소 또는 최종 커밋 해시
2_database/     필요한 SQLite DB 백업 + SHA-256
3_uploads/      필요한 업로드 원본 압축 + SHA-256
4_secrets/      비밀관리 도구에서 별도 공유; 일반 압축에 넣지 않음
5_accounts/     서비스명, URL, 권한, 소유자 목록
6_documents/    이 문서와 PPT, 운영 연락망
```

### 6.4 파일 무결성 확인

macOS:

```bash
shasum -a 256 annual_statistics_20260827.sqlite
```

Windows PowerShell:

```powershell
Get-FileHash .\annual_statistics_20260827.sqlite -Algorithm SHA256
```

보내는 사람과 받는 사람의 SHA-256 값이 같아야 파일이 손상되지 않은 것이다.

---

## 7. macOS 상세 설치

### 7.1 도구 설치

#### 터미널 여는 방법

1. 키보드에서 `Command(⌘) + Space`를 누른다.
2. `터미널` 또는 `Terminal`을 입력한다.
3. 검은색 또는 흰색 명령 창이 열리면 아래 명령을 **한 줄 입력하고 Enter**를 누른다.

Git이 없다면 Apple 명령줄 도구를 설치한다.

```bash
xcode-select --install
```

설치 안내 창이 나오면 `설치`를 누르고 완료될 때까지 기다린다. 이미 설치되었다는 메시지가 나오면 정상이다.

컴퓨터에 Homebrew가 이미 있는 개발자는 다음을 사용할 수 있다.

```bash
brew install git python@3.12 node
```

Homebrew를 모르는 사람은 새로 설치할 필요가 없다. 2.1의 공식 링크에서 다음 설치 파일을 받아 화면의 기본 안내대로 설치한다.

- Python: `macOS 64-bit universal2 installer`인 `.pkg`
- Node.js: `24 LTS`, macOS용 `.pkg`

설치가 끝나면 터미널을 닫았다가 다시 열고 확인한다.

설치 확인:

```bash
git --version
python3.12 --version
node --version
npm --version
```

네 줄 모두 버전 번호를 보여야 한다. `python3.12`만 찾지 못하면 Python 설치 폴더의 안내를 확인하고, 다른 Python 버전으로 계속 진행하지 않는다.

### 7.2 저장소 받기

```bash
mkdir -p ~/work
cd ~/work
git clone https://github.com/wtdnrr/statyearbook.git
cd statyearbook
git status
git branch --show-current
git log -1 --oneline
```

인계자가 알려준 브랜치/커밋과 일치하는지 확인한다. 일치하지 않으면 실행 전에 먼저 확인한다.

### 7.3 Python 환경 만들기

```bash
python3.12 -m venv .venv
./.venv/bin/python -m pip install --upgrade pip
./.venv/bin/python -m pip install -r backend/requirements.txt
```

검사:

```bash
./.venv/bin/python --version
./.venv/bin/python -c "import fastapi, openpyxl, psycopg; print('backend dependencies ok')"
```

### 7.4 프론트엔드 환경 만들기

```bash
cd frontend
npm ci
npm run build
cd ..
```

`npm ci`는 `package-lock.json`과 정확히 맞는 버전을 설치한다. 의존성을 의도적으로 바꾸는 작업이 아니라면 `npm install`보다 `npm ci`를 우선한다.

### 7.5 환경변수 파일 만들기

```bash
cp .env.example .env
```

처음에는 아래 핵심값을 유지한다.

```dotenv
DATABASE_BACKEND=sqlite
ANNUAL_STATISTICS_DB_PATH=backend/app/db/annual_statistics_test.sqlite
LLM_REVIEW_ENABLED=0
PROFILE_LLM_ENABLED=0
AUTO_IMPORT_INCLUDE_LLM=0
SOURCE_STORAGE_BACKEND=local
JOB_EXECUTOR_BACKEND=inprocess
```

---

## 8. Windows 상세 설치

### 8.1 도구 설치 시 체크

#### PowerShell 여는 방법

1. 화면 아래 Windows 시작 버튼을 누른다.
2. `PowerShell`을 입력한다.
3. `Windows PowerShell` 또는 `터미널`을 일반 권한으로 연다. 이 설치에는 관리자 PowerShell이 필요하지 않다.

#### Git 설치

1. <https://git-scm.com/install/windows>에서 64-bit Git for Windows 설치 파일을 받는다.
2. 설치 파일을 실행한다.
3. 특별한 조직 지침이 없다면 기본 선택으로 `Next`를 진행한다.
4. PATH 선택 화면에서는 명령줄과 다른 프로그램에서 Git을 사용할 수 있는 권장 옵션을 유지한다.
5. 설치 완료 후 열려 있던 PowerShell을 닫고 새로 연다.

Git for Windows 설치 시:

- 명령줄에서 Git을 사용할 수 있게 PATH 옵션을 켠다.
- 기본 편집기는 익숙한 것을 선택한다.
- 줄바꿈 변환은 이 저장소에서 끌 것이므로 설치 후 저장소 로컬 설정을 적용한다.

#### Python 3.12 설치

1. <https://www.python.org/downloads/release/python-31210/>의 `Windows installer (64-bit)`를 받는다.
2. 설치 파일 첫 화면에서 `Add python.exe to PATH`를 체크한다.
3. `Install Now`를 누른다.
4. 설치가 끝나면 `Disable path length limit`가 보일 경우 조직 정책에 어긋나지 않는 범위에서 선택한다.
5. PowerShell을 닫았다가 다시 연다.

Python 설치 시 확인할 항목:

- `Add Python to PATH`를 체크한다.
- Python Launcher(`py`)를 함께 설치한다.

#### Node.js 설치

1. <https://nodejs.org/en/download>에서 `LTS`로 표시된 24 계열의 Windows Installer를 받는다.
2. 설치 파일을 실행하고 기본 선택으로 진행한다.
3. npm은 Node.js와 함께 설치되므로 별도로 내려받지 않는다.
4. 설치 후 새 PowerShell을 연다.

확인:

```powershell
git --version
py -3.12 --version
node --version
npm --version
```

각 명령 아래에 버전 번호가 나오면 설치가 끝난 것이다. 특히 `py -3.12 --version`은 `Python 3.12.x`, `node --version`은 `v24.x.x`와 비슷하게 보여야 한다.

### 8.2 저장소 받기

```powershell
New-Item -ItemType Directory -Force C:\work | Out-Null
Set-Location C:\work
git -c core.longpaths=true -c core.autocrlf=false clone https://github.com/wtdnrr/statyearbook.git
Set-Location C:\work\statyearbook
git config core.longpaths true
git config core.autocrlf false
git status
git branch --show-current
git log -1 --oneline
```

`core.autocrlf=false`는 Python/TypeScript 파일 전체가 Windows 줄바꿈으로 바뀌어 거대한 가짜 diff가 생기는 일을 줄인다.

### 8.3 Python 환경 만들기

```powershell
Set-Location C:\work\statyearbook
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

검사:

```powershell
& .\.venv\Scripts\python.exe --version
& .\.venv\Scripts\python.exe -c "import fastapi, openpyxl, psycopg; print('backend dependencies ok')"
```

### 8.4 프론트엔드 환경 만들기

```powershell
Set-Location C:\work\statyearbook\frontend
npm ci
npm run build
Set-Location ..
```

### 8.5 환경변수 파일 만들기

```powershell
Copy-Item .env.example .env
notepad .env
```

Windows에서도 `.env` 경로 값에 `/`를 써도 Python이 처리할 수 있다. 다음처럼 그대로 두는 편이 OS 간 공유가 쉽다.

```dotenv
ANNUAL_STATISTICS_DB_PATH=backend/app/db/annual_statistics_test.sqlite
UPLOAD_DIR=backend/uploads
```

### 8.6 PowerShell 실행 정책 오류

오류 예:

```text
Activate.ps1 cannot be loaded because running scripts is disabled
```

해결은 가상환경 활성화를 생략하고 아래처럼 Python 실행 파일을 직접 쓰는 것이다.

```powershell
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload
```

조직 보안정책을 임의로 바꾸기 위해 관리자 PowerShell을 열거나 실행 정책을 전체 해제하지 않는다.

### 8.7 Windows Defender/OneDrive로 느릴 때

- 저장소를 OneDrive 밖의 `C:\work`에 둔다.
- `node_modules`, `.venv`, 대용량 SQLite를 동기화 폴더에 두지 않는다.
- 백신 예외가 필요하면 조직 보안담당자의 승인을 먼저 받는다.
- DB를 네트워크 드라이브에서 직접 열지 않는다. 로컬로 안전하게 복사하고 해시를 확인한다.

---

## 9. 환경변수 완전 설명

백엔드는 저장소 루트의 `.env`를 읽는다. 이미 OS 환경변수로 설정된 값이 있으면 `.env`가 덮어쓰지 않는다. `.env`를 바꾼 뒤에는 백엔드를 재시작한다.

프론트엔드는 `frontend/.env.local` 또는 배포 플랫폼의 `VITE_API_BASE_URL`을 빌드 시 읽는다. 바꾼 뒤에는 Vite를 재시작하거나 다시 배포한다.

### 9.1 데이터베이스

| 변수 | 로컬 권장 | 설명 |
| --- | --- | --- |
| `DATABASE_BACKEND` | `sqlite` | `auto`, `sqlite`, `postgres` 지원 |
| `DATABASE_URL` | 빈 값 | PostgreSQL 연결 문자열; Git/문서에 넣지 않음 |
| `ANNUAL_STATISTICS_DB_PATH` | 테스트 DB 경로 | SQLite 파일 경로 |

동작 규칙:

- `DATABASE_BACKEND=auto`이고 `DATABASE_URL`이 있으면 PostgreSQL을 사용한다.
- `DATABASE_BACKEND=auto`이고 URL이 없으면 SQLite를 사용한다.
- `DATABASE_BACKEND=postgres`인데 URL이 없으면 시작에 실패한다.
- 처음 개발할 때는 명시적으로 `sqlite`를 사용해 운영 DB 오접속을 막는다.

### 9.2 API, 업로드, CORS

| 변수 | 기본/예시 | 설명 |
| --- | --- | --- |
| `UPLOAD_DIR` | `backend/uploads` | 로컬 업로드 원본 폴더 |
| `MAX_UPLOAD_BYTES` | `104857600` | 한 파일 최대 100MB |
| `ALLOWED_ORIGINS` | localhost 목록 | 허용할 프론트엔드 주소, 쉼표 구분 |
| `ALLOWED_ORIGIN_REGEX` | 빈 값 | Preview URL 패턴용; 운영은 정확한 URL 권장 |

### 9.3 작업 실행과 보존

| 변수 | 로컬 권장 | 설명 |
| --- | --- | --- |
| `JOB_EXECUTOR_BACKEND` | `inprocess` | API 내부 처리 또는 별도 `worker` |
| `JOB_LEASE_SECONDS` | `300` | worker 작업 점유 만료 시간 |
| `COMPLETED_SOURCE_RETENTION_DAYS` | `365` | 완료 원본 보존일; `0`은 무기한 |
| `FAILED_SOURCE_RETENTION_DAYS` | `90` | 실패 원본 보존일; `0`은 무기한 |

### 9.4 S3/R2 객체 저장소

| 변수 | 설명 |
| --- | --- |
| `SOURCE_STORAGE_BACKEND` | `local` 또는 `s3`/`r2`/`object` |
| `OBJECT_STORAGE_BUCKET` | 버킷 이름 |
| `OBJECT_STORAGE_ENDPOINT` | S3 호환 endpoint |
| `OBJECT_STORAGE_REGION` | 리전, R2는 보통 `auto` |
| `OBJECT_STORAGE_ACCESS_KEY` | 액세스 키; 비밀 |
| `OBJECT_STORAGE_SECRET_KEY` | 시크릿 키; 비밀 |

API와 worker를 분리하면 두 프로세스가 같은 원본 파일을 봐야 하므로 로컬 폴더가 아니라 공용 S3/R2 또는 공유 볼륨을 사용한다.

### 9.5 LLM

| 변수 | 안전한 초기값 | 설명 |
| --- | --- | --- |
| `LLM_PROVIDER` | `auto` | `auto`, `bizrouter`, `openai` |
| `LLM_REVIEW_ENABLED` | `0` | 언어 후보 LLM 판정 허용 |
| `PROFILE_LLM_ENABLED` | `0` | 새/변경 표 프로파일 보강 |
| `AUTO_IMPORT_INCLUDE_LLM` | `0` | 업로드 때 자동 LLM 실행 여부 |
| `BIZROUTER_API_KEY` | 빈 값 | BizRouter 키 |
| `BIZROUTER_MODEL` | 예시 모델 | BizRouter 모델명 |
| `OPENAI_API_KEY` | 빈 값 | OpenAI 키 |
| `OPENAI_TRANSLATION_MODEL` | 예시 모델 | 번역 검수 모델명 |
| `LLM_REVIEW_BATCH_SIZE` | `10` | 한 요청의 후보 수 |
| `LLM_REVIEW_CONCURRENCY` | `3` | 동시 요청 수 |
| `LLM_REVIEW_LIMIT` | 빈 값 | 한 실행 최대 후보 수 |
| `LLM_REVIEW_TIMEOUT` | `90` | 요청 제한 시간(초) |
| `LLM_REVIEW_SLEEP` | `0.2` | 요청 사이 대기 |
| `LLM_INPUT_COST_PER_MILLION` | `0` | 예상 비용 계산용 입력 단가 |
| `LLM_OUTPUT_COST_PER_MILLION` | `0` | 예상 비용 계산용 출력 단가 |

`LLM_PROVIDER=auto`는 BizRouter 키가 있으면 BizRouter를 우선하고, 없으면 OpenAI를 선택한다. 키만 넣어도 테스트에 영향을 줄 수 있으므로 평소 로컬 `.env`는 기능 플래그를 `0`으로 유지하고, LLM 검수할 때만 명시적으로 켠다.

### 9.6 프론트엔드

`frontend/.env.local`:

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8000
```

로컬에서는 이 파일이 없어도 위 주소가 기본값이다. 값 뒤에 `/api`를 붙이지 않는다. 코드가 각 요청에 `/api/...`를 붙인다.

---

## 10. 매일 실행하는 절차

### 10.1 시작 전

```text
1. 저장소 루트인지 확인한다.
2. git status로 내 변경과 다른 사람 변경을 확인한다.
3. .env가 테스트 DB인지 운영 DB인지 확인한다.
4. 실제 DB를 쓸 경우 백업 시각을 확인한다.
5. 백엔드와 프론트엔드를 별도 터미널에서 실행한다.
6. /ready와 브라우저를 확인한다.
```

macOS:

```bash
cd ~/work/statyearbook
git status
./.venv/bin/python -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

Windows:

```powershell
Set-Location C:\work\statyearbook
git status
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

두 번째 터미널 공통:

```text
저장소/frontend로 이동
npm run dev
```

### 10.2 정상 여부 판단

- 백엔드 터미널에 `Uvicorn running on http://127.0.0.1:8000`이 보인다.
- `/health`는 `{"status":"ok"}`를 반환한다.
- `/ready`는 `status=ready`, `database=sqlite` 또는 `postgres`를 반환한다.
- 프론트 화면이 열리고 브라우저 콘솔에 CORS/fetch 오류가 없다.
- 연보 데이터가 없다면 화면이 비어 있을 수 있다. 이것은 빈 DB에서는 정상이다.

### 10.3 종료 전

- 처리 중인 업로드/검수가 없는지 확인한다.
- 각 터미널에서 `Ctrl+C`로 종료한다.
- 코드 변경이 있다면 테스트하고 `git status`를 확인한다.
- 실제 데이터를 변경했다면 백업/변경 기록을 남긴다.

---

## 11. 화면 사용 방법

### 11.1 완성 연보 업로드

1. 프론트 화면을 연다.
2. 상단 `연보 등록`을 누른다.
3. `전체 연보 업로드`를 선택한다.
4. 화면에서 `.hwpx`, `.md` 중 하나를 선택한다. `.xlsx` 완성 연보는 현재 화면이 아니라 API 수준에서만 지원하므로 개발자 확인 없이 사용하지 않는다.
5. 연도와 제목을 확인한다.
6. 처음에는 LLM 자동 실행 옵션을 끈다.
7. 업로드를 시작한다.
8. 화면이 작업 ID를 받아 상태를 주기적으로 확인한다.
9. 완료 후 생성된 연보가 자동 선택되는지 확인한다.
10. 실패하면 오류 메시지와 백엔드 로그를 함께 보관한다.

주의:

- 기본 최대 크기는 100MB다.
- 같은 파일/연도/제목/옵션은 해시로 기존 작업을 재사용할 수 있다.
- 원본 파일을 임의로 이름만 바꿔 재업로드하면 중복 데이터가 생길 수 있다.
- HWP가 아니라 HWPX를 지원한다. `.hwp`는 먼저 `.hwpx`로 변환해야 한다.

### 11.2 검수 실행

1. 대상 연보를 선택한다.
2. `검수 진행`을 연다.
3. 화면에 표시되는 합계/비율/오탈자/번역/메타정보/이상치/파란색 표기 중 필요한 항목을 선택한다. 증감률·증감액 산식은 엔진 내부에서 검수되며, 현재 화면에서는 증감률 결과가 `비율 검수`, 증감액 결과가 `합계 검수` 범주에 합쳐져 보인다.
4. 이전 결과 재사용 여부와 원본 run을 확인한다.
5. 합계·비율을 선택했을 때만 `합계·비율 프로파일 LLM 보조`를 사용할 수 있다. 새 표의 산식 초안 보강이 필요한 경우에만 켠다.
6. 오탈자·번역을 선택했을 때만 `오탈자·번역 LLM 검수`를 사용할 수 있다. 언어 후보를 외부 모델로 보내도 되는지와 비용 승인을 먼저 확인한다.
7. 비용 또는 외부 전송 승인을 받지 않았다면 두 LLM 옵션을 모두 끈다.
8. 실행하면 현재 단계, 완료 단위, 전체 단위, 백분율이 표시되는지 확인한다.
9. 중단해야 하면 `중단하고 저장`을 누른다. 즉시 강제 종료하는 방식이 아니라 현재 작업이 안전한 중단 지점에 도달하면 멈추며, 중단 시점까지 완료된 결과는 저장된다.
10. 결과에서 `오류 의심`과 `확인 필요`를 우선 본다.
11. 상세 표에서 대상/관련/헤더 셀 하이라이트와 판정 근거를 확인한다.
12. 수정한 표는 다시 검수한다.

상태 의미:

| 상태 | 의미 | 해야 할 일 |
| --- | --- | --- |
| 정상 | 규칙상 문제가 발견되지 않음 | 표본 확인 후 통과 |
| 확인 필요 | 자동 판단이 애매함 | 담당자가 원문/원장을 확인 |
| 오류 의심 | 계산/번역 등 불일치 가능성이 큼 | 근거를 확인하고 수정 또는 예외 처리 |
| 대기 | 주로 언어 후보 판정 전 | 사전/수동/LLM 판정 수행 |

### 11.3 원장 Excel 3종으로 새 연도 만들기

1. 기준 연보가 DB에 있는지 확인한다.
2. 원천 시스템에서 같은 배치의 `표정보`, `표항목`, `표데이터`를 준비한다.
3. 파일명만 보지 말고 대상 연도와 추출 시각을 기록한다.
4. 상단 `연보 등록`에서 `증분 업로드`를 선택한다.
5. 기준 연보, 대상 연도, 제목을 정확히 선택한다.
6. Excel 세 파일을 각각 맞는 칸에 올린다.
7. 생성된 증분 초안이 자동 선택되면 상태 요약에서 자동 반영 표와 확인 필요 표의 수를 본다.
8. `확인 필요` 표를 열어 자동 연결 근거, 추천 M키, 적용 예정 셀을 확인한다.
9. 추천 연결이 맞으면 추천 후보를 누르고 미리보기 확인창에서 반영한다. 직접 키를 아는 경우 상세 화면의 `연결 키 입력`을 사용한다.
10. 호환되지 않는 연결은 값을 강제로 넣지 않고 연결 확인 상태로 남길 수 있다. 원장 담당자와 표 구조를 먼저 확인한다.
11. 신규 통계 추가, 기존값 유지, 이번 연보 제외가 필요한 경우 업무 담당자의 결정을 기록한 뒤 처리한다.
12. 모든 확인 대상을 처리한 다음 요약 영역의 `연보 확정`을 누른다.
13. 확정된 연보에서 필요한 검수를 새로 실행한다. 초안 생성 상태와 최종 검수 상태를 혼동하지 않는다.

### 11.4 연보 비교

1. 비교 기준과 비교 대상을 연도만으로 고르지 말고 제목/ID까지 확인한다.
2. 추가, 삭제, 변경 표 수를 본다.
3. 변경 셀 목록에서 데이터 변경인지 파싱 차이인지 구분한다.
4. 비교 결과는 “오류 판정”이 아니라 “차이 목록”임을 기억한다.

### 11.5 웹 수정

1. 연보/통계표의 수정 비밀번호 정책을 확인한다.
2. 표 상세 화면의 `수정`을 누르고 해당 통계의 비밀번호로 인증한다.
3. 제목·영문 제목·단위·기준일·출처·담당 부서·담당자·내선과 표 셀을 수정할 수 있다.
4. 표 번호와 장/절 계층을 바꿀 때 다른 표 번호와 중복되지 않는지 확인한다.
5. 표 구조를 복제해 새 통계를 만들거나 허가된 통계를 삭제할 수 있으므로 대상 연보와 표를 다시 확인한다.
6. 저장 후 표 목록과 상세 화면에서 변경값을 다시 읽어 본다.
7. 수정 후 기존 검수 결과는 오래된 결과가 될 수 있으므로 다시 검수한다.
8. 비밀번호를 분실하면 DB를 직접 수정하기 전에 담당자와 복구 절차를 합의한다.

### 11.6 통계 연보 목록과 표 상세 보기

1. 상단 `통계 연보` 메뉴를 누른다.
2. 왼쪽 위 연보 선택 상자에서 **연도뿐 아니라 제목과 표 개수**까지 보고 대상을 고른다.
3. 상태 카드의 `전체 표`, `정상`, `확인 필요`, `오류 의심`을 눌러 목록을 좁힌다. 아직 검수하지 않은 연보나 증분 초안은 카드 이름과 개수가 다르게 표시될 수 있다.
4. 검색창에서 표명 또는 표 코드를 입력한다.
5. 필터의 `검수 항목`은 정상 여부와 관계없이 표시할 검수 내역이 있는 표를 찾을 때 사용한다.
6. 표를 한 번 누르면 미리보기가 바뀌고, 두 번 누르거나 `상세 보기`를 누르면 상세 화면으로 이동한다.
7. 상세 화면에서는 하위 표 탭, 헤더 고정, 검수 결과, 메타정보, 하이라이트 대상 셀을 확인한다.
8. 검수 결과 한 건을 선택하면 관련 셀로 이동하고 산식에 사용된 셀과 헤더가 함께 강조되는지 확인한다.
9. `정상`은 자동 규칙에서 문제를 찾지 못했다는 의미이지 원자료가 절대적으로 정확하다는 보증이 아니다. 중요 표는 표본 대조한다.

### 11.7 다운로드

#### 표 하나 내려받기

1. 표 상세 화면 오른쪽 위 `다운로드`를 누른다.
2. 다른 프로그램에서 단순히 열려면 `CSV`, 셀 구조를 유지하려면 `XLSX`를 선택한다.
3. 파일을 열어 한글, 숫자, 헤더, 행 수가 화면과 같은지 확인한다.

#### 연보 내려받기

1. 연보 요약 영역의 `연보 다운`을 누른다.
2. 전체 표 또는 필요한 표 번호만 선택한다.
3. `연보 다운`을 누르고 진행 수/전체 수가 끝날 때까지 브라우저 탭을 닫지 않는다.
4. 이 파일은 브라우저가 각 표를 조회해 만드는 XLSX이므로 연보가 크면 시간이 걸린다.

#### 검수 리포트 내려받기

1. 검수가 있는 연보에서 `검수 리포트`를 누른다.
2. 대상 상태에서 `오류 의심`, `확인 필요` 중 하나 이상을 선택한다.
3. 포함 파일에서 `검수 내역`, `하이라이트 표`, `메타데이터` 중 하나 이상을 선택한다.
4. `리포트 다운로드`를 누르면 선택한 Excel 파일이 ZIP으로 내려온다.
5. ZIP을 풀고 검수 인덱스의 표 번호와 하이라이트 파일의 셀 위치가 일치하는지 표본 확인한다.

### 11.8 통계 원장 조회

1. 상단 `통계 원장` 메뉴를 누른다.
2. 요약에서 전체 통계 수, 값이 있는 통계 수, 원장 셀 수, 수록 기간을 확인한다.
3. 왼쪽 검색창에서 통계명, 표 ID, 부서를 검색한다.
4. 통계를 선택하고 오른쪽 위 기준시점을 바꾸어 시점별 행을 조회한다.
5. 이 화면은 연보 표가 아니라 `표정보·표항목·표데이터`에서 적재한 원천 통계 조회 화면이다. 연보 화면의 값과 다르면 기준시점, 갱신 정책, 연결 M키를 함께 확인한다.
6. 빈 화면이면 먼저 증분 업로드가 있었는지와 DB가 올바른지 확인한다. 현재 화면에는 원장 파일만 독립적으로 가져오는 버튼이 노출되어 있지 않다.

### 11.9 수정 권한 관리

1. 상단 `수정 권한` 메뉴를 누른다.
2. 대상 연보를 선택한다.
3. 표 번호, 제목, 담당자를 검색한다.
4. 통계별로 현재 비밀번호를 입력하고 새 비밀번호를 설정한다.
5. 초기 비밀번호는 담당 주무관 내선번호 마지막 네 자리이며 번호가 없으면 `0000`이다. 운영 시작 전에 반드시 변경한다.
6. 비밀번호를 바꾸면 그 통계의 기존 수정 세션은 폐기된다.
7. 비밀번호 값은 문서, 메신저, 코드, 이슈에 기록하지 않는다. 승인된 비밀관리 방법으로 전달한다.

### 11.10 연보 삭제

1. 삭제 전 대상 연보의 ID, 제목, 연도, 표 개수를 기록하고 필요한 DB/원본 백업을 만든다.
2. 연보 요약의 `연보 삭제`를 누른다.
3. 확인창에서 표 개수와 함께 검수 결과도 삭제된다는 경고를 다시 읽는다.
4. 삭제는 화면에서 되돌릴 수 없다. 잘못 삭제했으면 새 업로드로 해결하려 하지 말고 백업 복원 여부를 먼저 결정한다.
5. 테스트 연보에는 삭제 버튼이 보이지 않을 수 있으며, 운영 데이터 삭제를 DB 명령으로 우회하지 않는다.

---

## 12. 코드를 수정하는 표준 절차

### 12.1 작업 시작

```text
1. 요구사항을 한 문장으로 쓴다.
2. 재현 방법과 기대 결과를 쓴다.
3. 새 브랜치를 만든다.
4. 수정 전 관련 테스트를 실행한다.
5. 작은 단위로 수정한다.
6. 관련 테스트 → 전체 테스트 → 프론트 빌드 순으로 확인한다.
7. DB/환경변수/배포 영향과 롤백 방법을 기록한다.
8. 비밀값과 대용량 데이터가 Git에 들어가지 않았는지 확인한다.
```

브랜치 예:

```bash
git switch -c fix/validation-filter
```

PowerShell에서도 Git 명령은 같다.

### 12.2 프론트 화면 변경

일반적인 흐름:

```text
types.ts에서 데이터 모양 확인
  → api/reportApi.ts에서 요청/응답 확인
  → hooks에서 상태 흐름 확인
  → components에서 화면 변경
  → global.css에서 스타일 변경
  → 같은 이름의 .test.tsx 또는 새 테스트 추가
```

검증:

```bash
cd frontend
npm run test
npm run build
```

Windows:

```powershell
Set-Location frontend
npm run test
npm run build
```

### 12.3 API/백엔드 업무 로직 변경

일반적인 흐름:

```text
models의 요청/응답 계약 확인
  → api/routes.py에서 HTTP 경계 확인
  → application에서 유스케이스 확인
  → services에서 업무 규칙 변경
  → repository/db 접근 확인
  → backend/tests에 회귀 테스트 추가
```

라우터에 모든 로직을 넣지 않는다. HTTP 입력 검증과 오류 변환은 라우터, 실제 업무 규칙은 service/application 계층에 둔다.

### 12.4 DB 스키마 변경

DB 변경은 가장 조심해야 한다.

1. `backend/app/db/schema.py`에서 새 설치용 스키마를 수정한다.
2. 기존 DB가 새 구조로 이동할 수 있도록 `backend/app/db/migrations.py`와 필요한 migration 함수를 수정한다.
3. 같은 migration이 두 번 실행되어도 안전한지 확인한다.
4. 새 SQLite 파일에서 테스트한다.
5. 기존 DB 복사본에서 migration을 테스트한다.
6. PostgreSQL 테스트 DB에서도 확인한다.
7. 운영 적용 전 백업과 롤백 계획을 만든다.

주의: 앱 시작 시 `initialize_default_database()`가 schema와 data migration을 실행한다. 운영 DB를 예전 코드로 되돌려도 이미 적용된 DB 변경이 자동으로 취소되지는 않는다.

### 12.5 새 환경변수 추가

다음을 모두 바꿔야 한다.

- 설정을 읽는 Python/TypeScript 코드
- `.env.example` 또는 `frontend/.env.example`
- 이 인수인계 문서의 환경변수 표
- Railway/Vercel 변수
- 기본값과 비활성 상태 테스트
- 비밀값 여부와 로그 마스킹 확인

### 12.6 의존성 변경

Python:

1. `backend/requirements.txt`를 수정한다.
2. 새 가상환경에서 설치한다.
3. Docker 빌드 가능성을 확인한다.

Frontend:

1. `npm install 패키지명`으로 `package.json`과 `package-lock.json`을 함께 갱신한다.
2. `npm ci`, 테스트, 빌드를 새 폴더/CI 환경에서 확인한다.
3. `node_modules`는 커밋하지 않는다.

### 12.7 새 기능을 처음부터 끝까지 추가하는 절차

예를 들어 “표에 담당자 검토 완료 표시를 추가한다”는 기능을 만든다고 가정한다.

1. 사용자 행동, 입력, 기대 화면, 저장해야 할 값, 권한을 먼저 문장으로 정한다.
2. DB 저장이 필요하면 `schema.py`와 `migrations.py`를 설계하고 새 DB·기존 DB 양쪽 테스트를 쓴다.
3. 백엔드 `models/`에 요청/응답 계약을 만든다.
4. `services/`에 검토 완료 처리 규칙을 구현한다. 라우터는 서비스를 호출하고 HTTP 오류로 변환한다.
5. `api/routes.py`에 엔드포인트를 추가하고 성공, 잘못된 입력, 없는 대상, 권한 실패 테스트를 만든다.
6. 프런트 `types.ts`에 백엔드와 같은 데이터 모양을 추가한다.
7. `api/reportApi.ts`에 호출 함수를 만들고 hook에서 loading/success/error 상태를 관리한다.
8. `components/`에 화면을 추가하고 키보드 조작, 빈 상태, 처리 중 중복 클릭 방지를 확인한다.
9. 관련 프런트 테스트와 백엔드 테스트를 먼저 통과시킨다.
10. 백엔드 전체 테스트, 프런트 전체 테스트, production build를 실행한다.
11. 새 환경변수·migration·배포 순서·롤백 방법·운영 권한이 필요한지 PR에 기록한다.
12. 빈 테스트 DB와 기존 DB 복사본에서 브라우저로 처음부터 끝까지 한 번 사용한다.

API 응답을 바꿀 때 백엔드 Pydantic 모델과 프런트 TypeScript 타입을 함께 수정하지 않으면 화면은 빌드되더라도 실행 중 데이터가 비거나 오류가 날 수 있다. 기존 필드를 삭제/이름 변경하기보다 먼저 새 필드를 추가하고 양쪽 배포가 끝난 뒤 구 필드를 제거하는 순서를 권장한다.

---

## 13. 테스트와 현재 기준선

### 13.1 백엔드 전체 테스트

macOS, 저장소 루트:

```bash
PYTHONPATH=backend ./.venv/bin/python -m unittest discover -s backend/tests -q
```

Windows PowerShell, 저장소 루트:

```powershell
$env:PYTHONPATH = "backend"
& .\.venv\Scripts\python.exe -m unittest discover -s backend\tests -q
Remove-Item Env:PYTHONPATH
```

특정 파일만 실행하는 예:

macOS:

```bash
PYTHONPATH=backend ./.venv/bin/python -m unittest discover -s backend/tests -p 'test_application_services.py' -q
```

Windows:

```powershell
$env:PYTHONPATH = "backend"
& .\.venv\Scripts\python.exe -m unittest discover -s backend\tests -p "test_application_services.py" -q
Remove-Item Env:PYTHONPATH
```

### 13.2 프론트엔드 테스트와 빌드

```text
frontend 폴더에서:
npm run test
npm run build
```

### 13.3 PostgreSQL 통합 테스트

`backend/tests/test_postgres_integration.py`는 `TEST_DATABASE_URL`이 있을 때만 실행된다. 반드시 운영 DB가 아닌 **삭제 가능한 전용 테스트 DB**를 사용한다.

macOS 예:

```bash
TEST_DATABASE_URL='postgresql://...' PYTHONPATH=backend ./.venv/bin/python -m unittest backend/tests/test_postgres_integration.py -q
```

Windows 예:

```powershell
$env:TEST_DATABASE_URL = "postgresql://..."
$env:PYTHONPATH = "backend"
& .\.venv\Scripts\python.exe -m unittest backend\tests\test_postgres_integration.py -q
Remove-Item Env:TEST_DATABASE_URL
Remove-Item Env:PYTHONPATH
```

### 13.4 2026-08-28 실제 점검 결과

현재 작업 트리에서 확인한 결과:

| 검사 | 결과 |
| --- | --- |
| `npm run test` | 9개 파일, 49개 테스트 모두 통과 |
| `npm run build` | TypeScript 검사와 Vite production build 성공 |
| 빈 SQLite 백엔드 기동 | Uvicorn 시작 성공, `/health`와 `/ready` 성공, `database=sqlite` 확인 |
| 백엔드 전체 unittest | 397개 실행, 6 failures, 2 skipped |

백엔드 실패 분류:

1. `test_profile_preflight_keeps_uncertain_profiles_in_review_without_llm` 1건: 루트 `.env`의 LLM 사용 가능 상태가 “LLM 없음”을 가정한 테스트에 영향을 준 것으로 보인다. 테스트에서 환경을 완전히 격리해야 한다.
2. `test_validation_baseline` 관련 5건: 로컬 2025 대표 표의 검수 결과가 snapshot과 다르고 2026 연보 제목도 기대값과 달랐다. 소스 로직 문제인지, 로컬 DB/검수 run이 바뀐 것인지 기준선을 다시 합의해야 한다.
3. PostgreSQL 전용 테스트 2건은 `TEST_DATABASE_URL`이 없어 skip된 상태다.

**이 상태를 “전체 테스트 통과”라고 인계하면 안 된다.** 인계 전 다음 중 하나를 해야 한다.

- 현재 DB가 정답이면 승인 후 baseline fixture를 의도적으로 갱신한다.
- 기존 fixture가 정답이면 로컬 DB/검수 run을 복원한다.
- LLM 테스트가 `.env`에 의존하지 않도록 테스트 환경을 격리한다.
- 전용 PostgreSQL에서 통합 테스트를 별도로 실행한다.

기준선 변경은 단순히 테스트를 통과시키기 위한 작업이 아니다. 실제 검수 담당자가 결과를 확인하고 승인한 뒤 반영해야 한다.

---

## 14. 데이터베이스와 백업

### 14.1 SQLite를 쓸 때

- 개인 개발과 단일 프로세스 로컬 실행에 적합하다.
- 파일 하나처럼 보이지만 서버 실행 중 복사하면 일관성이 깨질 수 있으므로 먼저 백엔드를 종료한다.
- 실제 DB와 테스트 DB의 경로를 `.env`에서 명확히 나눈다.
- 대용량 DB를 Git에 추가하지 않는다.

macOS 수동 백업 예:

```bash
cp -p backend/app/db/annual_statistics.sqlite backend/app/db/annual_statistics_20260827_before_change.sqlite
shasum -a 256 backend/app/db/annual_statistics_20260827_before_change.sqlite
```

Windows 수동 백업 예:

```powershell
Copy-Item backend\app\db\annual_statistics.sqlite backend\app\db\annual_statistics_20260827_before_change.sqlite
Get-FileHash backend\app\db\annual_statistics_20260827_before_change.sqlite -Algorithm SHA256
```

백업 파일도 저장소 안에 오래 두지 말고 승인된 백업 위치로 옮긴다.

### 14.2 기존 DB를 보존한 테스트 DB 만들기

대상 파일이 이미 있으면 보호를 위해 덮어쓰지 않는다.

macOS:

```bash
PYTHONPATH=backend ./.venv/bin/python -m app.db.prepare_test_database \
  --source backend/app/db/annual_statistics.sqlite \
  --destination backend/app/db/annual_statistics_test_new.sqlite
```

Windows:

```powershell
$env:PYTHONPATH = "backend"
& .\.venv\Scripts\python.exe -m app.db.prepare_test_database `
  --source backend\app\db\annual_statistics.sqlite `
  --destination backend\app\db\annual_statistics_test_new.sqlite
Remove-Item Env:PYTHONPATH
```

### 14.3 migration만 실행

macOS:

```bash
PYTHONPATH=backend ./.venv/bin/python -m app.db.migrate
```

Windows:

```powershell
$env:PYTHONPATH = "backend"
& .\.venv\Scripts\python.exe -m app.db.migrate
Remove-Item Env:PYTHONPATH
```

### 14.4 PostgreSQL을 쓸 때

- 운영 배포에서는 Railway PostgreSQL을 기준으로 한다.
- `DATABASE_BACKEND=postgres`와 `DATABASE_URL`이 모두 필요하다.
- 연결 문자열을 채팅, 이슈, 문서, 화면 캡처에 노출하지 않는다.
- Railway의 백업 기능과 필요하면 Point-in-Time Recovery를 사용한다.
- 복원 연습은 운영 DB를 덮어쓰지 말고 별도 복원 서비스에서 한다.

SQLite의 특정 연보/run을 PostgreSQL로 복사하는 도구가 있다.

```text
python -m app.db.copy_report_to_postgres --report-id <ID> --dry-run
```

먼저 `--dry-run` 결과를 확인한다. 실제 실행 전 대상 PostgreSQL 백업과 ID 충돌을 점검한다.

### 14.5 DB와 업로드 원본의 관계

DB에는 업로드 원본 위치와 작업 이력이 저장된다. DB만 받고 `backend/uploads`를 받지 않으면 과거 작업 재시도나 원본 재처리가 실패할 수 있다. 반대로 업로드 폴더만 있고 DB가 없으면 어떤 작업의 원본인지 알기 어렵다. 둘을 같은 시점의 세트로 백업한다.

---

## 15. worker와 원본 저장소

### 15.1 로컬 개발

```dotenv
JOB_EXECUTOR_BACKEND=inprocess
SOURCE_STORAGE_BACKEND=local
```

API 프로세스가 백그라운드 작업을 실행하므로 별도 worker가 필요 없다.

### 15.2 별도 worker

API `.env`:

```dotenv
JOB_EXECUTOR_BACKEND=worker
SOURCE_STORAGE_BACKEND=s3
```

worker 시작:

macOS:

```bash
PYTHONPATH=backend ./.venv/bin/python -m app.workflows.report_worker
```

Windows:

```powershell
$env:PYTHONPATH = "backend"
& .\.venv\Scripts\python.exe -m app.workflows.report_worker
Remove-Item Env:PYTHONPATH
```

한 번만 poll하려면 `--once`, 주기를 바꾸려면 `--poll-seconds 2`를 사용한다.

### 15.3 worker 장애 판단

- 업로드 작업이 계속 `queued`: worker가 없거나 DB가 다를 가능성
- `running`에서 멈춤: worker 종료, lease, 원본 접근, 외부 LLM timeout 확인
- API는 정상인데 worker만 실패: 두 서비스의 Git 커밋, `DATABASE_URL`, storage 변수를 비교
- 로컬 storage + 분리 worker: 서로 다른 파일시스템이면 원본을 찾을 수 없음

---

## 16. 배포 절차

현재 권장 운영 구조:

```text
Vercel frontend
   → Railway API
       → Railway PostgreSQL
       → S3/R2
   ← Railway worker (같은 DB와 S3/R2 사용)
```

### 16.1 배포 전 체크

- [ ] 배포할 커밋 해시가 승인되었다.
- [ ] 프론트 테스트와 빌드가 성공했다.
- [ ] 백엔드 테스트 실패가 새 회귀인지 기존 기준선 문제인지 분류했다.
- [ ] DB migration을 복사본/테스트 DB에서 실행했다.
- [ ] PostgreSQL 백업을 확인했다.
- [ ] 새 환경변수가 배포 플랫폼에 등록되었다.
- [ ] CORS에 정확한 Vercel 운영 URL이 있다.
- [ ] LLM 비용/키 사용이 승인되었다.
- [ ] 롤백할 이전 배포와 담당자가 정해졌다.

### 16.2 Railway API

- Config file: `/railway.json`
- Dockerfile: `/Dockerfile`
- pre-deploy: `python -m app.db.migrate`
- start: Dockerfile의 Uvicorn 명령
- healthcheck: `/ready`

필수 예:

```dotenv
DATABASE_BACKEND=postgres
DATABASE_URL=${{Postgres.DATABASE_URL}}
UPLOAD_DIR=/data/uploads
ALLOWED_ORIGINS=https://실제-vercel-주소
AUTO_IMPORT_INCLUDE_LLM=0
PROFILE_LLM_ENABLED=0
JOB_EXECUTOR_BACKEND=worker
SOURCE_STORAGE_BACKEND=s3
```

### 16.3 Railway worker

- Config file: `/railway.worker.json`
- start: `python -m app.workflows.report_worker`
- 공개 네트워크 불필요
- API와 같은 커밋, `DATABASE_URL`, S3/R2 변수를 사용

### 16.4 Vercel 프론트엔드

저장소 루트를 프로젝트 Root Directory로 사용하면 루트 `vercel.json`이 `frontend`에서 설치/빌드하도록 설정되어 있다.

필수 변수:

```dotenv
VITE_API_BASE_URL=https://실제-railway-api-주소
```

주의:

- 주소 뒤에 `/api`를 붙이지 않는다.
- 변수를 바꾼 뒤 새 Production Deployment가 필요하다.
- Preview와 Production 환경변수를 구분한다.

### 16.5 배포 후 점검 순서

1. Railway API 배포 로그에서 migration 성공 확인
2. `https://API주소/health` 확인
3. `https://API주소/ready`에서 `database=postgres` 확인
4. worker 로그에서 poll/claim 오류가 없는지 확인
5. Vercel 화면에서 목록/상세 확인
6. 작은 테스트 파일 업로드
7. import → calculation → language 단계 완료 확인
8. 검수 결과 하이라이트와 다운로드 확인
9. `/api/operations/metrics?window_days=30` 확인
10. 운영 로그에 API 키/DB URL/개인정보가 노출되지 않았는지 확인

### 16.6 롤백

1. 추가 업로드/검수를 잠시 중단한다.
2. 실패 시각, 배포 ID, 커밋, migration 상태를 기록한다.
3. 코드만 문제이고 DB 변경이 호환되면 이전 Railway/Vercel 배포로 되돌린다.
4. DB가 변경되었다면 임의로 파일/테이블을 삭제하지 말고 백업 복원 여부를 결정한다.
5. 복원은 가능하면 별도 서비스에서 검증 후 진행한다.
6. API `/ready`, 대표 연보, 업로드, 검수를 다시 확인한다.

---

## 17. 운영, 보안, 비용

### 운영 공개 전 반드시 확인할 인증 한계

현재 애플리케이션에는 서비스 전체를 보호하는 사용자 로그인, 조직 계정 연동, 역할 기반 권한 관리가 없다. 읽기·업로드·연보 삭제·검수 실행·다운로드·운영 지표 API도 애플리케이션 수준의 공통 로그인을 요구하지 않는다. `ALLOWED_ORIGINS`는 브라우저 CORS 설정일 뿐 인증이나 방화벽이 아니다.

표 수정 기능에만 통계표별 비밀번호와 Bearer 세션이 있다. 구현상 초기 비밀번호는 담당자 내선번호의 마지막 4자리이며, 내선번호를 찾지 못하면 `0000`이 된다. 비밀번호 해시는 PBKDF2-SHA256으로 저장되지만, 현재 수정 세션은 명시적인 유효기간 검사가 없고 비밀번호 변경 시 해당 표의 세션이 폐기된다.

따라서 기관 내부 자료를 운영 배포하기 전에는 다음을 완료한다.

- Railway API를 아무나 접근할 수 있는 공개 데이터 변경 API로 방치하지 않는다. 조직의 접근 제어 프록시, VPN, SSO/API gateway 등 승인된 보호 수단을 적용한다.
- 최초 배포 직후 모든 초기 수정 비밀번호를 변경하고 `0000`인 표가 없는지 확인한다.
- 서비스 전체 인증, 역할별 권한, 세션 만료가 요구사항이면 기능 개발 항목으로 별도 등록한다.
- 프런트 주소를 정확히 제한하되 CORS만으로 보안이 끝났다고 판단하지 않는다.
- 브라우저 Bearer token, 초기 비밀번호, DB의 해시·salt를 로그/화면 캡처/이슈에 남기지 않는다.
- 삭제·업로드·검수 API를 외부 자동화에서 사용할 때 호출 주체와 변경 이력을 별도로 기록한다.

### 17.1 절대 커밋하지 말 것

- `.env`, `frontend/.env.local`
- `DATABASE_URL`
- BizRouter/OpenAI/S3/R2 키
- 실데이터 SQLite DB
- 업로드 원본과 개인정보/기관 내부자료
- 편집 비밀번호나 세션 token

커밋 전:

```bash
git status --short
git diff --check
git diff -- .env
```

`.env`가 Git에 보이면 즉시 커밋하지 말고 원인을 확인한다. 이미 공개 저장소에 올라간 키는 파일만 지우는 것으로 끝나지 않으며 키를 폐기하고 재발급해야 한다.

### 17.2 최소 권한

- 개발자는 필요한 서비스만 접근한다.
- 운영 DB 쓰기 권한과 백업 복원 권한을 분리할 수 있으면 분리한다.
- API 키는 개인 키가 아니라 프로젝트 전용 키를 사용한다.
- 퇴사/이동 시 계정을 비활성화하고 키를 회전한다.

### 17.3 LLM 비용

- 기본은 비활성화한다.
- 후보 수와 `LLM_REVIEW_LIMIT`을 먼저 확인한다.
- 운영 지표의 비용은 설정 단가로 계산한 예상값이며 실제 청구액과 다를 수 있다.
- 개인정보/비공개 통계가 외부 모델로 전송 가능한지 정책을 확인한다.
- 모델이나 공급자를 바꾸면 정확도 기준선을 다시 검토한다.

### 17.4 원본 보존 정리

삭제 후보만 확인:

```text
python -m app.operations.maintenance --prune-sources
```

실제 삭제:

```text
python -m app.operations.maintenance --prune-sources --apply
```

`--apply`는 되돌리기 어려운 삭제다. 백업, 보존기간, 대상 목록을 확인한 뒤 실행한다.

---

## 18. 자주 생기는 문제와 해결

### 18.1 `python`, `py`, `python3.12`를 찾을 수 없음

원인: Python 미설치 또는 PATH 미반영.

해결:

1. Python 3.12 설치 여부를 확인한다.
2. Windows는 새 PowerShell에서 `py -0p`로 설치 목록을 본다.
3. macOS는 `which python3.12`를 확인한다.
4. 가상환경을 다시 만든다.

### 18.2 `No module named app`

원인: 잘못된 폴더/명령으로 백엔드를 실행했다.

해결: 저장소 루트에서 `--app-dir backend`를 포함해 실행한다.

### 18.3 `No module named fastapi` 또는 `openpyxl`

원인: 시스템 Python을 쓰거나 requirements 설치가 안 됨.

해결: `.venv` 안의 Python 경로를 직접 사용해 다시 설치한다.

### 18.4 `npm`을 찾을 수 없음

원인: Node.js 미설치 또는 설치 직후 PATH 미반영.

해결: Node.js 설치 후 PowerShell/터미널을 새로 연다.

### 18.5 `EBADENGINE` 또는 Vite Node 버전 오류

원인: Node 버전이 Vite 8 요구 범위 밖.

해결: 권장 Node 24 LTS를 설치하고 `node --version`을 확인한 뒤 `frontend/node_modules`를 새로 설치한다. 기존 `node_modules`를 다른 OS에서 복사해 쓰지 않는다.

### 18.6 포트 8000 또는 5173이 이미 사용 중

macOS 확인:

```bash
lsof -i :8000
lsof -i :5173
```

Windows 확인:

```powershell
Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
Get-NetTCPConnection -LocalPort 5173 -ErrorAction SilentlyContinue
```

기존 프로세스가 내 작업인지 확인하고 정상 종료한다. 임의로 시스템 프로세스를 종료하지 않는다.

### 18.7 프론트는 열리지만 데이터를 못 불러옴

확인 순서:

1. 백엔드 `/health`
2. 백엔드 `/ready`
3. `frontend/.env.local`의 주소
4. 브라우저 개발자 도구 Network의 실제 요청 URL
5. Railway API의 `ALLOWED_ORIGINS`
6. 주소 뒤에 `/api`를 중복으로 붙였는지

### 18.8 CORS 오류

원인: 브라우저가 연 프론트 주소가 `ALLOWED_ORIGINS`에 없음.

해결: 프로토콜, 호스트, 포트까지 정확히 추가하고 백엔드를 재시작한다. 예를 들어 `http://localhost:5173`과 `http://127.0.0.1:5173`은 서로 다른 origin이다.

### 18.9 `/health`는 되지만 `/ready`가 실패

원인: API 프로세스는 살아 있지만 DB 연결/migration에 문제가 있음.

확인:

- `DATABASE_BACKEND`
- SQLite 경로와 폴더 쓰기 권한
- PostgreSQL URL/SSL/네트워크
- Railway migration 로그
- 디스크 여유 공간

### 18.10 화면에 연보가 없음

새로운 빈 SQLite면 정상이다. 연보를 업로드하거나 인계받은 DB 경로를 `.env`에 지정한다. 운영 DB인 줄 알고 빈 로컬 DB를 수정하지 않도록 `/ready`와 `.env`를 먼저 본다.

### 18.11 업로드가 계속 `queued`

- 로컬이면 `JOB_EXECUTOR_BACKEND=inprocess`인지 확인
- worker 방식이면 worker가 실행 중인지 확인
- API와 worker가 같은 DB를 보는지 확인
- worker가 같은 S3/R2 원본을 읽을 수 있는지 확인

### 18.12 업로드 원본을 찾을 수 없음

DB만 옮기고 `backend/uploads`를 옮기지 않았거나, 저장 경로가 달라진 경우다. 같은 시점 백업을 복원하고 object key/경로를 확인한다.

### 18.13 SQLite `database is locked`

- 동시에 여러 백엔드/worker가 같은 SQLite를 쓰는지 확인한다.
- DB를 OneDrive/네트워크 드라이브에서 열지 않는다.
- 실행 중인 백엔드를 정상 종료하고 다시 시도한다.
- 다중 프로세스 운영은 PostgreSQL로 전환한다.

### 18.14 Windows에서 한글 파일명/경로 문제

- 저장소 자체는 `C:\work\statyearbook`에 둔다.
- Git long paths를 켠다.
- PowerShell과 Windows를 UTF-8 지원 최신 상태로 유지한다.
- 원본 파일명이 깨졌다면 이름만 억지로 바꾸기 전에 원본 해시와 확장자를 보존한다.

### 18.15 LLM 검수가 안 됨

확인 순서:

1. 화면에서 LLM 옵션을 선택했는가
2. `LLM_REVIEW_ENABLED=1`인가
3. 공급자가 `auto/openai/bizrouter` 중 하나인가
4. 선택 공급자의 API 키가 있는가
5. 모델명이 공급자에서 지원되는가
6. timeout/rate limit/429 로그가 있는가
7. 조직 네트워크가 외부 API를 허용하는가

키 값을 로그나 문의 글에 붙이지 않는다.

### 18.16 테스트가 내 PC에서만 실패

다음을 비교한다.

- Python/Node 버전
- `.env`가 테스트에 영향을 주는지
- 현재 SQLite DB 내용
- Git 커밋과 미커밋 변경
- `npm ci` 사용 여부
- `TEST_DATABASE_URL` 존재 여부
- macOS와 Windows의 경로/줄바꿈 차이

---

## 19. Git 협업과 릴리스 규칙

### 19.1 커밋 전 최소 확인

```bash
git status --short
git diff --check
git diff --stat
```

그다음 관련 테스트, 전체 테스트, 프론트 빌드를 실행한다.

### 19.2 커밋에 포함하지 않을 변경

- 운영 데이터가 우연히 바뀐 것
- `.env` 비밀값
- macOS/Windows가 만든 캐시
- `node_modules`, `.venv`, `dist`
- 목적과 무관한 다른 사람의 변경

### 19.3 Pull Request에 적을 내용

- 왜 바꾸는가
- 사용자에게 무엇이 달라지는가
- 핵심 파일
- 실행한 테스트와 결과
- 알려진 실패/미검증 항목
- DB migration 여부
- 환경변수 추가 여부
- 배포 순서와 롤백 방법
- 화면 변경 전/후 캡처

### 19.4 릴리스 기록 예

```text
배포일시: 2026-08-27 15:00 KST
Git commit: abcdef1
Frontend: Vercel deployment ID/URL
Backend API: Railway deployment ID
Worker: Railway deployment ID
DB migration: yes/no, key 목록
Backup: 생성 시각/보관 위치
Smoke test: health, ready, upload, validation, export
Known issues: ...
Rollback owner: ...
```

---

## 20. 첫날 실습 시나리오

다음 담당자는 운영 데이터를 건드리기 전에 아래를 직접 해본다.

### 실습 A: 빈 DB 실행

- [ ] 새 SQLite 경로를 `.env`에 지정
- [ ] 백엔드 시작
- [ ] `/health`, `/ready` 확인
- [ ] 프론트 시작
- [ ] 빈 화면이 오류 없이 뜨는지 확인

### 실습 B: 테스트 연보

- [ ] `generated/` 또는 승인된 작은 테스트 파일 선택
- [ ] 완성 연보 업로드
- [ ] 작업 완료 확인
- [ ] 합계/메타정보만 선택해 검수
- [ ] 표 상세 하이라이트 확인
- [ ] 결과 리포트 다운로드

### 실습 C: 코드 수정

- [ ] 새 브랜치 생성
- [ ] 화면의 작은 문구 하나 수정
- [ ] 관련 프론트 테스트 실행
- [ ] production build 실행
- [ ] diff 확인
- [ ] 수정 취소 또는 연습 커밋 정리

### 실습 D: 복구

- [ ] 테스트 DB 백업
- [ ] 테스트 데이터 하나 변경
- [ ] 서버 종료
- [ ] 백업 DB 복원
- [ ] `/ready`와 데이터 복원 확인

---

## 21. 최종 인계 회의 체크리스트

### 코드

- [ ] 최종 브랜치/커밋을 화면으로 함께 확인
- [ ] `git status`의 미커밋 파일을 하나씩 처리
- [ ] 미추적 `scripts`, `exports`, `references`, `tools`의 필요 여부 결정
- [ ] 프론트 테스트/빌드 결과 공유
- [ ] 백엔드 6개 실패의 처리 방향과 담당자 지정

### 데이터

- [ ] 실제 SQLite와 테스트 SQLite를 구분
- [ ] DB 크기, 백업 시각, SHA-256 기록
- [ ] `backend/uploads`의 같은 시점 백업
- [ ] 원본 데이터의 보안 등급/보존기간 공유
- [ ] PostgreSQL 백업과 복원 권한 확인

### 계정/배포

- [ ] GitHub 저장소 권한
- [ ] Vercel 프로젝트/팀 권한
- [ ] Railway API/worker/PostgreSQL 권한
- [ ] S3/R2 버킷 권한
- [ ] LLM 계정과 비용 담당자
- [ ] DNS/공식 URL/인증서 담당자

### 운영 지식

- [ ] 대표 정상 파일 1개와 대표 실패 파일 1개
- [ ] 기준 연보와 최신 연보 ID/제목
- [ ] 승인된 검수 baseline
- [ ] 알려진 데이터 예외와 수동 처리 규칙
- [ ] 배포/롤백 시연
- [ ] 장애 연락망과 응답 우선순위

---

## 22. 명령어 치트시트

### macOS

```bash
# 백엔드
./.venv/bin/python -m uvicorn app.main:app --app-dir backend --reload

# 프론트엔드
cd frontend && npm run dev

# 백엔드 테스트
PYTHONPATH=backend ./.venv/bin/python -m unittest discover -s backend/tests -q

# 프론트 테스트/빌드
cd frontend
npm run test
npm run build

# DB migration
PYTHONPATH=backend ./.venv/bin/python -m app.db.migrate

# worker
PYTHONPATH=backend ./.venv/bin/python -m app.workflows.report_worker
```

### Windows PowerShell

```powershell
# 백엔드
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --reload

# 프론트엔드
Set-Location frontend
npm run dev

# 백엔드 테스트
Set-Location C:\work\statyearbook
$env:PYTHONPATH = "backend"
& .\.venv\Scripts\python.exe -m unittest discover -s backend\tests -q
Remove-Item Env:PYTHONPATH

# 프론트 테스트/빌드
Set-Location frontend
npm run test
npm run build

# DB migration
Set-Location C:\work\statyearbook
$env:PYTHONPATH = "backend"
& .\.venv\Scripts\python.exe -m app.db.migrate
Remove-Item Env:PYTHONPATH

# worker
$env:PYTHONPATH = "backend"
& .\.venv\Scripts\python.exe -m app.workflows.report_worker
Remove-Item Env:PYTHONPATH
```

---

## 23. 담당자 기록란

인계할 때 빈칸을 채운다. 비밀번호와 API 키 값은 적지 않는다.

| 역할 | 이름/팀 | 연락 방법 | 비고 |
| --- | --- | --- | --- |
| 서비스 책임자 |  |  |  |
| 백엔드 담당 |  |  |  |
| 프론트엔드 담당 |  |  |  |
| 통계 데이터 담당 |  |  |  |
| 검수 기준 승인자 |  |  |  |
| Railway/PostgreSQL 담당 |  |  |  |
| Vercel 담당 |  |  |  |
| S3/R2 담당 |  |  |  |
| LLM 비용/키 담당 |  |  |  |
| 보안/개인정보 담당 |  |  |  |

운영 주소 기록:

| 항목 | 주소/식별자 |
| --- | --- |
| Git 저장소 | `https://github.com/wtdnrr/statyearbook.git` |
| 운영 프론트엔드 |  |
| 운영 API |  |
| Railway 프로젝트 |  |
| Vercel 프로젝트 |  |
| 객체 저장소 버킷 |  |
| 모니터링/로그 |  |
| 백업 위치 |  |

---

## 24. 더 깊게 볼 문서

- `README.md`: 기능과 코드 구조 전체 개요
- `docs/feature-guide.md`: 화면과 기능 상세
- `docs/automated-validation-workflow.md`: 업로드/검수 작업, 재시도, worker
- `docs/excel-series-yearbook-architecture.md`: 원장 기반 연보 생성 구조
- `docs/deployment-operations.md`: Railway/Vercel 운영과 백업
- `docs/virtual-yearbook-integration-test.md`: 가상 연보 통합 테스트
- `docs/2026_increment_connection_audit.md`: 2026 증분 원장 연결 감사

---

## 마지막 원칙

문제가 생겼을 때 가장 먼저 확인할 것은 “어떤 코드”, “어떤 환경변수”, “어떤 DB”, “어떤 원본 파일”, “어떤 작업 ID”를 사용했는지다. 이 다섯 가지를 기록하면 대부분의 장애를 재현할 수 있다. 운영 데이터와 비밀값을 보호하면서, 작은 테스트 DB에서 재현하고, 자동 테스트와 사람의 검수 기준을 함께 확인한다.
