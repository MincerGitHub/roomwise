import {useEffect,useId,useRef,useState} from 'react';
import {Armchair,Info,LockKeyhole,Ruler} from 'lucide-react';
import type {Scene} from './types';

export default function RoomDetails({scene}:{scene:Scene}){
 const id=useId(),root=useRef<HTMLDivElement>(null);
 const [hovered,setHovered]=useState(false),[expanded,setExpanded]=useState(false),[dismissed,setDismissed]=useState(false);
 const open=expanded||(hovered&&!dismissed);
 const counts=[
  {icon:Ruler,label:'房间面积',value:`${(scene.room.width*scene.room.depth).toFixed(1)} m²`},
  {icon:Armchair,label:'家具',value:`${scene.items.length} 件`},
  {icon:LockKeyhole,label:'已锁定',value:`${scene.items.filter(item=>item.locked).length} 件`},
 ];
 function close(){setExpanded(false);setDismissed(true);}

 useEffect(()=>{
  if(!expanded)return;
  function outside(event:PointerEvent){if(!root.current?.contains(event.target as Node)){setExpanded(false);setDismissed(true);}}
  document.addEventListener('pointerdown',outside);
  return()=>document.removeEventListener('pointerdown',outside);
 },[expanded]);

 return <div ref={root} className="room-details" onPointerEnter={event=>{if(event.pointerType==='mouse'){setHovered(true);setDismissed(false);}}} onPointerLeave={event=>{if(event.pointerType==='mouse')setHovered(false);}} onBlur={event=>{if(!event.currentTarget.contains(event.relatedTarget))setExpanded(false);}} onKeyDown={event=>{if(event.key==='Escape'&&open){event.stopPropagation();close();}}}>
  <button type="button" className="btn details-trigger" aria-expanded={open} aria-controls={id} onClick={()=>expanded?close():setExpanded(true)}><Info size={16}/>详情</button>
  <dl id={id} className="room-details-metrics" data-open={open} aria-hidden={!open}>
   {counts.map(({icon:Icon,label,value})=><div className="room-details-metric" key={label}>
    <Icon size={17} aria-hidden="true"/><dt>{label}</dt><dd>{value}</dd>
   </div>)}
  </dl>
 </div>;
}
