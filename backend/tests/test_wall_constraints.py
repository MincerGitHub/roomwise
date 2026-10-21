"""Real geometry and atomic editing regressions for reusable wall requests."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from roomwise.catalog import demo_scene
from roomwise.commands import apply_command
from roomwise.generator import generate_layouts
from roomwise.geometry import assert_invariants, validate_scene
from roomwise.schemas import Preference, Scene
from roomwise.window_constraints import evaluate_layout_requirements, evaluate_wall_preference


def bookshelf_scene():
    scene = demo_scene()
    scene["items"] = [{"id": "bookshelf-1", "label": "旧书架", "category": "bookshelf",
                       "width": .8, "depth": .3, "height": 1.8,
                       "x": 1.2, "z": 2.3, "rotation": 90., "locked": False,
                       "keep": True, "source": "brought"}]
    scene["preferences"] = []
    scene["room"]["door"] = None
    scene["room"]["windows"] = []
    return scene


@pytest.fixture(autouse=True)
def no_model_import(monkeypatch):
    monkeypatch.setattr("roomwise.generator.learning_status", lambda: {"available": False})


@pytest.mark.parametrize("text", ["书架靠墙", "书架贴墙摆", "书柜挨着墙", "把书架沿墙放", "bookshelf-1靠墙"])
def test_common_requests_become_same_primitive_without_moving_original(text):
    scene = bookshelf_scene()
    original = deepcopy(scene)
    reply = apply_command(scene, text)
    assert reply["action"] == "generate", reply
    assert reply["scene"]["preferences"] == [{"kind": "near_wall", "itemId": "bookshelf-1", "required": True}]
    assert reply["scene"]["items"] == original["items"]
    assert scene == original
    assert "背面朝墙" in reply["message"]
    Scene.model_validate(reply["scene"])


@pytest.mark.parametrize("name,wall", [("北", "north"), ("后", "north"), ("南", "south"), ("前", "south"),
                                       ("东", "east"), ("右", "east"), ("西", "west"), ("左", "west")])
def test_named_wall_has_camera_independent_coordinates(name, wall):
    reply = apply_command(bookshelf_scene(), f"书架靠{name}墙")
    assert reply["scene"]["preferences"][0]["wall"] == wall
    assert "房间" in reply["message"]


def test_soft_preference_can_be_replaced_without_stale_direction_or_duplicates():
    reply = apply_command(bookshelf_scene(), "书架尽量靠北墙")
    assert not reply["scene"]["preferences"][0]["required"]
    repeated = apply_command(reply["scene"], "书架靠墙")
    assert repeated["scene"]["preferences"] == [{"kind": "near_wall", "itemId": "bookshelf-1", "required": True}]


@pytest.mark.parametrize("text", ["书架不要靠墙", "书架不能贴北墙", "书架别再挨着墙", "书柜不靠西墙"])
def test_negative_wall_requests_do_not_silently_become_positive(text):
    scene = bookshelf_scene()
    original = deepcopy(scene)
    reply = apply_command(scene, text)
    assert reply["action"] == "clarify"
    assert "scene" not in reply
    assert scene == original


def test_locked_item_requires_explicit_unlock_and_edit_is_atomic():
    scene = bookshelf_scene()
    scene["items"][0]["locked"] = True
    blocked = apply_command(scene, "书架靠墙")
    assert blocked["action"] == "clarify"
    assert "scene" not in blocked
    accepted = apply_command(scene, "书架解锁并靠西墙")
    assert accepted["action"] == "generate"
    assert not accepted["scene"]["items"][0]["locked"]


def test_schema_rejects_cross_kind_targets_and_unknown_walls():
    Preference(kind="near_wall", itemId="one", wall="north", required=True)
    for invalid in ({"kind": "near_wall", "targetId": "window-1"},
                    {"kind": "near_wall", "wall": "ceiling"},
                    {"kind": "face_window", "wall": "north"},
                    {"kind": "min_move", "wall": "east"}):
        with pytest.raises(ValidationError):
            Preference(itemId="one", **invalid)


@pytest.mark.parametrize("wall,rotation", [("north", 180), ("south", 0), ("east", 270), ("west", 90)])
def test_generator_satisfies_actual_wall_gap_with_back_to_wall(wall, rotation):
    scene = bookshelf_scene()
    scene["preferences"] = [{"kind": "near_wall", "itemId": "bookshelf-1", "required": True, "wall": wall}]
    result = generate_layouts(scene, mode="rules", count=1, seed=42)
    assert result["candidates"], result["diagnostics"]
    candidate = result["candidates"][0]
    item = candidate["scene"]["items"][0]
    assert item["rotation"] == rotation
    assert candidate["requirements"]["satisfied"]
    metrics = candidate["requirements"]["checks"][0]["metrics"]
    assert metrics["distanceMeters"] <= .15
    assert metrics["backAlignmentErrorDegrees"] == 0
    assert_invariants(scene, candidate["scene"])
    assert validate_scene(candidate["scene"])["valid"]


def test_side_touch_or_front_towards_wall_is_not_valid_back_to_wall_arrangement():
    scene = bookshelf_scene()
    item = scene["items"][0]
    item.update(x=2., z=4.02, rotation=0.)
    preference = {"kind": "near_wall", "itemId": item["id"], "wall": "north", "required": True}
    check = evaluate_wall_preference(item, scene["room"], preference)
    assert check["metrics"]["distanceMeters"] < .15
    assert not check["satisfied"]


def test_local_request_keeps_unmentioned_furniture_and_uses_nearest_wall():
    scene = bookshelf_scene()
    scene["items"][0].update(x=.7, z=2., rotation=90.)
    untouched = {"id": "bed-1", "label": "床", "category": "double_bed",
                 "width": 1.8, "depth": 2., "height": .55, "x": 3., "z": 2.,
                 "rotation": 0, "locked": False, "keep": True, "source": "brought"}
    scene["items"].append(untouched)
    scene = apply_command(scene, "书架靠墙")["scene"]
    original = deepcopy(scene)
    result = generate_layouts(scene, mode="hybrid", count=1)
    assert result["candidates"], result["diagnostics"]
    candidate = result["candidates"][0]
    assert candidate["scene"]["items"][1] == untouched
    assert candidate["requirements"]["checks"][0]["wall"] == "west"
    assert candidate["changes"]["otherMovedItemIds"] == []
    assert candidate["provenance"]["layoutNetwork"] is False
    assert scene == original


def test_nonrectangular_room_uses_real_sloping_wall_and_rejects_absent_north_wall():
    scene = bookshelf_scene()
    scene["room"].update(width=5., depth=5., polygon=[[0, 0], [5, 0], [0, 5]])
    scene["items"][0].update(x=2.2, z=2.2, rotation=225.)
    scene["preferences"] = [{"kind": "near_wall", "itemId": "bookshelf-1", "required": True}]
    result = generate_layouts(scene, mode="rules", count=1)
    assert result["candidates"], result["diagnostics"]
    check = result["candidates"][0]["requirements"]["checks"][0]
    assert check["satisfied"]
    assert check["wall"].startswith("boundary-")
    assert check["metrics"]["backAlignmentErrorDegrees"] < 1e-6
    scene["preferences"][0]["wall"] = "north"
    missing = generate_layouts(scene, mode="rules", count=1)
    assert not missing["candidates"]
    assert "没有指定方向" in missing["diagnostics"]["message"]


def test_unsatisfied_locked_wall_constraint_has_no_geometry_only_fallback():
    scene = bookshelf_scene()
    scene["items"][0]["locked"] = True
    scene["preferences"] = [{"kind": "near_wall", "itemId": "bookshelf-1", "required": True}]
    result = generate_layouts(scene, mode="rules", count=1)
    assert not result["candidates"]
    assert "锁定" in result["diagnostics"]["message"]
    assert not result["diagnostics"]["requirements"]["satisfied"]


def test_window_desk_chair_group_and_wall_request_are_checked_together():
    scene = demo_scene()
    scene["items"] = [item for item in scene["items"] if item["id"] in {"desk-1", "chair-1"}]
    scene["items"].append(bookshelf_scene()["items"][0])
    scene["room"]["door"] = None
    reply = apply_command(scene, "桌子靠窗，椅子面朝窗户方向，书架靠西墙")
    assert reply["action"] == "generate"
    result = generate_layouts(reply["scene"], mode="rules", count=1)
    assert result["candidates"], result["diagnostics"]
    candidate = result["candidates"][0]
    assert candidate["validation"]["valid"]
    assert candidate["requirements"]["satisfied"]
    assert {check["kind"] for check in candidate["requirements"]["checks"]} == {"near_wall", "near_window", "face_window"}
    assert_invariants(scene, candidate["scene"])


def test_global_except_chair_wall_request_targets_all_movable_non_chairs():
    scene = demo_scene()
    reply = apply_command(scene, "办公桌靠窗，除了椅子以外的家具尽量靠墙摆放")
    assert reply["action"] == "generate", reply
    preferences = reply["scene"]["preferences"]
    wall_preferences = {preference["itemId"]: preference for preference in preferences
                        if preference["kind"] == "near_wall"}
    # The locked wardrobe is already fixed in place. The command should
    # target every other movable item except the chair, rather than resolving
    # only the literal word "椅子".
    assert set(wall_preferences) == {"bed-1", "desk-1", "nightstand-1"}
    assert all(not preference["required"] for preference in wall_preferences.values())
    assert "chair-1" not in wall_preferences


def test_global_soft_wall_request_moves_non_chairs_when_combined_with_window_request():
    scene = demo_scene()
    reply = apply_command(scene, "办公桌靠窗，除了椅子以外的家具尽量靠墙摆放")
    result = generate_layouts(reply["scene"], mode="rules", count=1, seed=42)
    assert result["candidates"], result["diagnostics"]
    candidate = result["candidates"][0]
    for item in candidate["scene"]["items"]:
        if item["category"] == "chair":
            continue
        check = evaluate_wall_preference(item, candidate["scene"]["room"],
                                         {"kind": "near_wall", "itemId": item["id"], "required": True})
        assert check["satisfied"], (item["id"], check)
    assert candidate["requirements"]["satisfied"]


@pytest.mark.parametrize("reference", ["chair-1和chair-2", "办公椅和备用椅"])
def test_only_adjust_accepts_explicit_multiple_ids_or_unique_full_names(reference):
    scene = demo_scene()
    chair = next(item for item in scene["items"] if item["id"] == "chair-1")
    scene["items"].append({**chair, "id": "chair-2", "label": "备用椅", "x": 4., "z": 3.})
    reply = apply_command(scene, f"只调整{reference}")
    assert reply["action"] == "generate", reply
    after = {item["id"]: item for item in reply["scene"]["items"]}
    assert not after["chair-1"]["locked"] and not after["chair-2"]["locked"]
    assert after["desk-1"]["locked"]


def test_only_adjust_generic_category_still_clarifies_multiple_chairs():
    scene = demo_scene()
    chair = next(item for item in scene["items"] if item["id"] == "chair-1")
    scene["items"].append({**chair, "id": "chair-2", "label": "备用椅", "x": 4., "z": 3.})
    reply = apply_command(scene, "只调整椅子")
    assert reply["action"] == "clarify"
    assert "scene" not in reply

