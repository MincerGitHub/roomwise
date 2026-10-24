import {useEffect,useRef,useState} from 'react';
import * as THREE from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import type {Item} from './types';
import {createFurniture,disposeFurniture} from './furnitureMesh';

export default function FurniturePreview({item}:{item:Item|null}){
 const host=useRef<HTMLDivElement>(null);const [error,setError]=useState('');
 useEffect(()=>{
  const target=host.current;if(!target||!item)return;
  let renderer:THREE.WebGLRenderer;
  try{renderer=new THREE.WebGLRenderer({antialias:true})}catch{setError('当前浏览器无法显示三维预览，仍可保存草稿。');return}
  setError('');renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));target.appendChild(renderer.domElement);
  const scene=new THREE.Scene();scene.background=new THREE.Color('#f0f2ec');
  const model=createFurniture(item);scene.add(model);
  const bounds=new THREE.Box3().setFromObject(model),size=bounds.getSize(new THREE.Vector3());
  target.dataset.bounds=JSON.stringify({width:size.x,height:size.y,depth:size.z,minY:bounds.min.y});
  const camera=new THREE.PerspectiveCamera(38,1,.001,1000);const span=Math.max(item.width,item.depth,item.height);
  camera.position.set(span*1.8,item.height*.5+span,span*2);
  const orbit=new OrbitControls(camera,renderer.domElement);orbit.target.set(0,item.height*.5,0);orbit.enableDamping=true;
  scene.add(new THREE.HemisphereLight(0xffffff,0x6a7565,2.5));const light=new THREE.DirectionalLight(0xffffff,2);light.position.set(3,6,4);scene.add(light);
  const resize=()=>{const width=target.clientWidth||400,height=target.clientHeight||300;renderer.setSize(width,height);camera.aspect=width/height;camera.updateProjectionMatrix()};
  const observer=new ResizeObserver(resize);observer.observe(target);resize();
  let frame=0;const render=()=>{orbit.update();renderer.render(scene,camera);frame=requestAnimationFrame(render)};render();
  return()=>{cancelAnimationFrame(frame);observer.disconnect();orbit.dispose();disposeFurniture(model);renderer.dispose();renderer.forceContextLoss();renderer.domElement.remove()};
 },[item]);
 return <div className="furniture-preview" ref={host} aria-label="家具参数化三维预览">{!item&&<p>补全类别和宽深高后显示预览。</p>}{error&&<p role="alert">{error}</p>}</div>;
}
