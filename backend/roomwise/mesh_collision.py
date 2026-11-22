"""Triangle-level collision helpers for local GLB furniture assets."""
from __future__ import annotations

import json
import math
import struct
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np

EPSILON = 1e-7


def _read_accessor(document, binary, accessor_index):
    accessor = document["accessors"][accessor_index]
    view = document["bufferViews"][accessor["bufferView"]]
    component = {5121: ("B", 1), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}[accessor["componentType"]]
    count = int(accessor["count"])
    arity = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[accessor["type"]]
    stride = int(view.get("byteStride") or component[1] * arity)
    offset = int(view.get("byteOffset", 0)) + int(accessor.get("byteOffset", 0))
    result = np.empty((count, arity), dtype=np.float32 if component[0] == "f" else np.uint32)
    for index in range(count):
        start = offset + index * stride
        values = struct.unpack_from("<" + component[0] * arity, binary, start)
        result[index] = values
    return result[:, 0] if arity == 1 else result


def _matrix(node):
    if "matrix" in node:
        return np.asarray(node["matrix"], dtype=np.float64).reshape(4, 4, order="F")
    t = np.asarray(node.get("translation", [0, 0, 0]), dtype=np.float64)
    s = np.asarray(node.get("scale", [1, 1, 1]), dtype=np.float64)
    q = np.asarray(node.get("rotation", [0, 0, 0, 1]), dtype=np.float64)
    x, y, z, w = q
    rotation = np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])
    result = np.eye(4)
    result[:3, :3] = rotation * s[np.newaxis, :]
    result[:3, 3] = t
    return result


@lru_cache(maxsize=16)
def _triangles_from_glb_cached(path_string: str, modified_ns: int, size: int) -> np.ndarray:
    return _triangles_from_glb(Path(path_string))


def _triangles_from_glb(path: Path) -> np.ndarray:
    raw = path.read_bytes()
    if len(raw) < 20 or raw[:4] != b"glTF":
        raise ValueError("invalid GLB")
    json_size, json_type = struct.unpack_from("<II", raw, 12)
    if json_type != 0x4E4F534A:
        raise ValueError("GLB JSON chunk missing")
    document = json.loads(raw[20:20 + json_size])
    binary_start = 20 + json_size
    binary_size, binary_type = struct.unpack_from("<II", raw, binary_start)
    if binary_type != 0x004E4942:
        raise ValueError("GLB binary chunk missing")
    binary = raw[binary_start + 8:binary_start + 8 + binary_size]
    nodes = document.get("nodes", [])
    meshes = document.get("meshes", [])
    roots = document.get("scenes", [{}])[document.get("scene", 0)].get("nodes", []) if document.get("scenes") else list(range(len(nodes)))
    triangles = []

    def visit(node_index, parent):
        node = nodes[node_index]
        world = parent @ _matrix(node)
        mesh_index = node.get("mesh")
        if mesh_index is not None:
            for primitive in meshes[mesh_index].get("primitives", []):
                if primitive.get("mode", 4) != 4 or "POSITION" not in primitive.get("attributes", {}):
                    continue
                positions = _read_accessor(document, binary, primitive["attributes"]["POSITION"]).astype(np.float64)
                if "indices" in primitive:
                    indices = _read_accessor(document, binary, primitive["indices"]).astype(np.int64).reshape(-1)
                else:
                    indices = np.arange(len(positions), dtype=np.int64)
                indices = indices[:len(indices) - len(indices) % 3].reshape(-1, 3)
                homogeneous = np.concatenate([positions, np.ones((len(positions), 1))], axis=1)
                transformed = (world @ homogeneous.T).T[:, :3]
                if len(indices):
                    triangles.append(transformed[indices])
        for child in node.get("children", []):
            visit(child, world)

    for root in roots:
        visit(root, np.eye(4))
    if not triangles:
        raise ValueError("GLB contains no triangle primitives")
    return np.concatenate(triangles, axis=0)


def _box_triangles(part):
    outline = np.asarray(part["shape"].exterior.coords, dtype=np.float64)[:4]
    low, high = part["low"], part["high"]
    vertices = np.empty((8, 3), dtype=np.float64)
    vertices[:4, 0], vertices[:4, 2] = outline[:, 0], outline[:, 1]
    vertices[4:, 0], vertices[4:, 2] = outline[:, 0], outline[:, 1]
    vertices[:4, 1], vertices[4:, 1] = low, high
    faces = np.asarray([[0, 1, 2], [0, 2, 3], [4, 6, 5], [4, 7, 6],
                        [0, 4, 5], [0, 5, 1], [1, 5, 6], [1, 6, 2],
                        [2, 6, 7], [2, 7, 3], [3, 7, 4], [3, 4, 0]])
    return vertices[faces]


def _asset_path(asset_url: str | None, uploads_root: Path) -> Path | None:
    if not asset_url or not asset_url.startswith("/uploads/"):
        return None
    relative = urlsplit(asset_url).path.removeprefix("/uploads/")
    path = (uploads_root / relative).resolve()
    root = uploads_root.resolve()
    return path if path == root or root in path.parents else None


@lru_cache(maxsize=32)
def _transformed_mesh_cached(path_string: str, modified_ns: int, size: int,
                            width: float, depth: float, height: float,
                            x: float, z: float, rotation: float, y: float) -> np.ndarray:
    item = {"width": width, "depth": depth, "height": height,
            "x": x, "z": z, "rotation": rotation, "y": y}
    return _transform_mesh(_triangles_from_glb_cached(path_string, modified_ns, size), item)


def _transform_mesh(triangles, item):
    vertices = triangles.reshape(-1, 3)
    minimum, maximum = vertices.min(axis=0), vertices.max(axis=0)
    size = maximum - minimum
    if np.any(size < EPSILON):
        raise ValueError("degenerate GLB mesh")
    vertices = vertices - (minimum + maximum) / 2
    vertices[:, 1] -= (minimum[1] - (minimum[1] + maximum[1]) / 2)
    scale = np.asarray([item["width"] / size[0], item["height"] / size[1], item["depth"] / size[2]])
    vertices *= scale
    radians = math.radians(float(item.get("rotation", 0)))
    cosine, sine = math.cos(radians), math.sin(radians)
    x, z = vertices[:, 0].copy(), vertices[:, 2].copy()
    vertices[:, 0] = cosine * x + sine * z + float(item.get("x", 0))
    vertices[:, 2] = -sine * x + cosine * z + float(item.get("z", 0))
    vertices[:, 1] += float(item.get("y", 0))
    return vertices.reshape(-1, 3, 3)


def _sat_intersects(left, right):
    edges_left = np.roll(left, -1, axis=0) - left
    edges_right = np.roll(right, -1, axis=0) - right
    axes = [np.cross(edges_left[0], edges_left[1]), np.cross(edges_right[0], edges_right[1])]
    axes.extend(np.cross(a, b) for a in edges_left for b in edges_right)
    for axis in axes:
        length = np.linalg.norm(axis)
        if length < EPSILON:
            continue
        axis /= length
        first = left @ axis
        second = right @ axis
        if first.max() < second.min() - EPSILON or second.max() < first.min() - EPSILON:
            return False
    return True


def _triangle_pairs_intersect(left, right):
    """Vectorized SAT for corresponding triangle pairs, including coplanar ones."""
    if not len(left):
        return False
    edges_left = np.roll(left, -1, axis=1) - left
    edges_right = np.roll(right, -1, axis=1) - right
    normal_left = np.cross(edges_left[:, 0], edges_left[:, 1])
    normal_right = np.cross(edges_right[:, 0], edges_right[:, 1])
    axes = np.concatenate([
        normal_left[:, None], normal_right[:, None],
        np.cross(edges_left[:, :, None], edges_right[:, None, :]).reshape(-1, 9, 3),
        np.cross(normal_left[:, None], edges_left),
        np.cross(normal_right[:, None], edges_right),
    ], axis=1)
    lengths = np.linalg.norm(axes, axis=2)
    # Axis magnitude depends on triangle area; use a numerical zero here,
    # then apply the metre tolerance only after normalization.
    valid = lengths > 1e-15
    axes = axes / np.where(valid, lengths, 1.)[:, :, None]
    first = np.einsum('nvc,nac->nav', left, axes)
    second = np.einsum('nvc,nac->nav', right, axes)
    separate = ((first.max(axis=2) < second.min(axis=2) - EPSILON)
                | (second.max(axis=2) < first.min(axis=2) - EPSILON)) & valid
    nondegenerate = ((np.linalg.norm(normal_left, axis=1) > 1e-15)
                     & (np.linalg.norm(normal_right, axis=1) > 1e-15))
    return bool(np.any(~separate.any(axis=1) & nondegenerate))


def _ray_intersects_triangle(origin, direction, triangle):
    edge_a, edge_b = triangle[1] - triangle[0], triangle[2] - triangle[0]
    cross = np.cross(direction, edge_b)
    determinant = float(edge_a @ cross)
    if abs(determinant) < EPSILON:
        return False
    inverse = 1.0 / determinant
    offset = origin - triangle[0]
    u = float((offset @ cross) * inverse)
    if u < -EPSILON or u > 1 + EPSILON:
        return False
    cross_offset = np.cross(offset, edge_a)
    v = float((direction @ cross_offset) * inverse)
    if v < -EPSILON or u + v > 1 + EPSILON:
        return False
    return float((edge_b @ cross_offset) * inverse) > EPSILON


def _point_inside_mesh(point, triangles):
    direction = np.asarray([1.0, .371, .173], dtype=np.float64)
    direction /= np.linalg.norm(direction)
    edge_a, edge_b = triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    cross = np.cross(direction, edge_b)
    determinant = np.einsum('ij,ij->i', edge_a, cross)
    valid = np.abs(determinant) >= EPSILON
    inverse = np.divide(1., determinant, out=np.zeros_like(determinant), where=valid)
    offset = point - triangles[:, 0]
    u = np.einsum('ij,ij->i', offset, cross) * inverse
    cross_offset = np.cross(offset, edge_a)
    v = (cross_offset @ direction) * inverse
    distance = np.einsum('ij,ij->i', edge_b, cross_offset) * inverse
    hits = np.sort(distance[valid & (u >= -EPSILON) & (v >= -EPSILON)
                            & (u + v <= 1 + EPSILON) & (distance > EPSILON)])
    # A ray through a shared edge hits two triangles on the same surface.
    crossings = int(bool(len(hits))) + int(np.count_nonzero(np.diff(hits) > EPSILON))
    return crossings % 2 == 1


_BVH_CACHE = {}
_BVH_LEAF = 16
_BVH_CACHE_LIMIT = 16


def _build_bvh(mesh):
    minimum, maximum = mesh.min(axis=1), mesh.max(axis=1)
    centroids = (minimum + maximum) * .5
    nodes = []

    def build(indices):
        node_index = len(nodes)
        low, high = minimum[indices].min(axis=0), maximum[indices].max(axis=0)
        nodes.append((low, high, None, None, None))
        if len(indices) <= _BVH_LEAF:
            nodes[node_index] = (low, high, indices, None, None)
            return node_index
        axis = int(np.argmax(high - low))
        ordered = indices[np.argsort(centroids[indices, axis], kind="stable")]
        middle = len(ordered) // 2
        left = build(ordered[:middle])
        right = build(ordered[middle:])
        nodes[node_index] = (low, high, None, left, right)
        return node_index

    root = build(np.arange(len(mesh), dtype=np.int32))
    return nodes, root


def _mesh_bvh(mesh):
    key = id(mesh)
    cached = _BVH_CACHE.get(key)
    if cached is not None and cached[0] is mesh:
        return cached[1]
    result = _build_bvh(mesh)
    _BVH_CACHE[key] = (mesh, result)
    if len(_BVH_CACHE) > _BVH_CACHE_LIMIT:
        _BVH_CACHE.pop(next(iter(_BVH_CACHE)))
    return result


def _aabb_overlap(left, right):
    return not (np.any(left[1] < right[0] - EPSILON) or np.any(right[1] < left[0] - EPSILON))


def _mesh_intersects(left, right):
    left_min, left_max = left.min(axis=1), left.max(axis=1)
    right_min, right_max = right.min(axis=1), right.max(axis=1)
    if not _aabb_overlap((left_min.min(axis=0), left_max.max(axis=0)),
                         (right_min.min(axis=0), right_max.max(axis=0))):
        return False
    left_nodes, left_root = _mesh_bvh(left)
    right_nodes, right_root = _mesh_bvh(right)
    stack = [(left_root, right_root)]
    while stack:
        left_index, right_index = stack.pop()
        left_node, right_node = left_nodes[left_index], right_nodes[right_index]
        if not _aabb_overlap((left_node[0], left_node[1]), (right_node[0], right_node[1])):
            continue
        left_triangles, right_triangles = left_node[2], right_node[2]
        if left_triangles is not None and right_triangles is not None:
            overlap = (np.all(left_max[left_triangles, None] >= right_min[right_triangles] - EPSILON, axis=2)
                       & np.all(right_max[right_triangles] >= left_min[left_triangles, None] - EPSILON, axis=2))
            first, second = np.nonzero(overlap)
            if _triangle_pairs_intersect(left[left_triangles[first]], right[right_triangles[second]]):
                return True
            continue
        if left_triangles is not None:
            stack.extend((left_index, child) for child in right_node[3:5] if child is not None)
        elif right_triangles is not None:
            stack.extend((child, right_index) for child in left_node[3:5] if child is not None)
        else:
            stack.extend((left_child, right_child) for left_child in left_node[3:5] if left_child is not None for right_child in right_node[3:5] if right_child is not None)
    if len(left) and len(right):
        left_inside = np.all(left_min[0] > right_min.min(axis=0) + EPSILON) and np.all(left_max[0] < right_max.max(axis=0) - EPSILON)
        right_inside = np.all(right_min[0] > left_min.min(axis=0) + EPSILON) and np.all(right_max[0] < left_max.max(axis=0) - EPSILON)
        if (left_inside and _point_inside_mesh(left[0, 0], right)) or (right_inside and _point_inside_mesh(right[0, 0], left)):
            return True
    return False


def _has_asset(item, uploads_root):
    path = _asset_path(item.get("assetUrl"), uploads_root)
    return path if path and path.is_file() else None


def _component_collision(first, second, fallback_parts):
    for left in fallback_parts(first):
        for right in fallback_parts(second):
            if left["high"] <= right["low"] + EPSILON or right["high"] <= left["low"] + EPSILON:
                continue
            if left["shape"].intersection(right["shape"]).area > EPSILON:
                return True
    return False


def triangle_collision(first, second, uploads_root: Path, fallback_parts):
    """Use asset triangles when available, with procedural boxes only as legacy input."""
    first_path, second_path = _has_asset(first, uploads_root), _has_asset(second, uploads_root)
    if first_path is None and second_path is None:
        return _component_collision(first, second, fallback_parts)

    def load(item, path):
        if path is not None:
            try:
                stat = path.stat()
                return _transformed_mesh_cached(
                    str(path), stat.st_mtime_ns, stat.st_size,
                    float(item["width"]), float(item["depth"]), float(item["height"]),
                    float(item.get("x", 0)), float(item.get("z", 0)),
                    float(item.get("rotation", 0)), float(item.get("y", 0)),
                )
            except (OSError, ValueError, KeyError, IndexError, struct.error, json.JSONDecodeError):
                pass
        return np.concatenate([_box_triangles(part) for part in fallback_parts(item)])

    if first.get("y", 0) + first["height"] <= second.get("y", 0) + EPSILON or second.get("y", 0) + second["height"] <= first.get("y", 0) + EPSILON:
        return False
    return _mesh_intersects(load(first, first_path), load(second, second_path))
