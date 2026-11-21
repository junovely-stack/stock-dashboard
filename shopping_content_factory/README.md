# SHOPPING CONTENT FACTORY V1.0

쇼핑 키워드에서 고객 문제를 찾고 → 상품을 100점 기준으로 고르고 → 사실 검사를 통과한 9:16 숏폼·이미지·랜딩을 만들고 → 사람이 승인한 것만 게시하고 → 조회부터 제휴수익까지 실측과 추정을 나눠 기록하는 파이프라인.

**현재 상태: MVP (PHASE 2) 완료 — 외부 API 키 없이 mock 으로 전 구간 실행, 테스트 78개 통과.** 실제 게시·실데이터 연결은 권한이 생기는 대로 하나씩 켠다.

먼저 읽을 문서: [docs/PROGRESS.md](docs/PROGRESS.md) (진행 현황) → [docs/SCF_지식체계_REV01.html](docs/SCF_지식체계_REV01.html) (모든 내용을 한 그래프로 — 진행·지도·탐색기·추적표) → [docs/DECISIONS.md](docs/DECISIONS.md) (내가 정할 것 — 이번 주 7건) → [docs/VIRTUAL_OPERATION.md](docs/VIRTUAL_OPERATION.md) (가상 운영 30일 — 방해 요소·필요한 도움) → [docs/AUTOMATION_REVIEW.md](docs/AUTOMATION_REVIEW.md) (기획안 재검토) → [docs/SCF_온톨로지_REV02.html](docs/SCF_온톨로지_REV02.html) (개념·자동화 지도) → [docs/BUSINESS_RISK_ANALYSIS.md](docs/BUSINESS_RISK_ANALYSIS.md) (수익성 위험). 전체 문서 지도: [docs/README.md](docs/README.md)

> **알려진 결함 (2026-11-18 자체 검토·가상 운영)** — **수동 입력 모드는 가격 확인 시각이 매일 자동 갱신되고 관리자 재확인 가격이 덮어써짐(재현) → 수정 전 실운영 금지**, 상품명 속 숫자를 사실 검사가 오탐, 크래시 후 작업이 `running` 으로 고착되면 `--force` 로도 안 풀림(임시 복구: [docs/RUNBOOK.md](docs/RUNBOOK.md)), 웹 실행 버튼은 gunicorn 30초 시간초과에 걸림, 쿠팡 API 모드는 후보가 전부 '보류', 메인→상품 이동 시 유입경로 유실, 관리자 로그인 시도 제한 없음. 수정은 결정 D2 대기. 목록: [docs/BUSINESS_RISK_ANALYSIS.md](docs/BUSINESS_RISK_ANALYSIS.md) 6절.

---

## 1. 설치 (신규 환경)

필요: Python 3.11 이상, FFmpeg, (선택) Node 18+ 와 Playwright — 브라우저 E2E 점검용.

```bash
cd shopping_content_factory
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
ffmpeg -version                      # 없으면: Ubuntu `sudo apt install ffmpeg` / macOS `brew install ffmpeg` / Windows `winget install Gyan.FFmpeg`
cp .env.example .env                 # 최소 SCF_ADMIN_PASSWORD, SCF_SECRET_KEY 입력
```

한글 폰트(Pretendard, OFL)는 `assets/fonts` 에 들어 있다.

## 2. 실행

```bash
python scf.py init-db
python scf.py run-daily --no-publish          # mock 데이터로 07:00~09:00 단계 전부 (약 1~2분, 영상 렌더 포함)
python scf.py status                          # 단계·데이터 소스·콘텐츠 상태
python scf.py serve --port 5000               # http://localhost:5000 (랜딩), /admin (관리자)
```

정상 동작 확인: `status` 에서 `qa_check succeeded`, 콘텐츠 `C<오늘날짜>-01 awaiting_approval` → 관리자 `콘텐츠 검수`에서 영상 2개 재생 → `승인` → 랜딩 `/p/demo-001` 에 상품·장단점·주의사항·영상이 보이고 구매 버튼은 '제휴 링크 등록 대기'.

| 명령 | 용도 |
|---|---|
| `python scf.py scheduler` | 상시 루프 (Asia/Seoul 07:00~12:00 일정, 30초 간격, 중복 실행 방지) |
| `python scf.py run-stage <stage> [--force]` | 단계 하나 실행. stage: collect_metrics, daily_report, collect_trends, score_candidates, select_verify, generate_script, produce_media, qa_check, publish_approved |
| `python scf.py retry-failed` | 오늘 실패 단계 재시도(백오프·횟수 상한 준수) |
| `python scf.py approve <id> --by <이름>` | 승인 (관리자 화면과 동일 검사) |
| `python scf.py register-link <product> <url> --by <이름>` | 쿠팡파트너스에서 만든 링크 수동 등록 → 관리자 화면에서 '직접 열어 확인함' |
| `python scf.py publish <id> --platform instagram|youtube --by <이름>` | 수동 게시 (게이트 재검사) |
| `python scf.py import-metrics <csv>` / `import-coupang <csv>` | 성과·실적 CSV 적재 (`data/templates/`) |
| `python scf.py report [--date]` | 일일 수익성 보고서 HTML |
| `python scf.py simulate --out docs/ROI_REPORT.md` | 12개월 시뮬레이션 |
| `python scf.py purge-events` / `delete-product <id>` | 개인정보·데이터 삭제 |
| `python scf.py resolve-publication <id> --status ...` | 응답 불확실 게시를 사람이 확인 후 기록 |

운영 배포: `gunicorn -w 2 -b 0.0.0.0:5000 wsgi:app` + `python scf.py scheduler`, 또는 `docker compose up -d` (web + scheduler). 스케줄 대안: `workflows/crontab.example`, n8n 은 `workflows/n8n_daily_workflow.json` 가져오기 → `SCF_API_TOKEN` 으로 `/api/jobs/run` 호출.

## 3. 테스트

```bash
python -m pytest                     # 78개, 약 27초 (mock, 외부 호출 없음, 영상은 6fps 로 렌더)
node scripts/e2e_check.mjs http://localhost:5000 <관리자비밀번호> <스크린샷폴더>   # 서버 띄운 뒤, 콘솔 오류·가로 넘침·필수 요소 점검
```

## 4. 일일 일정 (Asia/Seoul)

| 시각 | 단계 | 선행 |
|---|---|---|
| 07:00 | 전일 성과 집계(collect_metrics) → 보고서(daily_report) | — |
| 07:00 | 트렌드 수집·중복 제거·급상승·화제성 제외(collect_trends) | — |
| 07:20 | 후보 발굴(20개 이상)·100점 평가·필터·상위 5(score_candidates) | 트렌드 |
| 07:35 | 상위 후보 재검증(가격·재고·권리·사양) → 최종 1(select_verify) | 평가 |
| 07:45 | 구매심리 10문항 + 대본 A/B + 사실 검사(generate_script) | 선정 |
| 08:00 | 이미지 6종 + 영상 2종 + 자막·매니페스트(produce_media) | 대본 |
| 09:00 | 자동 QA → 승인 대기(qa_check) | 제작 |
| 12:00 | 승인된 콘텐츠만 게시(publish_approved). `AUTO_PUBLISH=false` 면 '게시 대기' | — |

시간이 넘어도 무조건 게시하지 않는다. 각 단계는 `job_runs` 에 상태·사유를 남기고, 실패는 백오프 재시도, 정책 차단은 사람 조치 대기.

## 5. 구조

```
shopping_content_factory/
├── scf.py                     CLI
├── wsgi.py                    운영 WSGI 진입점
├── app/                       Flask — routes(public·admin·api), templates, static, models(schema.py)
├── services/
│   ├── trend_collector/       수집·정규화·급상승·화제성 제외
│   ├── product_discovery/     후보 발굴·중복 제거·DB 반영
│   ├── product_scoring/       100점 평가·필수 필터·상위 5·재검증·최종 선정
│   ├── psychology_engine/     구매심리 10문항·심리요소 1~2개 (규칙 / Claude)
│   ├── script_generator/      대본 A/B·캡션·해시태그 + fact_guard(사실·표시 검사)
│   ├── image_generator/       이미지 6종·원형 보존 검수·image_manifest
│   ├── video_renderer/        Pillow 프레임 → FFmpeg H.264, 자막 SRT, 자동 QA
│   ├── affiliate_links/       링크 형식 검증·수동 등록·사람 확인·고지 문구 검사
│   ├── social_publishers/     게시 게이트·중복 방지·검수 액션·삭제
│   ├── analytics/             퍼널(실측/추정 분리)·CSV 적재·학습·재무 산식·시뮬레이션·보고서
│   └── common/                설정·DB·HTTP 재시도·비용 상한·비밀값 마스킹·사실 해시
├── adapters/                  naver(DataLab, mock) · coupang(Partners HMAC, 카탈로그) · instagram · youtube · llm(anthropic) · tts
├── workflows/                 pipeline(작업 큐) · scheduler(상시 루프) · crontab.example · n8n_daily_workflow.json
├── config/                    settings.py + scoring/compliance/finance/costs/categories.toml (사람이 손보는 정책값)
├── data/mock/                 DEMO 트렌드·상품 24개 (실재하지 않음)
├── data/templates/            수동 입력·CSV 양식
├── assets/fonts/              Pretendard (OFL)
├── demo/                      데모 콘텐츠 1개 산출물·화면 캡처·보고서
├── docs/                      보고서·매트릭스·체크리스트·비용·스키마·프롬프트·장애 대응·ROI
└── tests/                     pytest 78개
```

## 6. 완료 판정 기준 (요구서 17장) ↔ 검증

| 기준 | 검증 |
|---|---|
| mock 상품 20개 이상 수집 | `test_trends_discovery::test_discovery_collects_at_least_20_candidates` (24개) |
| 100점 점수 계산 | `test_scoring::test_scores_are_0_to_100_and_breakdown_sums` |
| 선정 과정 기록 | `test_scoring::test_selection_is_logged_and_final_chosen` |
| 사실과 다르면 게시 차단 | `test_fact_guard::test_spec_mismatch_blocks`, `test_facts_change_after_generation_blocks_publish` |
| 권리 불확실 이미지 차단 | `test_media::test_unclear_image_rights_block_content`, `test_partner_display_image_not_used_in_video_by_default` |
| 대본·이미지 저장 | `test_media::test_script_images_and_manifests_saved` |
| 실행 가능한 MP4 | `test_media::test_mp4_is_valid_vertical_short` (1080×1920, 15~30초, H.264+AAC) |
| 랜딩 정상 표시 | `test_landing_admin::test_landing_shows_product_info_after_approval` + `scripts/e2e_check.mjs` |
| 미승인 콘텐츠 게시 안 됨 | `test_publish_gate::test_unapproved_content_is_not_published`, `test_unapproved_product_not_public` |
| 중복 실행에도 중복 업로드 없음 | `test_publish_gate::test_duplicate_runs_upload_once_and_states_are_separate`, `test_jobs::test_stage_runs_once_per_day` |
| 실측·추정 구분 | `test_analytics::test_measured_vs_estimated_and_unattributed`, `test_no_metrics_means_waiting_not_zero` |
| 재무 단위테스트 | `test_finance` 6개 (손계산 검산) |
| API 비용·실패 로그 | `test_jobs::test_anthropic_client_with_fake_sdk_records_cost`, `test_security::test_failed_api_call_records_redacted_error` |
| 비밀키 미노출 | `test_security` 4개 |
| README 로 신규 환경 실행 | 위 1~3절 절차를 새 폴더·새 venv 에서 재현해 확인 (보고 참조) |

## 7. 아직 안 된 것 (권한·승인 필요)

| 항목 | 막힌 이유 | 켜는 방법 |
|---|---|---|
| 실데이터 트렌드 | 네이버 키 없음 (신규는 API HUB) | `.env` NAVER_* → `SCF_TREND_PROVIDER=naver` |
| 상품 자동 탐색·딥링크·실적 API | 쿠팡 최종 승인 전 | 수동 입력(`data/manual/products.json`) → 승인 후 COUPANG_* + `SCF_PRODUCT_PROVIDER=coupang` |
| Instagram 게시·인사이트 | 계정 토큰·공개 영상 URL 없음 | INSTAGRAM_* + `SCF_PUBLIC_MEDIA_BASE_URL` |
| YouTube 업로드·Analytics | OAuth 없음 | YOUTUBE_* (처음엔 `YOUTUBE_PRIVACY_STATUS=private`) |
| Claude 대본 | 키 없음(기본 mock) | `ANTHROPIC_API_KEY` + `SCF_LLM_PROVIDER=anthropic` (비용 상한 적용) |
| 생성형 이미지·영상 | 단가 미확인, 상품 왜곡 위험 | 배경만 외부 도구로 만들어 파일로 가져오기(`rights=ai_generated`) |
| 실측 성과 | 게시 전 | 게시 후 API 또는 CSV |

## 8. 온톨로지·결정 문서 갱신

```bash
python scripts/build_ontology.py --rev 02            # scripts/ontology_data.py → HTML 새 REV + md 자동 구간 갱신
node scripts/check_ontology_html.mjs docs/SCF_온톨로지_REV02.html <스크린샷폴더>   # 글자 넘침·겹침·콘솔 오류 점검
python scripts/simulate_operations.py --days 30 --with-links   # 가상 운영(임시 DB) — 후보 고갈일·차단 사유·사람 개입 기록
python scripts/build_knowledge.py --rev 02            # 지식체계: scripts/knowledge_data.py → HTML·KNOWLEDGE_BASE·PROGRESS·RDF(TTL)·JSON
node scripts/check_knowledge_html.mjs docs/SCF_지식체계_REV02.html <스크린샷폴더>
```

외부 게시, 유료 API 활성화, 결제, 계정 설정 변경은 사용자가 직접 승인한 범위에서만 한다. 이 저장소의 어떤 명령도 기본 설정으로는 외부에 게시하지 않는다.

## 변경 이력
- REV01 (2026-11-18): 최초 작성.
- REV02 (2026-11-18): 먼저 읽을 문서에 결정·재검토·온톨로지 추가, 알려진 결함 고지, 온톨로지 갱신 명령.
- REV03 (2026-11-18): 가상 운영 문서·결함 3건 추가, 온톨로지 REV02, 시뮬레이터 명령.
- REV04 (2026-11-21): 진행 현황(PROGRESS)·지식체계(HTML·KNOWLEDGE_BASE·RDF) 추가, 테스트 78개.
