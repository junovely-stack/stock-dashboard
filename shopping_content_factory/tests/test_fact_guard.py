import copy

import pytest

from tests.conftest import RUN_DATE


@pytest.fixture
def content(pipeline):
    from app.models import Content
    from services.common.db import session_scope

    with session_scope() as s:
        c = s.get(Content, "C20261118-01")
        return copy.deepcopy(c.script), c.product_id


def _check(script, pid):
    from app.models import Product
    from services.common.db import session_scope
    from services.script_generator.fact_guard import check_script

    with session_scope() as s:
        return check_script(script, s.get(Product, pid))


def test_generated_script_passes(content):
    script, pid = content
    res = _check(script, pid)
    assert res["passed"], res["issues"]


def test_spec_mismatch_blocks(content):
    script, pid = content
    script["scenes"][3]["on_screen_text"] = "최대 하중 10kg 까지 거뜬"   # 검증 사양은 5kg
    res = _check(script, pid)
    assert not res["passed"]
    assert any(i["rule"] == "spec_mismatch" and "10kg" in i["message"] for i in res["issues"])


def test_price_and_banned_phrases_block(content):
    script, pid = content
    script["scenes"][4]["on_screen_text"] = "오늘만 19900원! 최저가 품절 임박"
    script["scenes"][1]["narration"] = "직접 써보니 완벽합니다"
    rules = {i["rule"] for i in _check(script, pid)["issues"]}
    assert {"no_price_in_video", "banned.false_scarcity", "banned.superlative_unverified",
            "banned.absolute", "banned.experience_claims"} <= rules


def test_disclosure_rules(content):
    script, pid = content
    script["scenes"][0]["show_disclosure"] = False
    script["caption"]["instagram"] = "광고 아님\n" + script["caption"]["instagram"]
    script["hashtags"] = ["#정리", "#광고"]
    script["caption"]["youtube_title"] = "제목"
    script["disclosure"]["opening"] = "구매 시 수수료를 제공받을 수 있습니다"
    rules = {i["rule"] for i in _check(script, pid)["issues"]}
    assert {"disclosure_opening", "disclosure_caption", "disclosure_hashtag", "disclosure_title",
            "disclosure_wording"} <= rules


def test_missing_caution_and_bad_duration(content):
    script, pid = content
    script["scenes"][3]["on_screen_text"] = "좋은 점만"
    script["scenes"][3]["narration"] = "좋은 점만"
    script["scenes"][2]["duration"] = 30
    rules = {i["rule"] for i in _check(script, pid)["issues"]}
    assert "caution_missing" in rules and "duration" in rules


def test_facts_change_after_generation_blocks_publish(pipeline):
    from app.models import Content, Product
    from services.common.db import session_scope
    from services.common.facts import facts_hash
    from services.social_publishers.publisher import gate
    from services.social_publishers.review import approve
    from config.settings import get_settings

    with session_scope() as s:
        c = s.get(Content, "C20261118-01")
        approve(s, c, "tester")
    with session_scope() as s:
        p = s.get(Product, "DEMO-001")
        p.verified_specs = [dict(x, value="3") if x["key"] == "최대 하중" else x for x in p.verified_specs]
        p.facts_hash = facts_hash(p)
    with session_scope() as s:
        reasons = gate(s.get(Content, "C20261118-01"), "instagram", get_settings())
    assert any("사실 정보가 바뀜" in r for r in reasons)
