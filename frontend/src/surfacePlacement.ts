import type {Item,Room,Scene} from './types';

const surfaces=new Set(['desk','table','coffee_table','nightstand','tv_stand','cabinet','children_cabinet']);
export const edgeMargin=.03;
export type Placement={x:number;z:number;y:number;supportId:string|null};
export const baseY=(item:Item)=>item.y??0;
export const isSurface=(item:Item)=>surfaces.has(item.category)&&!item.supportId&&baseY(item)===0&&item.height<=1.5;
const radians=(degrees:number)=>degrees*Math.PI/180;
const round=(value:number)=>Math.round(value*100000)/100000;
function local(item:Item,x:number,z:number){const a=radians(item.rotation),dx=x-item.x,dz=z-item.z;return {x:Math.cos(a)*dx-Math.sin(a)*dz,z:Math.sin(a)*dx+Math.cos(a)*dz}}
function world(item:Item,x:number,z:number){const a=radians(item.rotation);return {x:item.x+Math.cos(a)*x+Math.sin(a)*z,z:item.z-Math.sin(a)*x+Math.cos(a)*z}}
function corners(item:Item){return [-1,1].flatMap(sx=>[-1,1].map(sz=>world(item,sx*item.width/2,sz*item.depth/2)))}
export function fitsSurface(item:Item,target:Item){
 return item.category==='storage_box'&&item.height<=.6&&isSurface(target)&&corners(item).every(point=>{const p=local(target,point.x,point.z);return Math.abs(p.x)<=target.width/2-edgeMargin+.00001&&Math.abs(p.z)<=target.depth/2-edgeMargin+.00001});
}
function overlap(a:Item,b:Item){
 const ac=corners(a),bc=corners(b);
 return [a,b].every(item=>{const angle=radians(item.rotation);return [[Math.cos(angle),-Math.sin(angle)],[Math.sin(angle),Math.cos(angle)]].every(([x,z])=>{
  const av=ac.map(p=>p.x*x+p.z*z),bv=bc.map(p=>p.x*x+p.z*z);
  return Math.max(...av)>Math.min(...bv)+.00001&&Math.max(...bv)>Math.min(...av)+.00001;
 })});
}
function inRoom(item:Item,room:Room){
 const polygon=room.polygon?.length?room.polygon:[[0,0],[room.width,0],[room.width,room.depth],[0,room.depth]];
 const cross=(ax:number,az:number,bx:number,bz:number,cx:number,cz:number)=>(bx-ax)*(cz-az)-(bz-az)*(cx-ax);
 const inside=(x:number,z:number)=>{let yes=false;for(let i=0,j=polygon.length-1;i<polygon.length;j=i++){
  const [ax,az]=polygon[i],[bx,bz]=polygon[j];
  if(Math.abs(cross(ax,az,bx,bz,x,z))<.0000001&&x>=Math.min(ax,bx)&&x<=Math.max(ax,bx)&&z>=Math.min(az,bz)&&z<=Math.max(az,bz))return true;
  if((az>z)!==(bz>z)&&x<(bx-ax)*(z-az)/(bz-az)+ax)yes=!yes;
 }return yes};
 const points=corners(item);return points.every((p,index)=>{
  const next=points[[1,3,0,2][index]];
  if(!inside(p.x,p.z)||!inside((p.x+next.x)/2,(p.z+next.z)/2))return false;
  return polygon.every(([ax,az],edge)=>{const [bx,bz]=polygon[(edge+1)%polygon.length];
   return !(cross(p.x,p.z,next.x,next.z,ax,az)*cross(p.x,p.z,next.x,next.z,bx,bz)<-1e-12&&cross(ax,az,bx,bz,p.x,p.z)*cross(ax,az,bx,bz,next.x,next.z)<-1e-12);
  });
 });
}
export function surfacePlacement(item:Item,x:number,z:number,scene:Scene,preferredId=item.supportId):Placement{
 const floor={x:round(x),z:round(z),y:0,supportId:null};
 if(item.category!=='storage_box'||item.height>.6)return floor;
 const options:{pose:Placement;distance:number}[]=[];
 for(const target of scene.items){
  if(target.id===item.id||!isSurface(target)||target.height+item.height>scene.room.height+.00001)continue;
  const angle=radians(item.rotation-target.rotation),c=Math.abs(Math.cos(angle)),s=Math.abs(Math.sin(angle));
  const halfX=target.width/2-edgeMargin-(c*item.width+s*item.depth)/2,halfZ=target.depth/2-edgeMargin-(s*item.width+c*item.depth)/2;
  if(halfX<0||halfZ<0)continue;
  const point=local(target,x,z),clamped={x:Math.max(-halfX,Math.min(halfX,point.x)),z:Math.max(-halfZ,Math.min(halfZ,point.z))};
  const distance=Math.hypot(point.x-clamped.x,point.z-clamped.z),retained=preferredId===target.id;
  if(distance>(retained?.25:.16))continue;
  const pos=world(target,clamped.x,clamped.z),pose={x:round(pos.x),z:round(pos.z),y:target.height,supportId:target.id};
  const candidate={...item,...pose};
  if(!fitsSurface(candidate,target)||!inRoom(candidate,scene.room))continue;
  if(scene.items.some(other=>other.id!==item.id&&other.id!==target.id&&other.category!=='rug'&&baseY(candidate)<baseY(other)+other.height-.00001&&baseY(other)<baseY(candidate)+candidate.height-.00001&&overlap(candidate,other)))continue;
  options.push({pose,distance:distance+(retained?-.1:0)});
 }
 options.sort((a,b)=>a.distance-b.distance||a.pose.y-b.pose.y||a.pose.supportId!.localeCompare(b.pose.supportId!));
 return options[0]?.pose??floor;
}

/** Keep attachments coherent when a host moves, rotates, resizes or is removed. */
export function reconcileSupports(next:Scene,before:Scene):Scene{
 for(const item of next.items){
  if(!item.supportId)continue;
  const old=before.items.find(value=>value.id===item.id),target=next.items.find(value=>value.id===item.supportId),prior=before.items.find(value=>value.id===item.supportId);
  if(target&&prior&&old?.supportId===item.supportId&&old.x===item.x&&old.z===item.z&&old.rotation===item.rotation){
   const transformed=target.x!==prior.x||target.z!==prior.z||target.rotation!==prior.rotation||target.height!==prior.height;
   if(transformed){
    if(item.locked)throw new Error(`“${item.label}”已锁定，请先解锁再移动承托家具。`);
    const relative=local(prior,old.x,old.z),point=world(target,relative.x,relative.z);
    item.x=round(point.x);item.z=round(point.z);item.rotation=(old.rotation+target.rotation-prior.rotation+360)%360;
   }
  }
  if(target&&fitsSurface(item,target)&&target.height+item.height<=next.room.height+.00001){item.y=target.height;continue}
  if(item.locked)throw new Error(`“${item.label}”已锁定，请先解锁再更改或移除承托家具。`);
  item.supportId=null;item.y=0;
 }
 return next;
}
