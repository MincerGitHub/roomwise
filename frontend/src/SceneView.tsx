import {useEffect,useRef} from 'react';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import type {Item,Scene,Validation} from './types';

type Props={scene:Scene;selectedId:string|null;validation:Validation|null;top:boolean;editable?:boolean;onSelect:(id:string|null)=>void;onMove:(id:string,x:number,z:number)=>void};
const colors={wood:0xb28c65,lightWood:0xd8cbb7,cream:0xf1ece2,dark:0x596159,sage:0x82a28a,rust:0xba826b};
function box(g:THREE.Group,w:number,h:number,d:number,x:number,y:number,z:number,color:number,radius=0){
 const m=new THREE.Mesh(new THREE.BoxGeometry(Math.max(.005,w),Math.max(.005,h),Math.max(.005,d)),new THREE.MeshStandardMaterial({color,roughness:.78}));m.position.set(x,y,z);m.castShadow=true;m.receiveShadow=true;g.add(m);return m;
}
function legs(g:THREE.Group,w:number,d:number,h:number){for(const x of [-1,1])for(const z of [-1,1])box(g,.045,h,.045,x*(w/2-.07),h/2,z*(d/2-.07),colors.dark)}
function furniture(it:Item):THREE.Group{
 const g=new THREE.Group();const {width:w,depth:d,height:h}=it;g.userData.itemId=it.id;
 if(it.category.includes('bed')){
  box(g,w,.13,d,0,.13,0,colors.wood);box(g,w*.97,.16,d*.95,0,.29,0,colors.cream);
  box(g,w*.96,Math.max(.02,h-.39),d*.76,0,.39+(Math.max(.02,h-.39)/2),d*.10,colors.sage);
  box(g,w,Math.min(h*.8,.45),.075,0,Math.min(h*.8,.45)/2,-d/2+.04,colors.lightWood);
  for(const x of w>1.3?[-w*.24,w*.24]:[0])box(g,w>1.3?w*.40:w*.75,.10,d*.19,x,.41,-d*.33,0xfcfaf4);
 }else if(['desk','table','coffee_table','dressing_table'].includes(it.category)){
  legs(g,w,d,Math.max(.1,h-.055));box(g,w,.055,d,0,h-.027,0,colors.lightWood);
  if(it.category==='desk'){box(g,.30,h*.60,d*.82,w/2-.17,h*.45,0,0xd5dbd0);for(let n=0;n<3;n++)box(g,.26,.006,.012,w/2-.17,h*.3+n*.12,d*.41+.01,colors.wood)}
  if(it.category==='dressing_table'){
   // Local +z is the usable front: the paired chair sits here and faces -z.
   // A framed mirror at the back makes that orientation visible in the 3D view.
   box(g,w*.50,.43,.035,0,h+.22,-d*.30,colors.wood);
   box(g,w*.43,.35,.012,0,h+.22,-d*.30+.024,0xa9c2be);
   box(g,w*.38,.13,d*.28,0,h-.12,d*.20,colors.wood);
   box(g,.025,.025,.018,0,h-.12,d*.35,colors.cream);
  }
 }else if(['chair','dressing_chair','stool','armchair'].includes(it.category)){
  const seatH=it.category==='armchair'?h*.40:h*.52;legs(g,w,d,seatH);box(g,w,.07,d,0,seatH,0,colors.sage);
  if(it.category!=='stool')box(g,w,h-seatH-.04,.08,0,seatH+(h-seatH-.04)/2,-d/2+.04,colors.sage);
  if(it.category==='armchair')for(const x of [-1,1])box(g,.10,h*.36,d,x*(w/2-.05),h*.47,0,colors.cream);
 }else if(it.category==='sofa'){
  box(g,w,.13,d,0,.09,0,colors.wood);box(g,w*.84,h*.38,d*.79,0,h*.32,d*.07,colors.sage);box(g,w,h*.66,.16,0,h*.62,-d/2+.08,colors.sage);for(const x of [-1,1])box(g,.14,h*.62,d,x*(w/2-.07),h*.47,0,colors.sage);
 }else if(it.category==='rug'){
  box(g,w,.012,d,0,.012,0,0xdacabd);for(let n=0;n<4;n++)box(g,w*.9,.003,.018,0,.022,(n-1.5)*d*.18,0xc7b5a3);
 }else if(['bookshelf','shelf'].includes(it.category)){
  box(g,w,h,.035,0,h/2,-d/2+.02,colors.lightWood);for(const x of [-1,1])box(g,.04,h,d,x*(w/2-.02),h/2,0,colors.wood);
  for(let n=0;n<4;n++){const y=.07+n*(h-.13)/3;box(g,w,.035,d,0,y,0,colors.wood);if(n<3){for(let k=0;k<3;k++)box(g,.08,.22,d*.5,-w*.3+k*.12,y+.13,0,k%2?colors.sage:colors.rust)}}
 }else{
  box(g,w,h,d,0,h/2,0,it.category==='nightstand'?colors.lightWood:0xd4d8c9);
  const parts=w>1?2:1;for(let n=0;n<parts;n++){const x=parts===1?0:(n-.5)*w/2;box(g,w/parts-.026,h-.02,.014,x,h/2,d/2+.008,0xe5e5da);box(g,.012,.14,.018,x+(parts===1?w*.25:(n?-.04:.04)),h*.53,d/2+.03,colors.wood)}
 }
 return g;
}
function dispose(g:THREE.Object3D){g.traverse(o=>{if(o instanceof THREE.Mesh||o instanceof THREE.LineSegments||o instanceof THREE.Line){o.geometry.dispose();const ms=Array.isArray(o.material)?o.material:[o.material];ms.forEach(m=>m.dispose())}})}

export default function SceneView(props:Props){
 const host=useRef<HTMLDivElement>(null),headMarker=useRef<HTMLDivElement>(null);const latest=useRef(props);latest.current=props;
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
  let drag:{id:string;offset:THREE.Vector3;origin:THREE.Vector3;moved:boolean}|null=null;
  const ray=new THREE.Raycaster(),pointer=new THREE.Vector2(),plane=new THREE.Plane(new THREE.Vector3(0,1,0),0);
  function cast(e:PointerEvent){const b=renderer.domElement.getBoundingClientRect();pointer.set((e.clientX-b.left)/b.width*2-1,-(e.clientY-b.top)/b.height*2+1);ray.setFromCamera(pointer,latest.current.top?ortho:camera)}
  function down(e:PointerEvent){if(e.button!==0)return;cast(e);const hits=ray.intersectObjects(itemsGroup.children,true);if(!hits.length){latest.current.onSelect(null);return}let o:THREE.Object3D|null=hits[0].object;while(o&&!o.userData.itemId)o=o.parent;if(!o)return;const id=o.userData.itemId as string;latest.current.onSelect(id);const it=latest.current.scene.items.find(x=>x.id===id);if(latest.current.editable===false||!it||it.locked)return;const pt=new THREE.Vector3();if(ray.ray.intersectPlane(plane,pt)){drag={id,offset:pt.clone().sub(o.position),origin:o.position.clone(),moved:false};orbit.enabled=false;renderer.domElement.setPointerCapture(e.pointerId);renderer.domElement.style.cursor='grabbing'}}
  function move(e:PointerEvent){if(!drag)return;cast(e);const pt=new THREE.Vector3();if(!ray.ray.intersectPlane(plane,pt))return;const g=groups.get(drag.id);if(!g)return;pt.sub(drag.offset);const r=latest.current.scene.room;g.position.x=THREE.MathUtils.clamp(pt.x,-1,r.width+1);g.position.z=THREE.MathUtils.clamp(pt.z,-1,r.depth+1);drag.moved=drag.origin.distanceTo(g.position)>.015}
  function up(){if(!drag)return;const current=drag;drag=null;const g=groups.get(current.id);orbit.enabled=!latest.current.top;renderer.domElement.style.cursor='';if(g&&current.moved)latest.current.onMove(current.id,Math.round(g.position.x*100)/100,Math.round(g.position.z*100)/100)}
  renderer.domElement.addEventListener('pointerdown',down);renderer.domElement.addEventListener('pointermove',move);renderer.domElement.addEventListener('pointerup',up);renderer.domElement.addEventListener('pointercancel',up);
  let raf=0;const animate=()=>{raf=requestAnimationFrame(animate);orbit.enabled=!latest.current.top&&!drag;orbit.update();const activeCamera=latest.current.top?ortho:camera;renderer.render(world,activeCamera);const bed=latest.current.scene.items.find(item=>item.id===latest.current.selectedId&&['double_bed','single_bed','kids_bed'].includes(item.category));const marker=headMarker.current;if(marker&&bed){const g=groups.get(bed.id),angle=THREE.MathUtils.degToRad(bed.rotation);const head=new THREE.Vector3((g?.position.x??bed.x)-Math.sin(angle)*bed.depth/2,bed.height+.22,(g?.position.z??bed.z)-Math.cos(angle)*bed.depth/2).project(activeCamera);marker.style.left=`${(head.x+1)*div.clientWidth/2}px`;marker.style.top=`${(1-head.y)*div.clientHeight/2}px`;marker.style.visibility=Math.abs(head.x)<1&&Math.abs(head.y)<1&&head.z>=-1&&head.z<=1?'visible':'hidden'}};animate();
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
   const g=furniture(it);g.position.set(it.x,0,it.z);g.rotation.y=THREE.MathUtils.degToRad(it.rotation);rt.itemsGroup.add(g);rt.groups.set(it.id,g);
   if(it.assetUrl)loader.load(it.assetUrl,glb=>{if(cancelled){dispose(glb.scene);return}const a=glb.scene;const b=new THREE.Box3().setFromObject(a),s=b.getSize(new THREE.Vector3()),c=b.getCenter(new THREE.Vector3());if(Math.min(s.x,s.y,s.z)<.0001){dispose(a);return}a.position.set(-c.x,-b.min.y,-c.z);const wrapper=new THREE.Group();wrapper.add(a);wrapper.scale.set(it.width/s.x,it.height/s.y,it.depth/s.z);wrapper.traverse(o=>{if(o instanceof THREE.Mesh){o.castShadow=true;o.receiveShadow=true}});dispose(g);g.clear();g.add(wrapper)},undefined,()=>{/* Keep procedural fallback on unreadable asset. */});
  });return()=>{cancelled=true};
 },[props.scene.items]);
 useEffect(()=>{const rt=runtime.current;if(!rt)return;dispose(rt.highlight);rt.highlight.clear();const bad=new Set(props.validation?.issues.filter(x=>x.severity==='error').flatMap(x=>x.itemIds||[])||[]);for(const it of props.scene.items){if(it.id!==props.selectedId&&!bad.has(it.id))continue;const geo=new THREE.EdgesGeometry(new THREE.BoxGeometry(it.width+.05,Math.max(.045,it.height+.05),it.depth+.05));const lines=new THREE.LineSegments(geo,new THREE.LineBasicMaterial({color:bad.has(it.id)?0xc6604c:0x478371}));lines.position.set(it.x,it.height/2,it.z);lines.rotation.y=THREE.MathUtils.degToRad(it.rotation);rt.highlight.add(lines)}for(const preference of props.scene.preferences){if(preference.kind!=='face_window')continue;const it=props.scene.items.find(item=>item.id===preference.itemId);if(!it)continue;const angle=THREE.MathUtils.degToRad(it.rotation),direction=new THREE.Vector3(Math.sin(angle),0,Math.cos(angle));const arrow=new THREE.ArrowHelper(direction,new THREE.Vector3(it.x,Math.max(.12,it.height+.1),it.z),Math.max(.55,it.depth*.85),0x386a8d,.14,.09);rt.highlight.add(arrow)}},[props.scene.items,props.scene.preferences,props.selectedId,props.validation]);
 useEffect(()=>{runtime.current?.fit()},[props.scene.room.width,props.scene.room.depth,props.top]);
 const selectedBed=props.scene.items.find(item=>item.id===props.selectedId&&['double_bed','single_bed','kids_bed'].includes(item.category));
 const headMetadata=selectedBed?{itemId:selectedBed.id,localDirection:'-z',rightLocalDirection:'+x',reference:'站在床尾看床头',x:selectedBed.x-Math.sin(selectedBed.rotation*Math.PI/180)*selectedBed.depth/2,z:selectedBed.z-Math.cos(selectedBed.rotation*Math.PI/180)*selectedBed.depth/2}:undefined;
 return <div ref={host} className="scene-canvas" data-testid="scene-canvas" data-layout={JSON.stringify(props.scene.items.map(it=>[it.id,it.x,it.z,it.rotation]))} data-bed-head={headMetadata?JSON.stringify(headMetadata):undefined}>{selectedBed&&<div ref={headMarker} className="bed-head-marker" data-testid="bed-head-marker" title="枕头和床头板所在的一端；左右按站在床尾看床头判断">床头<span>左右：站在床尾看床头</span></div>}</div>;
}
