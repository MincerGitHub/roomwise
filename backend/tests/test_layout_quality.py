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


def test_quality_penalizes_vanity_chair_away_from_front_of_vanity():
    scene = demo_scene()
    scene["items"] = [
        {"id": "vanity", "label": "vanity", "category": "dressing_table",
         "width": 1.0, "depth": .45, "height": .75, "x": 2.5, "z": 3.7,
         "rotation": 180., "locked": False, "keep": True, "source": "brought"},
        {"id": "vanity-chair", "label": "vanity chair", "category": "dressing_chair",
         "width": .4, "depth": .4, "height": .75, "x": 2.5, "z": 3.15,
         "rotation": 0., "locked": False, "keep": True, "source": "brought"},
    ]
    paired = layout_quality(scene)
    scene["items"][1].update(x=4.2, z=1.1, rotation=90.)
    detached = layout_quality(scene)
    assert detached["components"]["functionalGrouping"] > paired["components"]["functionalGrouping"]
    assert detached["components"]["seatFacing"] > paired["components"]["seatFacing"]



def test_vanity_seating_postcondition_rejects_sideways_or_rear_chair():
    from roomwise.geometry import evaluate_vanity_seating

    scene = demo_scene()
    scene["items"] = [
        {"id": "vanity", "label": "???", "category": "dressing_table",
         "width": 1.0, "depth": .45, "height": .75, "x": 2.5, "z": 3.7,
         "rotation": 180., "locked": False, "keep": True, "source": "brought"},
        {"id": "vanity-chair", "label": "???", "category": "dressing_chair",
         "width": .4, "depth": .4, "height": .75, "x": 3.2, "z": 3.3,
         "rotation": 90., "locked": False, "keep": True, "source": "brought"},
    ]
    sideways = evaluate_vanity_seating(scene)
    assert not sideways["satisfied"]
    assert sideways["unsatisfied"][0]["chairId"] == "vanity-chair"

    scene["items"][1].update(x=2.5, z=3.1, rotation=0.)
    front = evaluate_vanity_seating(scene)
    assert front["satisfied"], front



def test_model_candidate_with_sideways_vanity_chair_is_not_accepted(monkeypatch):
    from types import SimpleNamespace
    import roomwise.generator as generator

    scene = demo_scene()
    scene["items"] = [
        {"id": "vanity", "label": "???", "category": "dressing_table",
         "width": 1.0, "depth": .45, "height": .75, "x": 3.5, "z": 3.45,
         "rotation": 0., "locked": False, "keep": True, "source": "brought"},
        {"id": "vanity-chair", "label": "???", "category": "dressing_chair",
         "width": .4, "depth": .4, "height": .75, "x": 4.2, "z": 3.45,
         "rotation": 90., "locked": False, "keep": True, "source": "brought"},
    ]
    fake_learning = SimpleNamespace(refine_scene=lambda candidate, iterations=3: candidate)
    monkeypatch.setattr(generator, "learning_status", lambda: {"available": True})
    monkeypatch.setattr(generator.importlib, "import_module", lambda name: fake_learning)
    result = generator.generate_layouts(scene, mode="model", count=1, seed=42)
    assert result["candidates"] == []
    assert result["diagnostics"]["rejected"]["functionalRelations"] > 0
    assert result["diagnostics"]["lastUnsatisfiedVanitySeating"]
