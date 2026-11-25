from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from roomwise.geometry import validate_scene, search_placement_errors
from roomwise.schemas import Scene
from roomwise.wall_appliance_constraints import evaluate_wall_appliances, window_conflicts


def item(identifier,category,**values):
    return {"id":identifier,"label":identifier,"category":category,"width":1.,"depth":.4,"height":1.,
            "x":3.,"z":2.5,"rotation":0.,"locked":False,"keep":True,"source":"brought",**values}


def scene(*items,windows=None):
    return {"id":"appliance-check","name":"壁挂检查","version":0,"room":{"width":6.,"depth":5.,"height":3.,"door":None,"windows":windows or []},
            "items":list(items),"preferences":[]}


def tv(**values):return item('tv','wall_tv',depth=.08,height=.7,x=3,z=4.94,y=1.05,rotation=180,locked=True,**values)
def sofa():return item('sofa','sofa',width=1.8,depth=.8,height=.85,x=3,z=1,rotation=0)
def ac(**values):
    base=dict(width=.9,depth=.2,height=.3,x=3,z=4.88,y=2.2,rotation=180,locked=True);base.update(values)
    return item('ac','air_conditioner',**base)


def test_tall_blocker_on_viewing_path_fails_even_with_no_physical_collision():
    value=scene(tv(),sofa(),item('shelf','bookshelf',x=3,z=3,width=1.2,depth=.3,height=2.))
    result=validate_scene(value)
    assert result['metrics']['collisions']==0
    assert not result['valid']
    check=next(check for check in result['wallAppliances']['checks'] if check['kind']=='tv_visibility')
    assert not check['satisfied'] and check['blockers']==['shelf'] and check['metrics']['blockedRays']>0


def test_low_coffee_table_and_off_axis_tall_furniture_leave_screen_visible():
    value=scene(tv(),sofa(),item('coffee','coffee_table',height=.4,depth=.5),item('shelf','bookshelf',x=5,z=3,height=2.))
    assert validate_scene(value)['valid']
    assert next(c for c in evaluate_wall_appliances(value)['checks'] if c['kind']=='tv_visibility')['satisfied']


@pytest.mark.parametrize('rotation',[0,90,180,270])
def test_visibility_is_invariant_under_rotation_of_whole_scene(rotation):
    import math
    value=scene(tv(),sofa(),item('cabinet','cabinet',width=1.2,depth=.2,height=1.8,doorCount=0))
    for obj in value['items']:
        x,z=obj['x']-3,obj['z']-2.5;r=math.radians(rotation)
        obj.update(x=3+x*math.cos(r)+z*math.sin(r),z=2.5-x*math.sin(r)+z*math.cos(r),rotation=obj['rotation']+rotation)
    result=evaluate_wall_appliances(value)
    check=next(c for c in result['checks'] if c['kind']=='tv_visibility')
    assert not check['satisfied'] and check['blockers']==['cabinet']


def test_explicit_viewer_for_multiple_tvs_and_no_viewer_warning():
    value=scene(tv(),item('chair','chair',x=3,z=1,height=.9),item('shelf','bookshelf',height=2.))
    value['preferences']=[{'kind':'face_item','itemId':'chair','targetId':'tv','required':True}]
    assert not evaluate_wall_appliances(value)['satisfied']
    value['preferences']=[]
    result=evaluate_wall_appliances(value)
    assert result['satisfied'] and result['warnings'][0]['kind']=='tv_viewpoint'


def test_ac_low_furniture_passes_but_nearby_tall_furniture_blocks_airflow_and_service():
    low=item('low','nightstand',x=3,z=4.2,height=.6,width=.8,depth=.3)
    value=scene(ac(),low)
    assert validate_scene(value)['valid']
    low.update(category='bookshelf',height=2.05)
    check=validate_scene(value)
    assert check['metrics']['collisions']==0 and not check['valid']
    assert any(issue['type']=='ac_airflow' and 'low' in issue['itemIds'] for issue in check['issues'])


def test_ac_top_return_and_ceiling_clearance():
    above=item('overhead','storage_box',width=.5,depth=.2,height=.1,x=3,z=4.88,y=2.53)
    assert any(not c['satisfied'] and c['kind']=='ac_return' for c in evaluate_wall_appliances(scene(ac(),above))['checks'])
    value=scene(ac(y=2.7))
    assert any(issue['type']=='ac_return' for issue in validate_scene(value)['issues'])


@pytest.mark.parametrize('wall,pose',[
    ('north',{'x':3,'z':4.88,'rotation':180}),('south',{'x':3,'z':.12,'rotation':0}),
    ('west',{'x':.12,'z':3,'rotation':90}),('east',{'x':5.88,'z':3,'rotation':270}),
])
def test_window_overlap_checked_in_both_width_and_height_on_four_walls(wall,pose):
    window={'id':'window','wall':wall,'offset':2.,'width':2.,'sillHeight':1.,'height':1.2}
    device=ac(y=1.5,**pose);value=scene(device,windows=[window])
    assert window_conflicts(device,value['room'])
    assert not validate_scene(value)['valid']
    assert search_placement_errors(device,value['room'],[])
    device['y']=2.25
    assert not window_conflicts(device,value['room'])
    assert validate_scene(value)['valid']


def test_window_height_survives_schema_and_display_default_matches_legacy():
    window={'id':'w','wall':'north','offset':2,'width':1.5,'sillHeight':1.25}
    value=Scene.model_validate(scene(ac(y=2.25),windows=[window])).model_dump()
    assert 'height' not in value['room']['windows'][0]
    assert window_conflicts(value['items'][0],value['room'])
    window['height']=.5
    value=Scene.model_validate(scene(ac(y=2.25),windows=[window])).model_dump()
    assert value['room']['windows'][0]['height']==.5
    assert not window_conflicts(value['items'][0],value['room'])
    with pytest.raises(ValueError):
        Scene.model_validate(scene(ac(),windows=[{**window,'height':2.}]))


def test_search_blocks_front_clearance_symmetrically_before_final_acceptance():
    device=ac();blocker=item('shelf','bookshelf',x=3,z=4.3,width=.8,depth=.2,height=2.5)
    room=scene()['room']
    assert search_placement_errors(blocker,room,[device])
    assert search_placement_errors(device,room,[blocker])


def test_public_api_and_generation_reject_window_conflicts_without_mutating_input():
    from roomwise.main import app
    value=scene(ac(y=1.5),windows=[{'id':'w','wall':'north','offset':2,'width':2,'sillHeight':1.,'height':1.2}])
    before=deepcopy(value);client=TestClient(app)
    check=client.post('/api/validate',json={'scene':value})
    assert check.status_code==200 and not check.json()['valid']
    assert any(issue['type']=='wall_window_overlap' for issue in check.json()['issues'])
    generated=client.post('/api/generate',json={'scene':value,'mode':'rules','count':1,'seed':42})
    assert generated.status_code==200 and not generated.json()['candidates']
    assert value==before


def test_model_candidate_with_blocked_tv_is_rejected_by_final_generation_acceptance(monkeypatch):
    from types import SimpleNamespace
    from roomwise import generator
    value=scene(tv(),sofa(),item('shelf','bookshelf',x=5,z=3,height=2.))
    blocked=deepcopy(value);blocked['items'][2]['x']=3
    monkeypatch.setattr(generator,'learning_status',lambda:{'available':True})
    monkeypatch.setattr(generator.importlib,'import_module',lambda name:SimpleNamespace(refine_scene=lambda *args,**kwargs:deepcopy(blocked)))
    result=generator.generate_layouts(value,'model',1,42)
    assert not result['candidates']
    assert any(check['kind']=='tv_visibility' for check in result['diagnostics']['lastUnsatisfiedWallAppliances'])


def test_partial_screen_occlusion_is_not_reported_as_fully_clear():
    value=scene(tv(),sofa(),item('narrow','bookshelf',x=3.22,z=3,width=.12,depth=.12,height=2.))
    check=next(c for c in evaluate_wall_appliances(value)['checks'] if c['kind']=='tv_visibility')
    assert not check['satisfied'] and 0 < check['metrics']['blockedRays'] < check['metrics']['sampledRays']
