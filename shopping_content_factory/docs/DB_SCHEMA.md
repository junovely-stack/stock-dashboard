# DB 스키마 (STEP 4)

정의: `app/models/schema.py` (SQLAlchemy 2.0). SQLite(MVP, WAL) / PostgreSQL(`SCF_DATABASE_URL`). 모든 시각은 UTC 로 저장, 화면은 Asia/Seoul.

```
trend_snapshots ─┐
                 ▼ (keywords)
products ──< product_images
   │     ──< affiliate_links (sub_id, content_id)
   │     ──< price_history
   ├──< product_scores (run_date, 100점 내역, 필터, 순위, 선정)
   ├──< psychology_profiles
   └──< contents ──< publications (content, variant, platform 유일)
                 ──< metric_observations (실측/추정 구분)
site_events (IP·UA 없음) · affiliate_reports (sub_id 귀속) · job_runs · api_usage · cost_entries · audit_logs · data_sources · selection_logs
```

## 테이블

| 테이블 | 핵심 컬럼 | 제약·비고 |
|---|---|---|
| `data_sources` | name, kind, state(connected/mock/manual/not_configured/error), note, last_success_at, last_error | 운영 화면 '데이터 연결 상태' |
| `trend_snapshots` | run_date, source, keyword, intent(purchase/problem/buzz), series(JSON), latest_ratio, growth_7d/30d, is_surging, excluded_reason, collected_at, source_url, raw_ref, confidence | UNIQUE(run_date, source, keyword). ratio 는 상대지수 |
| `products` | id, slug, name, category_key, seller, base_price, price_checked_at, stock_status, verified_specs(JSON), pros/cons/recommended_for/not_recommended_for/cautions/usage_steps, problem(JSON), signals(JSON), image_rights_status, affiliate_link_status, total_score, selection_reason, expected_revenue, content_status, facts_hash, is_demo | facts_hash = 이름·사양·장단점·주의사항 해시 |
| `product_images` | product_id, path, url, role, source, rights_status, rights_evidence, verified_by | rights: own/licensed/ai_generated/partner_display_only/reference_only/unknown/denied |
| `affiliate_links` | product_id, program, url, sub_id, content_id, status(missing/registered/verified/invalid), source(manual/api), verified_at/by | 사람 확인 또는 공식 API 생성일 때만 verified |
| `price_history` | product_id, price, checked_at, source | 가격 변동 감점 근거 |
| `product_scores` | run_date, product_id, total, breakdown(JSON: 항목별 score/max/evidence/conservative), filter_result(pass/hold/exclude), filter_reasons, penalties, rank, selection(top5/final), selection_reason, expected_revenue | UNIQUE(run_date, product_id) |
| `selection_logs` | run_date, step(discover/score/final), message, data | 선정 과정 기록 |
| `psychology_profiles` | run_date, product_id, answers(10문항), levers(1~2), hooks(A/B), cautions, generator, model, validation | UNIQUE(run_date, product_id) |
| `contents` | id(C20261118-01), run_date, product_id, status, title, primary_variant, script(JSON), facts_hash, caption, hashtags, landing_path, output_dir, assets, fact_check, qa_result, block_reasons, cost_estimate_krw, ai_generated_media, approved_by/at, review_notes, scheduled_at, is_demo | 상태: generated → awaiting_approval → approved → published / blocked / revision_requested / rejected |
| `publications` | content_id, variant, platform, status, idempotency_key, platform_media_id, platform_url, detail, confounders, attempts, error, requested_at, api_accepted_at, verified_at | UNIQUE(content_id, variant, platform), UNIQUE(idempotency_key). 상태: queued/blocked/pending_credentials/waiting_manual/in_progress/**api_accepted**/**published_verified**/failed/unknown |
| `site_events` | ts, event_type(page_view/link_click/video_play), product_id, content_id, src, link_id, ref_domain | IP·UA·쿠키 컬럼 없음 |
| `metric_observations` | metric_date, content_id, variant, platform, metric, value, source(api/manual_csv/site_log), is_estimate | UNIQUE(date, content, variant, platform, metric, source) |
| `affiliate_reports` | report_date, program, sub_id, clicks, orders, gmv_krw, commission_krw, cancel_count, cancel_amount_krw, settlement_status, source | sub_id ↔ affiliate_links.content_id 로만 콘텐츠 귀속 |
| `job_runs` | run_date, stage, status(pending/running/succeeded/failed/blocked/skipped_upstream), attempts, started_at, finished_at, next_retry_at, message, detail, lock_owner | UNIQUE(run_date, stage) — 중복 실행 방지 |
| `api_usage` | ts, provider, operation, status_code, success, latency_ms, attempts, units, cost_krw, error(마스킹) | 비용 상한 계산 원천 |
| `cost_entries` | cost_date, category, amount_krw, content_id, note | API 외 비용 수동 입력 |
| `audit_logs` | ts, actor, action, target_type, target_id, detail | 승인·거절·수정·게시·삭제·권리 변경 |

## 상태 전이 규칙 (코드로 강제)

- 승인은 `awaiting_approval` + 사실 검사·QA 통과 + 사실 해시 일치일 때만.
- 문구 수정 → 사실 검사 재실행 → 승인 해제(재승인 필요). 자막이 바뀌면 `revision_requested`(재렌더 필요).
- 게시는 승인 + 링크 verified + 가격 유효 + 재고 + 권리 + 영상 해시 일치일 때만. 실패 사유는 `publications.detail.reasons`.
- `api_accepted` 는 '플랫폼이 ID 를 줬다', `published_verified` 는 '조회로 공개 확인' — 콘텐츠 `published` 는 후자일 때만.
