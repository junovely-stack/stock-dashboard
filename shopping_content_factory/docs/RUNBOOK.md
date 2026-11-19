# 자동화 장애 대응 매뉴얼

먼저 볼 곳: 관리자 **대시보드**(오늘 단계 상태·데이터 연결·최근 API 오류) → **로그·비용**(job_runs, api_usage, 감사 로그) → CLI `python scf.py status`.

판정 원칙: 플로우가 '성공'으로 끝나도 결과가 맞는지는 별개다. 산출물 시각, 행 수, 데이터 기준일, 적재 시각을 같이 본다. 앞 단계가 실패하면 뒤 단계는 `skipped_upstream` 으로 표시되고 결과를 신뢰하지 않는다.

## 1. 단계 상태별 조치

| 상태 | 뜻 | 조치 |
|---|---|---|
| `failed` | 예외 발생. 백오프 후 자동 재시도(최대 `SCF_JOB_MAX_ATTEMPTS`=3) | `job_runs.message` 확인 → 원인 해결 → `python scf.py retry-failed` 또는 관리자 '실행' |
| `failed` + 시도 3회 | 자동 재시도 중단 | 원인 해결 후 `python scf.py run-stage <stage> --force` |
| `blocked` | 정책상 중단(기준 미달·비용 상한·한도·권리·사실 검사) — 재시도 안 함 | 메시지의 사유를 해결(아래 표) 후 `--force` |
| `skipped_upstream` | 선행 단계 미성공 | 선행 단계부터 해결. 선행이 성공하면 다음 실행에서 자동 진행 |
| `running` 이 계속 | 프로세스가 죽었거나 오래 걸림 | **알려진 결함(D2): `--force` 로도 안 풀림.** 아래 '임시 복구' 절차 사용. 잠금 파일 `outputs/.pipeline.lock` 은 2시간 지나면 자동 회수 |
| 대시보드 '스케줄러 마지막 동작'이 오래됨 | 스케줄러 중지 | `python scf.py scheduler` 재시작(또는 compose `scheduler` 서비스) |

### 임시 복구 — 크래시 후 `running` 고착 (결함 수정 D2 전까지)

1. 실행 중인 파이프라인 프로세스가 정말 없는지 확인 (`ps aux | grep scf.py`, Windows 는 작업 관리자).
2. 프로젝트 폴더에서:

```bash
python - <<'PY'
from sqlalchemy import update
from services.common.db import session_scope
from app.models import JobRun
with session_scope() as s:
    n = s.execute(update(JobRun).where(JobRun.status == "running")
                  .values(status="failed", message="수동 회수: 크래시 후 running 고착")).rowcount
print(n, "건 회수")
PY
```

3. 잠금 파일이 남아 있으면 삭제: `outputs/.pipeline.lock`
4. `python scf.py run-stage <멈춘 단계> --force` → 뒤 단계는 다음 실행에서 이어짐 (2026-11-18 재현·복구 확인)

**원인 요약**: 관리자 '실행' 버튼과 `/api/jobs/run` 이 단계를 웹 요청 안에서 실행 → gunicorn 기본 30초 시간초과로 영상 제작(약 75초) 중 워커가 죽으면 바로 이 상태가 된다. 수정 전까지는 무거운 단계(produce_media)를 CLI·스케줄러로만 실행할 것.

### 수동 입력 모드 가격 결함 (D2 수정 전)

수동 JSON 상품은 수집할 때마다 가격 확인 시각이 '방금'으로 바뀌고, 관리자 화면에서 재확인한 가격이 JSON 값으로 되돌아간다(재현). 가격 만료 검사가 동작하지 않으므로 **수정 전에는 수동 모드로 실제 게시하지 않는다.** 불가피하면 게시 직전에 판매 페이지 가격을 눈으로 확인하고 `data/manual/products.json` 의 가격도 같이 고친다.

## 2. blocked 사유별

| 메시지 | 원인 | 조치 |
|---|---|---|
| 최종 선정 없음 / 점수 < 기준 | 통과 후보 없음 또는 `SCF_MIN_FINAL_SCORE` 미달. **가장 흔한 원인은 후보 고갈**(30일 내 같은 상품 재선정 금지 — 가상 운영에서 D11) | 새 후보 등록 → `score_candidates --force`. 보류 사유(권리·사양·가격) 보완. 억지로 기준을 낮추지 말 것. 고갈일 예측: `python scripts/simulate_operations.py --provider manual` |
| 평가 통과 상품 0개 | 후보 데이터 문제 | `data/manual/products.json` 확인 |
| CostCapExceeded | 일/월 API 비용 상한 | 로그·비용 화면에서 사용량 확인. 상한 조정은 의도적으로만 |
| UnpricedProvider | `config/costs.toml` 단가 미확인(-1) | 공식 가격표 확인 후 단가·확인일 입력 |
| 이미지 사용권 미확인 | 원본 이미지 권리 unknown 등 | 상품 화면에서 권리 상태·증빙 입력(직접 촬영 사진이면 own) → 이미지·영상 재생성 |
| 사실·표시 검사 실패 | 자막에 검증 안 된 숫자·금칙어·표시 누락 | 콘텐츠 화면 '사실·표시 검사' 목록대로 문구 수정 → 저장(자동 재검사) |
| 일일 생성 한도 | `SCF_DAILY_CONTENT_LIMIT` | 정상. 늘리기는 수익성 입증 후 |
| NotConfiguredError | 자격증명 없음 | `.env` 입력. 없으면 mock/수동 경로 사용 |

## 3. 게시 문제

| 증상 | 조치 |
|---|---|
| `pending_credentials` | 실제 게시 안 됨. `.env` 에 IG/YT 자격증명 입력 후 관리자 '게시' 다시 |
| `waiting_manual` | `AUTO_PUBLISH=false` — 정상. 콘텐츠 화면에서 '게시' |
| `blocked` (링크·가격·재고·사실 변경·영상 변경) | 사유대로: 링크 등록·직접 확인 / 상품 화면 '판매처에서 지금 확인함' / 재생성·재승인 |
| `api_accepted` 에서 멈춤 | 플랫폼 처리 중 또는 비공개 상태. 다음 성과 수집 때 재확인. YouTube 는 `YOUTUBE_PRIVACY_STATUS` 확인 |
| `unknown` | 업로드 응답이 끊김 — **자동 재시도하지 않음(중복 업로드 방지)**. 앱에서 직접 확인 후 `python scf.py resolve-publication <id> --status published_verified --media-id <ID> --by <이름>` 또는 `--status failed` 후 재게시 |
| Instagram 컨테이너 ERROR/EXPIRED | 영상 URL 이 공개 접근 안 됨, 규격 불일치 | 브라우저 시크릿 창에서 `SCF_PUBLIC_MEDIA_BASE_URL/<콘텐츠>/reel_final.mp4` 열리는지 확인 |
| 24시간 게시 한도 | `SCF_DAILY_PUBLISH_LIMIT` 또는 IG `content_publishing_limit` | 다음 날 |

## 4. 외부 API

| 증상 | 조치 |
|---|---|
| 429·5xx | 자동 지수 백오프(Retry-After 준수). 지속되면 `api_usage` 에서 빈도 확인, 호출 간격 조정 |
| 401·403 | 토큰 만료·권한 변경. Instagram 장기 토큰은 갱신 필요, YouTube refresh token 폐기 시 재인증 |
| 네이버 DataLab 오류(2027-07 이후) | 개발자센터 키 종료 → `NAVER_API_MODE=apihub` + HUB 키·URL |
| 쿠팡 rCode 오류 | 메시지 확인(서명 시각 오차 → 서버 시계 동기화) |

## 5. 렌더링·환경

| 증상 | 조치 |
|---|---|
| `ffmpeg 가 PATH 에 없습니다` | FFmpeg 설치(README) |
| 한글 폰트 없음 | `assets/fonts` 확인 또는 `SCF_FONT_PATH` |
| 렌더 시간이 길다 | `SCF_RENDER_FPS` 낮추기(QA 기준 24fps 이상 권장 — Instagram 23fps 이상) |
| 디스크 부족 | `outputs/contents` 의 거절·오래된 콘텐츠 정리, `outputs/raw` 원본 응답 보관 기간 정하기 |
| `database is locked`(SQLite) | 동시 접근 과다 → PostgreSQL 전환(`SCF_DATABASE_URL`) |

## 6. 데이터 신뢰

- 대시보드 '데이터 연결 상태'가 `mock` 이면 그 날 숫자는 실데이터가 아니다. 보고서 상단에도 표시된다.
- 성과 화면의 '연동 대기' = 값 없음(0 아님). 0 으로 해석하지 말 것.
- CSV 적재 시 거부된 행은 사유와 함께 표시된다(미등록 콘텐츠·음수·논리 역전). 조용히 넘기지 말고 원본을 고친 뒤 다시 올릴 것.

## 7. 개인정보·삭제 요청

- 이벤트 정리: `python scf.py purge-events --days 90`
- 상품 단위 삭제: 관리자 상품 화면 하단 또는 `python scf.py delete-product <id> --by <이름>` — 플랫폼에 올라간 게시물은 각 앱에서 직접 삭제(결과에 개수 표시).

## 변경 이력
- REV01 (2026-11-18): 최초 작성.
- REV03 (2026-11-18): 후보 고갈 원인·예측 명령, 수동 입력 모드 가격 결함 경고 추가.
- REV02 (2026-11-18): `running` 고착 항목 정정 — 기존 안내(`--force`)는 동작하지 않음을 재현으로 확인, 임시 복구 절차와 원인 추가.
