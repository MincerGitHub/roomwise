from copy import deepcopy
import math
import random

import pytest

from roomwise.catalog import demo_scene
from roomwise.geometry import assert_invariants, footprint, validate_scene
from roomwise.layout_templates import functional_template
from roomwise.window_constraints import evaluate_wall_preference


def scene_with_bookshelf():
    scene = demo_scene()
    scene["items"].append({"id": "bookshelf-1", "label": "旧书架", "category": "bookshelf",
                           "width": .8, "depth": .3, "height": 1.8, "x": .55, "z": 1.5,
                           "rotation": 90., "locked": False, "keep": True, "source": "brought"})
    return scene


def _forward_dot(item, target):
    angle = math.radians(item["rotation"])
    dx, dz = target["x"] - item["x"], target["z"] - item["z"]
    return (math.sin(angle) * dx + math.cos(angle) * dz) / math.hypot(dx, dz)


@pytest.mark.parametrize("extra_bookshelf", [False, True])
def test_complete_demo_has_head_wall_bedside_and_front_facing_desk_chair(extra_bookshelf):
    scene = scene_with_bookshelf() if extra_bookshelf else demo_scene()
    original = deepcopy(scene)
    proposed = functional_template(scene, random.Random(42))
    assert proposed is not None
    assert scene == original
    assert_invariants(scene, proposed)
    assert validate_scene(proposed)["valid"]
    items = {item["id"]: item for item in proposed["items"]}
    for item_id in ["bed-1", *(["bookshelf-1"] if extra_bookshelf else [])]:
        check = evaluate_wall_preference(items[item_id], proposed["room"], {"kind": "near_wall", "itemId": item_id})
        assert check["satisfied"], check
    desk, chair = items["desk-1"], items["chair-1"]
    assert _forward_dot(chair, desk) > .95
    assert (desk["rotation"] - chair["rotation"]) % 360 == 180
    assert .07 <= footprint(desk).distance(footprint(chair)) <= .26
    bed, stand = items["bed-1"], items["nightstand-1"]
    angle = math.radians(bed["rotation"])
    dx, dz = stand["x"] - bed["x"], stand["z"] - bed["z"]
    local_x = math.cos(angle) * dx - math.sin(angle) * dz
    local_z = math.sin(angle) * dx + math.cos(angle) * dz
    assert abs(local_x) > bed["width"] / 2
    assert local_z < -bed["depth"] / 4
    assert footprint(bed).distance(footprint(stand)) < .2
    assert items["wardrobe-1"] == next(item for item in original["items"] if item["id"] == "wardrobe-1")


def test_locked_chair_anchors_movable_desk_without_being_moved():
    scene = demo_scene()
    scene["items"] = [item for item in scene["items"] if item["id"] in {"desk-1", "chair-1"}]
    scene["room"]["door"] = None
    scene["preferences"] = []
    scene["items"][1].update(locked=True, x=2.6, z=2.2, rotation=0.)
    original_chair = deepcopy(scene["items"][1])
    proposed = functional_template(scene, random.Random(9))
    assert proposed is not None
    desk, chair = proposed["items"]
    assert chair == original_chair
    assert _forward_dot(chair, desk) > .95
    assert_invariants(scene, proposed)
    assert validate_scene(proposed)["valid"]


def test_locked_bed_can_remain_freestanding_but_stand_is_grouped_to_its_head():
    scene = demo_scene()
    scene["items"] = [item for item in scene["items"] if item["id"] in {"bed-1", "nightstand-1"}]
    scene["items"][0].update(locked=True, x=2.6, z=2.1, rotation=0.)
    scene["room"]["door"] = None
    scene["preferences"] = []
    original_bed = deepcopy(scene["items"][0])
    proposed = functional_template(scene, random.Random(42))
    assert proposed is not None
    bed, stand = proposed["items"]
    assert bed == original_bed
    assert stand["z"] < bed["z"] - bed["depth"] / 4
    assert_invariants(scene, proposed)


def test_two_bedside_tables_use_opposite_head_sides_and_retain_both_ids():
    scene = demo_scene()
    scene["items"] = [item for item in scene["items"] if item["id"] in {"bed-1", "nightstand-1"}]
    scene["items"].append({**scene["items"][1], "id": "nightstand-2", "label": "第二床头柜", "x": 1.3, "z": 3.1})
    scene["room"]["door"] = None
    scene["preferences"] = []
    proposed = functional_template(scene, random.Random(22))
    assert proposed is not None
    bed, first, second = proposed["items"]
    angle = math.radians(bed["rotation"])
    offsets = [(math.cos(angle) * (stand["x"] - bed["x"]) - math.sin(angle) * (stand["z"] - bed["z"])) for stand in (first, second)]
    assert offsets[0] * offsets[1] < 0
    assert_invariants(scene, proposed)
    assert validate_scene(proposed)["valid"]


def test_sloping_wall_template_uses_actual_wall_normal_not_cardinal_rounding():
    scene = scene_with_bookshelf()
    scene["items"] = [scene["items"][-1]]
    scene["items"][0].update(x=2.2, z=2.2, rotation=225.)
    scene["room"].update(width=5., depth=5., polygon=[[0, 0], [5, 0], [0, 5]], door=None, windows=[])
    scene["preferences"] = []
    proposed = functional_template(scene, random.Random(42))
    assert proposed is not None
    check = evaluate_wall_preference(proposed["items"][0], proposed["room"], {"kind": "near_wall", "itemId": "bookshelf-1"})
    assert check["satisfied"]
    assert check["wall"].startswith("boundary-")
    assert validate_scene(proposed)["valid"]


@pytest.mark.parametrize("kind", ["near_window", "near_wall", "face_window", "min_move"])
def test_explicit_requirements_bypass_whole_room_templates(kind):
    scene = demo_scene()
    scene["preferences"] = [{"kind": kind, "itemId": "desk-1", "required": True}]
    original = deepcopy(scene)
    assert functional_template(scene, random.Random(42)) is None
    assert scene == original


def test_budget_exhaustion_returns_none_without_any_partial_edit():
    class TinyBudget:
        remaining = 2
        def take(self):
            self.remaining -= 1
            return self.remaining >= 0
    scene = scene_with_bookshelf()
    original = deepcopy(scene)
    assert functional_template(scene, random.Random(42), TinyBudget()) is None
    assert scene == original


def test_impossible_retained_furniture_is_not_shrunk_or_dropped():
    scene = demo_scene()
    scene["room"].update(width=2., depth=2., door=None, windows=[])
    scene["items"] = [scene["items"][0]]
    scene["items"][0].update(width=3., depth=3.)
    scene["preferences"] = []
    original = deepcopy(scene)
    assert functional_template(scene, random.Random(42)) is None
    assert scene == original


def test_invalid_locked_obstacle_never_moved_to_make_a_template_fit():
    scene = demo_scene()
    scene["items"][1].update(x=-2.)
    original = deepcopy(scene)
    assert functional_template(scene, random.Random(42)) is None
    assert scene == original


@pytest.mark.parametrize("mode,extra_bookshelf", [("hybrid", False), ("rules", True)])
def test_generator_count_three_uses_truthful_functional_groups_and_preserves_furniture(monkeypatch, mode, extra_bookshelf):
    from roomwise.generator import generate_layouts
    monkeypatch.setattr("roomwise.generator.learning_status", lambda: {"available": True})
    scene = scene_with_bookshelf() if extra_bookshelf else demo_scene()
    original = deepcopy(scene)
    result = generate_layouts(scene, mode=mode, count=3, seed=42)
    assert len(result["candidates"]) == 3, result["diagnostics"]
    assert result["diagnostics"]["functionalTemplates"]["accepted"] == 3
    assert result["diagnostics"]["modelProposals"] == 0
    for candidate in result["candidates"]:
        assert candidate["mode"] == "rules"
        assert candidate["provenance"]["initialization"] == "functional_group_template"
        assert candidate["provenance"]["layoutNetwork"] is False
        assert candidate["validation"]["valid"]
        assert_invariants(scene, candidate["scene"])
        items = {item["id"]: item for item in candidate["scene"]["items"]}
        assert _forward_dot(items["chair-1"], items["desk-1"]) > .95
        bed = items["bed-1"]
        assert evaluate_wall_preference(bed, scene["room"], {"kind": "near_wall", "itemId": bed["id"]})["satisfied"]
    assert scene == original


def test_generator_required_min_move_bypasses_template_and_uses_explicit_legacy_fallback(monkeypatch):
    from roomwise.generator import generate_layouts
    monkeypatch.setattr("roomwise.generator.learning_status", lambda: {"available": False})
    scene = demo_scene()
    scene["preferences"] = [{"kind": "min_move", "itemId": "desk-1", "required": True}]
    result = generate_layouts(scene, mode="rules", count=1, seed=42)
    assert result["candidates"], result["diagnostics"]
    assert result["diagnostics"]["functionalTemplates"]["accepted"] == 0
    for candidate in result["candidates"]:
        assert candidate.get("provenance", {}).get("initialization") != "functional_group_template"
        assert_invariants(scene, candidate["scene"])


def test_generator_preserves_false_keep_and_true_keep_metadata(monkeypatch):
    from roomwise.generator import generate_layouts
    monkeypatch.setattr("roomwise.generator.learning_status", lambda: {"available": False})
    scene = demo_scene()
    scene["items"][0]["keep"] = False
    result = generate_layouts(scene, mode="rules", count=1, seed=42)
    assert result["candidates"]
    proposed = result["candidates"][0]["scene"]
    assert_invariants(scene, proposed)
    assert len(proposed["items"]) == len(scene["items"])
    assert proposed["items"][0]["keep"] is False


def test_constraint_search_keeps_vanity_chair_paired_with_its_table():
    from roomwise.generator import rule_candidate

    scene = demo_scene()
    scene["room"]["door"] = None
    scene["preferences"] = [{"kind": "near_window", "itemId": "desk-1", "targetId": "window-1", "required": True}]
    scene["items"].extend([
        {"id": "vanity-1", "label": "vanity", "category": "dressing_table",
         "width": 1.0, "depth": .45, "height": .75, "x": .7, "z": .7,
         "rotation": 0., "locked": False, "keep": True, "source": "brought"},
        {"id": "vanity-chair-1", "label": "vanity chair", "category": "dressing_chair",
         "width": .4, "depth": .4, "height": .75, "x": 4.0, "z": 3.4,
         "rotation": 90., "locked": False, "keep": True, "source": "brought"},
    ])
    proposed = rule_candidate(scene, random.Random(42))
    assert proposed is not None
    assert validate_scene(proposed)["valid"]
    from roomwise.geometry import evaluate_vanity_seating
    assert evaluate_vanity_seating(proposed)["satisfied"]
    items = {item["id"]: item for item in proposed["items"]}
    vanity, chair = items["vanity-1"], items["vanity-chair-1"]
    assert _forward_dot(items["chair-1"], items["desk-1"]) > .95
    assert _forward_dot(chair, vanity) > .95
    assert (vanity["rotation"] - chair["rotation"]) % 360 == 180
    assert .07 <= footprint(vanity).distance(footprint(chair)) <= .30
    angle = math.radians(vanity["rotation"])
    dx, dz = chair["x"] - vanity["x"], chair["z"] - vanity["z"]
    local_x = math.cos(angle) * dx - math.sin(angle) * dz
    local_z = math.sin(angle) * dx + math.cos(angle) * dz
    assert abs(local_x) <= .11
    assert local_z > 0


def test_rule_fallback_keeps_new_vanity_at_wall_and_pairs_catalog_stool(monkeypatch):
    from roomwise.generator import generate_layouts, rule_candidate
    from roomwise.window_constraints import evaluate_wall_preference
    from roomwise.geometry import evaluate_vanity_seating

    # Recreate the app flow: generate once, then add the two catalog items at
    # the room centre. Force the documented fallback after the group template
    # so this covers the path that used to accept a vanity in the middle.
    first = generate_layouts(demo_scene(), mode="rules", count=1, seed=42)
    assert first["candidates"]
    scene = deepcopy(first["candidates"][0]["scene"])
    scene["items"].extend([
        {"id": "vanity-new", "label": "梳妆台", "category": "dressing_table",
         "width": 1.0, "depth": .45, "height": .75,
         "x": scene["room"]["width"] / 2, "z": scene["room"]["depth"] / 2,
         "rotation": 0., "locked": False, "keep": True, "source": "brought"},
        {"id": "vanity-stool-new", "label": "梳妆凳", "category": "stool",
         "width": .4, "depth": .4, "height": .45,
         "x": scene["room"]["width"] / 2, "z": scene["room"]["depth"] / 2,
         "rotation": 0., "locked": False, "keep": True, "source": "brought"},
    ])
    monkeypatch.setattr("roomwise.generator.learning_status", lambda: {"available": False})
    monkeypatch.setattr("roomwise.generator.functional_template", lambda *args: None)

    # Exercise the rule fallback directly: it must be safe even when the
    # group template cannot supply the proposal.
    candidate = rule_candidate(scene, random.Random(0))
    assert candidate is not None
    items = {item["id"]: item for item in candidate["items"]}
    wall = evaluate_wall_preference(items["vanity-new"], candidate["room"],
                                    {"kind": "near_wall", "itemId": "vanity-new"})
    assert wall["satisfied"], wall
    seating = evaluate_vanity_seating(candidate)
    assert seating["satisfied"], seating
    assert any(check["chairId"] == "vanity-stool-new" for check in seating["checks"])


def test_functional_template_pairs_catalog_stool_with_vanity_before_desk():
    from roomwise.geometry import evaluate_vanity_seating
    from roomwise.layout_templates import _groups

    scene = demo_scene()
    scene["room"]["door"] = None
    scene["preferences"] = []
    scene["items"] = [item for item in scene["items"] if item["id"] in {"desk-1", "chair-1"}]
    scene["items"].extend([
        {"id": "vanity", "label": "梳妆台", "category": "dressing_table",
         "width": 1.0, "depth": .45, "height": .75, "x": 2.6, "z": 2.1,
         "rotation": 0., "locked": False, "keep": True, "source": "brought"},
        {"id": "stool", "label": "梳妆凳", "category": "stool",
         "width": .4, "depth": .4, "height": .45, "x": 2.6, "z": 2.1,
         "rotation": 0., "locked": False, "keep": True, "source": "brought"},
    ])

    groups = _groups(scene["items"])
    vanity_group = next(group for group in groups if group[0]["id"] == "vanity")
    assert [seat["id"] for seat in vanity_group[1]] == ["stool"]

    proposed = functional_template(scene, random.Random(42))

    assert proposed is not None
    assert validate_scene(proposed)["valid"]
    items = {item["id"]: item for item in proposed["items"]}
    wall = evaluate_wall_preference(items["vanity"], proposed["room"],
                                    {"kind": "near_wall", "itemId": "vanity"})
    assert wall["satisfied"], wall
    assert evaluate_vanity_seating(proposed)["satisfied"]
