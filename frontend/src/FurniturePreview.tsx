import {useEffect,useRef,useState} from 'react';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import type {Item} from './types';
import {FurnitureObjects,type ModelState} from './furnitureObjects';
import ModelLoading from './ModelLoading';

export default function FurniturePreview({item,onModelLoaded}:{item:Item|null;onModelLoaded?:(loaded:boolean)=>void}){
 const host=useRef<HTMLDivElement>(null);const [error,setError]=useState(''),[models,setModels]=useState<ModelState[]>([]);
 const runtime=useRef<{furniture:FurnitureObjects;camera:THREE.PerspectiveCamera;orbit:OrbitControls}|null>(null);
 const hasItem=!!item;
 useEffect(()=>{
  const target=host.current;if(!target||!item){setModels([]);return}
  let renderer:THREE.WebGLRenderer;
  try{renderer=new THREE.WebGLRenderer({antialias:true})}catch{setError('无法显示三维预览。');return}
  setError('');renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));target.appendChild(renderer.domElement);
  const scene=new THREE.Scene();scene.background=new THREE.Color('#f0f2ec');
  const objects=new THREE.Group();scene.add(objects);const furniture=new FurnitureObjects(objects,setModels);
  const camera=new THREE.PerspectiveCamera(38,1,.001,1000);const span=Math.max(item.width,item.depth,item.height);
  camera.position.set(span*1.8,item.height*.5+span,span*2);
  const orbit=new OrbitControls(camera,renderer.domElement);orbit.target.set(0,item.height*.5,0);orbit.enableDamping=true;
  runtime.current={furniture,camera,orbit};
  scene.add(new THREE.HemisphereLight(0xffffff,0x6a7565,2.5));const light=new THREE.DirectionalLight(0xffffff,2);light.position.set(3,6,4);scene.add(light);
  const resize=()=>{const width=target.clientWidth||400,height=target.clientHeight||300;renderer.setSize(width,height);camera.aspect=width/height;camera.updateProjectionMatrix()};
  const observer=new ResizeObserver(resize);observer.observe(target);resize();
  let frame=0;const render=()=>{orbit.update();renderer.render(scene,camera);frame=requestAnimationFrame(render)};render();
  return()=>{cancelAnimationFrame(frame);observer.disconnect();orbit.dispose();furniture.dispose();renderer.dispose();renderer.forceContextLoss();renderer.domElement.remove();runtime.current=null};
 },[hasItem]);
 useEffect(()=>{
  const rt=runtime.current;if(!rt||!item)return;
  rt.furniture.sync([{...item,x:0,z:0,y:0,rotation:0}]);
  const span=Math.max(item.width,item.depth,item.height);
  rt.camera.position.set(span*1.8,item.height*.5+span,span*2);rt.orbit.target.set(0,item.height*.5,0);rt.orbit.update();
  if(host.current)host.current.dataset.bounds=JSON.stringify({width:item.width,height:item.height,depth:item.depth,minY:0});
 },[item]);
 useEffect(()=>{onModelLoaded?.(!!item&&!!runtime.current?.furniture.isLoaded(item.id))},[item,models,onModelLoaded]);
 return <div className="furniture-preview" ref={host} aria-label="家具三维预览" data-models={JSON.stringify(models)}>{!item&&<p>填写类别和尺寸后预览。</p>}{item&&<ModelLoading states={models} retry={()=>runtime.current?.furniture.retry()}/>}{error&&<p role="alert">{error}</p>}</div>;
}
