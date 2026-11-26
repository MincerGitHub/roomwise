import * as THREE from 'three';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';
import {createFurniture,displayFurnitureVertexColors} from './furnitureMesh';
import type {Item} from './types';

export type ModelState={id:string;label:string;status:'loading'|'loaded'|'error'|'procedural'};
type Entry={item:Item;key:string;root:THREE.Group;content:THREE.Group;size:THREE.Vector3;state:ModelState['status']};

function release(object:THREE.Object3D){
 const geometries=new Set<THREE.BufferGeometry>(),materials=new Set<THREE.Material>(),textures=new Set<THREE.Texture>();
 object.traverse(child=>{
  if(!(child instanceof THREE.Mesh||child instanceof THREE.LineSegments))return;
  geometries.add(child.geometry);
  for(const material of Array.isArray(child.material)?child.material:[child.material]){
   materials.add(material);
   for(const value of Object.values(material))if(value instanceof THREE.Texture)textures.add(value);
  }
 });
 textures.forEach(texture=>texture.dispose());materials.forEach(material=>material.dispose());geometries.forEach(geometry=>geometry.dispose());
}

function outline(){
 const group=new THREE.Group(),geometry=new THREE.BoxGeometry(1,1,1);
 const pickable=new THREE.Mesh(geometry,new THREE.MeshBasicMaterial({color:0x879a82,transparent:true,opacity:.035,depthWrite:false}));
 pickable.position.y=.5;group.add(pickable);
 const edges=new THREE.LineSegments(new THREE.EdgesGeometry(geometry),new THREE.LineBasicMaterial({color:0x879a82,transparent:true,opacity:.65}));
 edges.position.y=.5;edges.raycast=()=>{};group.add(edges);
 return group;
}

/** Keep each model alive through pose/size edits; only a source change reloads. */
export class FurnitureObjects{
 readonly groups=new Map<string,THREE.Group>();
 private entries=new Map<string,Entry>();
 private loader=new GLTFLoader();
 private stateKey='';
 constructor(private parent:THREE.Group,private changed:(states:ModelState[])=>void){}

 private notify(){
  const states=[...this.entries].map(([id,entry])=>({id,label:entry.item.label,status:entry.state}));
  const key=JSON.stringify(states);
  if(key!==this.stateKey){this.stateKey=key;this.changed(states)}
 }

 private pose(entry:Entry){
  const {item,root,content,size}=entry;
  root.position.set(item.x,item.y??0,item.z);root.rotation.y=THREE.MathUtils.degToRad(item.rotation);
  if(item.assetUrl)content.scale.set(item.width/size.x,item.height/size.y,item.depth/size.z);
 }

 private remove(id:string){
  const entry=this.entries.get(id);if(!entry)return;
  this.entries.delete(id);this.groups.delete(id);this.parent.remove(entry.root);release(entry.root);
 }

 sync(items:Item[]){
  const ids=new Set(items.map(item=>item.id));
  for(const id of this.entries.keys())if(!ids.has(id))this.remove(id);
  for(const item of items){
   const key=item.assetUrl?`glb:${item.assetUrl}`:JSON.stringify([item.category,item.width,item.depth,item.height,item.furnitureSnapshot?.parameters]);
   let entry=this.entries.get(item.id);
   if(entry&&entry.key!==key){this.remove(item.id);entry=undefined}
   if(entry){entry.item=item;this.pose(entry);continue}
   const root=new THREE.Group();root.userData.itemId=item.id;
   const content=item.assetUrl?outline():createFurniture(item);
   root.add(content);this.parent.add(root);this.groups.set(item.id,root);
   entry={item,key,root,content,size:new THREE.Vector3(1,1,1),state:item.assetUrl?'loading':'procedural'};
   this.entries.set(item.id,entry);this.pose(entry);
   if(!item.assetUrl)continue;
   const pending=entry;
   const failed=()=>{
    if(this.entries.get(item.id)!==pending)return;
    pending.state='error';this.notify();
   };
   this.loader.load(item.assetUrl,glb=>{
    if(this.entries.get(item.id)!==pending){release(glb.scene);return}
    const model=glb.scene,bounds=new THREE.Box3().setFromObject(model),size=bounds.getSize(new THREE.Vector3());
    if(!size.toArray().every(value=>Number.isFinite(value)&&value>=.0001)){release(model);failed();return}
    displayFurnitureVertexColors(model);
    const center=bounds.getCenter(new THREE.Vector3());model.position.set(-center.x,-bounds.min.y,-center.z);
    release(pending.content);pending.root.remove(pending.content);
    const wrapper=new THREE.Group();wrapper.add(model);pending.root.add(wrapper);
    pending.content=wrapper;pending.size=size;pending.state='loaded';
    this.pose(pending);this.notify();
   },undefined,failed);
  }
  this.notify();
 }

 retry(){
  const items=[...this.entries.values()].map(entry=>entry.item);
  for(const [id,entry] of this.entries)if(entry.state==='error')this.remove(id);
  this.sync(items);
 }

 isLoaded(id:string){return this.entries.get(id)?.state==='loaded'}

 dispose(){for(const id of this.entries.keys())this.remove(id)}
}
