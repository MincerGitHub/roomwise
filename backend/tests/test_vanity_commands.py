from copy import deepcopy

import pytest

from roomwise.catalog import CATALOG, demo_scene
from roomwise.command_service import interpret_command
from roomwise.generator import generate_layouts
from roomwise.geometry import evaluate_vanity_preference, evaluate_vanity_seating
from roomwise.intent_planner import compile_plan, validate_plan_against_scene
from roomwise.schemas import Scene


def vanity_scene():
    scene = demo_scene()
    scene["room"]["door"] = None
    scene["room"]["windows"] = []
    scene["items"] = []
    for category, item_id, x, z in (
        ("dressing_table", "vanity-1", 4.1, 3.4),
        ("dressing_chair", "vanity-chair-1", .7, .7),
        ("rug", "rug-1", 2.6, 2.1),
    ):
        item = deepcopy(next(entry for entry in CATALOG if entry["category"] == category))
        item.update(id=item_id, x=x, z=z, rotation=0., locked=False, keep=True, source="brought")
        scene["items"].append(item)
    scene["preferences"] = [{"kind": "near_wall", "itemId": "rug-1", "required": True}]
    return scene


def test_screenshot_instruction_is_parsed_locally_and_applied_as_two_requirements(monkeypatch):
    scene = vanity_scene()
    monkeypatch.setattr("roomwise.command_service.language_status", lambda: pytest.fail("must use deterministic local parser"))
    monkeypatch.setattr("roomwise.command_service.plan_command", lambda *args: pytest.fail("must not call the model"))

    result = interpret_command(scene, "地毯不用靠墙，梳妆椅摆在梳妆镜前")

    assert result["action"] == "generate", result
    assert result["parser"] == "offline_restricted_chinese"
    preferences = result["scene"]["preferences"]
    assert {preference["kind"] for preference in preferences} == {"vanity_seating"}
    assert preferences[0]["itemId"] == "vanity-chair-1"
    assert preferences[0]["targetId"] == "vanity-1"
    assert "不设置靠墙要求" in result["message"]
    Scene.model_validate(result["scene"])


def test_generator_places_requested_chair_in_front_of_the_named_vanity():
    scene = vanity_scene()
    scene["preferences"] = [{"kind": "vanity_seating", "itemId": "vanity-chair-1",
                             "targetId": "vanity-1", "required": True}]
    result = generate_layouts(scene, mode="rules", count=1, seed=42)
    assert result["candidates"], result["diagnostics"]
    candidate = result["candidates"][0]
    check = next(check for check in candidate["requirements"]["checks"] if check["kind"] == "vanity_seating")
    assert check["satisfied"], check
    items = {item["id"]: item for item in candidate["scene"]["items"]}
    assert evaluate_vanity_preference(items["vanity-chair-1"], items["vanity-1"], scene["preferences"][0])["satisfied"]


def test_screenshot_sentence_works_in_a_furnished_bedroom():
    scene = demo_scene()
    scene["preferences"] = []
    for category, item_id, x, z, rotation in (
        ("dressing_table", "vanity-1", 2.5, 3.7, 0.),
        ("dressing_chair", "vanity-chair-1", 2.5, 2.8, 180.),
        ("rug", "rug-1", 2.5, .7, 0.),
    ):
        item = deepcopy(next(entry for entry in CATALOG if entry["category"] == category))
        item.update(id=item_id, x=x, z=z, rotation=rotation, locked=False, keep=True, source="brought")
        scene["items"].append(item)
    text = "\u5730\u6bef\u4e0d\u7528\u9760\u5899\uff0c\u68b3\u5986\u6905\u6446\u5728\u68b3\u5986\u955c\u524d"
    command = interpret_command(scene, text)
    assert command["action"] == "generate", command
    assert not any(preference["itemId"] == "rug-1" and preference["kind"] == "near_wall"
                   for preference in command["scene"]["preferences"])
    result = generate_layouts(command["scene"], mode="rules", count=1, seed=42)
    assert result["candidates"], result["diagnostics"]
    candidate = result["candidates"][0]
    requirement = next(check for check in candidate["requirements"]["checks"]
                       if check["kind"] == "vanity_seating")
    assert requirement["satisfied"], requirement


def test_ambiguous_vanity_target_is_not_guessed():
    scene = vanity_scene()
    scene["items"].append({**deepcopy(scene["items"][0]), "id": "vanity-2", "x": 1.4})
    before = deepcopy(scene)
    result = interpret_command(scene, "梳妆椅摆在梳妆镜前")
    assert result["action"] == "clarify" and "scene" not in result
    assert scene == before


def test_planner_can_compile_and_validate_explicit_vanity_relation():
    scene = vanity_scene()
    plan = {"action": "apply", "operations": [{"name": "vanity_seating", "itemIds": ["vanity-chair-1"],
                                                  "targetId": "vanity-1", "required": True}]}
    validated = validate_plan_against_scene(plan, scene)
    assert compile_plan(validated, scene) == "vanity-chair-1放在vanity-1前"


def test_explicit_pairing_is_not_replaced_by_nearest_chair_heuristic():
    scene = vanity_scene()
    second_table = deepcopy(scene["items"][0])
    second_table.update(id="vanity-2", x=1.1, z=1.1)
    second_chair = deepcopy(scene["items"][1])
    second_chair.update(id="vanity-chair-2", x=1.1, z=1.65, rotation=180.)
    scene["items"].extend((second_table, second_chair))
    scene["preferences"] = [{"kind": "vanity_seating", "itemId": "vanity-chair-1",
                             "targetId": "vanity-1", "required": True}]
    # The unrequested chair is nearer to vanity-1; the stated relation still wins.
    requested_chair = next(item for item in scene["items"] if item["id"] == "vanity-chair-1")
    requested_chair.update(x=4.1, z=3.3, rotation=180.)
    result = evaluate_vanity_seating(scene)
    assert result["checks"][0]["tableId"] == "vanity-1"
    assert result["checks"][0]["chairId"] == "vanity-chair-1"


@pytest.mark.parametrize("text", ["地毯不用靠墙", "地毯不需要靠墙", "地毯无需靠墙"])
def test_rug_wall_exemption_never_becomes_positive_wall_requirement(text):
    scene = vanity_scene()
    result = interpret_command(scene, text)
    assert result["action"] == "generate", result
    assert not any(pref["itemId"] == "rug-1" and pref["kind"] == "near_wall"
                   for pref in result["scene"]["preferences"])
