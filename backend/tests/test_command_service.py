"""The language adapter translates; the deterministic executor retains authority."""
from copy import deepcopy
import json

import pytest

from roomwise import command_service as service
from roomwise.catalog import demo_scene, CATALOG
from roomwise.schemas import Scene


def test_disabled_or_missing_key_remains_offline_without_network(monkeypatch):
    monkeypatch.setattr(service, "language_status", lambda: {"enabled": False, "configured": True})
    monkeypatch.setattr(service, "plan_command", lambda *args: pytest.fail("Must not call a model without credentials"))
    reply = service.interpret_command(demo_scene(), "旧书桌旋转90度")
    assert reply["action"] == "edit"
    assert reply["parser"] == "offline_restricted_chinese"
    assert reply["language"]["enabled"] is False


def test_bed_in_front_of_wardrobe_creates_a_relation(monkeypatch):
    scene = demo_scene()
    before = deepcopy(scene)
    monkeypatch.setattr(service, "language_status", lambda: pytest.fail("relative positions are parsed locally"))
    monkeypatch.setattr(service, "plan_command", lambda *args: pytest.fail("relative positions use the local geometry solver"))

    reply = service.interpret_command(scene, "\u628a\u5e8a\u653e\u5728\u8863\u67dc\u524d\u9762")

    assert reply["action"] == "generate"
    assert reply["scene"]["preferences"][-1] == {
        "kind": "relative_position", "itemId": "bed-1", "targetId": "wardrobe-1",
        "required": True, "direction": "front",
    }
    assert scene == before


def test_bed_in_front_of_wardrobe_alias_maps_to_front():
    reply = service.interpret_command(demo_scene(), "\u5e8a\u6446\u5230\u8863\u67dc\u524d\u65b9")
    preference = next(value for value in reply["scene"]["preferences"]
                      if value["kind"] == "relative_position")
    assert reply["action"] == "generate"
    assert preference["direction"] == "front"


def test_chair_facing_coffee_table_creates_a_facing_preference_without_moving_table():
    scene = demo_scene()
    chair = next(item for item in scene["items"] if item["id"] == "chair-1")
    chair["label"] = "木质扶手椅"
    chair["category"] = "armchair"
    table = next(item for item in scene["items"] if item["id"] == "desk-1")
    table["label"] = "茶几"
    table["category"] = "coffee_table"
    before = deepcopy(scene)

    reply = service.interpret_command(scene, "木质扶手椅要朝向茶几")

    assert reply["action"] == "generate", reply
    assert reply["scene"]["preferences"][-1] == {
        "kind": "face_item", "itemId": "chair-1", "targetId": "desk-1", "required": True,
    }
    assert scene == before


def test_chair_facing_coffee_table_generates_a_checked_rotation():
    scene = demo_scene()
    chair = next(item for item in scene["items"] if item["id"] == "chair-1")
    chair.update(label="木质扶手椅", category="armchair", x=1., z=1., rotation=0.)
    table = next(item for item in scene["items"] if item["id"] == "desk-1")
    table.update(label="茶几", category="coffee_table", x=4., z=4., rotation=0., locked=True)
    reply = service.interpret_command(scene, "木质扶手椅朝向茶几")

    assert reply["action"] == "generate", reply
    result = service.apply_command(reply["scene"], "生成布局")
    assert result["action"] == "generate"


@pytest.mark.parametrize("text", [
    "床不要放在衣柜前面", "床别放在衣柜前面", "床不在衣柜前面",
    "不要把床放在衣柜前面", "把床旋转90度后放在衣柜前面",
    "红色的床放在衣柜前面", "床放在不允许移动的衣柜前面",
])
def test_relative_commands_do_not_drop_negation_or_extra_requirements(text):
    scene = demo_scene()
    before = deepcopy(scene)

    reply = service.interpret_command(scene, text)

    assert reply["action"] in {"clarify", "unsupported"}, reply
    assert "scene" not in reply
    assert scene == before


@pytest.mark.parametrize("text,direction,required", [
    ("请把床放在衣柜的前面", "front", True),
    ("把床尽量放在衣柜后方", "back", False),
    ("尽量把床放在衣柜左面", "left", False),
    ("把床放在衣柜右面", "right", True),
    ("床放在衣柜前面！", "front", True),
    ("床放在衣柜前面!", "front", True),
])
def test_relative_command_modifiers_preserve_direction_and_strength(text, direction, required):
    reply = service.interpret_command(demo_scene(), text)

    assert reply["action"] == "generate", reply
    assert reply["scene"]["preferences"][-1] == {
        "kind": "relative_position", "itemId": "bed-1", "targetId": "wardrobe-1",
        "required": required, "direction": direction,
    }


def test_position_lock_in_another_clause_is_not_a_negated_relative_relation():
    for separator in ("，", "然后", "同时"):
        reply = service.interpret_command(demo_scene(), f"书桌不移动{separator}床放在衣柜前面")

        assert reply["action"] == "generate", reply
        assert next(item for item in reply["scene"]["items"] if item["id"] == "desk-1")["locked"]
        assert reply["scene"]["preferences"][-1]["direction"] == "front"


def test_model_rotation_with_relative_position_still_requests_generation(monkeypatch):
    scene = demo_scene()
    monkeypatch.setattr(service, "language_status", lambda: {"enabled": True})
    monkeypatch.setattr(service, "plan_command", lambda *args: {
        "action": "apply", "canonicalText": "bed-1旋转90度；bed-1放在wardrobe-1前方",
        "operations": [{"name": "rotate", "itemIds": ["bed-1"], "degrees": 90},
                       {"name": "relative_position", "itemIds": ["bed-1"],
                        "targetId": "wardrobe-1", "direction": "front", "required": True}],
    })

    reply = service.interpret_command(scene, "先转动床，再摆到衣柜前面去")

    assert reply["action"] == "generate", reply
    assert reply["parser"] == "language_model_with_validated_executor"
    assert reply["scene"]["preferences"][-1]["kind"] == "relative_position"


def test_configured_language_uses_executor_and_preserves_ids_sizes(monkeypatch):
    scene = demo_scene()
    shelf = next(item for item in CATALOG if item["category"] == "bookshelf")
    scene["items"].append(dict(shelf, id="shelf-1", x=.5, z=1.5, rotation=0,
                               locked=False, keep=True, source="brought"))
    before = deepcopy(scene)
    monkeypatch.setattr(service, "language_status", lambda: {"enabled": True, "provider": "chatcompletions", "model": "test"})
    monkeypatch.setattr(service, "plan_command", lambda *args: {
        "action": "apply", "canonicalText": "shelf-1靠墙", "provider": "chatcompletions", "model": "test",
        "operations": [{"name": "near_wall", "itemIds": ["shelf-1"], "required": True}]})
    reply = service.interpret_command(scene, "把放书的那个架子贴到墙边去")
    assert reply["action"] == "generate"
    assert reply["parser"] == "language_model_with_validated_executor"
    assert reply["scene"]["items"] == before["items"]
    assert any(pref["kind"] == "near_wall" and pref["itemId"] == "shelf-1" for pref in reply["scene"]["preferences"])
    Scene.model_validate(reply["scene"])
    assert scene == before


def test_bad_model_plan_does_not_fall_back_to_partially_matching_regex(monkeypatch):
    scene = demo_scene()
    monkeypatch.setattr(service, "language_status", lambda: {"enabled": True})
    monkeypatch.setattr(service, "plan_command", lambda *args: {
        "action": "clarify", "message": "请说明是哪把椅子。", "operations": []})
    reply = service.interpret_command(scene, "书桌靠窗，那把椅子随便安排")
    assert reply["action"] == "clarify" and "scene" not in reply


def test_exact_undo_does_not_incure_language_call(monkeypatch):
    monkeypatch.setattr(service, "language_status", lambda: pytest.fail("Undo should remain local"))
    monkeypatch.setattr(service, "plan_command", lambda *args: pytest.fail("Undo should remain local"))
    assert service.interpret_command(demo_scene(), "撤销")["action"] == "undo"


def test_executor_rejects_model_attempt_to_move_a_locked_item(monkeypatch):
    monkeypatch.setattr(service, "language_status", lambda: {"enabled": True})
    monkeypatch.setattr(service, "plan_command", lambda *args: {
        "action": "apply", "canonicalText": "wardrobe-1向右移动1米", "operations": []})
    reply = service.interpret_command(demo_scene(), "衣柜向右移动一米")
    assert reply["action"] == "clarify" and "scene" not in reply
    assert "锁定" in reply["message"]


def test_only_adjust_with_exact_displacement_does_not_trigger_random_generation(monkeypatch):
    scene = demo_scene()
    desk = next(item for item in scene["items"] if item["id"] == "desk-1")
    monkeypatch.setattr(service, "language_status", lambda: {"enabled": True})
    monkeypatch.setattr(service, "plan_command", lambda *args: {
        "action": "apply", "canonicalText": "只调整desk-1；desk-1向右移动0.2米",
        "operations": [{"name": "only_adjust", "itemIds": ["desk-1"]},
                       {"name": "move", "itemIds": ["desk-1"], "dx": .2}]})
    reply = service.interpret_command(scene, "只把书桌往右挪20厘米")
    assert reply["action"] == "edit"
    after = {item["id"]: item for item in reply["scene"]["items"]}
    assert after["desk-1"]["x"] == pytest.approx(desk["x"]+.2)
    for item in scene["items"]:
        if item["id"] != "desk-1":
            assert (after[item["id"]]["x"], after[item["id"]]["z"], after[item["id"]]["rotation"]) == (item["x"], item["z"], item["rotation"])



def test_global_wall_quantifier_uses_local_executor_even_with_language_provider(monkeypatch):
    scene = demo_scene()
    monkeypatch.setattr(service, "language_status", lambda: {"enabled": True, "provider": "deepseek"})
    monkeypatch.setattr(service, "plan_command", lambda *args: pytest.fail("quantified wall request must stay local"))
    text = "\u529e\u516c\u684c\u9760\u7a97\uff0c\u9664\u4e86\u6905\u5b50\u4ee5\u5916\u7684\u5bb6\u5177\u5c3d\u91cf\u9760\u5899\u6446\u653e"
    reply = service.interpret_command(scene, text)
    assert reply["action"] == "generate"
    wall_ids = {p["itemId"] for p in reply["scene"]["preferences"] if p["kind"] == "near_wall"}
    assert {"bed-1", "desk-1", "nightstand-1"}.issubset(wall_ids)
    assert "chair-1" not in wall_ids
