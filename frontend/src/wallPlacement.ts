import type {Item,Room,Wall} from './types';
import {overlapsWindow,windowHeights} from './windowGeometry';

export const isWallMounted=(item:Item)=>['wall_tv','air_conditioner'].includes(item.category);
const gap=.02,edge=.03,round=(value:number)=>Math.round(value*100000)/100000;
const clamp=(value:number,min:number,max:number)=>Math.max(min,Math.min(max,value));

/** Project a wall appliance to the nearest real cardinal wall segment. */
export function wallPlacement(item:Item,x:number,z:number,room:Room,requestedWall?:Wall,ceilingMargin=0){
 const polygon=room.polygon?.length?room.polygon:[[0,0],[room.width,0],[room.width,room.depth],[0,room.depth]];
 const options:{wall:Wall;distance:number;placement:{x:number;z:number;y:number;rotation:number;supportId:null}}[]=[];
 for(let index=0;index<polygon.length;index++){
  const a=polygon[index],b=polygon[(index+1)%polygon.length];
  let wall:Wall;
  if(Math.abs(a[1])<1e-6&&Math.abs(b[1])<1e-6)wall='south';
  else if(Math.abs(a[1]-room.depth)<1e-6&&Math.abs(b[1]-room.depth)<1e-6)wall='north';
  else if(Math.abs(a[0])<1e-6&&Math.abs(b[0])<1e-6)wall='west';
  else if(Math.abs(a[0]-room.width)<1e-6&&Math.abs(b[0]-room.width)<1e-6)wall='east';
  else continue;
  if(requestedWall&&wall!==requestedWall)continue;
  const horizontal=wall==='north'||wall==='south',axis=horizontal?0:1;
  const min=Math.min(a[axis],b[axis])+item.width/2+edge,max=Math.max(a[axis],b[axis])-item.width/2-edge;
  if(min>max||item.depth+gap>Math.min(room.width,room.depth))continue;
  const highest=room.height-item.height-ceilingMargin;
  if(highest<.1)continue;
  const along=clamp(horizontal?x:z,min,max),normal=item.depth/2+gap;
  const rotation={south:0,west:90,north:180,east:270}[wall];
  const y=clamp(item.y??.1,.1,highest);
  const windows=room.windows.filter(window=>window.wall===wall),alongOptions=[along],heightOptions=[y];
  for(const window of windows){
   const span=windowHeights(window,room);
   alongOptions.push(clamp(window.offset-item.width/2-.03,min,max),clamp(window.offset+window.width+item.width/2+.03,min,max));
   heightOptions.push(clamp(span.bottom-item.height-.03,.1,highest),clamp(span.top+.03,.1,highest));
  }
  const free=[];
  for(const a of alongOptions)for(const h of heightOptions){
   if(windows.some(window=>overlapsWindow(a,h,item.width,item.height,window,room,.02)))continue;
   free.push({along:a,y:h,distance:Math.hypot(a-along,h-y)});
  }
  free.sort((a,b)=>a.distance-b.distance);
  const chosen=free[0];if(!chosen)continue;
  const px=horizontal?chosen.along:wall==='west'?normal:room.width-normal;
  const pz=horizontal?(wall==='south'?normal:room.depth-normal):chosen.along;
  // A small preference for the current face prevents corner jitter.
  const preference=Math.abs(((item.rotation-rotation)%360+540)%360-180)<1?-.04:0;
  options.push({wall,distance:Math.hypot(px-x,pz-z,chosen.y-y)+preference,
                placement:{x:round(px),z:round(pz),y:round(chosen.y),rotation,supportId:null}});
 }
 options.sort((a,b)=>a.distance-b.distance);
 return options[0]??null;
}
