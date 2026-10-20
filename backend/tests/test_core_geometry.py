from copy import deepcopy

import pytest
from pydantic import ValidationError

from roomwise.catalog import demo_scene
from roomwise.geometry import assert_invariants, footprint, layout_quality, validate_scene
from roomwise.schemas import Scene


def item(category="desk", **extra):
    return {"id": "one", "label": "测试物品", "category": category, "width": 1., "depth": .6, "height": .7, "x": 2., "z": 2., "rotation": 0, "keep": True, "locked": False, "source": "brought", **extra}


def scene_with(items):
    scene = demo_scene()
    scene["items"] = items
    scene["preferences"] = []
    return scene


def test_yaw_matches_threejs():
    poly = footprint(item(width=2., depth=1., x=0, z=0, rotation=30))
    assert poly.covers(__import__("shapely").geometry.Point(.85, -.49))
    assert not poly.covers(__import__("shapely").geometry.Point(.85, .49))


def test_rotated_boundary_door_and_collision():
    assert not validate_scene(scene_with([item(x=.1, rotation=45)]))["valid"]
    door_check = validate_scene(scene_with([item(x=.8, z=.3)]))
    assert door_check["metrics"]["doorConflicts"] == 1
    overlap = validate_scene(scene_with([item(), item(id="two", x=2.1)]))
    assert overlap["metrics"]["collisions"] == 1


def test_rug_not_obstacle_and_limited_chair_tuck():
    table = item(category="table", width=1.2, depth=.8, height=.75)
    rug = item(id="rug", category="rug", width=2, depth=2, height=.02)
    assert validate_scene(scene_with([table, rug]))["valid"]
    chair = item(id="chair", category="chair", width=.5, depth=.5, z=2.55, height=.85)
    check = validate_scene(scene_with([table, chair]))
    assert check["metrics"]["collisions"] == 0
    assert any(i["type"] == "seat_tuck" for i in check["issues"])
    chair["z"] = 2
    assert validate_scene(scene_with([table, chair]))["metrics"]["collisions"] == 1


def test_accessibility_blocked_by_full_width_furniture():
    barrier = item(category="wardrobe", width=5.2, depth=.5, x=2.6, z=1.6, height=2)
    bed = item(category="single_bed", id="bed", width=1, depth=1.8, x=3, z=3, height=.5)
    result = validate_scene(scene_with([barrier, bed]))
    assert result["metrics"]["reachable"] is False
    assert "bed" in result["metrics"]["accessibility"]["unreachableItemIds"]


def test_invariants_reject_resize_drop_metadata_and_locks():
    original = scene_with([item(locked=True)])
    for key, value in (("width", .5), ("x", 3), ("keep", False), ("source", "new")):
        proposed = deepcopy(original)
        proposed["items"][0][key] = value
        with pytest.raises(ValueError):
            assert_invariants(original, proposed)
    proposed = deepcopy(original)
    proposed["items"] = []
    with pytest.raises(ValueError):
        assert_invariants(original, proposed)


def test_schema_rejects_duplicate_nan_and_invalid_polygon():
    duplicate = scene_with([item(), item()])
    with pytest.raises(ValidationError):
        Scene.model_validate(duplicate)
    with pytest.raises(ValidationError):
        Scene.model_validate(scene_with([item(x=float("nan"))]))
    invalid = scene_with([])
    invalid["room"]["polygon"] = [[0, 0], [2, 2], [0, 2], [2, 0]]
    with pytest.raises(ValidationError):
        Scene.model_validate(invalid)


def test_layout_quality_prefers_wall_alignment_and_functional_grouping():
    # Both arrangements are geometrically valid.  The soft score should rank
    # the arrangement users normally expect to see in a room preview.
    desk_wall = item(x=.75, z=2.1)
    chair_near = item(id="chair", category="chair", x=1.35, z=2.1, width=.48, depth=.5, height=.85)
    good = scene_with([desk_wall, chair_near])
    desk_middle = item(x=2.6, z=2.1)
    chair_far = item(id="chair", category="chair", x=4.1, z=2.1, width=.48, depth=.5, height=.85)
    weak = scene_with([desk_middle, chair_far])
    assert validate_scene(good)["valid"]
    assert validate_scene(weak)["valid"]
    good_score = layout_quality(good)
    weak_score = layout_quality(weak)
    assert good_score["penalty"] < weak_score["penalty"]
    assert good_score["components"]["wallAnchoring"] < weak_score["components"]["wallAnchoring"]
    assert good_score["components"]["functionalGrouping"] < weak_score["components"]["functionalGrouping"]


def test_layout_quality_pairs_dressing_chair_with_dressing_table():
    dressing_table = item(id="dresser", category="dressing_table", x=1.4, z=2., width=1.1, depth=.5)
    close = item(id="seat", category="dressing_chair", x=1.4, z=2.7, width=.45, depth=.45)
    far = item(id="seat", category="dressing_chair", x=4.5, z=.5, width=.45, depth=.45)
    close_scene = scene_with([dressing_table, close])
    far_scene = scene_with([dressing_table, far])
    assert layout_quality(close_scene)["components"]["functionalGrouping"] < layout_quality(far_scene)["components"]["functionalGrouping"]


def test_quality_disables_cardinal_angle_bias_for_irregular_polygon():
    polygon_scene = scene_with([item(x=2.3, z=2.2, rotation=0)])
    polygon_scene["room"]["polygon"] = [[0, 0], [4.4, .4], [5.2, 3.4], [.4, 4.2]]
    polygon_scene["room"]["width"] = 5.2
    polygon_scene["room"]["depth"] = 4.2
    polygon_scene["items"][0]["rotation"] = 45
    quality = layout_quality(polygon_scene)
    assert quality["components"]["axisAlignment"] == 0


def test_nightstand_beside_bed_scores_better_than_at_foot():
    bed = item(id="bed", category="double_bed", width=1.8, depth=2., x=2.6, z=2.1)
    bedside = item(id="stand", category="nightstand", width=.5, depth=.5, x=1.4, z=2.1)
    footside = item(id="stand", category="nightstand", width=.5, depth=.5, x=2.6, z=3.45)
    side_score = layout_quality(scene_with([bed, bedside]))["components"]["functionalGrouping"]
    foot_score = layout_quality(scene_with([bed, footside]))["components"]["functionalGrouping"]
    assert side_score < foot_score


def test_quality_discourages_large_piece_covering_center():
    centered = item(category="double_bed", width=2.2, depth=2.2, x=2.6, z=2.1)
    beside = item(category="double_bed", width=2.2, depth=2.2, x=1.35, z=2.1)
    centered_score = layout_quality(scene_with([centered]))["components"]["openCenter"]
    beside_score = layout_quality(scene_with([beside]))["components"]["openCenter"]
    assert centered_score > beside_score
