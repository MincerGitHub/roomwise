# Roomwise implementation contract

Project: local, single-room furniture placement prototype. Backend package `backend/roomwise`, frontend `frontend`. Runtime binds 127.0.0.1. Units metres, ground axes x/z, height y. Item rotation in degrees around y; positive 90 swaps width/depth. Scene polygon coordinates in same frame as items; rectangular default [0,0]→[width,depth]. No item identity/size changes during generation.

Scene JSON:
```json
{"id":"demo","name":"搬家后的卧室","version":0,"room":{"width":5.2,"depth":4.2,"height":2.7,"polygon":null,"door":{"wall":"south","offset":0.45,"width":0.9,"clearance":0.9},"windows":[{"id":"window-1","wall":"north","offset":2.3,"width":1.5,"sillHeight":0.9}]},"items":[{"id":"bed-1","label":"旧双人床","category":"double_bed","width":1.8,"depth":2.0,"height":0.55,"x":2.5,"z":2.1,"rotation":0,"locked":false,"keep":true,"source":"brought","assetUrl":null,"photoUrl":null}],"preferences":[]}
```
All 19 bedroom classes supported: armchair,bookshelf,cabinet,chair,children_cabinet,coffee_table,desk,double_bed,dressing_chair,dressing_table,kids_bed,nightstand,shelf,single_bed,sofa,stool,table,tv_stand,wardrobe. Add rug as non-solid exception. Source brought|existing|new. `assetUrl` and `photoUrl` optional. Preferences `{kind:'near_window',itemId:'desk-1'}` or `{kind:'min_move',itemId:'bed-1'}`.

API (frontend prefix /api proxied to localhost:8765):
- GET /health -> {status,modelLoaded,videoDetector,...}
- GET /catalog -> {items:[{category,label,width,depth,height,...}]}
- GET /demo -> Scene
- POST /validate {scene} -> {valid,issues:[{type,severity,message,itemIds}],metrics:{collisions,outOfBounds,doorConflicts,reachable,checkedItems,...}}
- POST /generate {scene,mode:'hybrid'|'rules'|'model',count:3,seed:42} -> {baseVersion:scene.version,candidates:[{id,scene,validation,score,mode,summary}],diagnostics:{...}}. Return failure explicitly if no accepted candidates. Original locked transforms and ALL identity/size/keep/source protected.
- POST /command {scene,text,selectedId?} -> {baseVersion,action:'edit'|'generate'|'suggest'|'undo'|'clarify'|'unsupported',scene?,message,changes?:[],suggestions?:[],needsConfirmation?:bool}. Limited deterministic Chinese parser works offline; do not claim LLM if none. Commands can return generate intent, caller invokes generate with updated preferences/locks. Existing locks cannot be implicitly overridden.
- POST /suggest {scene,need:'work'|'storage'|'reading'} -> {suggestions:[{category,label,width,depth,height,reason,...}]}. User must accept.
- POST /scenes/save {scene} -> {id,version}; GET /scenes -> {scenes:[...]}; GET /scenes/{id} -> Scene. Server optimistic version rejection where saved state exists. Caller can use import/export JSON with same fields.
- POST /assets multipart file -> {url,name,type}; local glb/gltf or image accepted safe filename. No arbitrary path.
- POST /video/analyze multipart file -> {jobId}; GET /video/jobs/{jobId} -> {status:'queued'|'processing'|'complete'|'failed',progress,frames:[{id,url,timestamp,sharpness}],candidates:[{trackId,label,category,confidence,frameUrl,bbox}],detector,limitations,error?}. Candidate category is provisional; requires human confirmation, no inferred dimensions.
- GET /experiments -> summary of real available model experiment artifacts, absent -> honest no results.

Model module `roomwise.learning`: `model_status()` and `refine_scene(scene:dict,iterations:int=3)->dict`. Model absent must report unavailable, never fabricate model generation. Root owns venv dependency installation. Agents do not edit each others' files; backend geometry tests validate ML output independently.

Ownership: backend agent schemas/geometry/generator/commands/storage/API/tests. Model agent learning.py + scripts + artifacts + training/evaluation tests. Video agent video.py + setup model downloader + video tests. Root frontend/integration/docs/launcher. No public publish, no redistributing restricted training arrays. Use self-made procedural furniture meshes in demo.
