from copy import deepcopy
import math

import pytest

from roomwise.catalog import CATALOG, demo_scene
from roomwise.command_service import interpret_command
from roomwise.generator import generate_layouts
from roomwise.geometry import cabinet_door_clearance_conflicts, footprint
from roomwise.intent_planner import _position_lock_guard, _scene_payload, compile_plan, validate_plan_against_scene
from roomwise.relative_constraints import evaluate_relative_position, relative_position_placements
from roomwise.facing_constraints import evaluate_facing_preference
from roomwise.schemas import Scene


def _item(category, item_id, x, z, rotation=0, locked=False):
    template = deepcopy(next(value for value in CATALOG if value["category"] == category))
    return {**template, "id": item_id, "x": x, "z": z, "rotation": rotation,
            "locked": locked, "keep": True, "source": "brought"}


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("direction", ["front", "back", "left", "right"])
def test_relative_placements_use_target_local_axes_and_independent_footprints(rotation, direction):
    target = _item("wardrobe", "target", 3., 3., rotation)
    subject = _item("double_bed", "subject", .8, .8)
    preference = {"kind": "relative_position", "itemId": "subject", "targetId": "target",
                  "direction": direction, "required": True}

    candidate = next(relative_position_placements(subject, target, preference))

    assert evaluate_relative_position(candidate, target, preference)["satisfied"]
    angle = math.radians(rotation)
    forward = (math.sin(angle), math.cos(angle))
    right = (math.cos(angle), -math.sin(angle))
    axis, lateral, positive = (forward, right, direction == "front") if direction in ("front", "back") else (right, forward, direction == "right")
    target_projection = [x * axis[0] + z * axis[1] for x, z in footprint(target).exterior.coords]
    subject_projection = [x * axis[0] + z * axis[1] for x, z in footprint(candidate).exterior.coords]
    target_lateral = [x * lateral[0] + z * lateral[1] for x, z in footprint(target).exterior.coords]
    subject_lateral = [x * lateral[0] + z * lateral[1] for x, z in footprint(candidate).exterior.coords]
    gap = min(subject_projection) - max(target_projection) if positive else min(target_projection) - max(subject_projection)
    overlap = min(max(target_lateral), max(subject_lateral)) - max(min(target_lateral), min(subject_lateral))
    assert .025 <= gap <= 1.5
    assert overlap >= .12


@pytest.mark.parametrize("target_locked", [False, True])
def test_required_relation_keeps_target_fixed_and_generates_preview(target_locked):
    scene = demo_scene()
    scene["room"].update(width=6., depth=6., door=None, windows=[])
    target = _item("wardrobe", "wardrobe-target", 3., 5., 180., locked=target_locked)
    bed = _item("double_bed", "bed-subject", 1., 1.)
    scene["items"] = [bed, target]
    scene["preferences"] = [{"kind": "relative_position", "itemId": bed["id"],
                             "targetId": target["id"], "direction": "front", "required": True}]
    Scene.model_validate(scene)

    result = generate_layouts(scene, mode="rules", count=1, seed=23)

    assert result["candidates"], result["diagnostics"]
    candidate = result["candidates"][0]
    assert candidate["validation"]["valid"]
    check = next(value for value in candidate["requirements"]["checks"] if value["kind"] == "relative_position")
    assert check["satisfied"], check
    placed = {item["id"]: item for item in candidate["scene"]["items"]}
    assert [placed[target["id"]][key] for key in ("x", "z", "rotation", "locked")] == [
        target[key] for key in ("x", "z", "rotation", "locked")]
    assert placed[bed["id"]] != bed


def test_fallback_room_bed_on_wardrobe_left_uses_edge_alignment():
    """A wide bed beside the north-wall wardrobe must not require centring.

    In the fallback room, the fixed wardrobe's left-side relationship is
    feasible only when the bed shares a small part of the wardrobe's length
    near an edge. A centred pose would extend through the north wall.
    """
    scene = demo_scene()
    scene["room"].update(
        width=5.2, depth=4.2,
        door={"wall": "south", "offset": .45, "width": .9, "clearance": .9},
    )
    items = {item["id"]: item for item in scene["items"]}
    items["bed-1"].update(x=3.8, z=2.4, rotation=0., locked=False)
    items["wardrobe-1"].update(width=1.8, x=1.15, z=3.8, rotation=180., locked=True)
    items["desk-1"].update(x=3.7, z=.55, rotation=0., locked=False)
    items["chair-1"].update(width=.5, depth=.5, x=3.7, z=1.1, rotation=180., locked=False)
    items["nightstand-1"].update(width=.5, depth=.45, x=2.6, z=2.8, rotation=0., locked=False)
    scene["preferences"] = [{"kind": "relative_position", "itemId": "bed-1",
                             "targetId": "wardrobe-1", "direction": "left", "required": True}]

    result = generate_layouts(scene, mode="rules", count=1, seed=42)

    assert result["candidates"], result["diagnostics"]
    candidate = result["candidates"][0]
    placed = {item["id"]: item for item in candidate["scene"]["items"]}
    check = next(value for value in candidate["requirements"]["checks"]
                 if value["kind"] == "relative_position")
    assert candidate["validation"]["valid"]
    assert check["satisfied"], check
    assert check["metrics"]["lateralOverlapMeters"] >= check["metrics"]["minLateralOverlapMeters"]
    assert [placed["wardrobe-1"][key] for key in ("x", "z", "rotation", "locked")] == [
        items["wardrobe-1"][key] for key in ("x", "z", "rotation", "locked")]


def test_face_item_places_an_armchair_toward_a_locked_coffee_table():
    scene = demo_scene()
    scene["room"].update(width=8., depth=8., door=None, windows=[])
    chair = _item("armchair", "chair", 1., 1.)
    table = _item("coffee_table", "table", 4., 4., locked=True)
    scene["items"] = [chair, table]
    scene["preferences"] = [{"kind": "face_item", "itemId": "chair", "targetId": "table", "required": True}]

    result = generate_layouts(scene, mode="rules", count=1, seed=11)

    assert result["candidates"], result["diagnostics"]
    candidate = result["candidates"][0]
    placed = {item["id"]: item for item in candidate["scene"]["items"]}
    check = next(value for value in candidate["requirements"]["checks"] if value["kind"] == "face_item")
    assert check["satisfied"], check
    assert evaluate_facing_preference(placed["chair"], placed["table"], scene["preferences"][0])["satisfied"]
    assert [placed["table"][key] for key in ("x", "z", "rotation", "locked")] == [4., 4., 0., True]


def test_relative_generation_never_returns_a_nightstand_in_front_of_the_wardrobe():
    scene = demo_scene()
    scene["room"].update(
        width=5.2, depth=4.2,
        door={"wall": "south", "offset": .45, "width": .9, "clearance": .9},
    )
    items = {item["id"]: item for item in scene["items"]}
    items["bed-1"].update(x=3.03, z=2.64, rotation=180., locked=False)
    items["wardrobe-1"].update(width=1.8, x=1.15, z=3.8, rotation=180., locked=True)
    items["desk-1"].update(x=3.7, z=.55, rotation=0., locked=False)
    items["chair-1"].update(width=.5, depth=.5, x=3.7, z=1.1, rotation=180., locked=False)
    items["nightstand-1"].update(width=.5, depth=.45, x=1.9, z=3.2, rotation=0., locked=False)
    scene["preferences"] = [{"kind": "relative_position", "itemId": "bed-1",
                             "targetId": "wardrobe-1", "direction": "left", "required": True}]

    result = generate_layouts(scene, mode="rules", count=3, seed=42)

    assert result["candidates"], result["diagnostics"]
    for candidate in result["candidates"]:
        assert candidate["validation"]["valid"]
        placed = {item["id"]: item for item in candidate["scene"]["items"]}
        assert all(not cabinet_door_clearance_conflicts(cabinet, other)
                   for cabinet in placed.values() for other in placed.values())
        assert [placed["wardrobe-1"][key] for key in ("x", "z", "rotation", "locked")] == [
            items["wardrobe-1"][key] for key in ("x", "z", "rotation", "locked")]


def test_locked_subject_cannot_satisfy_a_relative_position_by_moving():
    scene = demo_scene()
    scene["room"].update(width=6., depth=6., door=None, windows=[])
    bed = _item("double_bed", "bed-subject", 1., 1., locked=True)
    target = _item("wardrobe", "wardrobe-target", 3., 5., 180., locked=True)
    scene["items"] = [bed, target]
    scene["preferences"] = [{"kind": "relative_position", "itemId": bed["id"],
                             "targetId": target["id"], "direction": "front", "required": True}]

    result = generate_layouts(scene, mode="rules", count=1, seed=23)

    assert result["candidates"] == []
    assert "锁定" in result["diagnostics"]["message"]


@pytest.mark.parametrize("target_category", ["desk", "dressing_table", "dressing_chair"])
def test_functional_groups_preserve_unlocked_relative_reference(target_category):
    scene = demo_scene()
    scene["room"].update(width=8., depth=8., door=None, windows=[])
    target = _item(target_category, "target", 4., 4.)
    subject = _item("bookshelf", "subject", 1., 1.)
    scene["items"] = [target, subject]
    if target_category == "desk":
        scene["room"]["windows"] = [{"id": "window-1", "wall": "north", "offset": 3.,
                                      "width": 2., "height": 1.2, "sillHeight": .9}]
        target.update(z=7.66, rotation=180.)
        scene["items"].append(_item("chair", "seat", 4., 6.9))
        scene["preferences"] = [{"kind": "near_window", "itemId": "target",
                                  "targetId": "window-1", "required": True}]
    elif target_category == "dressing_table":
        scene["items"].append(_item("dressing_chair", "seat", 4., 4.78, 180.))
        scene["preferences"] = []
    else:
        target.update(z=4.78, rotation=180.)
        scene["items"].append(_item("dressing_table", "table", 4., 4.))
        scene["preferences"] = []
    scene["preferences"].append({"kind": "relative_position", "itemId": "subject",
                                 "targetId": "target", "direction": "right", "required": True})
    before = deepcopy(scene)

    result = generate_layouts(scene, mode="rules", count=1, seed=23)

    assert result["candidates"], result["diagnostics"]
    placed_target = next(item for item in result["candidates"][0]["scene"]["items"]
                         if item["id"] == "target")
    assert placed_target == target
    assert scene == before


def test_relative_reference_with_conflicting_window_request_cannot_be_moved_to_fit():
    scene = demo_scene()
    scene["room"].update(width=8., depth=8., door=None,
                         windows=[{"id": "window-1", "wall": "north", "offset": 3.,
                                   "width": 2., "height": 1.2, "sillHeight": .9}])
    scene["items"] = [_item("desk", "target", 4., 4.), _item("bookshelf", "subject", 1., 1.)]
    scene["preferences"] = [
        {"kind": "near_window", "itemId": "target", "targetId": "window-1", "required": True},
        {"kind": "relative_position", "itemId": "subject", "targetId": "target",
         "direction": "front", "required": True},
    ]

    result = generate_layouts(scene, mode="rules", count=1, seed=23)

    assert result["candidates"] == []


def test_impossible_relative_position_returns_no_candidate():
    scene = demo_scene()
    scene["room"].update(width=3., depth=2.4, door=None, windows=[])
    bed = _item("double_bed", "bed-subject", 1.5, 1., 0., locked=False)
    target = _item("wardrobe", "wardrobe-target", 1.5, 2.1, 180., locked=True)
    scene["items"] = [bed, target]
    scene["preferences"] = [{"kind": "relative_position", "itemId": bed["id"],
                             "targetId": target["id"], "direction": "front", "required": True}]

    result = generate_layouts(scene, mode="rules", count=1, seed=42)

    assert result["candidates"] == []
    assert result["diagnostics"]["rejected"]["placementFailed"] > 0


def test_chinese_bed_in_front_of_wardrobe_becomes_a_validated_relation():
    scene = demo_scene()
    before = deepcopy(scene)
    reply = interpret_command(scene, "\u628a\u5e8a\u653e\u5728\u8863\u67dc\u524d\u9762")

    assert reply["action"] == "generate", reply
    preference = next(value for value in reply["scene"]["preferences"] if value["kind"] == "relative_position")
    assert preference == {"kind": "relative_position", "itemId": "bed-1", "targetId": "wardrobe-1",
                          "required": True, "direction": "front"}
    assert scene == before
    Scene.model_validate(reply["scene"])


@pytest.mark.parametrize("suffix,direction", [
    ("\u524d\u9762", "front"), ("\u540e\u9762", "back"),
    ("\u5de6\u8fb9", "left"), ("\u53f3\u4fa7", "right"),
])
def test_command_parser_maps_four_chinese_directions(suffix, direction):
    scene = demo_scene()
    reply = interpret_command(scene, f"\u628a\u5e8a\u653e\u5728\u8863\u67dc{suffix}")
    preference = next(value for value in reply["scene"]["preferences"]
                      if value["kind"] == "relative_position")
    assert reply["action"] == "generate"
    assert preference["direction"] == direction


def test_bed_front_uses_the_head_side_for_local_z_zero_rotation():
    bed = _item("double_bed", "bed", 3., 3., 0.)
    subject = _item("desk", "desk", .7, .7)
    preference = {"kind": "relative_position", "itemId": "desk", "targetId": "bed",
                  "direction": "front", "required": True}

    placed = next(relative_position_placements(subject, bed, preference))

    assert placed["z"] < bed["z"]
    assert evaluate_relative_position(placed, bed, preference)["satisfied"]


def test_structured_relative_plan_compiles_to_the_local_executor():
    scene = demo_scene()
    plan = {"action": "apply", "operations": [{"name": "relative_position", "itemIds": ["bed-1"],
             "targetId": "wardrobe-1", "direction": "front", "required": True}]}

    validated = validate_plan_against_scene(plan, scene)
    text = compile_plan(validated, scene)
    reply = interpret_command(scene, text)

    assert "bed-1放在wardrobe-1前方" in text
    assert reply["action"] == "generate", reply
    assert any(preference["kind"] == "relative_position" and preference["direction"] == "front"
               for preference in reply["scene"]["preferences"])

    assert _scene_payload(reply["scene"], None)["preferences"][-1]["direction"] == "front"


def test_soft_structured_relative_plan_preserves_preference_strength():
    scene = demo_scene()
    plan = {"action": "apply", "operations": [{"name": "relative_position", "itemIds": ["bed-1"],
             "targetId": "wardrobe-1", "direction": "front", "required": False}]}

    reply = interpret_command(scene, compile_plan(plan, scene))

    assert reply["action"] == "generate", reply
    preference = next(value for value in reply["scene"]["preferences"]
                      if value["kind"] == "relative_position")
    assert preference["required"] is False


@pytest.mark.parametrize("operation,message", [
    ({"itemIds": ["bed-1", "desk-1"], "targetId": "wardrobe-1", "direction": "front"}, "一件现有实体家具"),
    ({"itemIds": ["bed-1"], "targetId": "bed-1", "direction": "front"}, "另一件现有家具"),
    ({"itemIds": ["bed-1"], "targetId": "wardrobe-1"}, "指定前后左右方向"),
])
def test_invalid_structured_relative_plan_explains_the_problem(operation, message):
    plan = {"action": "apply", "operations": [{"name": "relative_position", **operation}]}
    with pytest.raises(ValueError, match=message):
        validate_plan_against_scene(plan, demo_scene())


def test_relative_target_is_implicitly_fixed_for_language_plan_lock_guard():
    scene = demo_scene()
    plan = {"action": "apply", "operations": [{"name": "relative_position", "itemIds": ["bed-1"],
             "targetId": "wardrobe-1", "direction": "front", "required": True}]}
    validated = validate_plan_against_scene(plan, scene)

    assert _position_lock_guard(validated, "衣柜保持原位，床放在衣柜前面", scene, None) is None


def test_scene_rejects_self_referential_relative_position():
    scene = demo_scene()
    scene["preferences"] = [{"kind": "relative_position", "itemId": "bed-1",
                             "targetId": "bed-1", "direction": "front", "required": True}]
    with pytest.raises(ValueError):
        Scene.model_validate(scene)
