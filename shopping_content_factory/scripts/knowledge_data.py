"""SCF 지식체계 — 지금까지의 모든 내용(요구·구현·검증·근거·판단·진행)을 하나의 온톨로지로.

도메인 개념·관계·자동화 액션·결정·기획 수정안은 ontology_data.py 를 그대로 가져오고(단일 원본),
여기에는 나머지 지식 층을 적는다. `python scripts/build_knowledge.py --rev NN` 이
HTML·md(KNOWLEDGE_BASE, PROGRESS)·JSON·Turtle(RDF) 을 만든다.

상태 값
- 산출물(Deliverable): done 완료 / partial 부분 / todo 미착수
- 완료 기준(Criterion): pass 통과 / caveat 통과(단서 있음) / fail
- 단계(Phase): done / partial / active 진행 중 / todo
- 결함(Defect): open / fixed · 종류: defect 결함 / gap 설계 약점
- 사실(Fact) 확인 수준: A 공식 원문 / B 공식 페이지 검색 색인 발췌 / C 커뮤니티·언론
- 리스크(Risk) 수준: 상 / 중 / 하
- 가정(Assumption) 출처: 사용자 / 판단값 / mock / 추정
"""

AS_OF = "2026-11-21"
NS = "https://example.invalid/scf/ontology#"   # 내부 식별용 네임스페이스(공개 주소 아님)

CLASSES = [
    # id, 라벨, 설명, 그룹(지도 배치 행)
    ("Deliverable", "산출물", "요구서 16장 최종 산출물 20개", "goal"),
    ("Criterion", "완료 기준", "요구서 17장 MVP 완료 판정 15개", "goal"),
    ("Phase", "단계", "PHASE 1~5 · STEP 1~10 · 수정 로드맵", "goal"),
    ("PlanChange", "기획 수정안", "원 기획 대비 수정", "goal"),
    ("Concept", "도메인 개념", "시스템이 다루는 업무 개념(도메인 온톨로지)", "system"),
    ("Component", "구현 요소", "코드·설정·스크립트 모듈", "system"),
    ("Verification", "검증", "pytest·브라우저 점검·시뮬레이션·재현", "system"),
    ("Evidence", "증거", "실행 결과물·재현 기록", "system"),
    ("Document", "문서", "README 와 docs/", "system"),
    ("Action", "자동화 액션", "6계층 자동화 액션", "system"),
    ("Party", "외부 주체", "플랫폼·기관·전문가·고용주·운영자", "judge"),
    ("Fact", "사실", "조사로 확인한 외부 사실(확인 수준 A/B/C)", "judge"),
    ("Regulation", "정책·규정", "법·심사지침·플랫폼 정책·약관", "judge"),
    ("Assumption", "가정", "재무·운영 가정과 판단값", "judge"),
    ("Risk", "리스크", "사업·운영·정책 위험", "judge"),
    ("Defect", "결함·약점", "확인된 결함과 설계상 약점", "judge"),
    ("Decision", "결정", "사용자가 정할 것", "judge"),
    ("Metric", "지표", "측정할 숫자", "judge"),
]

# 관계 유형: id, 라벨, 정의역(주어 클래스), 치역(목적어 클래스)
PROPERTIES = [
    ("realizes", "충족한다", ["Component"], ["Deliverable"]),
    ("implements", "구현한다", ["Component"], ["Concept"]),
    ("verifies", "검증한다", ["Verification"], ["Criterion", "Component", "Defect", "Deliverable"]),
    ("produces", "산출한다", ["Verification", "Component"], ["Evidence"]),
    ("describes", "기술한다", ["Document"], ["*"]),
    ("sourcedFrom", "출처", ["Fact", "Regulation"], ["Party"]),
    ("supports", "근거가 된다", ["Fact", "Evidence", "Assumption"], ["Risk", "Decision", "Defect", "Concept", "Regulation", "PlanChange", "Assumption"]),
    ("constrains", "제약한다", ["Regulation"], ["Concept", "Component", "Phase"]),
    ("feeds", "입력된다", ["Assumption"], ["Metric", "Component", "Concept", "Phase"]),
    ("threatens", "위협한다", ["Risk"], ["Concept", "Metric", "Phase"]),
    ("mitigatedBy", "완화된다", ["Risk"], ["Decision", "Component", "Action"]),
    ("affects", "영향을 준다", ["Defect"], ["Concept", "Component", "Criterion"]),
    ("resolvedBy", "해결된다", ["Defect"], ["Decision", "Document"]),
    ("foundBy", "발견됐다", ["Defect"], ["Evidence", "Verification"]),
    ("impacts", "영향 범위", ["Decision"], ["Concept"]),
    ("gates", "선행 조건이다", ["Decision"], ["Phase"]),
    ("decidedBy", "결정 주체", ["Decision"], ["Party"]),
    ("targets", "대상", ["Action"], ["Concept"]),
    ("dependsOn", "필요로 한다", ["Action", "PlanChange"], ["Decision"]),
    ("partOf", "속한다", ["Phase"], ["Phase"]),
    ("deliveredIn", "만든 단계", ["Deliverable"], ["Phase"]),
    ("measures", "측정한다", ["Metric"], ["Concept"]),
    ("provides", "제공한다", ["Party"], ["Concept"]),
    ("domain", "도메인 관계", ["Concept"], ["Concept"]),   # 세부 술어는 ontology_data.EDGES 의 한국어 관계명
]

# 도메인 관계(한국어) → RDF 속성 이름
DOMAIN_PRED = {
    "공급한다": "supplies", "드러낸다": "reveals", "속한다": "belongsTo", "겪는다": "experiences",
    "가로막힌다": "blockedBy", "자극한다": "stimulates", "해결한다": "solves", "연결된다": "linkedTo",
    "가진다": "has", "확인된다": "checkedBy", "뒷받침한다": "backs", "해소한다": "relieves", "평가한다": "evaluates",
    "근거로 한다": "basedOn", "판정한다": "judges", "확인한다": "checks", "고른다": "selects", "만든다": "creates",
    "다룬다": "covers", "인용한다": "cites", "보여준다": "shows", "사용한다": "uses", "바꾼다": "varies",
    "붙는다": "attachedTo", "렌더된다": "renderedFrom", "합성한다": "composites", "검사한다": "inspects",
    "허가한다": "authorizes", "올린다": "uploads", "향한다": "targetsPlatform", "요구한다": "requiresGate",
    "연결한다": "connects", "포함한다": "includes", "유입시킨다": "drivesTrafficTo", "측정한다": "measuresEvent",
    "발생한다": "occursOn", "귀속된다": "attributedTo", "집계한다": "aggregates", "읽는다": "reads",
    "보정한다": "calibrates", "제약한다": "constrainsRule", "정의한다": "defines", "실행한다": "executes",
    "제한한다": "limits", "기록한다": "records",
}

# ---------------------------------------------------------------- 단계
PHASES = [
    # id, 라벨, 상태, 설명, 상위
    ("PH1", "PHASE 1 실행 가능성 검증", "done", "API·권한·가격·정책 조사, 4개 보고서", None),
    ("PH2", "PHASE 2 mock MVP", "done", "외부 키 없이 전 구간 실행 — 결함 9건 미수정(7건은 D2 수정 묶음)", None),
    ("PH3", "PHASE 3 실제 서비스 연결", "todo", "권한 확보 순서대로 하나씩 — 실호출 0건", None),
    ("PH4", "PHASE 4 사업성 검증(30개)", "todo", "첫 30개 실측", None),
    ("PH5", "PHASE 5 운영 자동화 확대", "todo", "실측 수익 확인 후에만", None),
    ("ST1", "STEP 1 사업 결점 분석", "done", "BUSINESS_RISK_ANALYSIS", "PH1"),
    ("ST2", "STEP 2 API·정책 조사", "done", "B·C 등급 원문 재확인 6건 남음", "PH1"),
    ("ST3", "STEP 3 MVP 범위 확정", "done", "FEASIBILITY_REPORT 2절", "PH1"),
    ("ST4", "STEP 4 구조·DB 스키마", "done", "DB_SCHEMA", "PH2"),
    ("ST5", "STEP 5 코드 작성", "done", "약 8,500줄(파이썬)", "PH2"),
    ("ST6", "STEP 6 mock 수직 통합", "done", "트렌드 → 승인 대기까지", "PH2"),
    ("ST7", "STEP 7 영상·랜딩 생성·테스트", "done", "데모 C20261118-01", "PH2"),
    ("ST8", "STEP 8 실제 API 연결", "todo", "자격증명 없음", "PH3"),
    ("ST9", "STEP 9 반복 실행·복구·검수 검증", "partial", "가상 운영 30일 수행 → 결함 발견, 미수정", "PH2"),
    ("ST10", "STEP 10 문서화", "done", "문서 19종, 변경 이력 운영 중", "PH2"),
    ("RM1", "P2.5 착수 준비", "active", "이번 주 결정 7건 + 결함 수정 + 등록 화면", "PH3"),
    ("RM2", "P3a 30개 실험", "todo", "주 5개 × 6주 또는 1일 1개(D20)", "PH4"),
    ("RM3", "G1 판정 게이트", "todo", "확대 / 채널 전환 / 중단", "PH4"),
    ("RM4", "P3b API 연동", "todo", "YouTube → Instagram → 쿠팡 API", "PH3"),
    ("RM5", "P4 이후 확대", "todo", "조건부 승인 자동화·학습 보정·대체 채널", "PH5"),
]

# ---------------------------------------------------------------- 구현 요소
COMPONENTS = [
    # id, 라벨, 경로(매핑용 접두어들), 설명
    ("CP01", "설정 진입점", ["config/settings.py"], "환경변수·경로·안전장치 기본값"),
    ("CP02", "정책 설정(TOML)", ["config/", "config/*.toml"], "배점·금칙어·광고 표시·재무 가정·단가·카테고리"),
    ("CP03", "공통 모듈", ["services/common/"], "DB·HTTP 재시도·비용 상한·비밀값 마스킹·사실 해시"),
    ("CP04", "네이버 어댑터", ["adapters/naver/"], "DataLab(개발자센터·API HUB) + mock"),
    ("CP05", "쿠팡 어댑터", ["adapters/coupang/"], "Partners HMAC·카탈로그(mock·수동·검색)"),
    ("CP06", "Instagram 어댑터", ["adapters/instagram/"], "Reels 게시·인사이트"),
    ("CP07", "YouTube 어댑터", ["adapters/youtube/"], "업로드·공개 확인·Analytics"),
    ("CP08", "Claude 클라이언트", ["adapters/llm/"], "구조화 출력·비용 기록·거절 대체"),
    ("CP09", "음성 공급", ["adapters/tts/"], "무음·사용자 녹음"),
    ("CP10", "트렌드 수집기", ["services/trend_collector/"], "정규화·급상승·화제성 제외"),
    ("CP11", "후보 발굴", ["services/product_discovery/"], "중복 제거·DB 반영"),
    ("CP12", "평가·선정 엔진", ["services/product_scoring/"], "100점·필수 필터·상위 5·재검증"),
    ("CP13", "구매심리 엔진", ["services/psychology_engine/"], "10문항·심리요소·프롬프트"),
    ("CP14", "대본·사실 검사", ["services/script_generator/"], "대본 A/B·캡션·fact_guard"),
    ("CP15", "이미지 생성", ["services/image_generator/"], "이미지 6종·원형 보존 검수"),
    ("CP16", "영상 렌더·QA", ["services/video_renderer/"], "Pillow→FFmpeg·자막·자동 QA"),
    ("CP17", "제휴 링크", ["services/affiliate_links/"], "형식 검증·수동 등록·고지 검사"),
    ("CP18", "게시·검수", ["services/social_publishers/"], "게이트·중복 방지·승인·삭제"),
    ("CP19", "분석·재무", ["services/analytics/"], "퍼널·CSV 적재·학습·재무·시뮬레이션·보고서"),
    ("CP20", "작업 큐", ["workflows/pipeline.py"], "job_runs·재시도·상류 건너뜀·잠금"),
    ("CP21", "스케줄러·cron·n8n", ["workflows/scheduler.py", "workflows/"], "상시 루프·cron 예시·n8n JSON"),
    ("CP22", "랜딩 페이지", ["app/routes/public.py", "app/templates/public/", "app/static/js/"], "공개 상품 페이지·이벤트"),
    ("CP23", "관리자 화면", ["app/routes/admin.py", "app/templates/admin/"], "검수·링크·권리·성과·비용"),
    ("CP24", "운영 API", ["app/routes/api.py"], "/api/jobs/run · /api/health"),
    ("CP25", "DB 스키마", ["app/models/"], "18개 테이블(SQLAlchemy)"),
    ("CP26", "CLI(scf.py)", ["scf.py"], "실행·승인·게시·적재·시뮬레이션·삭제"),
    ("CP27", "온톨로지 생성기", ["scripts/build_ontology.py", "scripts/ontology_data.py", "scripts/ontology_template.html"], "도메인 지도 HTML·md 자동 구간"),
    ("CP28", "가상 운영 시뮬레이터", ["scripts/simulate_operations.py"], "N일 임시 운영·막힌 곳 기록"),
    ("CP29", "브라우저 점검 스크립트", ["scripts/e2e_check.mjs", "scripts/check_ontology_html.mjs", "scripts/check_knowledge_html.mjs"], "콘솔 오류·넘침·겹침"),
    ("CP30", "배포 구성", ["Dockerfile", "docker-compose.yml", "wsgi.py"], "gunicorn·compose(빌드 미검증)"),
    ("CP31", "DEMO 데이터", ["data/mock/"], "가상 상품 24·트렌드 28"),
    ("CP32", "폰트", ["assets/fonts/"], "Pretendard(OFL)"),
    ("CP33", "지식체계 생성기", ["scripts/build_knowledge.py", "scripts/knowledge_data.py", "scripts/knowledge_template.html"], "이 지식체계 HTML·md·RDF"),
]

# ---------------------------------------------------------------- 산출물 (요구서 16장)
DELIVERABLES = [
    # id, 라벨, 상태, 메모, 구현 요소, 단계
    ("DL01", "실행 가능한 Python 소스코드", "done", "mock 기준 전 구간 실행", ["CP26", "CP20"], "ST5"),
    ("DL02", "Flask 관리자 대시보드", "done", "8개 화면 · 모바일 승인 점검 전", ["CP23"], "ST5"),
    ("DL03", "상품 트렌드 수집기", "partial", "mock 완료 · 실데이터 키 대기", ["CP10", "CP04"], "ST5"),
    ("DL04", "상품 점수화 엔진", "done", "가중치는 판단값(보정 전)", ["CP12"], "ST5"),
    ("DL05", "구매심리 분석 프롬프트", "done", "Claude 실호출 미검증", ["CP13"], "ST5"),
    ("DL06", "영상 대본 생성 엔진", "done", "규칙 기반 · LLM 경로 가짜 응답 테스트만", ["CP14"], "ST5"),
    ("DL07", "이미지 제작 파이프라인", "partial", "데모 완료 · 실상품은 범용 배경", ["CP15"], "ST7"),
    ("DL08", "FFmpeg 영상 렌더러", "done", "1080×1920 28초 2종", ["CP16"], "ST7"),
    ("DL09", "상품 랜딩페이지", "done", "호스팅 대기(D6)", ["CP22"], "ST7"),
    ("DL10", "쿠팡파트너스 연동 모듈", "partial", "수동 링크 완료 · API 실호출 0 · API 모드 후보 전부 보류", ["CP05", "CP17"], "ST5"),
    ("DL11", "Instagram·YouTube 게시 어댑터", "partial", "코드 완료 · 실호출 0", ["CP06", "CP07", "CP18"], "ST5"),
    ("DL12", "성과 분석 대시보드", "done", "실측 데이터 없음", ["CP19", "CP23"], "ST5"),
    ("DL13", "n8n 워크플로 또는 대체 스케줄러", "partial", "동작함 · 실행 시각 코드 고정 · n8n 가져오기 미검증", ["CP21"], "ST5"),
    ("DL14", "환경변수 템플릿", "done", ".env.example", ["CP01"], "ST5"),
    ("DL15", "설치·실행 매뉴얼", "done", "신규 환경 재현 확인", ["CP26"], "ST10"),
    ("DL16", "자동화 장애 대응 매뉴얼", "done", "RUNBOOK REV03", [], "ST10"),
    ("DL17", "pytest 테스트", "done", "78개 통과(지식체계 4 포함)", [], "ST7"),
    ("DL18", "데모 콘텐츠 1개", "done", "C20261118-01", ["CP15", "CP16"], "ST7"),
    ("DL19", "12개월 수익 시뮬레이션", "done", "3 시나리오 + 손익분기", ["CP19"], "ST1"),
    ("DL20", "운영 비용·ROI 리포트", "done", "COST_MODEL + ROI_REPORT", ["CP19"], "ST3"),
]

# ---------------------------------------------------------------- 완료 기준 (요구서 17장)
CRITERIA = [
    # id, 라벨, 상태, 단서, 검증
    ("CR01", "mock 상품 20개 이상 수집", "pass", "", ["V01"]),
    ("CR02", "100점 점수 계산", "pass", "", ["V02"]),
    ("CR03", "선정 과정 기록", "pass", "", ["V02"]),
    ("CR04", "사실과 다르면 게시 차단", "caveat", "숫자 없는 과장은 못 잡음 · 상품명 숫자 오탐 · 수동 모드 가격 만료 검사 무력화", ["V03", "V05"]),
    ("CR05", "권리 불확실 이미지 차단", "pass", "", ["V04"]),
    ("CR06", "대본·이미지 저장", "pass", "", ["V04"]),
    ("CR07", "실행 가능한 MP4", "pass", "", ["V04", "V16"]),
    ("CR08", "랜딩 상품정보 정상 표시", "pass", "", ["V08", "V12"]),
    ("CR09", "미승인 콘텐츠 게시 안 됨", "pass", "", ["V05", "V08"]),
    ("CR10", "중복 실행에도 중복 업로드 없음", "pass", "", ["V05", "V10"]),
    ("CR11", "클릭·매출 실측·추정 구분", "pass", "", ["V07"]),
    ("CR12", "금융 계산 단위테스트", "pass", "", ["V06"]),
    ("CR13", "API 비용·실패 로그", "caveat", "실패 '알림'은 없음(대시보드 확인만)", ["V10", "V09"]),
    ("CR14", "비밀키 미노출", "pass", "", ["V09"]),
    ("CR15", "README 로 신규 환경 실행", "caveat", "Docker 빌드는 미검증", ["V15"]),
]

# ---------------------------------------------------------------- 검증
VERIFICATIONS = [
    # id, 라벨, 수(테스트 수 등), 설명, 검증 대상 구성요소
    ("V01", "test_trends_discovery", 5, "트렌드 수집·후보 20개·기준 키워드 재척도", ["CP10", "CP11", "CP04"]),
    ("V02", "test_scoring", 6, "100점·필수 필터·보수적 부여·선정 기록", ["CP12"]),
    ("V03", "test_fact_guard", 6, "사양 불일치·금칙어·광고 표시·사실 변경 차단", ["CP14"]),
    ("V04", "test_media", 7, "산출물·MP4 규격·원형 보존·권리 차단", ["CP15", "CP16"]),
    ("V05", "test_publish_gate", 10, "미승인·링크·자격증명·중복·상태 분리", ["CP18", "CP17"]),
    ("V06", "test_finance", 6, "산식 손계산 검산·시뮬레이션", ["CP19"]),
    ("V07", "test_analytics", 5, "실측·추정·미귀속·CSV 품질", ["CP19"]),
    ("V08", "test_landing_admin", 11, "랜딩·관리자·CSRF·삭제", ["CP22", "CP23", "CP24"]),
    ("V09", "test_security", 4, "로그 마스킹·하드코딩 키·.env", ["CP03"]),
    ("V10", "test_jobs", 7, "작업 큐·재시도·비용 상한·Claude 가짜 응답", ["CP20", "CP08", "CP03"]),
    ("V11", "test_adapters", 7, "재시도·HMAC·미설정·IG 상태 분리", ["CP04", "CP05", "CP06", "CP07", "CP09"]),
    ("V12", "브라우저 E2E 10화면", 10, "콘솔 오류·가로 넘침·필수 요소", ["CP22", "CP23"]),
    ("V13", "온톨로지 HTML 점검", 1, "글자 넘침·겹침·라벨 겹침 0", ["CP27"]),
    ("V14", "가상 운영 30일", 30, "임시 DB 로 30일 운영", ["CP28", "CP20", "CP12"]),
    ("V15", "신규 환경 재현", 1, "새 폴더·새 venv 에서 README 절차", ["CP26"]),
    ("V16", "영상 프레임 육안 검토", 7, "줄바꿈·배경·썸네일", ["CP16", "CP15"]),
    ("V17", "결함 재현 스크립트", 3, "running 고착·수동 가격 ①②", ["CP20", "CP11"]),
    ("V18", "지식체계 HTML 점검", 1, "이 문서의 넘침·겹침·탐색", ["CP33"]),
    ("V19", "test_knowledge", 4, "지식체계 참조·정의역·치역·상태·요약", ["CP33"]),
]

# ---------------------------------------------------------------- 증거
EVIDENCE = [
    ("E01", "데모 콘텐츠 C20261118-01", "demo/C20261118-01 — 영상 2·이미지 8·대본·자막·매니페스트", ["V04", "V16"]),
    ("E02", "화면 캡처 10장", "demo/screenshots — 랜딩 390·1366, 관리자 6화면", ["V12"]),
    ("E03", "pytest 78개 통과", "2026-11-21 실행", ["V01", "V02", "V03", "V04", "V05", "V06", "V07", "V08", "V09", "V10", "V11", "V19"]),
    ("E04", "신규 환경 실행 기록", "설치 → run-daily 약 79초 → 74 통과 → 랜딩 표시", ["V15"]),
    ("E05", "가상 운영 30일 결과", "D1~D10 제작, D7 오탐 차단, D11 고갈 후 20일 미제작, 10개 중 9개 범용 배경", ["V14"]),
    ("E06", "running 고착 재현", "일반 실행·--force 모두 running_elsewhere → 수동 회수 후 복구", ["V17"]),
    ("E07", "수동 가격 결함 재현", "① 3일 전 확인 → 0.0시간 ② 25,000원 재확인 → 19,900원", ["V17"]),
    ("E08", "온톨로지 HTML 점검 결과", "REV02 — 넘침·겹침·라벨 겹침 0, 가로 넘침 0", ["V13"]),
    ("E09", "외부 조사 보고 3건", "공식 도메인 직접 열람 실패 → 검색 색인 발췌·공식 저장소 원문", []),
    ("E12", "RDF 검증", "rdflib 파싱 2,648 트리플 · SPARQL 예시 2개 결과 확인", ["V18"]),
    ("E10", "12개월 시뮬레이션 표", "docs/ROI_REPORT.md — 기준 ROE −244%, 손익분기 콘텐츠당 약 12만 조회", []),
    ("E11", "프레임 검토 후 수정", "후킹 줄바꿈·사양 칩 비침·엔드카드 중복 상품·썸네일 배치 수정", ["V16"]),
]

# ---------------------------------------------------------------- 문서
DOCUMENTS = [
    ("DOC01", "README.md", "README.md", "설치·실행·구조·완료 기준 매핑·알려진 결함"),
    ("DOC02", "문서 지도", "docs/README.md", "읽는 순서·갱신 규칙"),
    ("DOC03", "사업 리스크 분석", "docs/BUSINESS_RISK_ANALYSIS.md", "STEP 1 + 자체 검토·가상 운영 결함"),
    ("DOC04", "실행 가능성 보고서", "docs/FEASIBILITY_REPORT.md", "가능/승인 필요/불가·MVP 범위"),
    ("DOC05", "API 접근 매트릭스", "docs/API_ACCESS_MATRIX.md", "외부 API 조건·확인 수준"),
    ("DOC06", "컴플라이언스 체크리스트", "docs/COMPLIANCE_CHECKLIST.md", "광고 표시·사실성·플랫폼·개인정보"),
    ("DOC07", "비용 모델", "docs/COST_MODEL.md", "콘텐츠당·월 비용·LLM 모델별"),
    ("DOC08", "ROI 리포트", "docs/ROI_REPORT.md", "12개월 3 시나리오·손익분기"),
    ("DOC09", "DB 스키마", "docs/DB_SCHEMA.md", "테이블·상태 전이"),
    ("DOC10", "구매심리 프롬프트", "docs/PSYCHOLOGY_PROMPTS.md", "프롬프트·검증 규칙·예시"),
    ("DOC11", "장애 대응", "docs/RUNBOOK.md", "상태별 조치·임시 복구"),
    ("DOC12", "결정 사항", "docs/DECISIONS.md", "결정 20건·결정 기록"),
    ("DOC13", "자동화 재검토", "docs/AUTOMATION_REVIEW.md", "착수 4문항·액션 지도·로드맵"),
    ("DOC14", "도메인 온톨로지", "docs/ONTOLOGY.md", "개념 36·관계 60"),
    ("DOC15", "가상 운영 점검", "docs/VIRTUAL_OPERATION.md", "30일 결과·방해 요소·필요한 도움"),
    ("DOC16", "도메인 지도 HTML", "docs/SCF_온톨로지_REV02.html", "개념·자동화 지도(REV01 보존)"),
    ("DOC17", "지식체계", "docs/KNOWLEDGE_BASE.md", "이 지식체계의 텍스트판"),
    ("DOC18", "진행 현황", "docs/PROGRESS.md", "단계·산출물·결정·결함·작업 기록"),
    ("DOC19", "지식체계 HTML", "docs/SCF_지식체계_REV01.html", "진행·지식 지도·탐색기·추적표"),
]

# ---------------------------------------------------------------- 외부 주체
PARTIES = [
    ("P_USER", "운영자(사용자)", "결정·승인·계정 명의·실촬영·결제"),
    ("P_COUPANG", "쿠팡파트너스", "제휴 링크·수수료·API(최종 승인 후)·약관"),
    ("P_NAVER", "네이버(개발자센터·NCP API HUB)", "DataLab 트렌드"),
    ("P_GOOGLE", "Google(Trends)", "Trends API 알파"),
    ("P_META", "Meta·Instagram", "Reels 게시·인사이트·브랜디드 콘텐츠·AI 라벨"),
    ("P_YOUTUBE", "YouTube", "Shorts 업로드·Analytics·쇼핑 제휴·정책"),
    ("P_ANTHROPIC", "Anthropic", "Claude API"),
    ("P_OPENAI", "OpenAI", "이미지·TTS(채택 안 함)"),
    ("P_HIGGS", "Higgsfield", "생성 이미지·영상(파일 가져오기 방식)"),
    ("P_FTC", "공정거래위원회", "추천·보증 표시광고 심사지침"),
    ("P_MSIT", "과기정통부·방미통위", "AI 기본법·AI 생성물 표시 제도"),
    ("P_TAX", "세무사", "사업소득·사업자등록"),
    ("P_LEGAL", "법률 검토자", "개인정보 처리방침·광고 고지"),
    ("P_EMPLOYER", "본업 회사", "취업규칙(겸업·영리활동)"),
    ("P_CONSUMER", "시청자·구매자", "조회·방문·클릭·구매"),
]
PARTY_PROVIDES = [
    ("P_NAVER", "keyword"), ("P_COUPANG", "product"), ("P_COUPANG", "link"), ("P_COUPANG", "report"),
    ("P_META", "platform"), ("P_META", "pmetric"), ("P_YOUTUBE", "platform"), ("P_YOUTUBE", "pmetric"),
    ("P_ANTHROPIC", "script"), ("P_CONSUMER", "event"), ("P_USER", "approval"), ("P_USER", "spec"),
    ("P_USER", "image"), ("P_USER", "usage"),
]

# ---------------------------------------------------------------- 사실 (확인 수준)
FACTS = [
    # id, 라벨, 확인 수준, 출처 주체, 근거가 되는 대상들
    ("F01", "DataLab 쇼핑인사이트: 일 1,000회, 요청당 키워드 5개, 값은 구간 최댓값 100 상대지수", "A", "P_NAVER", ["keyword"]),
    ("F02", "DataLab 신규 신청 2026-07-30 종료 → NCP API HUB, 기존 키 2027-06-30까지", "A", "P_NAVER", ["R05", "keyword"]),
    ("F03", "네이버 쇼핑 검색 API 2026-07-31 종료", "A", "P_NAVER", ["R05", "PC01"]),
    ("F04", "네이버 검색 API 결과 저장·캐싱·가공·AI 입력 금지(약관)", "A", "P_NAVER", ["G09", "R06"]),
    ("F05", "API HUB DataLab 월 50,000회", "B", "P_NAVER", ["keyword"]),
    ("F06", "Google Trends API 는 알파 — 허용 계정만", "B", "P_GOOGLE", ["keyword"]),
    ("F07", "쿠팡 API 키는 최종 승인 후 — 누적 판매 15만 원 이상에서 심사 시작", "B", "P_COUPANG", ["R05", "R18", "D11"]),
    ("F08", "쿠팡 기본 수수료 3%, 삼성·애플 스마트폰 1%", "B", "P_COUPANG", ["R03", "S03"]),
    ("F09", "쿠팡 클릭 후 24시간 내 다른 상품 구매도 인정", "B", "P_COUPANG", ["R03", "report"]),
    ("F10", "쿠팡 정산: 최종 승인 + 월 1만 원 이상, 2개월 뒤 15일, 개인은 사업소득", "B", "P_COUPANG", ["R18", "D15"]),
    ("F11", "쿠팡 고지 예시 '이 게시물은 쿠팡 파트너스 활동의 일환으로…', 반려 1위 사유는 고지 누락", "B", "P_COUPANG", ["disclosure", "R04"]),
    ("F12", "쿠팡 인증 HMAC 형식·subId 파라미터", "C", "P_COUPANG", ["link", "R13"]),
    ("F13", "쿠팡 검색 시간당 10회", "C", "P_COUPANG", ["K09"]),
    ("F14", "공정위 지침(2024-12 개정): '수수료를 지급받을 수 있음' 같은 조건부 표현은 명확한 표시 아님", "B", "P_FTC", ["G01", "disclosure", "R10"]),
    ("F15", "영상은 시작·끝·반복 표시, SNS 는 첫 부분, '더보기' 뒤 부적절, 해시태그는 첫 번째", "B", "P_FTC", ["G01", "disclosure"]),
    ("F16", "2026-06-01 AI 가상인물 '가상인물' 표시 의무", "B", "P_FTC", ["G01"]),
    ("F17", "AI 기본법(2026-01-22 시행) 표시 의무 주체는 AI 사업자 — 도구로 쓰는 개인 창작자는 의무 없음(가이드)", "B", "P_MSIT", ["G05"]),
    ("F18", "정보통신망법 AI 생성물 표시 개정안 미통과(2026-10-29 보도)", "C", "P_MSIT", ["G06"]),
    ("F19", "Instagram Login 경로: 페이스북 페이지 불필요, 내 계정만 쓰면 Standard Access", "B", "P_META", ["platform"]),
    ("F20", "Instagram 은 공개 URL 의 영상을 가져가서 게시", "B", "P_META", ["landing", "D6"]),
    ("F21", "Instagram 게시 한도 24시간 50 또는 100건(문서 충돌)", "B", "P_META", ["publication"]),
    ("F22", "Instagram is_ai_generated 라벨·trial_params 체험 릴스 지원", "B", "P_META", ["variant", "R07"]),
    ("F23", "Meta: 제3자 제휴 수수료 게시물은 유료 파트너십 라벨 사용 안내", "B", "P_META", ["G03", "R10"]),
    ("F24", "YouTube 업로드 쿼터 하루 100회(2026-06~)", "B", "P_YOUTUBE", ["publication"]),
    ("F25", "YouTube 미검증 프로젝트 비공개 고정 해제(2026-11-02)", "B", "P_YOUTUBE", ["publication"]),
    ("F26", "YouTube hasPaidProductPlacement 기본값 false 아님(2026-11-16)", "B", "P_YOUTUBE", ["G04", "publication"]),
    ("F27", "Shorts 설명란·댓글 링크 클릭 불가", "B", "P_YOUTUBE", ["R01", "platform"]),
    ("F28", "YouTube '진정성 없는 콘텐츠'(템플릿 대량생산) 정책(2025-07)", "B", "P_YOUTUBE", ["G04", "R08"]),
    ("F29", "YouTube 쇼핑 제휴(쿠팡) 2024-06 출시, YPP + 구독자 500(2026-03-30~), Shorts 상품 태그", "B", "P_YOUTUBE", ["D16", "R01"]),
    ("F30", "네이버 쇼핑커넥트 2025-07 정식 — 판매자가 수수료율 설정", "B", "P_NAVER", ["D16"]),
    ("F31", "YouTube Analytics 지연 48~72시간, Instagram 인사이트 최대 48시간", "B", "P_YOUTUBE", ["pmetric"]),
    ("F32", "Claude Opus 5.5 $4 / $20 (100만 토큰)", "A", "P_ANTHROPIC", ["D9", "cost"]),
    ("F33", "OpenAI gpt-image-1 종료(2026-10-23), TTS 3종 종료 예정(2027-01-06)", "A", "P_OPENAI", ["D8"]),
    ("F34", "Higgsfield REST API 선불 과금, 기본적으로 사용자 콘텐츠 학습 사용", "B", "P_HIGGS", ["D7"]),
]

# ---------------------------------------------------------------- 정책·규정
REGULATIONS = [
    # id, 라벨, 발행 주체, 제약 대상
    ("G01", "추천·보증 표시광고 심사지침", "P_FTC", ["disclosure", "check", "CP14"]),
    ("G02", "쿠팡파트너스 약관·운영정책", "P_COUPANG", ["link", "disclosure", "image"]),
    ("G03", "Meta 브랜디드 콘텐츠·AI 정보 라벨 정책", "P_META", ["publication", "platform"]),
    ("G04", "YouTube 유료 프로모션·합성 콘텐츠·진정성 정책", "P_YOUTUBE", ["media", "publication"]),
    ("G05", "AI 기본법", "P_MSIT", ["media"]),
    ("G06", "정보통신망법 AI 생성물 표시 개정안(미통과)", "P_MSIT", ["media"]),
    ("G07", "개인정보 보호법", "P_LEGAL", ["event", "landing"]),
    ("G08", "표시광고법(가격·효능 표시)", "P_FTC", ["check", "price"]),
    ("G09", "네이버 오픈 API 이용약관", "P_NAVER", ["keyword"]),
    ("G10", "소득세(사업소득)·사업자등록", "P_TAX", ["report"]),
    ("G11", "본업 회사 취업규칙(겸업·영리활동)", "P_EMPLOYER", ["RM1"]),
    ("G12", "SIL OFL 폰트 라이선스", "P_USER", ["CP32"]),
]

# ---------------------------------------------------------------- 가정
ASSUMPTIONS = [
    # id, 라벨, 출처 구분, 입력 대상
    ("S01", "초기 자기자본 500만 원", "사용자", ["M08"]),
    ("S02", "평균 인정 구매금액 65,000원", "사용자", ["M05"]),
    ("S03", "실효 수수료율 3%", "사용자", ["M05"]),
    ("S04", "초기 현금 구축비 100만 원", "사용자", ["M07"]),
    ("S05", "월 운영현금비 25만 원", "사용자", ["M07"]),
    ("S06", "창업자 노동 30시간/월 × 25,000원", "사용자", ["M07", "M09"]),
    ("S07", "퍼널 3 시나리오(보수 0.5%×20%×3% ~ 낙관 2%×40%×8%)", "판단값", ["M02", "M03", "M04"]),
    ("S08", "세율 6.6%", "판단값", ["M08"]),
    ("S09", "취소·반품 5%", "판단값", ["M05"]),
    ("S10", "100점 배점·임계값(근거 부족 30%, 최소 점수 55)", "판단값", ["CP12"]),
    ("S11", "중단 기준 '필요 조회수 > 실측 평균 3배'", "판단값", ["RM3"]),
    ("S12", "선정 가능 비율 약 42%(24개 중 10개)", "mock", ["M10"]),
    ("S13", "콘텐츠당 LLM 토큰 입력 8,500 / 출력 6,500", "추정", ["M11"]),
]

# ---------------------------------------------------------------- 리스크
RISKS = [
    # id, 라벨, 수준, 위협 대상, 완화(결정·구성요소·액션)
    ("R01", "퍼널 병목 — 조회에서 랜딩까지", "상", ["M02"], ["D6", "D16"]),
    ("R02", "노동 기회비용이 현금비의 3배", "상", ["M07", "M09"], ["D14", "D11", "D9"]),
    ("R03", "주문당 수수료가 작음(2만 원 상품 약 600원)", "중", ["M05"], ["D16"]),
    ("R04", "계정 단위 정책 위험(쿠팡 승인 반려·플랫폼)", "상", ["link", "platform"], ["CP14", "D1"]),
    ("R05", "API 접근 일정(쿠팡 승인·DataLab 이관)", "중", ["RM4"], ["D11"]),
    ("R06", "이미지 권리 불명", "상", ["image"], ["D7", "CP15"]),
    ("R07", "AI 연출의 오인·고지 누락", "중", ["media"], ["D7", "CP16"]),
    ("R08", "템플릿 대량생산으로 노출 억제", "상", ["media"], ["D7", "D8"]),
    ("R09", "A/B 판단 불가", "중", ["variant"], ["D12"]),
    ("R10", "광고 고지 위반", "상", ["disclosure"], ["CP14"]),
    ("R11", "상품 후보 고갈", "상", ["selection", "RM2"], ["D20", "A25"]),
    ("R12", "표본 부족(30개로 전환율 판정 불가)", "중", ["M04"], ["D3"]),
    ("R13", "콘텐츠별 매출 귀속 불가", "중", ["M05", "learning"], ["D16"]),
    ("R14", "본업 회사 겸업 규정", "상", ["RM1"], ["D19"]),
    ("R15", "저장소 공개로 전략 노출", "중", ["RM1"], ["D1"]),
    ("R16", "승인 시간이 본업과 충돌", "상", ["approval"], ["D18"]),
    ("R17", "수동 모드 가격 만료 검사 무력화", "상", ["price"], ["D2"]),
    ("R18", "최종 승인·정산 지연", "중", ["report", "RM3"], ["D3"]),
]
RISK_SUPPORT = [  # 리스크의 근거(사실·증거·가정)
    ("F27", "R01"), ("S06", "R02"), ("F08", "R03"), ("F11", "R04"), ("F28", "R04"), ("F02", "R05"),
    ("F07", "R05"), ("F04", "R06"), ("F17", "R07"), ("F22", "R07"), ("F28", "R08"), ("E05", "R08"),
    ("F14", "R10"), ("F15", "R10"), ("F23", "R10"), ("E05", "R11"), ("S12", "R11"), ("S07", "R12"),
    ("F12", "R13"), ("E07", "R17"), ("F07", "R18"), ("F10", "R18"),
]

# ---------------------------------------------------------------- 결함·약점
DEFECTS = [
    # id, 라벨, 종류, 상태, 영향 대상, 발견(증거·검증), 해결
    ("K01", "크래시 후 running 고착 — --force 로도 복구 불가", "defect", "open", ["job", "CP20"], ["E06"], ["D2"]),
    ("K02", "웹 실행 버튼·API 가 단계를 동기 실행 → gunicorn 30초 시간초과", "defect", "open", ["job", "CP23", "CP24"], ["V17"], ["D2"]),
    ("K03", "수동 모드 가격 확인 시각이 매일 '방금'으로 자동 갱신", "defect", "open", ["price", "CP11", "CR04"], ["E07"], ["D2"]),
    ("K04", "관리자가 재확인한 가격이 JSON 옛값으로 덮어써짐", "defect", "open", ["price", "CP11"], ["E07"], ["D2"]),
    ("K05", "사실 검사가 상품명 속 숫자('2단')를 오탐 차단", "defect", "open", ["check", "CP14", "CR04"], ["E05"], ["D2"]),
    ("K06", "쿠팡 API 모드에선 후보 전부 '보류'(사양·이미지 권리 없음)", "defect", "open", ["product", "CP05"], ["V17"], ["D11"]),
    ("K07", "메인 → 상품 이동 시 유입경로(src) 유실", "defect", "open", ["event", "CP22"], ["V17"], ["D2"]),
    ("K08", "로그인 시도 제한 없음·dev 고정 SECRET_KEY·프록시 공용 버킷", "defect", "open", ["CP23", "CP22", "CP01"], ["V17"], ["D2"]),
    ("K09", "쿠팡 검색을 키워드마다 호출(시간당 한도 초과 가능)", "defect", "open", ["CP05"], ["V17"], ["D11"]),
    ("K10", "파이프라인 실행 시각이 코드에 고정(07:00~12:00)", "gap", "open", ["job", "CP20"], ["E05"], ["D18"]),
    ("K11", "B 후킹은 만들기만 하고 게시 안 함", "gap", "open", ["variant"], ["V17"], ["D12"]),
    ("K12", "실상품 영상은 범용 그라디언트 배경(10개 중 9개)", "gap", "open", ["media", "CP15"], ["E05"], ["D7"]),
    ("K13", "DB·산출물 백업 없음", "gap", "open", ["CP25"], ["V17"], ["D6"]),
    ("K14", "실패 알림 없음(관측 Lv2)", "gap", "open", ["job", "CR13"], ["V17"], ["D17"]),
    ("K15", "RUNBOOK 의 running 복구 안내가 동작하지 않던 문제", "defect", "fixed", ["CP20"], ["E06"], ["DOC11"]),
]

# ---------------------------------------------------------------- 지표
METRICS = [
    # id, 라벨, 상태, 측정 대상 개념
    ("M01", "조회수", "측정 전(연동·게시 전)", ["pmetric"]),
    ("M02", "랜딩 방문율", "측정 전 — 30개 판정 지표", ["event", "landing"]),
    ("M03", "링크 클릭률", "측정 전 — 30개 판정 지표", ["event"]),
    ("M04", "구매전환율", "가정만 — 30개로 판정 불가", ["report"]),
    ("M05", "귀속 수수료", "측정 전 — sub_id 분리 미확인", ["report", "funnel"]),
    ("M06", "RPM(조회 1,000회당 수익)", "실측 귀속 시만 계산", ["funnel"]),
    ("M07", "조정이익", "가정 시뮬레이션만", ["funnel"]),
    ("M08", "조정 ROE", "가정: 보수 −259% · 기준 −244% · 낙관 +295%", ["funnel"]),
    ("M09", "사람 운영시간", "실측 양식만 — 첫 주 측정", ["approval"]),
    ("M10", "후보 잔량(남은 일수)", "가상 운영으로만 — 경보 미구현", ["selection"]),
    ("M11", "API 비용", "측정 가능 — 지금 0원(mock)", ["cost"]),
]

# 결정된 것: {"D1": ("2026-11-22", "선택 내용")} — DECISIONS.md 결정 기록과 같이 갱신
DECIDED: dict[str, tuple[str, str]] = {}

# 결정 → 선행 단계(when 으로 자동 연결하되 예외만 적음)
DECISION_GATE_DEFAULT = {"now": "RM1", "before": "RM2", "later": "RM3"}

# 작업 기록(커밋은 빌드 시 git log 로 덧붙임)
WORKLOG_NOTES = [
    ("2026-11-18", "MVP 구현 — 74 테스트, 데모 콘텐츠, 조사 보고 3건, 문서 9종"),
    ("2026-11-18", "자체 검토 — 결함 확인(running 고착 재현), 저장소 공개 확인"),
    ("2026-11-18", "결정 18건·자동화 재검토·도메인 온톨로지 REV01"),
    ("2026-11-19", "가상 운영 30일 — 후보 고갈 D11, 수동 가격 결함 2건 재현, 오탐, 결정 20건, 온톨로지 REV02"),
    ("2026-11-21", "지식체계(18 클래스) · 진행 현황 · RDF 내보내기"),
]

NEXT_ACTIONS = [
    ("운영자", "D19 회사 겸업 규정 확인 · D1 저장소 비공개 이전"),
    ("운영자", "D2 결함 수정 승인 → 수동 가격 결함 2건부터"),
    ("운영자", "D3·D18·D6·D4 — 실험 설계·시간표·호스팅·게시 방식"),
    ("운영자", "쿠팡·Meta·YouTube 고객센터 문의(VIRTUAL_OPERATION 5절)"),
    ("개발", "D2 승인 시: 결함 7건(K01~K05·K07·K08) → 상품 등록 화면·사양 추출 → 후보 잔량 경보 → 시간표 설정화"),
]
