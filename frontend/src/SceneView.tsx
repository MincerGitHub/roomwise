import {useEffect,useRef,useState} from 'react';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {box} from './furnitureMesh';
import {FurnitureObjects,type ModelState} from './furnitureObjects';
import ModelLoading from './ModelLoading';
import type {Item,Scene,Validation} from './types';
import {baseY,reconcileSupports,surfacePlacement,type Placement} from './surfacePlacement';
import {isWallMounted} from './wallPlacement';
import {beginWallDrag,moveWallDrag,type WallDrag} from './wallDrag';
import {windowHeights} from './windowGeometry';

type Props={scene:Scene;selectedId:string|null;validation:Validation|null;top:boolean;inside:boolean;editable?:boolean;onSelect:(id:string|null)=>void;onContextMenu:(id:string,x:number,y:number)=>void;onMove:(id:string,placement:Placement)=>void;onToggleInside:()=>void;onEditRoom:()=>void};
const SELECTION_GREEN=0x5b8c4d;
function dispose(g:THREE.Object3D){g.traverse(o=>{if(o instanceof THREE.Mesh||o instanceof THREE.LineSegments||o instanceof THREE.Line){o.geometry.dispose();const ms=Array.isArray(o.material)?o.material:[o.material];ms.forEach(m=>m.dispose())}})}

export default function SceneView(props:Props){
 const host=useRef<HTMLDivElement>(null),headMarker=useRef<HTMLDivElement>(null);const latest=useRef(props);latest.current=props;
 const {inside}=props,insideRef=useRef(inside);insideRef.current=inside;
 const [snapLabel,setSnapLabel]=useState('');
 const [models,setModels]=useState<ModelState[]>([]);
 const runtime=useRef<{world:THREE.Scene;roomGroup:THREE.Group;itemsGroup:THREE.Group;renderer:THREE.WebGLRenderer;camera:THREE.PerspectiveCamera;ortho:THREE.OrthographicCamera;orbit:OrbitControls;groups:Map<string,THREE.Group>;furniture:FurnitureObjects;highlight:THREE.Group;fit:()=>void}|null>(null);
 useEffect(()=>{
  const div=host.current!;const world=new THREE.Scene();world.background=new THREE.Color(0xeaf2e6);
  const renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.0;div.append(renderer.domElement);
  const camera=new THREE.PerspectiveCamera(38,1,.05,150);const ortho=new THREE.OrthographicCamera(-5,5,5,-5,.05,100);ortho.up.set(0,0,-1);
  const orbit=new OrbitControls(camera,renderer.domElement);orbit.enableDamping=true;orbit.maxPolarAngle=Math.PI*.47;orbit.minDistance=3;orbit.maxDistance=24;orbit.mouseButtons={LEFT:THREE.MOUSE.ROTATE,MIDDLE:THREE.MOUSE.DOLLY,RIGHT:THREE.MOUSE.PAN};
  world.add(new THREE.HemisphereLight(0xffffff,0xd4d6ce,1.3));const sun=new THREE.DirectionalLight(0xfff5e8,2.1);sun.position.set(1,9,3);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);sun.shadow.camera.left=-10;sun.shadow.camera.right=10;sun.shadow.camera.top=10;sun.shadow.camera.bottom=-10;sun.shadow.bias=-.0002;world.add(sun);
  const ambient=new THREE.DirectionalLight(0xd8e4de,.6);ambient.position.set(-5,3,-5);world.add(ambient);
  const roomGroup=new THREE.Group(),itemsGroup=new THREE.Group(),highlight=new THREE.Group();world.add(roomGroup,itemsGroup,highlight);
  const furniture=new FurnitureObjects(itemsGroup,setModels),groups=furniture.groups;
  function recordCamera(){const active=latest.current.top?ortho:camera;active.updateMatrixWorld();div.dataset.camera=JSON.stringify({projection:active.projectionMatrix.toArray(),view:active.matrixWorldInverse.toArray()})}
  orbit.addEventListener('change',recordCamera);
  function resize(){const w=div.clientWidth,h=div.clientHeight;renderer.setSize(w,h);camera.aspect=w/h;camera.zoom=1;camera.updateProjectionMatrix();const s=Math.max(latest.current.scene.room.width,latest.current.scene.room.depth)*.72/Math.min(1,w/h);ortho.left=-s*w/h;ortho.right=s*w/h;ortho.top=s;ortho.bottom=-s;ortho.updateProjectionMatrix();recordCamera()}
  let yaw=Math.PI,pitch=0;const keys=new Set<string>();
  function validPosition(x:number,z:number){const room=latest.current.scene.room,poly=room.polygon?.length?room.polygon:[[0,0],[room.width,0],[room.width,room.depth],[0,room.depth]];let insidePoly=false;for(let i=0,j=poly.length-1;i<poly.length;j=i++){const [xi,zi]=poly[i],[xj,zj]=poly[j];if((zi>z)!==(zj>z)&&x<(xj-xi)*(z-zi)/(zj-zi)+xi)insidePoly=!insidePoly;const dx=xj-xi,dz=zj-zi,t=THREE.MathUtils.clamp(((x-xi)*dx+(z-zi)*dz)/(dx*dx+dz*dz),0,1);if(Math.hypot(x-(xi+t*dx),z-(zi+t*dz))<.2)return false}if(!insidePoly)return false;for(const item of latest.current.scene.items){const a=-THREE.MathUtils.degToRad(item.rotation),dx=x-item.x,dz=z-item.z,lx=Math.cos(a)*dx-Math.sin(a)*dz,lz=Math.sin(a)*dx+Math.cos(a)*dz;if(Math.abs(lx)<item.width/2+.2&&Math.abs(lz)<item.depth/2+.2)return false}return true}
  function fit(){const r=latest.current.scene.room;if(insideRef.current){let best:{x:number;z:number;score:number}|null=null;for(let iz=1;iz<10;iz++)for(let ix=1;ix<10;ix++){const x=r.width*ix/10,z=r.depth*iz/10;if(!validPosition(x,z))continue;const score=Math.min(x,r.width-x,z,r.depth-z);if(!best||score>best.score)best={x,z,score}}const x=best?.x??r.width/2,z=best?.z??r.depth/2;camera.position.set(x,Math.min(1.6,r.height-.15),z);yaw=Math.PI;pitch=0;camera.rotation.set(pitch,yaw,0,'YXZ');orbit.enabled=false}else{resize();orbit.enabled=true;
   const centre=new THREE.Vector3(r.width/2,r.height/2,r.depth/2);
   const direction=new THREE.Vector3(r.width,Math.max(r.width,r.depth),-r.depth).normalize();
   camera.position.copy(centre).add(direction);camera.lookAt(centre);
   const inverse=camera.quaternion.clone().invert(),tanV=Math.tan(THREE.MathUtils.degToRad(camera.fov/2)),tanH=tanV*camera.aspect;
   let distance=0;
   for(const x of [0,r.width])for(const y of [0,r.height])for(const z of [0,r.depth]){
    const point=new THREE.Vector3(x,y,z).sub(centre).applyQuaternion(inverse);
    distance=Math.max(distance,point.z+Math.abs(point.x)/tanH,point.z+Math.abs(point.y)/tanV);
   }
   orbit.target.copy(centre);camera.position.copy(centre).addScaledVector(direction,distance*1.08);
}ortho.position.set(r.width/2,20,r.depth/2);ortho.lookAt(r.width/2,0,r.depth/2);resize()}
  runtime.current={world,roomGroup,itemsGroup,renderer,camera,ortho,orbit,groups,furniture,highlight,fit};fit();const ro=new ResizeObserver(()=>fit());ro.observe(div);
  let drag:{id:string;pointerId:number;offset:THREE.Vector3;origin:THREE.Vector3;moved:boolean;supportId:string|null;wall:WallDrag|null}|null=null;
  const ray=new THREE.Raycaster(),pointer=new THREE.Vector2(),plane=new THREE.Plane(new THREE.Vector3(0,1,0),0);
  function cast(e:MouseEvent){const b=renderer.domElement.getBoundingClientRect();pointer.set((e.clientX-b.left)/b.width*2-1,-(e.clientY-b.top)/b.height*2+1);ray.setFromCamera(pointer,latest.current.top?ortho:camera)}
  let looking=false,lastX=0,lastY=0;
  let press:{x:number;y:number;id:string|null;room:boolean}|null=null;
  function down(e:PointerEvent){
   if(e.button!==0||!e.isPrimary)return;
   setSnapLabel('');cast(e);
   const hit=ray.intersectObjects(itemsGroup.children,true)[0];
   // Floor decoration is not an editable surface.
   const surface=ray.intersectObject(roomGroup,true).find(hit=>hit.object instanceof THREE.Mesh);
   const room=!!surface&&(!hit||surface.distance<hit.distance);
   let o:THREE.Object3D|null=room?null:hit?.object??null;
   while(o&&o.parent!==itemsGroup)o=o.parent;
   const id=o?.userData.itemId as string|undefined;
   press={x:e.clientX,y:e.clientY,id:id??null,room};
   if(insideRef.current){looking=true;lastX=e.clientX;lastY=e.clientY;renderer.domElement.setPointerCapture(e.pointerId);return;}
   if(!id||!o)return;
   latest.current.onSelect(id);
   const it=latest.current.scene.items.find(x=>x.id===id);
   if(latest.current.editable===false||!it||it.locked)return;
   if(latest.current.scene.items.some(item=>item.supportId===id&&item.locked)){setSnapLabel('台面上的箱子已锁定，请先解锁');return}
   plane.constant=-baseY(it);const pt=new THREE.Vector3();
   const wall=isWallMounted(it)&&!latest.current.top?beginWallDrag(it,ray.ray,latest.current.scene.room):null;
   if(isWallMounted(it)&&!latest.current.top&&!wall){setSnapLabel('没有避开窗户且可容纳该家具的安装位置');return}
   if(wall||ray.ray.intersectPlane(plane,pt)){drag={id,pointerId:e.pointerId,offset:pt.clone().sub(o.position),origin:o.position.clone(),moved:false,supportId:it.supportId??null,wall};orbit.enabled=false;renderer.domElement.setPointerCapture(e.pointerId);renderer.domElement.style.cursor='grabbing'}
  }
  function contextMenu(e:MouseEvent){e.preventDefault();cast(e);const hit=ray.intersectObjects(itemsGroup.children,true)[0];let o=hit?.object as THREE.Object3D|null|undefined;while(o&&o.parent!==itemsGroup)o=o.parent;if(o?.userData.itemId)latest.current.onContextMenu(o.userData.itemId as string,e.clientX,e.clientY)}
  function move(e:PointerEvent){
   if(insideRef.current){if(looking){yaw-= (e.clientX-lastX)*.003;pitch=THREE.MathUtils.clamp(pitch-(e.clientY-lastY)*.003,-1.35,1.35);lastX=e.clientX;lastY=e.clientY;camera.rotation.set(pitch,yaw,0,'YXZ')}return}
   if(!drag)return;cast(e);const pt=new THREE.Vector3();
   const scene=latest.current.scene,it=scene.items.find(item=>item.id===drag!.id),g=groups.get(drag.id);if(!it||!g)return;
   let pose:Placement;
   if(drag.wall&&!latest.current.top){
    const snapped=moveWallDrag(drag.wall,ray.ray,scene.room);if(!snapped){setSnapLabel('该墙面没有避开窗户的可用安装位置');return}pose=snapped.placement;
   }else{
    if(!ray.ray.intersectPlane(plane,pt))return;
    pt.sub(drag.offset);pose=surfacePlacement(it,THREE.MathUtils.clamp(pt.x,-1,scene.room.width+1),THREE.MathUtils.clamp(pt.z,-1,scene.room.depth+1),scene,drag.supportId);
   }
   const preview={...scene,items:scene.items.map(item=>({...item,...(item.id===it.id?pose:{})}))};
   try{reconcileSupports(preview,scene)}catch{return}
   for(const item of preview.items){const group=groups.get(item.id);if(group){group.position.set(item.x,baseY(item),item.z);group.rotation.y=THREE.MathUtils.degToRad(item.rotation)}}
   drag.supportId=pose.supportId;drag.moved=drag.origin.distanceTo(g.position)>.015;
   const target=scene.items.find(item=>item.id===pose.supportId);
   const wall=pose.rotation===undefined?'':({0:'南墙',90:'西墙',180:'北墙',270:'东墙'} as Record<number,string>)[pose.rotation];
   setSnapLabel(isWallMounted(it)&&wall?`已吸附到${wall} · ${latest.current.top?'沿墙移动':`安装高度 ${pose.y.toFixed(2)} m，可上下拖动`}`:target?`已吸附到${target.label}台面 · 继续拖动可移开`:'');
  }
  function finish(cancelled=false){
   if(!drag)return;const current=drag;drag=null;const g=groups.get(current.id);
   orbit.enabled=!latest.current.top;renderer.domElement.style.cursor='';setSnapLabel('');
   if(renderer.domElement.hasPointerCapture(current.pointerId))renderer.domElement.releasePointerCapture(current.pointerId);
   if(!cancelled&&g&&current.moved){const round=(v:number)=>Math.round(v*100000)/100000;latest.current.onMove(current.id,{x:round(g.position.x),z:round(g.position.z),y:g.position.y,rotation:round(THREE.MathUtils.radToDeg(g.rotation.y)),supportId:current.supportId})}
   else for(const item of latest.current.scene.items){const group=groups.get(item.id);if(group){group.position.set(item.x,baseY(item),item.z);group.rotation.y=THREE.MathUtils.degToRad(item.rotation)}}
  }
  const up=(e:PointerEvent)=>{
   const clicked=press&&Math.hypot(e.clientX-press.x,e.clientY-press.y)<6?press:null;
   looking=false;press=null;finish();
   if(renderer.domElement.hasPointerCapture(e.pointerId))renderer.domElement.releasePointerCapture(e.pointerId);
   if(clicked?.room)latest.current.onEditRoom();
   else if(clicked&&(!clicked.id||insideRef.current))latest.current.onSelect(clicked.id);
  },cancel=()=>{looking=false;press=null;finish(true)};
  const keydown=(e:KeyboardEvent)=>{if(!insideRef.current||e.defaultPrevented||e.isComposing||e.ctrlKey||e.altKey||e.metaKey)return;if(e.target instanceof HTMLElement&&(e.target.isContentEditable||e.target.closest('input,textarea,select')))return;if(['w','a','s','d','arrowup','arrowdown','arrowleft','arrowright'].includes(e.key.toLowerCase())){keys.add(e.key.toLowerCase());e.preventDefault()}};
  const keyup=(e:KeyboardEvent)=>keys.delete(e.key.toLowerCase());
  const blur=()=>keys.clear();window.addEventListener('keydown',keydown);window.addEventListener('keyup',keyup);window.addEventListener('blur',blur);
  renderer.domElement.addEventListener('pointerdown',down);renderer.domElement.addEventListener('pointermove',move);renderer.domElement.addEventListener('pointerup',up);renderer.domElement.addEventListener('pointercancel',cancel);
  renderer.domElement.addEventListener('contextmenu',contextMenu);
  let raf=0,previous=performance.now();const animate=()=>{raf=requestAnimationFrame(animate);const now=performance.now(),dt=Math.min((now-previous)/1000,.05);previous=now;orbit.enabled=!insideRef.current&&!latest.current.top&&!drag;if(insideRef.current){const forward=(keys.has('w')||keys.has('arrowup')?1:0)-(keys.has('s')||keys.has('arrowdown')?1:0),side=(keys.has('d')||keys.has('arrowright')?1:0)-(keys.has('a')||keys.has('arrowleft')?1:0),length=Math.hypot(forward,side)||1,speed=2*dt;const dx=(-Math.sin(yaw)*forward+Math.cos(yaw)*side)/length*speed,dz=(-Math.cos(yaw)*forward-Math.sin(yaw)*side)/length*speed;const p=camera.position;if(validPosition(p.x+dx,p.z))p.x+=dx;if(validPosition(p.x,p.z+dz))p.z+=dz}else orbit.update();for(const outline of highlight.children){const group=groups.get(outline.userData.itemId);if(group){outline.position.set(group.position.x,group.position.y+(outline.userData.height??0)/2,group.position.z);outline.rotation.y=group.rotation.y}}const activeCamera=latest.current.top?ortho:camera;renderer.render(world,activeCamera);if(insideRef.current&&(looking||keys.size))recordCamera();const bed=latest.current.scene.items.find(item=>item.id===latest.current.selectedId&&['double_bed','single_bed','kids_bed'].includes(item.category));const marker=headMarker.current;if(marker&&bed){const g=groups.get(bed.id),angle=THREE.MathUtils.degToRad(bed.rotation);const head=new THREE.Vector3((g?.position.x??bed.x)-Math.sin(angle)*bed.depth/2,bed.height+.22,(g?.position.z??bed.z)-Math.cos(angle)*bed.depth/2).project(activeCamera);marker.style.left=`${(head.x+1)*div.clientWidth/2}px`;marker.style.top=`${(1-head.y)*div.clientHeight/2}px`;marker.style.visibility=Math.abs(head.x)<1&&Math.abs(head.y)<1&&head.z>=-1&&head.z<=1?'visible':'hidden'}};animate();
  const reset=()=>fit();div.addEventListener('roomwise-fit',reset);
  return()=>{cancelAnimationFrame(raf);ro.disconnect();orbit.dispose();furniture.dispose();dispose(world);renderer.dispose();renderer.forceContextLoss();renderer.domElement.remove();renderer.domElement.removeEventListener('contextmenu',contextMenu);div.removeEventListener('roomwise-fit',reset);window.removeEventListener('keydown',keydown);window.removeEventListener('keyup',keyup);window.removeEventListener('blur',blur);runtime.current=null};
 },[]);
 useEffect(()=>{
  const rt=runtime.current;if(!rt)return;dispose(rt.roomGroup);rt.roomGroup.clear();const r=props.scene.room;const poly=r.polygon?.length?r.polygon:[[0,0],[r.width,0],[r.width,r.depth],[0,r.depth]];
  const shape=new THREE.Shape(poly.map(p=>new THREE.Vector2(p[0],-p[1])));const floor=new THREE.Mesh(new THREE.ShapeGeometry(shape),new THREE.MeshStandardMaterial({color:0xe4d8c6,roughness:.93}));floor.rotation.x=-Math.PI/2;floor.receiveShadow=true;floor.position.y=.003;rt.roomGroup.add(floor);
  const floorBase=new THREE.Group();box(floorBase,r.width+.04,.12,r.depth+.04,r.width/2,-.07,r.depth/2,0xc9bdab);if(!r.polygon?.length)rt.roomGroup.add(floorBase);
  if(!r.polygon?.length){const verts:number[]=[];for(let z=.23;z<r.depth;z+=.23){verts.push(0,.008,z,r.width,.008,z);for(let x=(Math.round(z/.23)%2)*.6+.7;x<r.width;x+=1.2)verts.push(x,.008,z-.23,x,.008,z)}const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(verts,3));rt.roomGroup.add(new THREE.LineSegments(geo,new THREE.LineBasicMaterial({color:0xcfc0aa,transparent:true,opacity:.6})))}
  const walls=new THREE.Group();const wh=props.top?.03:r.height;for(let i=0;i<poly.length;i++){const a=poly[i],b=poly[(i+1)%poly.length];const dx=b[0]-a[0],dz=b[1]-a[1],len=Math.hypot(dx,dz);const high=Math.abs(a[1]-r.depth)<.03&&Math.abs(b[1]-r.depth)<.03||Math.abs(a[0])<.03&&Math.abs(b[0])<.03;const h=high?wh:.08;const m=box(walls,len,h,.08,(a[0]+b[0])/2,h/2,(a[1]+b[1])/2,0xe8e7dc);(m.material as THREE.MeshStandardMaterial).side=THREE.DoubleSide;m.rotation.y=-Math.atan2(dz,dx)}rt.roomGroup.add(walls);
  for(const w of r.windows||[]){
   const g=new THREE.Group(),{height,bottom}=windowHeights(w,r);
   const y=props.top?.025:bottom+height/2;
   if(['north','south'].includes(w.wall))box(g,w.width,props.top?.045:height,.024,w.offset+w.width/2,y,w.wall==='north'?r.depth-.045:.045,0xabc2be);
   else box(g,.024,props.top?.045:height,w.width,w.wall==='west'?.045:r.width-.045,y,w.offset+w.width/2,0xabc2be);
   rt.roomGroup.add(g);
  }
  if(r.door){const door=r.door;const g=new THREE.Group();const d=door.clearance,along=door.width;const horizontal=['south','north'].includes(door.wall);const x=horizontal?door.offset+along/2:(door.wall==='west'?d/2:r.width-d/2);const z=horizontal?(door.wall==='south'?d/2:r.depth-d/2):door.offset+along/2;const q=new THREE.Mesh(new THREE.PlaneGeometry(horizontal?along:d,horizontal?d:along),new THREE.MeshBasicMaterial({color:0xcab38c,transparent:true,opacity:.24,side:THREE.DoubleSide,depthWrite:false}));q.rotation.x=-Math.PI/2;q.position.set(x,.022,z);g.add(q);rt.roomGroup.add(g)}
 },[props.scene.room,props.top,inside]);
 useEffect(()=>{
  runtime.current?.furniture.sync(props.scene.items);
 },[props.scene.items]);
 useEffect(()=>{const rt=runtime.current;if(!rt)return;dispose(rt.highlight);rt.highlight.clear();const bad=new Set(props.validation?.issues.filter(x=>x.severity==='error').flatMap(x=>x.itemIds||[])||[]);for(const it of props.scene.items){if(it.id!==props.selectedId&&!bad.has(it.id))continue;const geo=new THREE.EdgesGeometry(new THREE.BoxGeometry(it.width+.05,Math.max(.045,it.height+.05),it.depth+.05));const lines=new THREE.LineSegments(geo,new THREE.LineBasicMaterial({color:it.id===props.selectedId?SELECTION_GREEN:0xc6604c}));lines.userData={itemId:it.id,height:it.height};lines.position.set(it.x,baseY(it)+it.height/2,it.z);lines.rotation.y=THREE.MathUtils.degToRad(it.rotation);rt.highlight.add(lines)}for(const preference of props.scene.preferences){if(preference.kind!=='face_window')continue;const it=props.scene.items.find(item=>item.id===preference.itemId);if(!it)continue;const angle=THREE.MathUtils.degToRad(it.rotation),direction=new THREE.Vector3(Math.sin(angle),0,Math.cos(angle));const arrow=new THREE.ArrowHelper(direction,new THREE.Vector3(it.x,Math.max(.12,it.height+.1),it.z),Math.max(.55,it.depth*.85),SELECTION_GREEN,.14,.09);rt.highlight.add(arrow)}},[props.scene.items,props.scene.preferences,props.selectedId,props.validation]);
 useEffect(()=>{runtime.current?.fit();},[inside,props.scene.room.width,props.scene.room.depth,props.scene.room.height,props.top]);
 useEffect(()=>{runtime.current?.renderer.domElement.setAttribute('aria-label',props.editable===false?'三维候选方案':'可编辑三维房间')},[props.editable]);
 const selectedBed=props.scene.items.find(item=>item.id===props.selectedId&&['double_bed','single_bed','kids_bed'].includes(item.category));
 const headMetadata=selectedBed?{itemId:selectedBed.id,localDirection:'-z',rightLocalDirection:'+x',reference:'站在床尾看床头',x:selectedBed.x-Math.sin(selectedBed.rotation*Math.PI/180)*selectedBed.depth/2,z:selectedBed.z-Math.cos(selectedBed.rotation*Math.PI/180)*selectedBed.depth/2}:undefined;
 return <div ref={host} className="scene-canvas" data-testid="scene-canvas" data-models={JSON.stringify(models)} data-layout={JSON.stringify(props.scene.items.map(it=>[it.id,it.x,it.z,it.rotation]))} data-placement={JSON.stringify(props.scene.items.map(it=>({id:it.id,x:it.x,y:baseY(it),z:it.z,rotation:it.rotation,supportId:it.supportId??null})))} data-bed-head={headMetadata?JSON.stringify(headMetadata):undefined}><ModelLoading states={models} retry={()=>runtime.current?.furniture.retry()}/>{snapLabel&&<div className="surface-snap-hint" role="status">{snapLabel}</div>}{selectedBed&&<div ref={headMarker} className="bed-head-marker" data-testid="bed-head-marker" title="枕头和床头板所在的一端；左右按站在床尾看床头判断">床头<span>左右：站在床尾看床头</span></div>}
  <button type="button" className="room-inside-toggle" aria-pressed={inside} disabled={props.top} onClick={props.onToggleInside}>{inside?'退出室内':'进入室内'}</button>
 </div>;
}
