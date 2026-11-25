import type {Item,Scene} from './types';
import {surfacePlacement,isSurface} from './surfacePlacement';
import {wallPlacement,isWallMounted} from './wallPlacement';

export function initialAppliancePlacement(item:Item,scene:Scene):Partial<Item>{
 if(isWallMounted(item)){
  const y=item.category==='air_conditioner'?scene.room.height-item.height-.2:Math.min(.95,scene.room.height-item.height-.2);
  return {...wallPlacement({...item,y:Math.max(.1,y),rotation:180},scene.room.width/2,scene.room.depth,scene.room,undefined,item.category==='air_conditioner'?.1:0)?.placement,locked:false};
 }
 if(item.category==='laptop'){
  for(const target of scene.items.filter(isSurface)){
   const pose=surfacePlacement(item,target.x,target.z,scene);
   if(pose.supportId)return pose;
  }
 }
 return {};
}
