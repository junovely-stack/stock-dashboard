"""지식체계(온톨로지) 무결성 — 참조·정의역·치역·상태 값·요약 수치."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_knowledge as B  # noqa: E402
import knowledge_data as K  # noqa: E402


def test_graph_is_consistent():
    ents, rels = B.build_graph()
    assert B.validate(ents, rels) == []
    assert len({e for e in ents}) == len(ents)
    classes = {c[0] for c in K.CLASSES}
    assert {e["cls"] for e in ents.values()} == classes  # 모든 클래스에 개체가 있다


def test_status_values_are_known():
    ents, _ = B.build_graph()
    allowed = {"Deliverable": {"done", "partial", "todo"}, "Criterion": {"pass", "caveat", "fail"},
               "Phase": {"done", "partial", "active", "todo"}, "Defect": {"open", "fixed"},
               "Decision": {"pending", "decided"}}
    for e in ents.values():
        if e["cls"] in allowed:
            assert e["status"] in allowed[e["cls"]], e["id"]
    for e in ents.values():
        if e["cls"] == "Fact":
            assert e["props"]["confidence"] in {"A", "B", "C"}


def test_summary_matches_requirements():
    ents, rels = B.build_graph()
    sm = B.summary(ents)
    assert sm["deliverables"]["total"] == 20 and sm["criteria"]["total"] == 15
    assert sm["decisions"]["total"] == 20
    assert sm["tests"] == sum(v[2] for v in K.VERIFICATIONS if v[1].startswith("test_"))
    # 모든 결정은 단계 하나를 막고, 모든 미해결 결함은 해결 경로가 있다
    gates = {r["s"] for r in rels if r["p"] == "gates"}
    assert {e for e, v in ents.items() if v["cls"] == "Decision"} <= gates
    resolved = {r["s"] for r in rels if r["p"] == "resolvedBy"}
    assert {e for e, v in ents.items() if v["cls"] == "Defect"} <= resolved


def test_turtle_export_is_well_formed_enough():
    ents, rels = B.build_graph()
    ttl = B.to_ttl(ents, rels)
    assert ttl.count(" a owl:Class ") == len(K.CLASSES)
    assert "scf:K03 scf:affects scf:price ." in ttl
    assert "\n\n" in ttl and ttl.rstrip().endswith(".")  # 문법 전체 검증은 rdflib 로 별도 수행(KNOWLEDGE_BASE.md)
