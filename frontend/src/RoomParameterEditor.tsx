import {useId,useLayoutEffect,useRef,useState} from 'react';
import {X} from 'lucide-react';
import type {Room,Wall} from './types';

const dimensions=[['width','宽度'],['depth','进深'],['height','净高']] as const;
const walls=[['south','前墙'],['north','后墙'],['west','左墙'],['east','右墙']] as const;

export function resizeRoom(room:Room,size:Pick<Room,'width'|'depth'|'height'>):Room{
 const resized=size.width!==room.width||size.depth!==room.depth;
 const polygon=resized&&room.polygon?room.polygon.map(([x,z])=>[x*size.width/room.width,z*size.depth/room.depth]):room.polygon;
 return {...room,...size,polygon};
}

export default function RoomParameterEditor({room,onSave,onClose}:{room:Room;onSave:(room:Room)=>Promise<boolean>;onClose:()=>void}){
 const ref=useRef<HTMLDialogElement>(null),title=useId();
 const [pending,setPending]=useState(false);
 const [error,setError]=useState('');
 const door=room.door,window=room.windows[0];

 useLayoutEffect(()=>{const dialog=ref.current!;dialog.showModal();return()=>dialog.close();},[]);

 return <dialog ref={ref} className="modal room-parameter-editor" aria-labelledby={title} onCancel={event=>{event.preventDefault();event.stopPropagation();if(!pending)onClose();}} onClick={event=>{if(event.target===event.currentTarget&&!pending)onClose();}}>
  <form onSubmit={async event=>{
   event.preventDefault();
   if(pending)return;
   const data=new FormData(event.currentTarget),number=(key:string)=>Number(data.get(key));
   const size={width:number('width'),depth:number('depth'),height:number('height')};
   const next=resizeRoom(room,size);
   if(door)next.door={wall:data.get('door-wall') as Wall,offset:number('door-offset'),width:number('door-width'),clearance:number('door-clearance')};
   if(window)next.windows=[{...window,offset:number('window-offset'),width:number('window-width')},...room.windows.slice(1)];
   setPending(true);setError('');
   try{if(await onSave(next))onClose();}
   catch(failure){setError(failure instanceof Error?failure.message:String(failure));}
   finally{setPending(false);}
  }}>
   <div className="modal-heading"><h2 id={title}>房间参数</h2><button type="button" className="icon-btn" aria-label="关闭房间参数" disabled={pending} onClick={onClose}><X size={19}/></button></div>
   <div className="field-grid">{dimensions.map(([key,label],index)=><label className="field" key={key}>{label} / m<input name={key} aria-label={`房间${label}`} type="number" min="1" max="20" step="any" required defaultValue={room[key]} autoFocus={index===0}/></label>)}</div>
   {door&&<fieldset><legend>门口与净空</legend><label className="field">门所在墙<select name="door-wall" defaultValue={door.wall}>{walls.map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label>
    <div className="field-grid">{([['offset','距墙角',0],['width','门宽',.01],['clearance','门内净空',0]] as const).map(([key,label,min])=><label className="field" key={key}>{label} / m<input name={`door-${key}`} type="number" min={min} step="any" required defaultValue={door[key]}/></label>)}</div>
   </fieldset>}
   {window&&<fieldset><legend>窗户参考</legend><div className="field-grid two"><label className="field">窗距墙角 / m<input name="window-offset" type="number" min="0" step="any" required defaultValue={window.offset}/></label><label className="field">窗宽 / m<input name="window-width" type="number" min=".01" step="any" required defaultValue={window.width}/></label></div></fieldset>}
   {error&&<p className="error-message" role="alert">{error}</p>}
   <div className="modal-actions"><button type="button" className="btn" disabled={pending} onClick={onClose}>取消</button><button type="submit" className="btn primary" disabled={pending}>应用参数</button></div>
  </form>
 </dialog>;
}
