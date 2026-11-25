import {lazy,Suspense,useRef,useState,type ComponentProps,type ReactNode} from 'react';
import {Box,Check,ChevronRight,Expand,Grid2X2,LockKeyhole,Maximize2,Minimize2,RotateCcw,Settings2,ShieldCheck,X} from 'lucide-react';
import type {Candidate,Item} from './types';

const SceneView=lazy(()=>import('./SceneView'));

type Props=Omit<ComponentProps<typeof SceneView>,'top'|'editable'|'inside'|'onToggleInside'> & {
 candidate:Candidate|null;
 candidates:Candidate[];
 selected?:Item;
 status:string;
 valid:boolean;
 canUndo:boolean;
 onUndo:()=>void;
 onClose:()=>void;
 fullscreen:boolean;
 onToggleFullscreen:()=>void;
 onCheck:()=>void;
 onSwitch:(candidate:Candidate)=>void;
 onApply:(candidate:Candidate)=>void;
 checks:ReactNode;
 busy:boolean;
 applyDisabled:boolean;
 children:ReactNode;
};

export default function RoomPreview({candidate,candidates,selected,status,valid,canUndo,onUndo,onClose,fullscreen,onToggleFullscreen,onCheck,onSwitch,onApply,checks,busy,applyDisabled,children,onEditRoom,...sceneProps}:Props){
 const stageRef=useRef<HTMLElement>(null);
 const [top,setTop]=useState(false);
 const [inside,setInside]=useState(false);
 const activeIndex=candidates.findIndex(item=>item.id===candidate?.id);

 return <section className="room-preview" aria-labelledby="room-preview-title">
  <div className={`preview-layout ${candidate?'has-candidates':''}`}>
   <header className="preview-banner">
    <h2 id="room-preview-title">{candidate?`方案 ${activeIndex+1}`:'房间预览'}</h2>
    <div className="preview-header-actions">
     {candidate&&<><button className="btn quiet" onClick={onClose}><X size={16}/>返回当前布局</button><button className="btn primary" disabled={busy||applyDisabled} onClick={()=>onApply(candidate)}><Check size={16}/>应用此方案</button></>}
     <button className="btn quiet" aria-label={fullscreen?'退出全屏':'全屏预览'} aria-pressed={fullscreen} onClick={onToggleFullscreen}>{fullscreen?<Minimize2 size={17}/>:<Expand size={17}/>}<span>{fullscreen?'退出全屏':'全屏'}</span></button>
    </div>
   </header>
   <section ref={stageRef} className="viewport preview-viewport" aria-label="房间布局画布">
    <div className="scene-actions">
     <div className="view-switch" role="group" aria-label="观察视角">
      <button className={!top?'active':''} aria-pressed={!top} onClick={()=>setTop(false)}><Box size={15}/>三维</button>
      <button className={top?'active':''} aria-pressed={top} onClick={()=>{setTop(true);if(inside)setInside(false)}}><Grid2X2 size={15}/>俯视</button>
     </div>
     <div className="canvas-tools">
      {!candidate&&<button title="撤销" aria-label="撤销" disabled={!canUndo} onClick={onUndo}><RotateCcw size={18}/></button>}
      <button title="房间参数" aria-label="编辑房间参数" disabled={busy} onClick={onEditRoom}><Settings2 size={18}/></button>
      <button title="重新适配视图" aria-label="重新适配视图" onClick={()=>stageRef.current?.querySelector('.scene-canvas')?.dispatchEvent(new Event('roomwise-fit'))}><Maximize2 size={18}/></button>
     </div>
    </div>
    <Suspense fallback={<p className="preview-loading" role="status">正在加载三维视图…</p>}>
     <SceneView {...sceneProps} top={top} editable={!candidate} inside={inside} onToggleInside={()=>setInside(!inside)} onEditRoom={onEditRoom}/>
    </Suspense>
    {selected&&<div className="selected-label">{selected.label}{selected.locked&&<LockKeyhole size={14} aria-label="已锁定"/>}</div>}
    {!candidate&&<div className={`canvas-validation ${valid?'ok':''}`}><span className="status-dot"/>{status}<button onClick={onCheck}>查看检查<ChevronRight size={13}/></button></div>}
   </section>
   {candidate&&<aside className="preview-candidates" aria-label="候选布局">
    <h3>切换方案</h3>
    <div className="preview-options" role="group" aria-label="切换方案">
     {candidates.map((item,index)=><button type="button" key={item.id} className="btn preview-option" disabled={busy} aria-pressed={item.id===candidate.id} onClick={()=>onSwitch(item)}>
      <span>方案 {index+1}</span>{item.id===candidate.id&&<Check size={16} aria-hidden="true"/>}
     </button>)}
    </div>
    <details className="preview-inspection">
     <summary><ShieldCheck size={17}/><span>{status}</span><ChevronRight size={15} aria-hidden="true"/></summary>
     <div className="preview-check-details" aria-label="预览检查详情">{checks}</div>
    </details>
   </aside>}
  </div>
  {children}
 </section>;
}
