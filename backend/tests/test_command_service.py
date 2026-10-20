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
