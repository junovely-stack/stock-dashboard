# API 접근 매트릭스

조사일 2026-11-18. **확인 수준**: A = 공식 문서 원문(네이버 공식 문서 저장소 `naver/naver-openapi-guide`, OpenAI 공식 SDK 소스) / B = 공식 페이지의 검색 색인 발췌(원문 직접 열람 실패 — 이 세션 네트워크가 해당 도메인을 막음) / C = 커뮤니티·언론 출처, 공식 미확인. **B·C 는 운영 전에 원문으로 다시 확인할 것.**

## 요약

| 기능 | 지금 가능 | 승인·조건 필요 | 현재 불가 | 구현 상태 |
|---|---|---|---|---|
| 쇼핑 관심도 트렌드 | 기존 네이버 키 보유 시 DataLab | 신규는 NCP API HUB 가입 | — | 어댑터 구현(개발자센터·HUB 두 방식), 기본 mock |
| 검색어 트렌드 | 위와 동일 | 위와 동일 | — | 같은 어댑터 구조(쇼핑 우선 구현) |
| 상품 검색·메타데이터 | — | 쿠팡 최종 승인 후 API | 네이버 쇼핑 검색 API(종료) | 쿠팡 어댑터 구현 + 수동 입력 경로 |
| 제휴 링크 생성 | 파트너스 웹에서 수동 생성 | 딥링크 API(최종 승인 후) | — | 수동 등록·형식 검증·사람 확인 |
| 제휴 실적 | 파트너스 대시보드 CSV | 리포트 API(최종 승인 후) | — | CSV 적재 + API 어댑터 |
| Google Trends | — | 알파(허용 계정만) | 비공식 pytrends(사용 안 함) | 미연동 → 수동 CSV |
| Instagram Reels 게시 | 프로페셔널 계정 + 앱 Standard Access(내 계정) | 공개 영상 URL 호스팅 | — | 어댑터 구현, 자격증명 없으면 대기 |
| YouTube Shorts 업로드 | OAuth 앱 + 내 채널 | — | Shorts 전용 필드 없음 | 어댑터 구현, 자격증명 없으면 대기 |
| 성과 지표 | IG Insights, YouTube Analytics | 각 OAuth 권한 | IG 릴스 단위 프로필 방문 지표 없음 | 어댑터 구현 + CSV |
| 대본 생성 LLM | Anthropic API (키 필요) | — | — | 구현(구조화 출력·비용 상한), 기본 mock |
| 이미지 생성 | 로컬 Pillow | OpenAI 이미지·Higgsfield API(유료) | gpt-image-1(2026-10-23 종료) | 로컬만 구현, 생성 도구는 수동 가져오기 |
| TTS | 사용자 녹음 파일 | — | OpenAI TTS 3종 2027-01-06 종료 예정 | 무음+자막 / 사용자 파일 |

## 상세

### 네이버 데이터랩 쇼핑인사이트 — 확인 A
- `POST https://openapi.naver.com/v1/datalab/shopping/` 아래 `categories`, `category/device|gender|age`, `category/keywords`, `category/keyword/device|gender|age`.
- 요청: `startDate`·`endDate`(2017-08-01부터), `timeUnit` date/week/month, `category`, `keyword[]`(최대 5쌍, 쌍당 검색어 1개), 선택 `device`·`gender`·`ages`.
- **일 1,000회**. 응답 `ratio` = 구간 최댓값 100 기준 상대값.
- **신규 신청 종료 2026-07-30 → NCP NAVER API HUB 이관. 기존 이용자 2027-06-30까지.** (약관 2026-10-07 개정 부칙)
- API HUB(확인 B): 헤더 `X-NCP-APIGW-API-KEY-ID`·`X-NCP-APIGW-API-KEY`, DataLab API 당 월 50,000회. 정확한 엔드포인트 경로는 HUB 콘솔에서 확인 → `NAVER_APIHUB_BASE_URL`.
- 대분류 코드: 문서에 목록 없음(쇼핑 URL 의 `cat_id` 로 확인하라고 안내). `config/categories.toml` 의 50000004·50000008 은 **실호출 전 재확인 필요**.
- 구현: `adapters/naver/datalab.py` — 묶음마다 anchor 키워드 포함 후 anchor 평균=50 으로 재척도.

### 네이버 검색 트렌드 — 확인 A
- `POST /v1/datalab/search`, `keywordGroups` 최대 5그룹 × 그룹당 20개, 2016-01-01부터, 일 1,000회. 이관 일정 동일.

### 네이버 쇼핑 검색 API — 확인 A
- **2026-07-31 서비스 종료**(기존 이용자 포함). 종료 전 약관도 결과의 저장·캐싱·가공, **AI 입력·학습** 금지. → 사용하지 않음.

### Google Trends API — 확인 B
- 2025-07 알파 발표, 신청 양식으로 제한 허용, 문서도 허용 계정만 열람. 2026-11 현재 정식 출시 근거 없음. 한국 지원 여부 미확인. pytrends 는 비공식·보관(archived). → 미연동, `data/manual/trends.csv` 수동 입력.

### 쿠팡파트너스 Open API — 확인 B/C
- 접근(B): **최종 승인** 필요. 누적 판매 15만 원 이상이면 최종 승인 심사 자동 시작(활동 페이지와 판매 발생 페이지 일치, 광고 표시 적정성 확인). 반려 1위 사유: 광고 고지 누락.
- 기능(B): 상품 API(골드박스 등)·딥링크 API·리포팅 API.
- 인증(C): `Authorization: CEA algorithm=HmacSHA256, access-key=…, signed-date=yyMMdd'T'HHmmss'Z', signature=hex(HMAC-SHA256(signed-date+METHOD+path+query))` — 커뮤니티 SDK 기준, 공식 원문 미확인. `adapters/coupang/partners.py` 에 구현·단위테스트.
- 한도(C): 검색 시간당 10회(블로그·GitHub). 리포트 조회 최대 30일 범위, 매일 15시경 갱신.
- `subId`(C): 상품·리포트 호출 선택 파라미터. 리포트가 subId 별로 나뉘는지 미확인 → 콘텐츠별 귀속은 sub_id 가 있을 때만.
- 재고 필드: **찾지 못함** → 재고는 사람이 확인(관리자 '판매처에서 지금 확인함').
- 수수료(B): 기본 3%, 삼성·애플 스마트폰 1%, 보증 서비스 제외. **클릭 후 24시간 내 다른 상품 구매도 인정.** 본인 구매·직접 복사 URL·쿠팡 공유 버튼 경유 클릭은 제외.
- 정산(B): 최종 승인 + 월 1만 원 이상. 개인은 사업소득(원천징수 후 지급, 세율은 원문 확인 필요), 2개월 뒤 15일 지급. 월 상한 3천만 원.

### Instagram (Instagram API with Instagram Login) — 확인 B
- `graph.instagram.com`, 프로페셔널 계정(비즈니스·크리에이터), 페이스북 페이지 불필요, 권한 `instagram_business_basic`·`instagram_business_content_publish`.
- **내 계정만 쓰는 앱은 Standard Access 로 App Review 불필요**(일부 기능 제한 경고).
- `video_url` 은 공개 서버 URL(Meta 가 직접 가져감) → `SCF_PUBLIC_MEDIA_BASE_URL` 또는 공개 도메인의 `/media`.
- REELS: MP4/MOV, H.264/HEVC, AAC 128kbps, 23–60fps, 9:16 권장, 3초~15분·300MB(다른 문서 60초·100MB — 충돌, 우리 영상 28초·약 2.3MB 로 양쪽 만족).
- 게시 한도 24시간 50 또는 100건(문서 간 충돌) → `content_publishing_limit` 으로 확인.
- 컨테이너 `status_code`: IN_PROGRESS → FINISHED / ERROR / EXPIRED(24h). 1분 간격, 최대 5분 폴링 권장.
- `is_ai_generated=true` 로 AI 정보 라벨(2026-06), `trial_params` 체험 릴스(2025-12).
- 인사이트: `views, reach, likes, comments, saved, shares, total_interactions, ig_reels_avg_watch_time, ig_reels_video_view_total_time`. `plays`·`impressions` 폐기(2025-04-21). 최대 48시간 지연, 데이터 없으면 빈 배열. **릴스 단위 프로필 방문 지표 없음.**

### YouTube Data API v3 — 확인 B
- `videos.insert`: 2026-06-01부터 별도 'Video Uploads' 쿼터, **기본 하루 100회**.
- **2026-11-02 revision: 미검증 프로젝트 업로드의 비공개 고정 해제**(2020-07-28 규칙 폐지). 다만 Videos 리소스 문서에는 옛 문구가 남아 있음 → 업로드 후 `videos.list` 로 공개 상태 재확인(구현됨).
- 범위: `youtube.upload`(최소 권한).
- `status.containsSyntheticMedia`(실사형 합성 고지), `status.selfDeclaredMadeForKids`.
- `paidProductPlacementDetails.hasPaidProductPlacement`: **2026-11-16부터 기본값 false 아님 → 명시 지정**. 일반 프로젝트 쓰기 가능 여부 모호 → 거절 시 필드 없이 재시도하고 'Studio 수동 체크' 표시(구현됨).
- Shorts: 3분 이하 + 세로/정사각. 전용 필드 없음.
- Analytics: `views`(2025-03-31부터 Shorts 재생·반복 모두 포함), `engagedViews`, `averageViewDuration`, `averageViewPercentage`, `likes`, `shares`, `subscribersGained`. 지연 48~72시간. `creatorContentType=SHORTS` 로 분리.

### Anthropic API — 확인 A(스킬 문서 캐시 2026-11-03)
- `claude-opus-5-5` 입력 $4 / 출력 $20 (100만 토큰당). 구조화 출력 `output_config.format`, 거절 시 서버측 `fallbacks="default"`(beta `server-side-fallback-2026-07-01`).

### OpenAI — 모델 상태 A, 가격 B
- `gpt-image-1` **2026-10-23 종료**. 현행 gpt-image-1.5 / 2 / 2.5 / 2.6.
- 가격(B, 스니펫 충돌 있음): gpt-image-2 세로 medium 약 $0.041, high 약 $0.165 / gpt-image-1.5 1024×1536 medium $0.05.
- TTS `tts-1`·`tts-1-hd`·`gpt-4o-mini-tts` **2027-01-06 종료 예정** → 채택 안 함. 정책상 AI 음성임을 청취자에게 고지 필요.

### Higgsfield — 확인 B
- 웹·MCP 와 별도 REST API(`api.higgsfield.ai`, `Authorization: Key ID:SECRET`), 비동기 작업.
- 선불 USD 잔액(최소 $5), 영상 초당·이미지 장당 과금, 성공분만 과금, 웹 요금제 크레딧과 별개.
- 생성물 소유권 주장 없음(상업 이용 가능), **기본적으로 사용자 콘텐츠를 학습에 사용**(Enterprise 제외).
- 구현: API 연동하지 않음. Higgsfield 에서 만든 배경·장면을 파일로 가져와 `rights=ai_generated` 로 등록하는 방식 권장(상품 자체는 생성하지 않음).

## 원문 재확인이 필요한 항목 (운영 전 체크)
1. 쿠팡 Open API 공식 인증 규격·엔드포인트·호출 한도·subId 리포트 분리.
2. 쿠팡 상품 이미지 사용·편집 허용 범위, 링크 단축·리디렉션 금지 조항, 원천징수율.
3. 쿠팡 고지 문구 최신 표기('게시물' vs '포스팅').
4. Instagram 게시 한도(50/100), REELS 길이·용량 문서 충돌, 유료 파트너십 라벨의 API 지정 가능 여부.
5. YouTube `hasPaidProductPlacement` 쓰기 가능 여부.
6. 네이버 쇼핑 대분류 코드, API HUB 엔드포인트·요금.
