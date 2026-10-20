from copy import deepcopy

import pytest
from pydantic import ValidationError

from roomwise.catalog import demo_scene
from roomwise.commands import apply_command
from roomwise.schemas import Scene


def preference(scene, item_id, kind):
    return next(p for p in scene["preferences"] if p["itemId"] == item_id and p["kind"] == kind)


def test_exact_window_request_parses_both_clauses_atomically():
    scene = demo_scene()
    original = deepcopy(scene)
    reply = apply_command(scene, "桌子靠窗，椅子面朝窗户方向")
    assert reply["action"] == "generate"
    assert reply["scene"]["items"] == original["items"]
    assert scene == original
    assert preference(reply["scene"], "desk-1", "near_window") == {
        "itemId": "desk-1", "kind": "near_window", "targetId": "window-1", "required": True,
    }
    assert preference(reply["scene"], "chair-1", "face_window") == {
        "itemId": "chair-1", "kind": "face_window", "targetId": "window-1", "required": True,
    }
    assert len(reply["changes"]) == 2
    assert "旧书桌靠窗" in reply["message"]
    assert "办公椅面朝窗户" in reply["message"]
    Scene.model_validate(reply["scene"])


@pytest.mark.parametrize("verb", ["面朝窗户方向", "朝向窗户", "正对窗户", "面向窗", "面朝着窗户方向"])
def test_window_facing_phrases(verb):
    reply = apply_command(demo_scene(), f"椅子{verb}")
    assert reply["action"] == "generate"
    assert preference(reply["scene"], "chair-1", "face_window")["required"]


@pytest.mark.parametrize("qualifier", ["尽量", "最好", "优先"])
def test_soft_near_window_request_and_legacy_preference(qualifier):
    scene = demo_scene()
    legacy = Scene.model_validate(scene)
    assert legacy.preferences[0].required is False
    reply = apply_command(scene, f"桌子{qualifier}靠窗")
    near = preference(reply["scene"], "desk-1", "near_window")
    assert not near["required"]
    assert near["targetId"] == "window-1"
    assert len([p for p in reply["scene"]["preferences"] if p["kind"] == "near_window"]) == 1
    repeated = apply_command(reply["scene"], "桌子靠窗")
    assert preference(repeated["scene"], "desk-1", "near_window")["required"]


def test_duplicate_window_preferences_are_updated_not_accumulated():
    scene = demo_scene()
    scene["preferences"].append(deepcopy(scene["preferences"][0]))
    reply = apply_command(scene, "书桌靠窗")
    assert len(reply["scene"]["preferences"]) == 1
    assert reply["scene"]["preferences"][0]["required"]


@pytest.mark.parametrize("text", ["桌子靠窗", "椅子面朝窗户方向"])
def test_no_window_returns_clarification_without_partial_edits(text):
    scene = demo_scene()
    scene["room"]["windows"] = []
    original = deepcopy(scene)
    reply = apply_command(scene, "旧床头柜锁定，" + text)
    assert reply["action"] == "clarify"
    assert "scene" not in reply
    assert "窗户" in reply["message"]
    assert scene == original


def test_multiple_windows_need_explicit_target_and_can_update_target():
    scene = demo_scene()
    scene["room"]["windows"].append({"id": "window-2", "wall": "east", "offset": 1.0, "width": 1.2, "sillHeight": .9})
    reply = apply_command(scene, "桌子靠窗，椅子面朝窗户方向")
    assert reply["action"] == "clarify"
    assert "scene" not in reply
    assert len(reply["windowOptions"]) == 2
    reply = apply_command(scene, "桌子靠窗 window-2，椅子面朝窗户 window-2")
    assert reply["action"] == "generate"
    assert all(p["targetId"] == "window-2" for p in reply["scene"]["preferences"])
    updated = apply_command(reply["scene"], "桌子靠窗 window-1")
    assert preference(updated["scene"], "desk-1", "near_window")["targetId"] == "window-1"
    assert len(updated["scene"]["preferences"]) == 2


@pytest.mark.parametrize("text", ["不要面朝窗户", "不面朝窗户", "不能面向窗户", "不想朝向窗户", "别再正对窗户"])
def test_negative_facing_request_is_never_applied(text):
    scene = demo_scene()
    original = deepcopy(scene)
    reply = apply_command(scene, "桌子靠窗，椅子" + text)
    assert reply["action"] == "clarify"
    assert "scene" not in reply
    assert scene == original


def test_locked_chair_blocks_whole_request_until_explicit_unlock():
    scene = demo_scene()
    chair = next(i for i in scene["items"] if i["id"] == "chair-1")
    chair["locked"] = True
    original = deepcopy(scene)
    blocked = apply_command(scene, "桌子靠窗，椅子面朝窗户方向")
    assert blocked["action"] == "clarify"
    assert "scene" not in blocked
    assert scene == original
    accepted = apply_command(scene, "桌子靠窗，椅子解锁并面朝窗户方向")
    assert accepted["action"] == "generate"
    assert not next(i for i in accepted["scene"]["items"] if i["id"] == "chair-1")["locked"]


def test_unsupported_second_clause_does_not_keep_first_clause():
    scene = demo_scene()
    original = deepcopy(scene)
    reply = apply_command(scene, "桌子靠窗，椅子换成蓝色")
    assert reply["action"] == "unsupported"
    assert "scene" not in reply
    assert scene == original


def test_schema_validates_window_target_and_preference_kind():
    scene = demo_scene()
    scene["preferences"] = [{"kind": "face_window", "itemId": "chair-1", "targetId": "window-1", "required": True}]
    Scene.model_validate(scene)
    scene["preferences"][0]["targetId"] = "missing-window"
    with pytest.raises(ValidationError):
        Scene.model_validate(scene)
    scene["preferences"][0].update(kind="min_move", targetId="window-1")
    with pytest.raises(ValidationError):
        Scene.model_validate(scene)
    scene["preferences"][0].update(kind="face_door", targetId=None)
    with pytest.raises(ValidationError):
        Scene.model_validate(scene)
