import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roomwise.catalog import demo_scene
from roomwise.geometry import layout_quality, validate_scene
from roomwise.generator import rule_candidate


def test_quality_exposes_explainable_components_and_penalty():
    scene = demo_scene()
    quality = layout_quality(scene)
    assert quality["penalty"] >= 0
    assert {"wallAnchoring", "axisAlignment", "functionalGrouping", "clearance", "openCenter", "rugPlacement"} <= set(quality["components"])


def test_rule_candidate_remains_valid_and_keeps_quality_metadata_path():
    scene = demo_scene()
    candidate = rule_candidate(scene, __import__("random").Random(17))
    assert candidate is not None
    assert validate_scene(candidate)["valid"]
    # The candidate should be scored through the same quality function used by
    # the API; this catches accidental changes that bypass aesthetic ranking.
    assert layout_quality(candidate)["penalty"] >= 0


def test_quality_penalizes_detached_desk_chair_pair():
    scene = demo_scene()
    baseline = layout_quality(scene)["components"]["functionalGrouping"]
    detached = copy.deepcopy(scene)
    chair = next(item for item in detached["items"] if item["category"] == "chair")
    chair["x"] = .35
    chair["z"] = .35
    assert layout_quality(detached)["components"]["functionalGrouping"] > baseline


def test_chair_facing_table_scores_better_than_same_position_facing_away():
    scene = demo_scene()
    desk = next(item for item in scene["items"] if item["id"] == "desk-1")
    chair = next(item for item in scene["items"] if item["id"] == "chair-1")
    desk.update(x=3.,z=3.,rotation=180.)
    chair.update(x=3.,z=2.2,rotation=0.)
    facing = layout_quality(scene)
    reverse = copy.deepcopy(scene)
    next(item for item in reverse["items"] if item["id"] == "chair-1")["rotation"] = 180.
    away = layout_quality(reverse)
    assert facing["components"]["seatFacing"] < away["components"]["seatFacing"]
    assert facing["penalty"] < away["penalty"]


def test_bed_headboard_at_wall_scores_better_than_bed_foot_at_same_wall():
    scene = demo_scene()
    scene["items"] = [scene["items"][0]]
    scene["items"][0].update(x=2.6,z=1.04,rotation=0.)
    head = layout_quality(scene)
    scene["items"][0]["rotation"] = 180.
    foot = layout_quality(scene)
    assert head["components"]["backAlignment"] < foot["components"]["backAlignment"]
    assert head["penalty"] < foot["penalty"]


def test_nightstand_near_head_scores_better_than_midpoint_or_foot():
    scene = demo_scene()
    scene["items"] = [item for item in scene["items"] if item["id"] in {"bed-1","nightstand-1"}]
    bed, stand = scene["items"]
    bed.update(x=2.6,z=2.1,rotation=0.)
    stand.update(x=1.4,z=1.35,rotation=0.)
    head = layout_quality(scene)["components"]["bedsidePlacement"]
    stand["z"] = 2.1
    middle = layout_quality(scene)["components"]["bedsidePlacement"]
    stand["z"] = 2.9
    foot = layout_quality(scene)["components"]["bedsidePlacement"]
    assert head < middle < foot
