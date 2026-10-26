from copy import deepcopy
from math import atan2, degrees, hypot

from roomwise.generator import _diversity_features, generate_layouts
from roomwise.geometry import footprint, validate_scene


def furniture(identifier, category, x, z, width, depth, height, rotation=0):
    return {
        "id": identifier, "label": identifier, "category": category,
        "x": x, "z": z, "width": width, "depth": depth, "height": height,
        "rotation": rotation, "locked": False, "keep": True, "source": "brought",
    }


def scene():
    return {
        "id": "layout-diversity", "name": "方案差异测试", "version": 0,
        "room": {"width": 7, "depth": 6, "height": 2.7, "door": None, "windows": []},
        "items": [
            furniture("desk", "desk", 2.7, 2.8, 1.2, .6, .75),
            furniture("chair", "chair", 2.7, 1.75, .5, .5, .85, 180),
        ],
        "preferences": [],
    }


def near_duplicate(source, shift):
    result = deepcopy(source)
    for item in result["items"]:
        item["x"] += shift
        item["z"] += shift
    return result


def relationship_signature(layout):
    items = {item["id"]: item for item in layout["items"]}
    room = layout["room"]
    pairs = []
    ordered = sorted(items)
    for index, left_id in enumerate(ordered):
        left = items[left_id]
        for right_id in ordered[index + 1:]:
            right = items[right_id]
            dx, dz = right["x"] - left["x"], right["z"] - left["z"]
            # A 45-degree compass sector describes the furniture-to-furniture
            # position relationship independently of small absolute shifts.
            angle = (degrees(atan2(dz, dx)) + 360) % 360
            sector = round(angle / 45) % 8
            relative_yaw = round(((right["rotation"] - left["rotation"]) % 360) / 45) % 8
            gap = footprint(left).distance(footprint(right))
            gap_class = next((limit for limit in (.10, .35, .75, 1.25) if gap <= limit), "far")
            intersects = footprint(left).intersection(footprint(right)).area > 1e-4
            pairs.append((left_id, right_id, sector, relative_yaw, gap_class, intersects))

    walls = []
    for identifier, item in sorted(items.items()):
        fp = footprint(item)
        distances = {"west": fp.bounds[0], "east": room["width"] - fp.bounds[2],
                     "south": fp.bounds[1], "north": room["depth"] - fp.bounds[3]}
        minimum = min(distances.values())
        nearest = tuple(sorted(wall for wall, distance in distances.items() if distance - minimum <= .10))
        wall_band = next((limit for limit in (.10, .25, .50) if minimum <= limit), "interior")
        x, z = item["x"], item["z"]
        corner_distances = {"south-west": hypot(x, z), "south-east": hypot(room["width"]-x, z),
                            "north-west": hypot(x, room["depth"]-z),
                            "north-east": hypot(room["width"]-x, room["depth"]-z)}
        corner = min(corner_distances, key=corner_distances.get) if min(corner_distances.values()) <= .35 else None
        facing = round((item.get("rotation", 0) % 360) / 45) % 8
        walls.append((identifier, nearest, wall_band, corner, facing))
    return tuple(pairs), tuple(walls)


def test_relationship_signature_tracks_orientation_wall_and_corner_anchors():
    base = scene()
    turned = deepcopy(base)
    turned["items"][1]["rotation"] = 90
    assert relationship_signature(base) != relationship_signature(turned)

    centered = {**scene(), "items": [furniture("desk", "desk", 3.5, 3., 1.2, .6, .75)]}
    beside_wall = deepcopy(centered)
    beside_wall["items"][0].update(x=.75, z=2.7)
    at_corner = {**scene(), "items": [furniture("chair", "chair", .3, .3, .48, .5, .85)]}
    assert relationship_signature(centered) != relationship_signature(beside_wall)
    assert relationship_signature(centered) != relationship_signature(at_corner)


def test_generated_previews_skip_same_relationship_jitter_and_show_a_different_arrangement(monkeypatch):
    original = scene()
    before = deepcopy(original)
    first = deepcopy(original)
    near_first = near_duplicate(first, .05)
    another_near_duplicate = near_duplicate(first, .12)
    different = deepcopy(first)
    # This remains collision-free, but the chair is now west of the desk rather
    # than south of it; a reviewer sees a genuinely different furniture layout.
    different["items"][1].update(x=1.55, z=2.8, rotation=90)
    assert relationship_signature(first) == relationship_signature(near_first)
    assert relationship_signature(first) != relationship_signature(different)
    assert _diversity_features(first) == _diversity_features(near_first)
    assert _diversity_features(first) != _diversity_features(different)
    near_variants = [near_duplicate(first, shift) for shift in (.02, .04, .06, .08, .10, .12)]
    proposals = iter((first, *near_variants, different))
    def propose(*_args, **_kwargs):
        try:
            value = next(proposals)
        except StopIteration:
            return None
        return deepcopy(value)

    monkeypatch.setattr("roomwise.generator.functional_template", propose)
    result = generate_layouts(original, mode="rules", count=2, seed=17)

    assert len(result["candidates"]) == 2, result["diagnostics"]
    layouts = [candidate["scene"] for candidate in result["candidates"]]
    assert all(validate_scene(layout)["valid"] for layout in layouts)
    assert len({relationship_signature(layout) for layout in layouts}) == len(layouts), [
        relationship_signature(layout) for layout in layouts
    ]
    assert result["diagnostics"]["diversity"]["distinctCount"] == len(layouts)
    assert all(candidate["diversity"]["signature"] for candidate in result["candidates"])
    assert all(candidate["diversity"]["reasons"] for candidate in result["candidates"][1:])
    assert original == before


def test_supported_box_can_make_two_floor_similar_layouts_structurally_distinct(monkeypatch):
    table = furniture("table", "table", 2.5, 2.5, 1.2, .8, .75)
    box = furniture("box", "storage_box", 2.5, 2.5, .4, .3, .3)
    box.update(y=.75, supportId="table")
    chair = furniture("chair", "chair", 2.5, 3.25, .5, .5, .85)
    original = {"id": "supported-diversity", "name": "supported", "version": 0,
                "room": {"width": 6, "depth": 5, "height": 2.7, "door": None, "windows": []},
                "items": [table, box, chair], "preferences": []}
    floor_signatures = []
    def propose(floor_scene, *_args, **_kwargs):
        result = deepcopy(floor_scene)
        if not floor_signatures:
            result["items"][-1].update(x=3.15, z=3.25)
            floor_signatures.append(_diversity_features(result))
            return result
        if len(floor_signatures) == 1:
            result["items"][-1].update(x=2.5, z=3.25)
            floor_signatures.append(_diversity_features(result))
            return result
        return None

    monkeypatch.setattr("roomwise.generator.functional_template", propose)
    monkeypatch.setattr("roomwise.generator.rule_candidate", lambda *_args, **_kwargs: None)
    result = generate_layouts(original, mode="rules", count=2, seed=4)

    assert floor_signatures[0] == floor_signatures[1]
    assert len(result["candidates"]) == 2, result["diagnostics"]
    assert all(validate_scene(candidate["scene"])["valid"] for candidate in result["candidates"])
    assert len({candidate["diversity"]["signature"] for candidate in result["candidates"]}) == 2
    assert result["candidates"][1]["diversity"]["reasons"]


def test_generator_does_not_fill_requested_count_with_only_coordinate_jitter(monkeypatch):
    original = scene()
    original["items"] = [furniture("desk", "desk", 3.5, 3., 1.2, .6, .75)]
    calls = 0
    def jitter_only(source, *_args, **_kwargs):
        nonlocal calls
        calls += 1
        result = deepcopy(source)
        result["items"][0]["x"] += calls * .02
        return result

    monkeypatch.setattr("roomwise.generator.functional_template", jitter_only)
    monkeypatch.setattr("roomwise.generator.rule_candidate", jitter_only)
    result = generate_layouts(original, mode="rules", count=2, seed=9)

    assert len(result["candidates"]) == 1
    assert result["diagnostics"]["diversity"]["achieved"] is False
    assert "没有用相似方案补足数量" in result["diagnostics"]["message"]
