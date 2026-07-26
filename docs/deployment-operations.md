# 배포·운영 가이드

운영 구성은 `Vercel 프론트엔드 + Railway API + Railway worker + Railway
PostgreSQL + S3/R2 원본 저장소`를 기준으로 합니다. API와 worker는 같은 Git
커밋과 DB를 사용하지만 실행 프로세스와 책임을 분리합니다.

## Railway 서비스

### API 서비스

- Git 저장소: 동일 저장소
- Config File: `/railway.json`
- Public Networking: 활성화
- `JOB_EXECUTOR_BACKEND=worker`
- `SOURCE_STORAGE_BACKEND=s3`

`railway.json`의 pre-deploy command가 `python -m app.db.migrate`를 실행합니다.
마이그레이션이 실패하면 새 API 배포는 시작되지 않습니다. `/ready`는 DB 연결까지
확인하고, `/health`는 프로세스 상태만 확인합니다.

### Worker 서비스

- Git 저장소: 동일 저장소
- Config File: `/railway.worker.json`
- Public Networking: 불필요
- API와 같은 `DATABASE_URL`, 객체 저장소 변수 사용

worker는 `python -m app.workflows.report_worker`로 실행됩니다. DB의 queued 작업을
claim하고 lease를 갱신하며, 중단된 running 작업은 lease가 만료된 후 이어받습니다.

API와 worker를 분리한 상태에서 로컬 파일 저장소를 사용하면 서로 업로드 파일을
볼 수 없습니다. 반드시 S3/R2 같은 공용 객체 저장소를 사용하거나 두 서비스가
공유하는 영속 볼륨을 구성해야 합니다.

## Vercel

Vercel에는 백엔드 주소 하나만 주입합니다.

```dotenv
VITE_API_BASE_URL=https://<api-service>.up.railway.app
```

값에는 변수명이나 `/api`를 다시 붙이지 않습니다. 환경 변수를 변경한 뒤에는 새
Production Deployment가 필요합니다. Railway API의 `ALLOWED_ORIGINS`에는 확정된
Vercel Production URL을 정확히 등록합니다.

## 운영 지표

다음 API는 최근 작업의 실패율, 단계별 평균 시간과 LLM 토큰·예상 비용을
DB 기준으로 집계합니다.

```bash
curl "https://<api-service>.up.railway.app/api/operations/metrics?window_days=30"
curl "https://<api-service>.up.railway.app/api/operations/metrics?window_days=30&report_id=42"
```

LLM 비용은 실제 청구액이 아니라 아래 단가로 계산한 예상치입니다.

```dotenv
LLM_INPUT_COST_PER_MILLION=0
LLM_OUTPUT_COST_PER_MILLION=0
```

사용 모델과 제공업체의 실제 단가를 입력해야 비용 값이 의미를 가집니다.

## 원본 파일 보존

기본 정책은 완료 작업 원본 365일, 실패 작업 원본 90일입니다. `0`은 자동 삭제하지
않는다는 뜻입니다.

```dotenv
COMPLETED_SOURCE_RETENTION_DAYS=365
FAILED_SOURCE_RETENTION_DAYS=90
```

삭제 전 후보만 확인합니다.

```bash
python -m app.operations.maintenance --prune-sources
```

결과를 확인한 뒤 실제 삭제합니다.

```bash
python -m app.operations.maintenance --prune-sources --apply
```

운영에서는 별도 Railway Cron 서비스가 위 `--apply` 명령을 하루 한 번 실행하도록
설정할 수 있습니다. 삭제된 원본은 해당 과거 작업의 재시도에 사용할 수 없으므로,
검수 확정 및 백업 완료 뒤의 보존 기간만 설정합니다.

## PostgreSQL 백업

DB 백업은 애플리케이션 컨테이너가 임의로 파일을 복사하지 않고 Railway Postgres
볼륨의 Backups 기능을 사용합니다.

권장 일정:

- Daily: 활성화
- Weekly: 활성화
- Monthly: 활성화
- 중요 운영 데이터라면 Point-in-Time Recovery도 활성화

Railway의 예약 백업은 Postgres 볼륨 전체를 대상으로 하며 Backups 탭에서 직접
복원합니다. 복원 연습은 운영 DB를 덮어쓰지 말고 별도 복원 서비스에서 분기해
API의 `/ready`와 대표 연보 조회를 확인합니다.

참고:

- Railway config as code: https://docs.railway.com/config-as-code
- Railway pre-deploy command: https://docs.railway.com/deployments/pre-deploy-command
- Railway backups: https://docs.railway.com/volumes/backups
- Railway point-in-time recovery: https://docs.railway.com/volumes/point-in-time-recovery
- Vercel Vite 환경 변수: https://vercel.com/docs/frameworks/frontend/vite

## 배포 점검표

1. API pre-deploy migration 성공
2. API `/health`와 `/ready` 성공
3. worker 로그에서 대기 작업 poll 확인
4. 테스트 파일 업로드 후 import → calculation → language 완료
5. `/api/operations/metrics`에서 완료 작업과 단계 시간이 증가
6. LLM 활성화 시 토큰 및 예상 비용 기록 확인
7. Vercel에서 목록·상세·하이라이트 확인
8. Postgres 예약 백업과 원본 저장소 보존 정책 확인
