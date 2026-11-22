import {useEffect,useState} from 'react';
import * as THREE from 'three';
import {createFurniture,disposeFurniture} from './furnitureMesh';
import type {Item} from './types';

let renderer:THREE.WebGLRenderer|undefined;
const cache=new Map<string,string>();
function thumbnail(item:Item) {
 const key=JSON.stringify([item.category,item.width,item.height,item.depth,item.furnitureSnapshot?.parameters]);
 const previous=cache.get(key);if(previous)return previous;
 renderer??=new THREE.WebGLRenderer({antialias:true,alpha:true});
 renderer.setSize(160,120,false);
 const scene=new THREE.Scene(),model=createFurniture(item);
 try {
  scene.add(model,new THREE.HemisphereLight(0xffffff,0xc6b6a5,2));
  const light=new THREE.DirectionalLight(0xffffff,2);light.position.set(2,4,3);scene.add(light);
  const bounds=new THREE.Box3().setFromObject(model),center=bounds.getCenter(new THREE.Vector3());
  const radius=Math.max(.01,bounds.getBoundingSphere(new THREE.Sphere()).radius);
  const camera=new THREE.OrthographicCamera(-radius*1.34,radius*1.34,radius,-radius,.001,radius*10);
  camera.position.copy(center).add(new THREE.Vector3(1,.72,1.35).normalize().multiplyScalar(radius*4));camera.lookAt(center);
  renderer.render(scene,camera);
  const url=renderer.domElement.toDataURL('image/png');
  if(cache.size>=128)cache.delete(cache.keys().next().value!);
  cache.set(key,url);return url;
 } finally {disposeFurniture(model)}
}
export default function FurnitureThumb({item}:{item:Item}) {
 const [src,setSrc]=useState('');
 const [failedPhoto,setFailedPhoto]=useState('');
 const photo=item.photoUrl&&item.photoUrl!==failedPhoto?item.photoUrl:'';
 useEffect(()=>{if(!photo){try{setSrc(thumbnail(item))}catch{setSrc('')}}},[item,photo]);
 return photo||src?<img src={photo||src} alt="" onError={()=>{if(photo)setFailedPhoto(photo)}}/>:<span aria-hidden="true">{item.label.slice(0,1)}</span>;
}
