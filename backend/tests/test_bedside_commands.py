from copy import deepcopy
import json

import pytest

from roomwise.catalog import demo_scene
from roomwise.commands import apply_command, is_bedside_only_command
from roomwise import command_service as service
from roomwise import intent_planner as planner


def bedside(scene):
    return next(preference for preference in scene["preferences"] if preference["kind"] == "bedside")


@pytest.mark.parametrize("text,side", [
    ("床头柜放床头的右侧", "right"),
    ("把床头柜挪到床头左边", "left"),
    ("床头柜放在床边", "either"),
    ("床头柜放在床头边", "either"),
    ("床头柜靠着床头", "either"),
    ("nightstand-1放在bed-1床头右侧", "right"),
    ("旧床头柜摆在旧双人床床头左侧", "left"),
])
def test_bedside_phrases_create_relation_without_moving_furniture(text, side):
    scene = demo_scene()
    original = deepcopy(scene)
    assert is_bedside_only_command(text)
    reply = apply_command(scene, text)
    assert reply["action"] == "generate", reply
    assert bedside(reply["scene"]) == {"kind": "bedside", "itemId": "nightstand-1", "targetId": "bed-1", "required": True, "side": side}
    assert reply["scene"]["items"] == original["items"] and scene == original
    assert "站在床尾" in reply["message"]


def test_soft_preference_updates_target_and_side_instead_of_duplicating():
    scene = apply_command(demo_scene(), "床头柜尽量放床头右侧")["scene"]
    assert not bedside(scene)["required"]
    scene = apply_command(scene, "床头柜放床头左侧")["scene"]
    assert bedside(scene)["required"] and bedside(scene)["side"] == "left"
    assert len([preference for preference in scene["preferences"] if preference["kind"] == "bedside"]) == 1


def test_multiple_beds_require_target_even_with_a_selected_bed():
    scene = demo_scene()
    another = deepcopy(scene["items"][0])
    another.update(id="bed-2", label="客床", category="single_bed")
    scene["items"].append(another)
    original = deepcopy(scene)
    unclear = apply_command(scene, "床头柜放床头右侧", "bed-1")
    assert unclear["action"] == "clarify" and "scene" not in unclear
    clear = apply_command(scene, "床头柜放在客床床头右侧", "bed-1")
    assert clear["action"] == "generate" and bedside(clear["scene"])["targetId"] == "bed-2"
    assert scene == original


def test_selected_subject_can_resolve_two_nightstands_without_overriding_bed_target():
    scene = demo_scene()
    another = deepcopy(next(item for item in scene["items"] if item["id"] == "nightstand-1"))
    another.update(id="nightstand-2", label="备用床头柜")
    scene["items"].append(another)
    result = apply_command(scene, "选中的床头柜放在bed-1床头右侧", "nightstand-2")
    assert result["action"] == "generate" and bedside(result["scene"])["itemId"] == "nightstand-2"
    assert bedside(result["scene"])["targetId"] == "bed-1"


def test_missing_bed_or_wrong_target_never_invents_reference():
    scene = demo_scene()
    scene["items"] = [item for item in scene["items"] if item["category"] != "double_bed"]
    reply = apply_command(scene, "床头柜放床头右侧")
    assert reply["action"] == "clarify" and "scene" not in reply
    wrong = apply_command(demo_scene(), "床头柜放在衣柜床头右侧")
    assert wrong["action"] == "clarify" and "scene" not in wrong


def test_locked_nightstand_blocks_but_locked_bed_allows_relation():
    scene = demo_scene()
    scene["items"][0]["locked"] = True
    assert apply_command(scene, "床头柜放床头右侧")["action"] == "generate"
    next(item for item in scene["items"] if item["id"] == "nightstand-1")["locked"] = True
    blocked = apply_command(scene, "床头柜放床头右侧")
    assert blocked["action"] == "clarify" and "scene" not in blocked
    unlocked = apply_command(scene, "nightstand-1解锁；nightstand-1放在bed-1床头右侧")
    assert unlocked["action"] == "generate"


@pytest.mark.parametrize("text", [
    "床头柜放床头右侧，书桌换成蓝色",
    "床头柜放床头右侧并换成蓝色",
    "床头柜换蓝色再放床头右侧",
    "床头柜不要放床头右侧",
])
def test_unsupported_or_negative_conditions_fail_atomically(text):
    scene = demo_scene()
    original = deepcopy(scene)
    reply = apply_command(scene, text)
    assert reply["action"] in ("unsupported", "clarify") and "scene" not in reply
    assert scene == original


def test_local_bedside_fastpath_never_calls_paid_provider(monkeypatch):
    monkeypatch.setattr(service, "language_status", lambda: pytest.fail("Complete bedside request is local"))
    monkeypatch.setattr(service, "plan_command", lambda *args: pytest.fail("Must not call language API"))
    result = service.interpret_command(demo_scene(), "床头柜放床头的右侧")
    assert result["action"] == "generate" and result["parser"] == "offline_restricted_chinese"


def test_ordinary_nightstand_edits_are_not_misclassified_as_bedside():
    assert apply_command(demo_scene(), "床头柜向右移动0.1米")["action"] == "edit"
    assert apply_command(demo_scene(), "床头柜尽量少移动")["action"] == "generate"


def test_non_bedside_compound_is_not_partially_fastpathed(monkeypatch):
    monkeypatch.setattr(service, "language_status", lambda: {"enabled": True})
    monkeypatch.setattr(service, "plan_command", lambda *args: {
        "action": "unsupported", "message": "颜色未支持，整句未执行。", "operations": [],
    })
    result = service.interpret_command(demo_scene(), "床头柜放床头右侧，书桌换成蓝色")
    assert result["action"] == "unsupported" and "scene" not in result


@pytest.mark.parametrize("side,canonical", [("right", "右侧"), ("left", "左侧"), ("either", "边"), (None, "边")])
def test_structured_bedside_plan_is_validated_then_compiled(side, canonical):
    plan = {"action": "apply", "operations": [{"name": "bedside", "itemIds": ["nightstand-1"], "targetId": "bed-1", "side": side}]}
    text = planner.compile_plan(plan, demo_scene())
    assert text == "nightstand-1放在bed-1床头" + canonical
    assert apply_command(demo_scene(), text)["action"] == "generate"


@pytest.mark.parametrize("operation", [
    {"name": "bedside", "itemIds": ["desk-1"], "targetId": "bed-1"},
    {"name": "bedside", "itemIds": ["nightstand-1"], "targetId": "window-1"},
    {"name": "bedside", "itemIds": ["nightstand-1"], "targetId": "wardrobe-1"},
    {"name": "bedside", "itemIds": ["nightstand-1"], "targetId": "nightstand-1"},
    {"name": "near_window", "itemIds": ["desk-1"], "side": "left"},
])
def test_bedside_plan_rejects_wrong_categories_and_irrelevant_side(operation):
    with pytest.raises(ValueError):
        planner.compile_plan({"action": "apply", "operations": [operation]}, demo_scene())


def test_model_cannot_reposition_fixed_nightstand_via_bedside(monkeypatch, tmp_path):
    monkeypatch.setenv("ROOMWISE_LANGUAGE_CONFIG", str(tmp_path / "no-config.json"))
    monkeypatch.setenv("ROOMWISE_LANGUAGE_PROVIDER", "ollama")
    monkeypatch.setenv("ROOMWISE_LANGUAGE_MODEL", "mock-model")
    monkeypatch.setenv("ROOMWISE_LANGUAGE_URL", "http://127.0.0.1:11434/api/chat")
    response = {"action": "apply", "operations": [{"name": "bedside", "itemIds": ["nightstand-1"], "targetId": "bed-1", "side": "right"}]}
    monkeypatch.setattr(planner, "_post_json", lambda *args: {"message": {"content": json.dumps(response)}})
    result = planner.plan_command(demo_scene(), "床头柜不动，帮我看看床头右侧")
    assert result["action"] == "clarify" and not result["canonicalText"]
