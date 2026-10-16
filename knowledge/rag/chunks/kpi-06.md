---
id: kpi-06
title: 신호등 판정 규칙 — 상향 지표 0.97, 하향 지표 1.30 (사내확정)
chapter: 9
chapter_title: 지표
order: 6
type: 사내확정
grade: C
aliases:
  - 신호등
  - good warn bad
  - 0.97
  - 1.30
  - 신호등 배수
  - 신호등 색상
questions:
  - 신호등 판정 기준
  - warn은 언제 뜨나
  - 신호등 색 코드
related:
  - kpi-01
  - kpi-04
---
배수 0.97 / 1.30은 담당자가 2026-09-13에 확인했다.

- **상향 지표**(당일검사완료율): `v ≥ 목표` → good / `v ≥ 목표×0.97` → warn / 그 외 bad
- **하향 지표**(용접불량률·정도불량률): `v ≤ 목표` → good / `v ≤ 목표×1.30` → warn / 그 외 bad
- 색상: good `#2c8a5f` / warn `#c89010` / bad `#b3402a`

예: 당일검사완료율 목표 98%면 good ≥ 98, warn ≥ 95.06, bad < 95.06. 용접불량률 목표 0.5면 good ≤ 0.5, warn ≤ 0.65, bad > 0.65.

배수가 연 단위로 바뀌는지 고정인지는 사내 확인 대기다.
