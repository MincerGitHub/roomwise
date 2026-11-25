import json
import struct

import numpy as np
import pytest
from copy import deepcopy

from roomwise.geometry import detailed_collision_area, _collision_part, _collision_parts_uncached, placement_errors, search_placement_errors
from roomwise.mesh_collision import _triangle_pairs_intersect, _point_inside_mesh, _triangles_from_glb, _box_triangles


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


def test_coplanar_triangles_with_overlapping_bounds_can_still_be_disjoint():
    first = np.asarray([[[0., 0., 0.], [2., 0., 0.], [0., 2., 0.]]])
    separate = np.asarray([[[2., 2., 0.], [2., .9, 0.], [.9, 2., 0.]]])
    assert not _triangle_pairs_intersect(first, separate)
    assert _triangle_pairs_intersect(first, separate - np.asarray([.6, .6, 0.]))
    crossing = np.asarray([[[.2, .2, -1.], [.2, .2, 1.], [1., 1., 0.]]])
    assert _triangle_pairs_intersect(first, crossing)
    assert _triangle_pairs_intersect(first * 1e-5, crossing * 1e-5)


def test_containment_counts_shared_face_crossing_once(tmp_path):
    path = tmp_path / 'cube.glb';cube_glb(path);triangles = _triangles_from_glb(path)
    assert _point_inside_mesh(np.asarray([.5, .5, .5]), triangles)
    assert not _point_inside_mesh(np.asarray([2., .5, .5]), triangles)


def test_rotated_component_offsets_and_vertices_follow_rendered_axes():
    table = {'category':'table','width':2.,'depth':1.,'height':.8,'rotation':90.,'x':5.,'z':5.}
    legs = [part for part in _collision_parts_uncached(table) if part['label']=='leg']
    centers = sorted((round(part['shape'].centroid.x, 3), round(part['shape'].centroid.y, 3)) for part in legs)
    assert centers == [(4.6,4.2),(4.6,5.8),(5.4,4.2),(5.4,5.8)]
    part = _collision_part({**table, 'rotation':45.}, 2., .2, 0, 0, 0, 1., 'bar')
    vertices = _box_triangles(part).reshape(-1,3)
    from shapely.geometry import Point
    assert all(part['shape'].buffer(1e-8).covers(Point(v[0],v[2])) for v in vertices)


def test_glb_search_is_conservative_but_final_validation_uses_real_empty_space(tmp_path, monkeypatch):
    from roomwise import geometry
    uploads = tmp_path/'uploads/assets';uploads.mkdir(parents=True)
    cube_glb(uploads/'cube.glb');unit = _triangles_from_glb(uploads/'cube.glb')
    # An arch with empty space beneath its top. Put a small box into the opening.
    triangles = np.concatenate([unit*[.2,1.2,1.]+[-1.,0.,-.5],
                                unit*[.2,1.2,1.]+[.8,0.,-.5],
                                unit*[2.,.2,1.]+[-1.,1.,-.5]])
    binary = triangles.astype('<f4').tobytes()
    document = {'asset':{'version':'2.0'},'scene':0,'scenes':[{'nodes':[0]}],'nodes':[{'mesh':0}],
                'meshes':[{'primitives':[{'attributes':{'POSITION':0}}]}],
                'buffers':[{'byteLength':len(binary)}],'bufferViews':[{'buffer':0,'byteOffset':0,'byteLength':len(binary)}],
                'accessors':[{'bufferView':0,'componentType':5126,'count':triangles.size//3,'type':'VEC3'}]}
    encoded = json.dumps(document).encode();encoded += b' '*(-len(encoded)%4)
    payload = struct.pack('<4sII',b'glTF',2,28+len(encoded)+len(binary))
    payload += struct.pack('<II',len(encoded),0x4E4F534A)+encoded+struct.pack('<II',len(binary),0x004E4942)+binary
    (uploads/'arch.glb').write_bytes(payload)
    monkeypatch.setenv('ROOMWISE_RUNTIME_DIR',str(tmp_path))
    arch = {**item('/uploads/assets/arch.glb'), 'id':'arch','category':'table','width':2.,'depth':1.,'height':1.2,'x':3.,'z':3.}
    small = {**item(None),'id':'small','width':.3,'depth':.3,'height':.3,'x':3.,'z':3.}
    room = {'width':6.,'depth':6.,'height':3.}
    assert detailed_collision_area(arch, small) == 0
    assert not placement_errors(small,room,[arch])
    monkeypatch.setattr(geometry,'detailed_collision_area',lambda *a:pytest.fail('Tentative GLB pose ran a mesh query'))
    assert search_placement_errors(small,room,[arch])


def test_generator_does_not_accept_an_overlapping_glb_candidate(tmp_path, monkeypatch):
    from roomwise import generator
    from roomwise.catalog import demo_scene
    uploads = tmp_path/'uploads/assets';uploads.mkdir(parents=True);cube_glb(uploads/'cube.glb')
    monkeypatch.setenv('ROOMWISE_RUNTIME_DIR',str(tmp_path))
    scene = demo_scene();scene['preferences']=[]
    first = {**item('/uploads/assets/cube.glb'),'id':'a','x':2.,'z':2.,'locked':False,'keep':True,'source':'brought'}
    second = {**first,'id':'b','x':2.3};scene['items']=[first,second]
    monkeypatch.setattr(generator,'learning_status',lambda:{'available':False})
    monkeypatch.setattr(generator,'functional_template',lambda *a:deepcopy(scene))
    monkeypatch.setattr(generator,'rule_candidate',lambda *a,**k:None)
    result=generator.generate_layouts(scene,mode='hybrid',count=1)
    assert result['candidates']==[] and result['diagnostics']['rejected']['geometry']>0


def test_glb_generation_preserves_snapshots_and_locked_pose(tmp_path, monkeypatch):
    from roomwise import generator
    from roomwise.catalog import demo_scene
    from roomwise.geometry import validate_scene, assert_invariants
    uploads=tmp_path/'uploads/assets';uploads.mkdir(parents=True);cube_glb(uploads/'cube.glb')
    monkeypatch.setenv('ROOMWISE_RUNTIME_DIR',str(tmp_path))
    monkeypatch.setattr(generator,'learning_status',lambda:{'available':False})
    scene=demo_scene();scene['preferences']=[]
    snapshot={'version':1,'label':'导入的椅子','category':'armchair','width':.5,'depth':.5,'height':.8,
              'photoUrls':[],'frontDirection':'positive_z','dimensionsConfirmed':True}
    fixed={**item('/uploads/assets/cube.glb'),'id':'fixed','label':snapshot['label'],'category':'armchair',
           'width':.5,'depth':.5,'height':.8,'x':1.5,'z':2.,'rotation':25.,'keep':True,'locked':True,
           'source':'brought','furnitureSnapshot':snapshot,'furnitureAssetId':'custom-chair'}
    scene['items']=[fixed,{**deepcopy(fixed),'id':'movable','locked':False}];before=deepcopy(scene)
    result=generator.generate_layouts(scene,mode='rules',count=3,seed=42)
    assert result['candidates'] and scene==before
    for candidate in result['candidates']:
        output=candidate['scene'];assert_invariants(scene,output);assert validate_scene(output)['valid']
        assert next(i for i in output['items'] if i['id']=='fixed')==fixed
        for value in output['items']:
            assert value['assetUrl']==fixed['assetUrl'] and value['furnitureSnapshot']==snapshot
