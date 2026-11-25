import * as THREE from 'three';
import type {Item,Room,Wall} from './types';
import {wallPlacement} from './wallPlacement';

export type WallDrag={item:Item;wall:Wall;grabAlong:number;grabY:number};
const walls:Wall[]=['south','west','north','east'];
const normal=(rotation:number)=>new THREE.Vector3(Math.sin(rotation*Math.PI/180),0,Math.cos(rotation*Math.PI/180));
const tangent=(rotation:number)=>new THREE.Vector3(Math.cos(rotation*Math.PI/180),0,-Math.sin(rotation*Math.PI/180));

function intersect(ray:THREE.Ray,rotation:number,x:number,z:number){
 const n=normal(rotation);
 if(Math.abs(ray.direction.dot(n))<.04)return null;
 return ray.intersectPlane(new THREE.Plane().setFromNormalAndCoplanarPoint(n,new THREE.Vector3(x,0,z)),new THREE.Vector3());
}

/** Record the grabbed point in wall coordinates so the model follows the pointer. */
export function beginWallDrag(item:Item,ray:THREE.Ray,room:Room):WallDrag|null{
 const snap=wallPlacement(item,item.x,item.z,room);
 if(!snap)return null;
 const point=intersect(ray,snap.placement.rotation,item.x,item.z);
 if(!point)return null;
 const relative=point.sub(new THREE.Vector3(item.x,item.y??0,item.z));
 return {item:{...item},wall:snap.wall,grabAlong:relative.dot(tangent(snap.placement.rotation)),grabY:relative.y};
}

/** Move on vertical wall planes, switching faces as the pointer crosses a corner. */
export function moveWallDrag(drag:WallDrag,ray:THREE.Ray,room:Room){
 const candidates=[];
 for(const wall of walls){
  const anchor=wallPlacement(drag.item,drag.item.x,drag.item.z,room,wall);
  if(!anchor)continue;
  const {rotation,x,z}=anchor.placement,n=normal(rotation);
  // New walls must face the pointer ray from the room side. This prevents the
  // front boundary, drawn low for visibility, from stealing a rear-wall drag.
  if(wall!==drag.wall&&ray.direction.dot(n)>=-.04)continue;
  const point=intersect(ray,rotation,x,z);
  if(!point)continue;
  point.addScaledVector(tangent(rotation),-drag.grabAlong);
  const proposed=wallPlacement({...drag.item,y:point.y-drag.grabY},point.x,point.z,room,wall);
  if(!proposed)continue;
  const overflow=Math.hypot(proposed.placement.x-point.x,proposed.placement.z-point.z,proposed.placement.y-(point.y-drag.grabY));
  // Pointer projections beyond a wall end should pick an adjacent face.
  const score=overflow*10+point.distanceTo(ray.origin)*.001-(wall===drag.wall?.06:0);
  candidates.push({score,...proposed});
 }
 candidates.sort((a,b)=>a.score-b.score);
 const best=candidates[0];
 if(!best)return null;
 drag.wall=best.wall;drag.item={...drag.item,...best.placement};
 return best;
}
