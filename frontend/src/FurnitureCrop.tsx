import {useEffect,useRef,useState} from 'react';

type Point={left:number;top:number};
export default function FurnitureCrop({file,index,onChange}:{file:File;index:number;onChange:(file:File)=>void}){
 const [url,setUrl]=useState(''),[selection,setSelection]=useState<{left:number;top:number;width:number;height:number}|null>(null),[error,setError]=useState('');
 const image=useRef<HTMLImageElement>(null),start=useRef<Point|null>(null);
 useEffect(()=>{const source=URL.createObjectURL(file);setUrl(source);setSelection(null);return()=>URL.revokeObjectURL(source)},[file]);
 function point(event:React.PointerEvent<HTMLDivElement>):Point{const bounds=event.currentTarget.getBoundingClientRect();return {left:Math.max(0,Math.min(1,(event.clientX-bounds.left)/bounds.width)),top:Math.max(0,Math.min(1,(event.clientY-bounds.top)/bounds.height))}}
 async function crop(){
  if(!selection||!image.current)return;
  const canvas=document.createElement('canvas'),source=image.current;
  canvas.width=Math.max(1,Math.round(selection.width*source.naturalWidth));canvas.height=Math.max(1,Math.round(selection.height*source.naturalHeight));
  const context=canvas.getContext('2d');if(!context)return;
  context.fillStyle='white';context.fillRect(0,0,canvas.width,canvas.height);
  context.drawImage(source,selection.left*source.naturalWidth,selection.top*source.naturalHeight,canvas.width,canvas.height,0,0,canvas.width,canvas.height);
  const blob=await new Promise<Blob|null>(resolve=>canvas.toBlob(resolve,'image/jpeg',.95));
  if(blob)onChange(new File([blob],`target-${index+1}.jpg`,{type:'image/jpeg'}));else setError('裁剪失败，请重新选择图片。');
 }
 return <div className="furniture-crop"><strong>图片 {index+1}</strong><div className="crop-surface" onPointerDown={event=>{event.currentTarget.setPointerCapture(event.pointerId);start.current=point(event);setSelection(null)}} onPointerMove={event=>{if(!start.current)return;const current=point(event),origin=start.current;setSelection({left:Math.min(origin.left,current.left),top:Math.min(origin.top,current.top),width:Math.abs(origin.left-current.left),height:Math.abs(origin.top-current.top)})}} onPointerUp={()=>{start.current=null}} onPointerCancel={()=>{start.current=null}}>
  <img ref={image} src={url} alt={`待识别图片 ${index+1}`} draggable={false} onError={()=>setError('图片无法显示，请选择 JPEG、PNG、WebP。')}/>
  {selection&&<span className="crop-selection" style={{left:`${selection.left*100}%`,top:`${selection.top*100}%`,width:`${selection.width*100}%`,height:`${selection.height*100}%`}}/>}
 </div><button className="btn" type="button" disabled={!selection||selection.width<.01||selection.height<.01} onClick={crop}>使用框选区域</button><small>拖动框选单件家具；工程拼图可保持整图。</small>{error&&<p role="alert">{error}</p>}</div>;
}
