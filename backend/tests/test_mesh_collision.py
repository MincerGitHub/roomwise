import json
import struct

import numpy as np

from roomwise.geometry import detailed_collision_area


def cube_glb(path):
    positions = np.asarray([
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
    ], dtype="<f4").tobytes()
    indices = np.asarray([
        0, 1, 2, 0, 2, 3, 4, 6, 5, 4, 7, 6,
        0, 4, 5, 0, 5, 1, 1, 5, 6, 1, 6, 2,
        2, 6, 7, 2, 7, 3, 3, 7, 4, 3, 4, 0,
    ], dtype="<u2").tobytes()
    binary = positions + indices
    document = {
        "asset": {"version": "2.0"}, "scene": 0,
        "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1}]}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
            {"buffer": 0, "byteOffset": len(positions), "byteLength": len(indices)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5123, "count": 36, "type": "SCALAR"},
        ],
    }
    encoded = json.dumps(document, separators=(",", ":")).encode()
    encoded += b" " * ((4 - len(encoded) % 4) % 4)
    binary += b"\0" * ((4 - len(binary) % 4) % 4)
    payload = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(encoded) + 8 + len(binary))
    payload += struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
    payload += struct.pack("<II", len(binary), 0x004E4942) + binary
    path.write_bytes(payload)


def item(asset_url, x=0):
    return {"id": str(x), "label": "cube", "category": "storage_box", "width": 1, "depth": 1, "height": 1,
            "x": x, "z": 0, "y": 0, "rotation": 0, "assetUrl": asset_url}


def test_triangle_level_collision_reads_glb(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"; (uploads / "assets").mkdir(parents=True)
    cube_glb(uploads / "assets" / "cube.glb")
    monkeypatch.setenv("ROOMWISE_RUNTIME_DIR", str(tmp_path))
    first, second = item("/uploads/assets/cube.glb"), item("/uploads/assets/cube.glb", x=.5)
    assert detailed_collision_area(first, second) > 0
    second["x"] = 2
    assert detailed_collision_area(first, second) == 0
    second["x"] = 0
    second["width"] = second["depth"] = second["height"] = 2
    assert detailed_collision_area(first, second) > 0
