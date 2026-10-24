import * as THREE from 'three';
import type {Item,FurnitureParameters} from './types';

const colors={wood:0xb28c65,lightWood:0xd8cbb7,cream:0xf1ece2,dark:0x596159,sage:0x82a28a,rust:0xba826b};
export function box(g:THREE.Group,w:number,h:number,d:number,x:number,y:number,z:number,color:number,radius=0){
 const m=new THREE.Mesh(new THREE.BoxGeometry(Math.max(.005,w),Math.max(.005,h),Math.max(.005,d)),new THREE.MeshStandardMaterial({color,roughness:.78}));m.position.set(x,y,z);m.castShadow=true;m.receiveShadow=true;g.add(m);return m;
}
function legs(g:THREE.Group,w:number,d:number,h:number){for(const x of [-1,1])for(const z of [-1,1])box(g,.045,h,.045,x*(w/2-.07),h/2,z*(d/2-.07),colors.dark)}

export function parameterKeys(category:string|null): (keyof FurnitureParameters)[]{
 const keys:(keyof FurnitureParameters)[]=['primaryColor','secondaryColor','material'];
 if(['chair','armchair','dressing_chair','stool','sofa'].includes(category||''))keys.push('hasBack','hasArms','hasLegs','seatHeightRatio');
 if(category==='sofa')keys.push('seatCount');
 if(['desk','table','coffee_table','dressing_table','cabinet','wardrobe','nightstand','tv_stand','children_cabinet'].includes(category||''))keys.push('hasLegs','drawerCount');
 if(['cabinet','wardrobe','nightstand','tv_stand','children_cabinet'].includes(category||''))keys.push('doorCount');
 if(['shelf','bookshelf'].includes(category||''))keys.push('shelfCount');
 return keys;
}

export function resetCategoryParameters(category:string|null,parameters:FurnitureParameters):FurnitureParameters{
 const result={...parameters};const allowed=parameterKeys(category);
 for(const key of Object.keys(result) as (keyof FurnitureParameters)[])if(!allowed.includes(key))Object.assign(result,{[key]:null});
 return result;
}

export function disposeFurniture(group:THREE.Object3D){
 group.traverse(object=>{if(object instanceof THREE.Mesh){object.geometry.dispose();const materials=Array.isArray(object.material)?object.material:[object.material];materials.forEach(material=>material.dispose())}});
}

export function createFurniture(item:Item,parameters?:FurnitureParameters):THREE.Group{
 const params=parameters||item.furnitureSnapshot?.parameters;
 if(!params)return legacyFurniture(item);
 const raw=new THREE.Group();const {width,depth,height,category}=item;
 const primary=new THREE.Color(params.primaryColor||'#b28c65').getHex();
 const secondary=new THREE.Color(params.secondaryColor||'#e8e2d6').getHex();
 const part=(partWidth:number,partHeight:number,partDepth:number,posX:number,posY:number,posZ:number,color=primary)=>box(raw,partWidth,partHeight,partDepth,posX,posY,posZ,color);
 const feet=(top:number)=>{for(const side of [-1,1])for(const front of [-1,1])part(width*.065,top,depth*.065,side*width*.4,top/2,front*depth*.4,secondary)};
 if(category.includes('bed')){
  part(width,height*.25,depth,0,height*.125,0);part(width*.97,height*.35,depth*.96,0,height*.425,0,secondary);
  part(width,height,.06*depth,0,height/2,-depth*.47);
  for(const side of width>1.3?[-1,1]:[0])part(width*(side===0?.7:.4),height*.15,depth*.2,side*width*.24,height*.67,-depth*.32,secondary);
 }else if(['chair','armchair','dressing_chair','stool','sofa'].includes(category)){
  const seat=height*(params.seatHeightRatio??(category==='sofa'?.4:.5));
  if(params.hasLegs!==false)feet(seat);else part(width*.85,seat,depth*.85,0,seat/2,0,secondary);
  part(width,height*.08,depth,0,seat,0);
  if(params.hasBack??category!=='stool')part(width,Math.max(height*.1,height-seat),depth*.1,0,(height+seat)/2,-depth*.45);
  if(params.hasArms??['armchair','sofa'].includes(category))for(const side of [-1,1])part(width*.08,height*.3,depth,side*width*.46,seat+height*.15,0);
  if(category==='sofa'){const seats=params.seatCount??3;for(let index=0;index<seats;index++)part(width*.8/seats,height*.07,depth*.78,((index+.5)/seats-.5)*width*.85,seat+height*.07,depth*.04,secondary)}
 }else if(['desk','table','coffee_table','dressing_table'].includes(category)){
  const top=category==='dressing_table'?height*.57:height;
  if(params.hasLegs!==false)feet(top*.94);else part(width*.6,top*.94,depth*.7,0,top*.47,0,secondary);
  part(width,top*.06,depth,0,top*.97,0);
  const drawers=params.drawerCount??(category==='desk'?3:0);
  if(drawers)for(let index=0;index<drawers;index++)part(width*.28,top*.65/drawers,depth*.8,width*.32,top*.22+(index+.5)*top*.65/drawers,0,secondary);
  if(category==='dressing_table')part(width*.55,height*.4,depth*.04,0,height*.8,-depth*.4,secondary);
 }else if(['shelf','bookshelf'].includes(category)){
  part(width,height,depth*.06,0,height/2,-depth*.47,secondary);
  for(const side of [-1,1])part(width*.045,height,depth,side*width*.4775,height/2,0);
  const shelves=params.shelfCount??4;
  for(let index=0;index<shelves;index++)part(width,height*.025,depth,0,(index+.5)*height/shelves,0);
 }else if(category==='rug'){
  part(width,height,depth,0,height/2,0);
 }else{
  const base=params.hasLegs?height*.12:0;
  if(base)feet(base);
  part(width,height-base,depth*.93,0,(height+base)/2,-depth*.035);
  const drawers=params.drawerCount??(category==='nightstand'?2:0),doors=params.doorCount??(drawers?0:width>1?2:1);
  const drawerHeight=drawers?(height-base)*(doors?.35:1):0;
  for(let index=0;index<drawers;index++){
   const center=height-(index+.5)*drawerHeight/drawers;
   part(width*.97,drawerHeight/drawers*.93,depth*.04,0,center,depth*.48,secondary);
   part(width*.12,height*.012,depth*.025,0,center,depth*.5125);
  }
  for(let index=0;index<doors;index++){
   const center=((index+.5)/doors-.5)*width;
   part(width/doors*.96,height-base-drawerHeight,depth*.04,center,(height+base-drawerHeight)/2,depth*.48,secondary);
   part(width*.015,height*.1,depth*.025,center+width/doors*.3,(height+base-drawerHeight)/2,depth*.5125);
  }
 }
 raw.traverse(object=>{if(object instanceof THREE.Mesh){const material=object.material as THREE.MeshStandardMaterial;material.roughness=params.material==='metal'?.3:params.material==='leather'?.5:.8;material.metalness=params.material==='metal'?.65:0}});
 const bounds=new THREE.Box3().setFromObject(raw),size=bounds.getSize(new THREE.Vector3()),center=bounds.getCenter(new THREE.Vector3());
 raw.position.set(-center.x,-bounds.min.y,-center.z);
 const wrapper=new THREE.Group();wrapper.add(raw);wrapper.scale.set(width/size.x,height/size.y,depth/size.z);
 const group=new THREE.Group();group.add(wrapper);group.userData.itemId=item.id;
 return group;
}

export async function exportFurnitureGLB(item:Item):Promise<Blob>{
 const group=createFurniture(item);
 group.traverse(object=>{delete object.userData.itemId});
 try{const {GLTFExporter}=await import('three/addons/exporters/GLTFExporter.js');const result=await new GLTFExporter().parseAsync(group,{binary:true});if(!(result instanceof ArrayBuffer))throw new Error('GLB导出未生成二进制文件');return new Blob([result],{type:'model/gltf-binary'})}
 finally{disposeFurniture(group)}
}
function legacyFurniture(it:Item):THREE.Group{
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

