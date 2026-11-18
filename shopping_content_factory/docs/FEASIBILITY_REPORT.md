# 실행 가능성 보고서 (PHASE 1 · STEP 2~3)

기준일 2026-11-18. 사업 논리 검토는 [BUSINESS_RISK_ANALYSIS.md](BUSINESS_RISK_ANALYSIS.md), API 상세는 [API_ACCESS_MATRIX.md](API_ACCESS_MATRIX.md), 규제는 [COMPLIANCE_CHECKLIST.md](COMPLIANCE_CHECKLIST.md), 비용은 [COST_MODEL.md](COST_MODEL.md).

## 결론 한 줄

기술적으로는 전 구간 구현 가능하고 MVP 는 mock 으로 끝까지 돌아간다. 막히는 곳은 기술이 아니라 **권한 3개** — 쿠팡 API(매출이 생겨야 열림), Instagram 공개 영상 URL(호스팅 필요), 네이버 DataLab 신규 키(API HUB) — 와 **퍼널 실측**이다.

## 1. 기능별 판정

| 구분 | 기능 |
|---|---|
| **지금 가능** | 규칙 기반 상품 평가·선정, 대본(규칙/Claude), 이미지·영상 로컬 생성, 랜딩 페이지, 관리자 검수, 수동 제휴 링크 등록, 파트너스 대시보드 CSV 실적 적재, 자체 이벤트 측정, YouTube 업로드(OAuth 앱 생성 시) |
| **승인·조건 필요** | 쿠팡 상품 검색·딥링크·리포트 API(최종 승인: 누적 판매 15만 원 이상에서 심사), 네이버 DataLab(기존 키 2027-06-30까지 / 신규는 NCP API HUB), Instagram 게시(프로페셔널 계정 + 공개 영상 URL), Google Trends API(알파 허용 계정), YouTube 쇼핑 제휴(YPP + 구독자 500), Claude·이미지 생성 API(키·결제) |
| **현재 불가** | 네이버 쇼핑 검색 API(2026-07-31 종료), Shorts·Reels 캡션 링크 클릭, 콘텐츠 단위 매출 귀속(sub_id 분리 리포트 확인 전), Instagram 릴스 단위 프로필 방문 지표, OpenAI gpt-image-1(종료) |

## 2. MVP 범위 확정 (STEP 3)

수익성·비용·난이도 기준으로 고른 범위. 선택 이유는 '측정 장치를 먼저, 생산 자동화는 그다음'.

| 포함 | 이유 |
|---|---|
| 후보 평가 100점 + 필수 필터 + 선정 기록 | 비용 0, 매일 판단 근거를 남김 |
| 수동 상품 입력 경로 | 쿠팡 API 없이 운영을 시작할 유일한 합법 경로 |
| 사실·표시 검사(fact_guard) | 한 번의 위반이 계정 전체를 위험하게 함 |
| 로컬 이미지·영상 렌더러 | 콘텐츠당 비용 0원 |
| 랜딩 + 유입경로·클릭 측정 | 퍼널 실측(최대 미지수)의 유일한 데이터원 |
| 승인 게이트·중복 방지·상태 분리 게시 | 잘못 게시하면 되돌릴 수 없음 |
| DB 작업 큐 + 스케줄러 | 사람이 매일 실행하지 않아도 되도록 |

| 제외(후속) | 이유 |
|---|---|
| AI 영상 생성 모델 상시 사용 | 단가 미확인, 상품 형태 왜곡 위험 |
| 유료 TTS | OpenAI TTS 3종 2027-01 종료 예정, 단가 미확인 |
| 하루 3~5개 생산 | 수익성 입증 전 확대 금지(요구서 원칙) |
| 댓글→DM 자동 응답 | 퍼널 개선 효과 크지만 Messaging API 권한·정책 검토 필요 |
| 이미지 생성 API 직접 연동 | 배경만 필요 — 수동 가져오기로 충분 |

## 3. 구현 결과 (STEP 4~7)

- 구조·스키마: [DB_SCHEMA.md](DB_SCHEMA.md), [../README.md](../README.md)
- mock 수직 통합: 트렌드 28개 → 후보 24개 → 평가(통과 13·보류 6·제외 5) → 상위 5 → 재검증 → 최종 1 → 심리분석 → 대본 A/B → 이미지 6종 → 영상 2종 → QA → 승인 대기 → (승인) → 랜딩 노출 → 게시 시도 시 '링크 미등록'으로 차단
- 데모 산출물: `demo/C20261118-01/` (영상·이미지·대본·자막·매니페스트), `demo/screenshots/`
- 테스트: `pytest` 74개 통과 (요구서 17장 완료 기준 매핑은 README)

## 4. 사용자 조치가 필요한 항목 (우선순위 순)

1. **쿠팡파트너스 가입·활동 페이지 등록** → 수동 링크로 첫 판매(최종 승인 조건 충족) → API 키 발급 후 `COUPANG_*` 입력.
2. **공개 호스팅 결정**(랜딩 + 영상 URL) → `SCF_SITE_BASE_URL`, `SCF_PUBLIC_MEDIA_BASE_URL`.
3. **Instagram 프로페셔널 계정 + Meta 앱(Instagram Login)** → 액세스 토큰.
4. **Google Cloud OAuth 클라이언트 + YouTube 채널 refresh token**.
5. **네이버**: 기존 개발자센터 키가 있으면 입력(2027-06-30까지), 없으면 NCP API HUB 가입.
6. (선택) **Anthropic API 키** → `SCF_LLM_PROVIDER=anthropic`.
7. 개인정보 처리방침에 사업자 정보 기입, 세무 상담(사업소득·사업자등록).
8. [API_ACCESS_MATRIX.md](API_ACCESS_MATRIX.md) 하단 '원문 재확인' 6개 항목 확인.

## 5. 다음 단계 (PHASE 3~4)

1. 수동 상품 입력으로 실제 콘텐츠 1개 → 직접 검수 → 수동 게시(플랫폼 앱) → 성과 CSV 적재까지 한 바퀴.
2. 권한 생기는 순서대로 어댑터를 하나씩 켜고 통합 테스트(실호출은 사용자 승인 후).
3. 30개 콘텐츠 후 [BUSINESS_RISK_ANALYSIS.md](BUSINESS_RISK_ANALYSIS.md) 5절 기준으로 확대·전환 판정.
