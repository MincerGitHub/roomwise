import {useEffect,useRef,useState} from 'react';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {createFurniture as furniture,box} from './furnitureMesh';
import type {Item,Scene,Validation} from './types';
import {baseY,reconcileSupports,surfacePlacement,type Placement} from './surfacePlacement';

type Props={scene:Scene;selectedId:string|null;validation:Validation|null;top:boolean;editable?:boolean;onSelect:(id:string|null)=>void;onMove:(id:string,placement:Placement)=>void};
function dispose(g:THREE.Object3D){g.traverse(o=>{if(o instanceof THREE.Mesh||o instanceof THREE.LineSegments||o instanceof THREE.Line){o.geometry.dispose();const ms=Array.isArray(o.material)?o.material:[o.material];ms.forEach(m=>m.dispose())}})}

export default function SceneView(props:Props){
 const host=useRef<HTMLDivElement>(null),headMarker=useRef<HTMLDivElement>(null);const latest=useRef(props);latest.current=props;
 const [snapLabel,setSnapLabel]=useState('');
 const runtime=useRef<{world:THREE.Scene;roomGroup:THREE.Group;itemsGroup:THREE.Group;renderer:THREE.WebGLRenderer;camera:THREE.PerspectiveCamera;ortho:THREE.OrthographicCamera;orbit:OrbitControls;groups:Map<string,THREE.Group>;highlight:THREE.Group;fit:()=>void}|null>(null);
 useEffect(()=>{
  const div=host.current!;const world=new THREE.Scene();world.background=new THREE.Color(0xf1f0eb);
  const renderer=new THREE.WebGLRenderer({antialias:true,preserveDrawingBuffer:true});renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.0;renderer.domElement.setAttribute('aria-label','可编辑三维房间');div.append(renderer.domElement);
  const camera=new THREE.PerspectiveCamera(38,1,.05,150);const ortho=new THREE.OrthographicCamera(-5,5,5,-5,.05,100);ortho.up.set(0,0,-1);
  const orbit=new OrbitControls(camera,renderer.domElement);orbit.enableDamping=true;orbit.maxPolarAngle=Math.PI*.47;orbit.minDistance=3;orbit.maxDistance=24;orbit.mouseButtons={LEFT:THREE.MOUSE.ROTATE,MIDDLE:THREE.MOUSE.DOLLY,RIGHT:THREE.MOUSE.PAN};
  world.add(new THREE.HemisphereLight(0xffffff,0xd4d6ce,1.3));const sun=new THREE.DirectionalLight(0xfff5e8,2.1);sun.position.set(1,9,3);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);sun.shadow.camera.left=-10;sun.shadow.camera.right=10;sun.shadow.camera.top=10;sun.shadow.camera.bottom=-10;sun.shadow.bias=-.0002;world.add(sun);
  const ambient=new THREE.DirectionalLight(0xd8e4de,.6);ambient.position.set(-5,3,-5);world.add(ambient);
  const roomGroup=new THREE.Group(),itemsGroup=new THREE.Group(),highlight=new THREE.Group();world.add(roomGroup,itemsGroup,highlight);
  const groups=new Map<string,THREE.Group>();
  function resize(){const w=div.clientWidth,h=div.clientHeight;renderer.setSize(w,h);camera.aspect=w/h;camera.updateProjectionMatrix();const s=Math.max(latest.current.scene.room.width,latest.current.scene.room.depth)*.72;ortho.left=-s*w/h;ortho.right=s*w/h;ortho.top=s;ortho.bottom=-s;ortho.updateProjectionMatrix()}
  function fit(){const r=latest.current.scene.room;orbit.target.set(r.width/2,.1,r.depth/2);camera.position.set(r.width/2+r.width*1.13,Math.max(r.width,r.depth)*1.13,r.depth/2-r.depth*1.15);ortho.position.set(r.width/2,20,r.depth/2);ortho.lookAt(r.width/2,0,r.depth/2);orbit.update();resize()}
  runtime.current={world,roomGroup,itemsGroup,renderer,camera,ortho,orbit,groups,highlight,fit};fit();const ro=new ResizeObserver(resize);ro.observe(div);
  let drag:{id:string;pointerId:number;offset:THREE.Vector3;origin:THREE.Vector3;moved:boolean;supportId:string|null}|null=null;
  const ray=new THREE.Raycaster(),pointer=new THREE.Vector2(),plane=new THREE.Plane(new THREE.Vector3(0,1,0),0);
  function cast(e:PointerEvent){const b=renderer.domElement.getBoundingClientRect();pointer.set((e.clientX-b.left)/b.width*2-1,-(e.clientY-b.top)/b.height*2+1);ray.setFromCamera(pointer,latest.current.top?ortho:camera)}
  function down(e:PointerEvent){
   if(e.button!==0)return;setSnapLabel('');cast(e);const hits=ray.intersectObjects(itemsGroup.children,true);
   if(!hits.length){latest.current.onSelect(null);return}let o:THREE.Object3D|null=hits[0].object;while(o&&o.parent!==itemsGroup)o=o.parent;
   if(!o?.userData.itemId)return;const id=o.userData.itemId as string;latest.current.onSelect(id);
   const it=latest.current.scene.items.find(x=>x.id===id);
   if(latest.current.editable===false||!it||it.locked)return;
   if(latest.current.scene.items.some(item=>item.supportId===id&&item.locked)){setSnapLabel('台面上的箱子已锁定，请先解锁');return}
   plane.constant=-baseY(it);const pt=new THREE.Vector3();
   if(ray.ray.intersectPlane(plane,pt)){drag={id,pointerId:e.pointerId,offset:pt.clone().sub(o.position),origin:o.position.clone(),moved:false,supportId:it.supportId??null};orbit.enabled=false;renderer.domElement.setPointerCapture(e.pointerId);renderer.domElement.style.cursor='grabbing'}
  }
  function move(e:PointerEvent){
   if(!drag)return;cast(e);const pt=new THREE.Vector3();if(!ray.ray.intersectPlane(plane,pt))return;
   const scene=latest.current.scene,it=scene.items.find(item=>item.id===drag!.id),g=groups.get(drag.id);if(!it||!g)return;
   pt.sub(drag.offset);const pose=surfacePlacement(it,THREE.MathUtils.clamp(pt.x,-1,scene.room.width+1),THREE.MathUtils.clamp(pt.z,-1,scene.room.depth+1),scene,drag.supportId);
   const preview={...scene,items:scene.items.map(item=>({...item,...(item.id===it.id?pose:{})}))};
   try{reconcileSupports(preview,scene)}catch{return}
   for(const item of preview.items){const group=groups.get(item.id);if(group){group.position.set(item.x,baseY(item),item.z);group.rotation.y=THREE.MathUtils.degToRad(item.rotation)}}
   drag.supportId=pose.supportId;drag.moved=drag.origin.distanceTo(g.position)>.015;
   const target=scene.items.find(item=>item.id===pose.supportId);setSnapLabel(target?`已吸附到${target.label}台面 · 继续拖动可移开`:'');
  }
  function finish(cancelled=false){
   if(!drag)return;const current=drag;drag=null;const g=groups.get(current.id);
   orbit.enabled=!latest.current.top;renderer.domElement.style.cursor='';setSnapLabel('');
   if(renderer.domElement.hasPointerCapture(current.pointerId))renderer.domElement.releasePointerCapture(current.pointerId);
   if(!cancelled&&g&&current.moved){const round=(v:number)=>Math.round(v*100000)/100000;latest.current.onMove(current.id,{x:round(g.position.x),z:round(g.position.z),y:g.position.y,supportId:current.supportId})}
   else for(const item of latest.current.scene.items){const group=groups.get(item.id);if(group){group.position.set(item.x,baseY(item),item.z);group.rotation.y=THREE.MathUtils.degToRad(item.rotation)}}
  }
  const up=()=>finish(),cancel=()=>finish(true);
  renderer.domElement.addEventListener('pointerdown',down);renderer.domElement.addEventListener('pointermove',move);renderer.domElement.addEventListener('pointerup',up);renderer.domElement.addEventListener('pointercancel',cancel);
  let raf=0;const animate=()=>{raf=requestAnimationFrame(animate);orbit.enabled=!latest.current.top&&!drag;orbit.update();for(const outline of highlight.children){const group=groups.get(outline.userData.itemId);if(group){outline.position.set(group.position.x,group.position.y+(outline.userData.height??0)/2,group.position.z);outline.rotation.y=group.rotation.y}}const activeCamera=latest.current.top?ortho:camera;renderer.render(world,activeCamera);const bed=latest.current.scene.items.find(item=>item.id===latest.current.selectedId&&['double_bed','single_bed','kids_bed'].includes(item.category));const marker=headMarker.current;if(marker&&bed){const g=groups.get(bed.id),angle=THREE.MathUtils.degToRad(bed.rotation);const head=new THREE.Vector3((g?.position.x??bed.x)-Math.sin(angle)*bed.depth/2,bed.height+.22,(g?.position.z??bed.z)-Math.cos(angle)*bed.depth/2).project(activeCamera);marker.style.left=`${(head.x+1)*div.clientWidth/2}px`;marker.style.top=`${(1-head.y)*div.clientHeight/2}px`;marker.style.visibility=Math.abs(head.x)<1&&Math.abs(head.y)<1&&head.z>=-1&&head.z<=1?'visible':'hidden'}};animate();
  const reset=()=>fit();div.addEventListener('roomwise-fit',reset);
  return()=>{cancelAnimationFrame(raf);ro.disconnect();orbit.dispose();dispose(world);renderer.dispose();renderer.domElement.remove();div.removeEventListener('roomwise-fit',reset);runtime.current=null};
 },[]);
 useEffect(()=>{
  const rt=runtime.current;if(!rt)return;dispose(rt.roomGroup);rt.roomGroup.clear();const r=props.scene.room;const poly=r.polygon?.length?r.polygon:[[0,0],[r.width,0],[r.width,r.depth],[0,r.depth]];
  const shape=new THREE.Shape(poly.map(p=>new THREE.Vector2(p[0],-p[1])));const floor=new THREE.Mesh(new THREE.ShapeGeometry(shape),new THREE.MeshStandardMaterial({color:0xe4d8c6,roughness:.93}));floor.rotation.x=-Math.PI/2;floor.receiveShadow=true;floor.position.y=.003;rt.roomGroup.add(floor);
  const floorBase=new THREE.Group();box(floorBase,r.width+.04,.12,r.depth+.04,r.width/2,-.07,r.depth/2,0xc9bdab);if(!r.polygon?.length)rt.roomGroup.add(floorBase);
  if(!r.polygon?.length){const verts:number[]=[];for(let z=.23;z<r.depth;z+=.23){verts.push(0,.008,z,r.width,.008,z);for(let x=(Math.round(z/.23)%2)*.6+.7;x<r.width;x+=1.2)verts.push(x,.008,z-.23,x,.008,z)}const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(verts,3));rt.roomGroup.add(new THREE.LineSegments(geo,new THREE.LineBasicMaterial({color:0xcfc0aa,transparent:true,opacity:.6})))}
  const walls=new THREE.Group();const wh=props.top?.03:Math.min(1.5,r.height);for(let i=0;i<poly.length;i++){const a=poly[i],b=poly[(i+1)%poly.length];const dx=b[0]-a[0],dz=b[1]-a[1],len=Math.hypot(dx,dz);const high=Math.abs(a[1]-r.depth)<.03&&Math.abs(b[1]-r.depth)<.03||Math.abs(a[0])<.03&&Math.abs(b[0])<.03;const h=high?wh:.08;const m=box(walls,len,h,.08,(a[0]+b[0])/2,h/2,(a[1]+b[1])/2,0xe8e7dc);m.rotation.y=-Math.atan2(dz,dx)}rt.roomGroup.add(walls);
  for(const w of r.windows||[]){const g=new THREE.Group();const y=props.top?.025:Math.min(.9,w.sillHeight+.3);if(['north','south'].includes(w.wall))box(g,w.width,props.top?.045:.45,.024,w.offset+w.width/2,y,w.wall==='north'?r.depth-.045:.045,0xabc2be);else box(g,.024,props.top?.045:.45,w.width,w.wall==='west'?.045:r.width-.045,y,w.offset+w.width/2,0xabc2be);rt.roomGroup.add(g)}
  if(r.door){const door=r.door;const g=new THREE.Group();const d=door.clearance,along=door.width;const horizontal=['south','north'].includes(door.wall);const x=horizontal?door.offset+along/2:(door.wall==='west'?d/2:r.width-d/2);const z=horizontal?(door.wall==='south'?d/2:r.depth-d/2):door.offset+along/2;const q=new THREE.Mesh(new THREE.PlaneGeometry(horizontal?along:d,horizontal?d:along),new THREE.MeshBasicMaterial({color:0xcab38c,transparent:true,opacity:.24,side:THREE.DoubleSide,depthWrite:false}));q.rotation.x=-Math.PI/2;q.position.set(x,.022,z);g.add(q);rt.roomGroup.add(g)}
 },[props.scene.room,props.top]);
 useEffect(()=>{
  const rt=runtime.current;if(!rt)return;dispose(rt.itemsGroup);rt.itemsGroup.clear();rt.groups.clear();const loader=new GLTFLoader();let cancelled=false;
  props.scene.items.forEach(it=>{
   const g=furniture(it);g.position.set(it.x,baseY(it),it.z);g.rotation.y=THREE.MathUtils.degToRad(it.rotation);rt.itemsGroup.add(g);rt.groups.set(it.id,g);
   if(it.assetUrl)loader.load(it.assetUrl,glb=>{if(cancelled){dispose(glb.scene);return}const a=glb.scene;const b=new THREE.Box3().setFromObject(a),s=b.getSize(new THREE.Vector3()),c=b.getCenter(new THREE.Vector3());if(Math.min(s.x,s.y,s.z)<.0001){dispose(a);return}a.position.set(-c.x,-b.min.y,-c.z);const wrapper=new THREE.Group();wrapper.add(a);wrapper.scale.set(it.width/s.x,it.height/s.y,it.depth/s.z);wrapper.traverse(o=>{if(o instanceof THREE.Mesh){o.castShadow=true;o.receiveShadow=true}});dispose(g);g.clear();g.add(wrapper)},undefined,()=>{/* Keep procedural fallback on unreadable asset. */});
  });return()=>{cancelled=true};
 },[props.scene.items]);
 useEffect(()=>{const rt=runtime.current;if(!rt)return;dispose(rt.highlight);rt.highlight.clear();const bad=new Set(props.validation?.issues.filter(x=>x.severity==='error').flatMap(x=>x.itemIds||[])||[]);for(const it of props.scene.items){if(it.id!==props.selectedId&&!bad.has(it.id))continue;const geo=new THREE.EdgesGeometry(new THREE.BoxGeometry(it.width+.05,Math.max(.045,it.height+.05),it.depth+.05));const lines=new THREE.LineSegments(geo,new THREE.LineBasicMaterial({color:bad.has(it.id)?0xc6604c:0x478371}));lines.userData={itemId:it.id,height:it.height};lines.position.set(it.x,baseY(it)+it.height/2,it.z);lines.rotation.y=THREE.MathUtils.degToRad(it.rotation);rt.highlight.add(lines)}for(const preference of props.scene.preferences){if(preference.kind!=='face_window')continue;const it=props.scene.items.find(item=>item.id===preference.itemId);if(!it)continue;const angle=THREE.MathUtils.degToRad(it.rotation),direction=new THREE.Vector3(Math.sin(angle),0,Math.cos(angle));const arrow=new THREE.ArrowHelper(direction,new THREE.Vector3(it.x,Math.max(.12,it.height+.1),it.z),Math.max(.55,it.depth*.85),0x386a8d,.14,.09);rt.highlight.add(arrow)}},[props.scene.items,props.scene.preferences,props.selectedId,props.validation]);
 useEffect(()=>{runtime.current?.fit()},[props.scene.room.width,props.scene.room.depth,props.top]);
 const selectedBed=props.scene.items.find(item=>item.id===props.selectedId&&['double_bed','single_bed','kids_bed'].includes(item.category));
 const headMetadata=selectedBed?{itemId:selectedBed.id,localDirection:'-z',rightLocalDirection:'+x',reference:'站在床尾看床头',x:selectedBed.x-Math.sin(selectedBed.rotation*Math.PI/180)*selectedBed.depth/2,z:selectedBed.z-Math.cos(selectedBed.rotation*Math.PI/180)*selectedBed.depth/2}:undefined;
 return <div ref={host} className="scene-canvas" data-testid="scene-canvas" data-layout={JSON.stringify(props.scene.items.map(it=>[it.id,it.x,it.z,it.rotation]))} data-placement={JSON.stringify(props.scene.items.map(it=>({id:it.id,x:it.x,y:baseY(it),z:it.z,rotation:it.rotation,supportId:it.supportId??null})))} data-bed-head={headMetadata?JSON.stringify(headMetadata):undefined}>{snapLabel&&<div className="surface-snap-hint" role="status">{snapLabel}</div>}{selectedBed&&<div ref={headMarker} className="bed-head-marker" data-testid="bed-head-marker" title="枕头和床头板所在的一端；左右按站在床尾看床头判断">床头<span>左右：站在床尾看床头</span></div>}</div>;
}
