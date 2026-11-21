# 문서 지도

기준일 2026-11-21. 처음이면 0 → 1 → 2 → 3 순서로. 전체를 한 그래프로 보려면 지식체계 HTML.

| 순서 | 문서 | 무엇을 답하나 | 갱신 시점 |
|---|---|---|---|
| 0 | [PROGRESS.md](PROGRESS.md) | **지금 어디까지 왔나** — 단계·산출물 20·완료 기준 15·결정·결함·작업 기록 (자동 생성) | `python scripts/build_knowledge.py --rev <번호>` |
| 0-1 | [SCF_지식체계_REV01.html](SCF_지식체계_REV01.html) · [KNOWLEDGE_BASE.md](KNOWLEDGE_BASE.md) | **모든 내용을 하나의 온톨로지로** — 클래스 18·개체 347·관계 1,009, 탐색기·추적표, RDF 내보내기 | 데이터 수정 시 REV 올려 재생성 |
| 1 | [DECISIONS.md](DECISIONS.md) | **내가 정해야 할 것** 20건, 이번 주 7건, 결정 기록 | 결정할 때마다 |
| 1-1 | [VIRTUAL_OPERATION.md](VIRTUAL_OPERATION.md) | **가상 운영 30일** — 어디서 막히고 누구 도움이 필요한가 | 시뮬레이터 재실행 시 |
| 2 | [AUTOMATION_REVIEW.md](AUTOMATION_REVIEW.md) | 기획안 재검토 — 무엇을 자동화하고 무엇을 사람이 계속하나, 로드맵 | 결정·실측 반영 시 |
| 3 | [SCF_온톨로지_REV02.html](SCF_온톨로지_REV02.html) (이전판 REV01) | 개념·관계·자동화 수준·막힌 것을 한 장으로 (더블클릭) | 데이터 파일 수정 시 REV 올려 재생성 |
| — | [ONTOLOGY.md](ONTOLOGY.md) | 위 HTML 의 텍스트판 + 핵심 경로 3개 | HTML 과 같이 |
| — | [BUSINESS_RISK_ANALYSIS.md](BUSINESS_RISK_ANALYSIS.md) | 수익 구조 한계, 논리적 결점, 자체 검토 결함 | 판정 게이트마다 |
| — | [FEASIBILITY_REPORT.md](FEASIBILITY_REPORT.md) | 가능 / 승인 필요 / 불가, MVP 범위 | 권한이 생길 때 |
| — | [API_ACCESS_MATRIX.md](API_ACCESS_MATRIX.md) | 외부 API 조건·한도·확인 수준(A/B/C) | 원문 재확인 시 |
| — | [COMPLIANCE_CHECKLIST.md](COMPLIANCE_CHECKLIST.md) | 광고 표시·사실성·플랫폼·개인정보 | 법·약관 변경 시 |
| — | [COST_MODEL.md](COST_MODEL.md) | 콘텐츠당·월 비용, LLM 모델별 비용 | 실측 1주 후 |
| — | [ROI_REPORT.md](ROI_REPORT.md) | 12개월 시뮬레이션·손익분기 (자동 생성) | `python scf.py simulate --out docs/ROI_REPORT.md` |
| — | [DB_SCHEMA.md](DB_SCHEMA.md) | 테이블·상태 전이 | 스키마 변경 시 |
| — | [PSYCHOLOGY_PROMPTS.md](PSYCHOLOGY_PROMPTS.md) | 구매심리·대본 프롬프트와 검증 규칙 | 프롬프트 변경 시 |
| — | [RUNBOOK.md](RUNBOOK.md) | 장애 대응 | 장애를 겪을 때마다 |

## 갱신 규칙

1. **새로 쓰지 말고 덧붙인다.** 기존 문단을 고칠 때도 맨 아래 `## 변경 이력` 에 `REVnn (날짜): 무엇을 왜` 한 줄.
2. **자동 생성 구간은 손대지 않는다.** `<!-- AUTO:...:START/END -->` 사이는 생성기가 덮어쓴다 — 도메인·결정·액션은 `scripts/ontology_data.py` → `build_ontology.py`, 진행·사실·결함·리스크 등은 `scripts/knowledge_data.py` → `build_knowledge.py`. 둘 다 고쳤으면 두 생성기를 모두 돌린다.
3. **결정이 나면**: DECISIONS.md 결정 기록 1줄 → `ontology_data.py` 반영(결정 상태·노드 상태) → 재생성(REV +1) → 영향 문서 변경 이력 1줄.
4. **HTML 은 REV 를 올려 새 파일로.** 이전 REV 는 지우지 않는다. 생성 후 `node scripts/check_ontology_html.mjs docs/SCF_온톨로지_REVnn.html <폴더>` 로 글자 넘침·겹침·콘솔 오류 확인.
5. **숫자는 출처와 함께.** 가정이면 '가정', 미확인이면 '미확인', 실측이면 측정 기간을 적는다.
