from copy import deepcopy

import pytest

from roomwise.geometry import validate_scene, assert_invariants
from roomwise.generator import generate_layouts
from roomwise.schemas import Scene
from roomwise.supports import support_errors


def item(identifier, category, **values):
    return {"id":identifier,"label":identifier,"category":category,"width":.9,"depth":.24,"height":.3,
            "x":2.,"z":4.86,"y":2.1,"rotation":180.,"locked":True,"keep":True,"source":"existing",**values}


def room(*items):
    return {"id":"devices","name":"设备","version":0,"room":{"width":6,"depth":5,"height":2.7,"door":None,"windows":[]},
            "items":list(items),"preferences":[]}


@pytest.mark.parametrize('category',['wall_tv','air_conditioner'])
def test_wall_devices_require_real_wall_contact_and_height(category):
    scene=room(item('device',category))
    assert validate_scene(scene)['valid']
    for patch in ({'y':0},{'z':2.},{'rotation':0},{'y':2.6}):
        changed=deepcopy(scene);changed['items'][0].update(patch)
        assert any(error['type']=='wall_mount' for error in support_errors(changed))


def test_laptop_can_follow_a_table_with_a_valid_surface_relation():
    table=item('table','table',width=1.2,depth=.8,height=.75,x=3,z=2.5,y=0,rotation=0,locked=False)
    laptop=item('laptop','laptop',width=.34,depth=.28,height=.25,x=3,z=2.5,y=.75,rotation=0,locked=False,supportId='table')
    device=item('ac','air_conditioner')
    scene=Scene.model_validate(room(table,laptop,device)).model_dump()
    assert validate_scene(scene)['valid']
    result=generate_layouts(scene,'rules',1,42)
    assert result['candidates'],result['diagnostics']
    for candidate in result['candidates']:
        proposed=candidate['scene']
        assert validate_scene(proposed)['valid']
        assert_invariants(scene,proposed)
        assert proposed['items'][2]==scene['items'][2]
        assert proposed['items'][1]['y']==.75 and proposed['items'][1]['supportId']=='table'


@pytest.mark.parametrize('category',['wall_tv','air_conditioner'])
def test_unlocked_wall_device_can_generate_without_changing_lock_or_height(category):
    original=room(item('device',category,locked=False,keep=False))
    result=generate_layouts(original,'rules',1,42)
    assert result['candidates'],result['diagnostics']
    for candidate in result['candidates']:
        assert validate_scene(candidate['scene'])['valid']
        assert_invariants(original,candidate['scene'])
        assert not candidate['scene']['items'][0]['locked'] and not candidate['scene']['items'][0]['keep']
        assert candidate['scene']['items'][0]['y']==2.1


def test_laptop_cannot_float_without_a_support_or_extend_beyond_table():
    table=item('table','table',width=1.2,depth=.8,height=.75,x=3,z=2.5,y=0)
    laptop=item('laptop','laptop',width=.34,depth=.28,height=.25,x=3,z=2.5,y=.75,supportId='table')
    scene=room(table,laptop)
    assert not support_errors(scene)
    laptop['x']=3.6
    assert support_errors(scene)
    laptop.pop('supportId')
    assert support_errors(scene)


def test_unlocked_wall_device_search_can_repair_initial_window_overlap():
    original=room(item('tv','wall_tv',locked=False,y=1.2))
    original['room']['windows']=[{'id':'w','wall':'north','offset':1.2,'width':2.,'sillHeight':1.,'height':1.3}]
    assert not validate_scene(original)['valid']
    result=generate_layouts(original,'rules',1,42)
    assert result['candidates'],result['diagnostics']
    for candidate in result['candidates']:
        assert validate_scene(candidate['scene'])['valid']
        assert candidate['scene']['items'][0]['y']==1.2
        assert not candidate['scene']['items'][0]['locked']


def test_appliance_candidate_domain_never_proposes_floor_positions_or_invalid_gaps():
    from roomwise.wall_placements import appliance_placements
    from roomwise.supports import wall_mount_errors
    from roomwise.wall_appliance_constraints import window_conflicts
    original=room(item('ac','air_conditioner',locked=False))
    original['room']['windows']=[{'id':'w','wall':'north','offset':1,'width':3,'sillHeight':1.9,'height':.7}]
    device=original['items'][0];poses=list(appliance_placements(device,original['room']))
    assert poses
    assert {round(pose['rotation']) for pose in poses}=={0,90,180,270}
    assert all(not wall_mount_errors(pose,original['room']) and not window_conflicts(pose,original['room']) and pose['y']==device['y'] for pose in poses)


def test_default_keep_is_false_but_explicit_protection_is_preserved():
    default=item('table','table',y=0,z=2.5)
    default.pop('keep')
    assert Scene.model_validate(room(default)).items[0].keep is False
    default['keep']=True
    assert Scene.model_validate(room(default)).items[0].keep is True
