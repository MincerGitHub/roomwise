import {useCallback,useEffect,useRef,useState} from 'react';
import {Armchair,ArrowDownToLine,ArrowUpFromLine,ArrowUpRight,Box,Check,CheckCircle2,ChevronDown,ChevronRight,Copy,Eye,FileImage,Film,FolderOpen,House,Layers3,LockKeyhole,Plus,RotateCcw,RotateCw,Save,Settings2,ShieldCheck,Sparkles,Trash2,UnlockKeyhole,X} from 'lucide-react';
import RoomPreview from './RoomPreview';
import {resizeRoom} from './RoomParameterEditor';
import RoomDetails from './RoomDetails';
import LayoutConversation,{type LayoutMessage} from './LayoutConversation';
import FurnitureThumb from './FurnitureThumb';
import {reconcileSupports,surfacePlacement} from './surfacePlacement';
import {initialAppliancePlacement} from './appliancePlacement';
import {wallPlacement,isWallMounted} from './wallPlacement';
import FurnitureLibrary,{furnitureInstance} from './FurnitureLibrary';
import './furniture.css';
import {api,clone,downloadJSON,sourceNames,type Scene,type Room,type Item,type Preference,type RequirementCheck,type Validation,type Candidate,type CatalogItem,type VideoJob} from './types';

type Tab='room'|'furniture'|'video'|'results';
type LanguageStatus={enabled:boolean;configured?:boolean;provider:string;model?:string|null;message:string};
type Health={status:string;modelLoaded:boolean;videoDetector?:unknown;language?:LanguageStatus;[key:string]:unknown};
const defaults:Scene={id:'demo',name:'搬家后的卧室',version:0,room:{width:5.2,depth:4.2,height:2.7,polygon:null,door:{wall:'south',offset:.45,width:.9,clearance:.9},windows:[{id:'window-1',wall:'north',offset:2.3,width:1.5,sillHeight:.9}]},items:[{id:'bed-1',label:'旧双人床',category:'double_bed',width:1.8,depth:2,height:.55,x:3.8,z:2.4,rotation:0,locked:false,keep:false,source:'brought'},{id:'wardrobe-1',label:'房内衣柜',category:'wardrobe',width:1.8,depth:.6,height:2.1,x:1.15,z:3.8,rotation:180,locked:true,keep:false,source:'existing'},{id:'desk-1',label:'旧书桌',category:'desk',width:1.2,depth:.6,height:.75,x:3.7,z:.55,rotation:0,locked:false,keep:false,source:'brought'},{id:'chair-1',label:'办公椅',category:'chair',width:.5,depth:.5,height:.85,x:3.7,z:1.1,rotation:180,locked:false,keep:false,source:'brought'},{id:'nightstand-1',label:'床头柜',category:'nightstand',width:.5,depth:.45,height:.5,x:2.6,z:2.8,rotation:0,locked:false,keep:false,source:'existing'}],preferences:[]};
const fallbackCatalog:CatalogItem[]=[{category:'storage_box',label:'收纳箱',width:.4,depth:.3,height:.3},{category:'double_bed',label:'双人床',width:1.8,depth:2,height:.55},{category:'desk',label:'书桌',width:1.2,depth:.6,height:.75},{category:'chair',label:'椅子',width:.5,depth:.5,height:.85},{category:'wardrobe',label:'衣柜',width:1.6,depth:.6,height:2.1},{category:'nightstand',label:'床头柜',width:.5,depth:.45,height:.5},{category:'sofa',label:'沙发',width:1.8,depth:.85,height:.85},{category:'bookshelf',label:'书架',width:.8,depth:.35,height:1.7},{category:'rug',label:'地毯',width:1.6,depth:2,height:.02}];
const catIcon=(c:string)=>c.includes('chair')||c==='sofa'?<Armchair size={18}/>:c.includes('bed')?<House size={18}/>:<Box size={18}/>;
function preferenceLabel(preference:Preference,scene:Scene){const label=scene.items.find(i=>i.id===preference.itemId)?.label||preference.itemId;if(preference.kind==='bedside'){const bed=scene.items.find(i=>i.id===preference.targetId)?.label||preference.targetId||'指定床';const side=preference.side==='left'?'左侧':preference.side==='right'?'右侧':'任一侧';return `${label}：${bed}的床头${side}（站在床尾看床头）`}if(preference.kind==='face_item'){const target=scene.items.find(i=>i.id===preference.targetId)?.label||'指定家具';return `${label}：正面朝向${target}`}if(preference.kind==='relative_position'){const reference=scene.items.find(i=>i.id===preference.targetId);const target=reference?.label||'指定家具';const bed=reference&&['double_bed','single_bed','kids_bed'].includes(reference.category);const direction:Record<string,string>=bed?{front:'床头端',back:'床尾端',left:'左侧（站在床尾看床头）',right:'右侧（站在床尾看床头）'}:{front:'前方',back:'后方',left:'左侧（面对正面）',right:'右侧（面对正面）'};return `${label}：位于${target}${direction[preference.direction||'front']}`}if(preference.kind==='vanity_seating'){const table=scene.items.find(i=>i.id===preference.targetId)?.label||'梳妆台';return `${label}：位于${table}前方并面朝桌面`}const target=preference.targetId?`窗户 ${Math.max(1,scene.room.windows.findIndex(w=>w.id===preference.targetId)+1)}`:'窗户';const wall=preference.wall&&preference.wall!=='nearest'?({north:'后墙',south:'前墙',west:'左墙',east:'右墙'}[preference.wall]):'最近的墙';const action:Record<string,string>={near_window:`靠近${target}`,face_window:`面朝${target}方向`,near_wall:`背面靠${wall}`,min_move:'减少位置变化'};return `${label}：${action[preference.kind]||preference.kind}`}
function metricText(check:RequirementCheck){const labels:Record<string,string>={lateralOffsetMeters:'横向偏移',depthMeters:'使用深度',surfaceHeightMeters:'台面高度',seatHeightMeters:'座面高度',heightDifferenceMeters:'台面与座面高度差',distance:'距窗',distanceToWindow:'距窗',windowDistance:'距窗',distanceMeters:check.kind==='near_wall'?'距墙':'距窗',distance_m:'距窗',maxDistance:'距离上限',maxDistanceMeters:'距离上限',maxDistance_m:'距离上限',projectionOverlapMeters:'沿窗重叠长度',projectionToleranceMeters:'沿窗允许偏差',backDistanceMeters:'背面距墙',backAlignmentErrorDegrees:'背面朝墙偏差',maxBackAngleDegrees:'偏差上限',angle:'朝向偏差',angleError:'朝向偏差',angleDegrees:'朝向偏差',angleErrorDegrees:'朝向偏差',angularErrorDegrees:'朝向偏差',angle_deg:'朝向偏差',maxAngle:'偏差上限',maxAngleDegrees:'偏差上限',maxAngle_deg:'偏差上限',sideGapMeters:'床侧间距',maxSideGapMeters:'床侧间距上限',headOffsetErrorMeters:'床头位置偏差',maxHeadOffsetErrorMeters:'床头位置允许偏差',overlapAreaM2:'占地重叠面积',gapMeters:'家具间距',maxGapMeters:'家具间距上限',lateralOverlapMeters:'横向对齐长度',minLateralOverlapMeters:'最小对齐长度'};const bedsideKeys=new Set(['sideGapMeters','maxSideGapMeters','headOffsetErrorMeters','maxHeadOffsetErrorMeters','overlapAreaM2']);return Object.entries(check.metrics||{}).filter(([key,value])=>typeof value==='number'&&(check.kind!=='bedside'||bedsideKeys.has(key))).map(([key,value])=>{const v=value as number;const unit=/area.*m2/i.test(key)?' m²':/angle|degree/i.test(key)?'°':/distance|meter/i.test(key)?' m':'';return `${labels[key]||key} ${v.toFixed(unit==='°'?1:2)}${unit}`}).join(' · ')}
function RequirementChecks({candidate}:{candidate:Pick<Candidate,'requirements'>}){const checks=candidate.requirements?.checks||[];return checks.length?<div className="requirement-checks" aria-label="布局要求检查">{checks.map((check,index)=><div className={`requirement-check ${check.satisfied?'met':'unmet'}`} key={`${check.kind}-${check.itemId}-${index}`}><strong>{check.satisfied?'已满足':'未满足'} · {check.required?'必须要求':'尽量要求'}</strong><span>{check.message}</span>{metricText(check)&&<small>{metricText(check)}</small>}</div>)}</div>:null}
function FunctionalRelationChecks({candidate}:{candidate:Candidate}){const relations=candidate.functionalRelations;if(!relations?.checks.length)return null;return <section className="functional-relations" aria-label="家具搭配检查"><h3>家具搭配检查</h3><div className="requirement-checks">{relations.checks.map((check,index)=><div key={`${check.kind}-${check.itemId}-${index}`} className={`requirement-check ${check.satisfied?'met':'unmet'}`}><strong>{check.satisfied?'搭配位置通过':check.blocking?'搭配位置未满足':'搭配位置需留意'} · {check.source==='explicit'?'文字要求':'默认搭配'}</strong><span>{check.message}</span>{metricText(check)&&<small>{metricText(check)}</small>}</div>)}</div></section>}
function FunctionalSpaceChecks({candidate}:{candidate:Pick<Candidate,'functionalSpaces'>}){
 const result=candidate.functionalSpaces;if(!result?.checks.length)return null;
 return <section className="functional-relations" aria-label="功能空间检查"><h3>功能空间检查 · {result.passed}/{result.total}</h3><p className="hint">{result.note}</p><div className="requirement-checks">{result.checks.map((check,index)=><div key={`${check.kind}-${check.itemId}-${index}`} className={`requirement-check ${check.satisfied?'met':'unmet'}`}><strong>{check.satisfied?'通过':check.required?'未满足':'建议调整'} · {check.required?'已声明参数':'默认建议'}</strong><span>{check.message}</span>{metricText(check)&&<small>{metricText(check)}</small>}</div>)}</div></section>
}
function WallApplianceChecks({result}:{result:Validation['wallAppliances']}){
 if(!result?.checks.length)return null;
 return <section className="functional-relations" aria-label="壁挂家具检查"><h3>壁挂家具检查 · {result.passed}/{result.total}</h3><p className="hint">{result.note}</p><div className="requirement-checks">{result.checks.map((check,index)=><div className={`requirement-check ${check.satisfied?'met':'unmet'}`} key={`${check.kind}-${index}`}><strong>{check.satisfied?'通过':check.required?'未满足':'待补充观看位置'}</strong><span>{check.message}</span></div>)}</div></section>
}
export default function App(){
 const [initialFurnitureDraft]=useState(()=>{const identifier=new URLSearchParams(window.location.search).get('furnitureDraft');return identifier&&/^[a-f0-9]{32}$/.test(identifier)?identifier:null});
 const [libraryOpen,setLibraryOpen]=useState(()=>!!new URLSearchParams(window.location.search).get('furnitureDraft'));
 const [scene,setScene]=useState<Scene>(defaults),[selectedId,setSelectedId]=useState<string|null>('bed-1'),[tab,setTab]=useState<Tab>('furniture'),[catalog,setCatalog]=useState(fallbackCatalog),[health,setHealth]=useState<Health|null>(null),[validation,setValidation]=useState<Validation|null>(null),[notice,setNotice]=useState(''),[busy,setBusy]=useState(false),[candidates,setCandidates]=useState<Candidate[]>([]),[previewCandidate,setPreviewCandidate]=useState<Candidate|null>(null),[mode,setMode]=useState<'hybrid'|'rules'|'model'>('hybrid'),[cmd,setCmd]=useState(''),[messages,setMessages]=useState<LayoutMessage[]>([]),[modal,setModal]=useState<'add'|'suggest'|'saved'|'experiments'|null>(null),[suggestions,setSuggestions]=useState<CatalogItem[]>([]),[saved,setSaved]=useState<{id:string;name:string;version:number;updatedAt?:string}[]>([]),[experiment,setExperiment]=useState<unknown>(null),[video,setVideo]=useState<VideoJob|null>(null),[jobId,setJobId]=useState<string|null>(null),[floorImg,setFloorImg]=useState<string|null>(null),[uploadBusy,setUploadBusy]=useState(false),[videoDraft,setVideoDraft]=useState<(CatalogItem & {photoUrl:string})|null>(null);
 const [contextMenu,setContextMenu]=useState<{id:string;x:number;y:number}|null>(null),[editTargetId,setEditTargetId]=useState<string|null>(null),[deleteTargetId,setDeleteTargetId]=useState<string|null>(null),[inspectorOpen,setInspectorOpen]=useState(false);
 const [candidateSelectedId,setCandidateSelectedId]=useState<string|null>(null);
 const [draftFurniture,setDraftFurniture]=useState<Item|null>(null);
 const [pendingCandidate,setPendingCandidate]=useState<Scene|null>(null),[candidateCheckFailed,setCandidateCheckFailed]=useState(false);
 const [fullscreen,setFullscreen]=useState(false),workspaceRef=useRef<HTMLElement>(null);
 const [previewChoices,setPreviewChoices]=useState<Candidate[]|null>(null);
 const previewHistory=useRef<{choices:Candidate[];candidate:Candidate;selectedId:string|null}[]>([]),previewSession=useRef(0);
 const revision=useRef(0),history=useRef<Scene[]>([]),current=useRef(scene);current.current=scene;
 const [commandWarning,setCommandWarning]=useState('');
 const [requirementsExpanded,setRequirementsExpanded]=useState(false);
 const [plansExpanded,setPlansExpanded]=useState(false);
 const startupUntouched=useRef(true);
 useEffect(()=>{
  let cancelled=false;const stamp=revision.current,initial=current.current;
  api<{scene:Scene|null}>('/startup-scene').then(({scene:opening})=>{
   if(cancelled||!opening||!startupUntouched.current||revision.current!==stamp||current.current!==initial)return;
   startupUntouched.current=false;revision.current++;
   current.current=clone(opening);setScene(current.current);setSelectedId(opening.items[0]?.id||null);setValidation(null);
  }).catch(()=>{});
  return()=>{cancelled=true};
 },[]);
 const [,renderHistory]=useState(0);const importRef=useRef<HTMLInputElement>(null),assetRef=useRef<HTMLInputElement>(null),floorRef=useRef<HTMLInputElement>(null),videoRef=useRef<HTMLInputElement>(null);
 const visibleCandidates=previewCandidate?(previewChoices??candidates):candidates;
 const displayScene=previewCandidate?.scene||scene;const displayValidation=previewCandidate?.validation||validation;
 const displayRequirements=previewCandidate?.requirements||displayValidation?.requirements;const requiredUnmet=(displayRequirements?.checks.some(c=>c.required&&!c.satisfied)||false)||(previewCandidate?.functionalSpaces||displayValidation?.functionalSpaces)?.satisfied===false;
 const previewSelection=previewCandidate?candidateSelectedId:selectedId;
 const selected=displayScene.items.find(i=>i.id===previewSelection);const editTarget=draftFurniture??scene.items.find(i=>i.id===editTargetId);const deleteTarget=scene.items.find(i=>i.id===deleteTargetId);const notify=(text:string)=>setNotice(text);
 function openItemMenu(id:string,x:number,y:number){if(busy)return;(previewCandidate?setCandidateSelectedId:setSelectedId)(id);setContextMenu({id,x:Math.min(x,window.innerWidth-176),y:Math.min(y,window.innerHeight-112)})}
 function openFurnitureEditor(id:string){
  if(previewCandidate){const item=previewCandidate.scene.items.find(item=>item.id===id);if(item)setDraftFurniture(clone(item));}
  else{setSelectedId(id);setEditTargetId(id);}
  setContextMenu(null);
 }
 function closeFurnitureEditor(){setEditTargetId(null);setDraftFurniture(null);}
 function removeFurniture(id:string){if(previewCandidate)return notify('请先退出方案预览再编辑家具');const item=current.current.items.find(x=>x.id===id);if(!item)return;if(item.keep){setDeleteTargetId(id);return}deleteFurniture(id)}
 function deleteFurniture(id:string,clearKeep=false){const n=clone(current.current);if(clearKeep){const item=n.items.find(x=>x.id===id);if(item)item.keep=false}n.items=n.items.filter(x=>x.id!==id);n.preferences=n.preferences.filter(p=>p.itemId!==id&&p.targetId!==id);commit(n,'已移除家具');setSelectedId(null);setDeleteTargetId(null)}
 const commit=useCallback((next:Scene,label?:string,force=false)=>{if(previewCandidate&&!force){notify('正在预览候选方案，请先退出预览或应用方案');return false}try{next=reconcileSupports(clone(next),current.current)}catch(error){notify(error instanceof Error?error.message:String(error));return false}history.current.push(clone(current.current));if(history.current.length>40)history.current.shift();revision.current++;setScene(clone(next));setValidation(null);setCandidates([]);setPreviewCandidate(null);if(label)setNotice(label);renderHistory(n=>n+1);return true},[previewCandidate]);
 function editItem(id:string,patch:Partial<Item>){if(previewCandidate){notify('正在预览候选方案，请先退出预览或应用方案');return}const next=clone(current.current);const i=next.items.find(x=>x.id===id);if(i){if(i.furnitureSnapshot&&patch.category&&patch.category!==i.category)i.assetUrl=null;if(i.locked&&['x','z','y','rotation','supportId'].some(key=>key in patch))return;Object.assign(i,patch);if(!i.locked&&isWallMounted(i)&&['x','z','rotation','y','width','depth','height'].some(key=>key in patch)){const snapped=wallPlacement(i,i.x,i.z,next.room);if(!snapped){notify('没有避开窗户且可容纳该家具的安装位置');return}Object.assign(i,snapped.placement);}if(['storage_box','laptop'].includes(i.category)&&!('supportId' in patch)&&['x','z','rotation','width','depth','height'].some(key=>key in patch))Object.assign(i,surfacePlacement(i,i.x,i.z,next))}commit(next)}
 function undo(){if(previewCandidate)return notify('正在预览候选方案，请先退出预览或应用方案');const old=history.current.pop();if(!old)return notify('没有可以撤销的操作');old.version=current.current.version;old.id=current.current.id;revision.current++;setScene(old);setCandidates([]);renderHistory(n=>n+1);notify('已撤销上一步')}
 useEffect(()=>{let off=false;Promise.allSettled([api<Health>('/health'),api<{items:CatalogItem[]}>('/catalog')]).then(rs=>{if(off)return;if(rs[0].status==='fulfilled')setHealth(rs[0].value);else notify('服务尚未连接，请先运行启动脚本。编辑和JSON导出仍可使用。');if(rs[1].status==='fulfilled'&&rs[1].value.items?.length)setCatalog(rs[1].value.items)});return()=>{off=true}},[]);
 useEffect(()=>{let off=false;setValidation(null);const t=setTimeout(()=>api<Validation>('/validate',{scene}).then(v=>{if(!off)setValidation(v)}).catch(e=>{if(!off)setValidation({valid:false,issues:[{type:'invalid_input',severity:'error',message:'?????????????????'+(e instanceof Error?e.message:String(e)),itemIds:[]}],metrics:{}})}),250);return()=>{off=true;clearTimeout(t)}},[scene]);
 useEffect(()=>{if(!notice)return;const t=setTimeout(()=>setNotice(''),6500);return()=>clearTimeout(t)},[notice]);
 useEffect(()=>{if(!jobId)return;let off=false;const check=async()=>{try{const j=await api<VideoJob>(`/video/jobs/${jobId}`);if(!off){setVideo(j);if(['complete','failed'].includes(j.status))setJobId(null)}}catch(e){if(!off){notify(String(e));setJobId(null)}}};check();const t=setInterval(check,1500);return()=>{off=true;clearInterval(t)}},[jobId]);
 function requestLayouts(input:Scene,stamp:number){return api<{candidates:Candidate[];diagnostics:Record<string,unknown>}>('/generate',{scene:input,mode,count:3,seed:42+stamp});}
 async function generate(input=current.current,acceptedCommand=false,openSession?:number){
  if(previewCandidate)return notify('请先退出预览或应用方案');
  if(commandWarning&&!acceptedCommand)return notify('本次文字要求尚未应用，请修改后重新发送，或明确忽略本次要求');
  const stamp=revision.current;setCandidates([]);setBusy(true);
  try{
   const result=await requestLayouts(input,stamp);
   if(stamp!==revision.current)return notify('房间在生成期间有修改，已丢弃旧结果，请重新生成');
   setCandidates(result.candidates||[]);
   setPlansExpanded(!!result.candidates?.length);
   if(openSession===previewSession.current&&result.candidates?.length)preview(result.candidates[0]);
   else setPreviewCandidate(null);
   if(!result.candidates?.length)notify('未找到满足当前要求的方案，请调整布局要求或房间参数后重试。');
  }catch(error){
   notify(`本次生成未完成：${error instanceof Error?error.message:String(error)}`);
  }finally{setBusy(false)}
 }
 function preview(c:Candidate){
  if(c.id===previewCandidate?.id)return;
  setPreviewCandidate(c);setCandidateCheckFailed(false);
  const selection=previewCandidate?candidateSelectedId:selectedId;
  setCandidateSelectedId(selection&&c.scene.items.some(i=>i.id===selection)?selection:c.scene.items[0]?.id??null);
  setNotice('');
  requestAnimationFrame(()=>document.querySelector('.room-preview')?.scrollIntoView({block:'nearest'}));
 }
 function exitPreview(){
  previewSession.current++;
  previewHistory.current=[];
  setPreviewChoices(null);
  setPendingCandidate(null);setCandidateCheckFailed(false);
  setPreviewCandidate(null);
  setContextMenu(null);
  closeFurnitureEditor();
  setDeleteTargetId(null);
  if(modal==='suggest')setModal(null);
 }
 function applyCandidate(c:Candidate){
  const n=clone(c.scene);n.id=current.current.id;n.version=current.current.version;
  if(!commit(n,'已应用方案',true))return;
  setSelectedId(candidateSelectedId??n.items[0]?.id??null);
  exitPreview();
  requestAnimationFrame(()=>document.getElementById('room-preview-title')?.scrollIntoView({block:'nearest'}));
 }
 async function saveCandidateChanges(next:Scene){
  if(!previewCandidate||busy)return false;
  const candidate=previewCandidate,choices=previewChoices??candidates,session=previewSession.current;
  setBusy(true);
  try{
   next=reconcileSupports(clone(next),candidate.scene);
   const checks=await api<Validation&{functionalRelations?:Candidate['functionalRelations']}>('/validate',{scene:next});
   if(session!==previewSession.current)return false;
   const updated={...candidate,scene:next,validation:checks,requirements:checks.requirements,functionalRelations:checks.functionalRelations,functionalSpaces:checks.functionalSpaces};
   previewHistory.current.push({choices,candidate,selectedId:candidateSelectedId});
   setPreviewChoices(choices.map(item=>item.id===candidate.id?updated:item));setPreviewCandidate(updated);
   return true;
  }finally{setBusy(false);}
 }
 function updateFurnitureEditor(id:string,patch:Partial<Item>){
  if(draftFurniture){if(!busy)setDraftFurniture(item=>item?{...item,...patch}:item);}
  else editItem(id,patch);
 }
 async function finishFurnitureEditor(){
  if(!previewCandidate||!draftFurniture){closeFurnitureEditor();return;}
  const next=clone(previewCandidate.scene);
  const index=next.items.findIndex(item=>item.id===draftFurniture.id);
  if(index<0)return;
  const updated={...draftFurniture},original=next.items[index];
  if(['storage_box','laptop'].includes(updated.category)&&(['x','z','rotation','width','depth','height'] as const).some(key=>updated[key]!==original[key]))Object.assign(updated,surfacePlacement(updated,updated.x,updated.z,next));
  if(!updated.locked&&isWallMounted(updated)){
   const snapped=wallPlacement(updated,updated.x,updated.z,next.room);
   if(!snapped){notify('没有避开窗户且可容纳该家具的安装位置');return;}
   Object.assign(updated,snapped.placement);
  }
  next.items[index]=updated;
  try{if(await saveCandidateChanges(next))closeFurnitureEditor();}
  catch(error){notify(error instanceof Error?error.message:String(error));}
 }
 function addItem(item:CatalogItem,source:Item['source']='new',photoUrl?:string){if(previewCandidate){notify('正在预览候选方案，请先退出预览或应用方案');return}const id=`${item.category}-${crypto.randomUUID().slice(0,8)}`;const n=clone(current.current);n.items.push({id,label:item.label,category:item.category,width:item.width,depth:item.depth,height:item.height,x:n.room.width/2,z:n.room.depth/2,rotation:0,locked:false,keep:false,source,photoUrl});Object.assign(n.items[n.items.length-1],initialAppliancePlacement(n.items[n.items.length-1],n));commit(n,'已添加家具，请确认尺寸和位置');setSelectedId(id);setModal(null);setTab('furniture')}
 async function suggest(need:string){try{const r=await api<{suggestions:CatalogItem[]}>('/suggest',{scene,need});setSuggestions(r.suggestions);setModal('suggest');if(!r.suggestions.length)notify('已有家具可满足该需求，暂不建议重复增加')}catch(e){notify(String(e))}}
 async function command(text=cmd){
  if(!text.trim()||busy)return;
  const candidate=previewCandidate,session=previewSession.current,stamp=revision.current;
  const base=candidate?.scene||current.current;
  const selection=candidate?candidateSelectedId:selectedId;
  const oldChoices=previewChoices??candidates;
  const sessionEnded=()=>previewSession.current!==session;
  const append=(text:string,warning=false)=>setMessages(m=>[...m,{role:'assistant',text,warning}]);
  const reportFailure=(message:string)=>{
   append(message,true);
   if(!candidate)setCommandWarning(message);
  };
  setCmd('');setMessages(m=>[...m,{role:'user',text}]);
  if(!candidate){setCandidates([]);}
  setBusy(true);
  try{
   const result=await api<{action:string;scene?:Scene;message:string;suggestions?:CatalogItem[];language?:LanguageStatus}>('/command',{scene:base,text,selectedId:selection});
   if(candidate&&sessionEnded())return;
   if(stamp!==revision.current){reportFailure('房间在解析期间有修改，本次要求未应用，请重新发送。');return;}
   if(result.language)setHealth(h=>h?{...h,language:result.language}:h);
   if(['unsupported','clarify'].includes(result.action)){reportFailure(`本次要求未应用：${result.message}`);return;}
   if(candidate){
    if(result.action==='undo'){
     const previous=previewHistory.current.pop();
     if(previous){setPreviewChoices(previous.choices);setPreviewCandidate(previous.candidate);setCandidateSelectedId(previous.selectedId);append('已撤销上一次预览调整。');}
     else append('没有可撤销的预览调整。');
     return;
    }
    const next=result.scene?reconcileSupports(clone(result.scene),base):base;
    if(result.action==='generate'){
     const generated=await requestLayouts(next,stamp);
     if(sessionEnded()||stamp!==revision.current)return;
     if(!generated.candidates?.length){reportFailure(String(generated.diagnostics?.message||'未找到符合要求的新方案，已保留当前预览。'));return;}
     previewHistory.current.push({choices:oldChoices,candidate,selectedId:selection});
     setPreviewChoices(generated.candidates);setPreviewCandidate(generated.candidates[0]);
     setCandidateSelectedId(generated.candidates[0].scene.items.find(item=>item.id===selection)?.id??generated.candidates[0].scene.items[0]?.id??null);
     append(`已生成 ${generated.candidates.length} 个调整方案。`);
    }else if(result.scene){
     const checks=await api<Validation&{functionalRelations?:Candidate['functionalRelations']}>('/validate',{scene:next});
     if(sessionEnded()||stamp!==revision.current)return;
     const updated={...candidate,scene:next,validation:checks,requirements:checks.requirements,functionalRelations:checks.functionalRelations,functionalSpaces:checks.functionalSpaces};
     previewHistory.current.push({choices:oldChoices,candidate,selectedId:selection});
     setPreviewChoices(oldChoices.map(item=>item.id===candidate.id?updated:item));setPreviewCandidate(updated);
     append(result.message);
    }else append(result.suggestions?.length?`${result.message} ${result.suggestions.map(item=>item.label).join('、')}`:result.message);
    return;
   }
   append(result.message);setCommandWarning('');
   if(result.action==='undo')undo();
   if(result.scene){const n=clone(result.scene);n.version=current.current.version;commit(n);}
   if(result.suggestions){setSuggestions(result.suggestions);setModal('suggest');}
   if(result.action==='generate')await generate(result.scene||current.current,true,!sessionEnded()?session:undefined);
  }catch(error){
   if(!candidate||!sessionEnded())reportFailure(`本次要求未应用：${error instanceof Error?error.message:String(error)}`);
  }finally{setBusy(false);}
 }
 async function save(asNew=false){if(previewCandidate)return notify('\u8bf7\u5148\u9000\u51fa\u9884\u89c8\u6216\u5e94\u7528\u65b9\u6848');try{const n=clone(current.current);if(asNew){n.id=crypto.randomUUID();n.version=0}const r=await api<{id:string;version:number}>('/scenes/save',{scene:n});setScene(s=>({...s,id:r.id,version:r.version}));notify('\u65b9\u6848\u5df2\u4fdd\u5b58\u5230\u672c\u673a')}catch(e){notify(`${String(e)}. Use Save As or export JSON.`)}}
 async function showSaved(){try{const r=await api<{scenes:typeof saved}>('/scenes');setSaved(r.scenes);setModal('saved')}catch(e){notify(String(e))}}
 async function load(id:string){const stamp=revision.current;try{const n=await api<Scene>(`/scenes/${id}`);if(stamp!==revision.current)return notify('??????????????????????????????????????????????');revision.current++;history.current=[];setScene(n);setModal(null);setPreviewCandidate(null);setCandidates([]);setSelectedId(n.items[0]?.id||null);notify('已打开方案')}catch(e){notify(String(e))}}
 async function showExperiments(){try{setExperiment(await api('/experiments'));setModal('experiments')}catch(e){notify(String(e))}}
 async function importFile(file:File){if(previewCandidate)return notify('\u8bf7\u5148\u9000\u51fa\u9884\u89c8\u6216\u5e94\u7528\u65b9\u6848');const stamp=revision.current;try{const n=JSON.parse(await file.text()) as Scene;if(!n.room||!Array.isArray(n.items))throw new Error('需要包含room与items的方案JSON');await api('/validate',{scene:n});if(stamp!==revision.current)return notify('??????????????????????????????????????????????');n.id=crypto.randomUUID();n.version=0;commit(n,'导入成功；另存为新方案');setSelectedId(n.items[0]?.id||null)}catch(e){notify(`导入失败：${String(e)}`)}}
 async function uploadAsset(file:File){if(!selected)return;const targetId=selected.id,sceneId=current.current.id;const form=new FormData();form.append('file',file);setUploadBusy(true);try{const r=await fetch('/api/assets',{method:'POST',body:form});if(!r.ok)throw new Error(await r.text());const a=await r.json();if(current.current.id!==sceneId||!current.current.items.some(i=>i.id===targetId))return notify('?????????????????????????????????????????????');editItem(targetId,file.type.startsWith('image/')?{photoUrl:a.url}:{assetUrl:a.url});notify('已绑定文件，模型按确认尺寸显示')}catch(e){notify(String(e))}finally{setUploadBusy(false)}}
 async function uploadFloor(file:File){const stamp=revision.current;const form=new FormData();form.append('file',file);setUploadBusy(true);try{const r=await fetch('/api/assets',{method:'POST',body:form});if(!r.ok)throw new Error(await r.text());const a=await r.json();if(stamp!==revision.current)return notify('???????????????????????????????????????');commit({...current.current,room:{...current.current.room,referenceImageUrl:a.url}},'???????????????????????????????????');setFloorImg(a.url)}catch(e){notify(String(e))}finally{setUploadBusy(false)}}
 async function analyzeVideo(file:File){const form=new FormData();form.append('file',file);setUploadBusy(true);setVideo(null);try{const r=await fetch('/api/video/analyze',{method:'POST',body:form});if(!r.ok)throw new Error(await r.text());const j=await r.json();setJobId(j.jobId);notify('视频已提交，本机处理后请核对候选清单')}catch(e){notify(String(e))}finally{setUploadBusy(false)}}
 const errors=validation?.issues.filter(i=>i.severity==='error').length??0;
 const previewErrors=displayValidation?.issues.filter(i=>i.severity==='error').length??0;
 const previewWarnings=(displayValidation?.issues.length??0)-previewErrors;
 const previewStatus=pendingCandidate?'正在检查调整后的布局':displayValidation?displayValidation.valid?(requiredUnmet?'功能空间或布局要求未满足':'空间检查通过'):`${previewErrors} 项冲突，${previewWarnings} 项提示`:'正在检查尺寸与位置';
 function showWorkspaceTab(next: Tab){
  setTab(next);
  const panel=document.getElementById('workspace-tool-panel');
  if(next!==tab)panel?.querySelector('.sidebar-content')?.scrollTo({top:0});

 }
 function showCanvasChecks(){
  showWorkspaceTab('results');
  requestAnimationFrame(()=>document.getElementById('workspace-checks-tab')?.focus());
 }
 function selectCanvasItem(id:string|null){
  (previewCandidate?setCandidateSelectedId:setSelectedId)(id);
  if(!id)return;
  showWorkspaceTab('furniture');setInspectorOpen(true);
  requestAnimationFrame(()=>document.querySelector('.sidebar-content')?.scrollTo({top:0}));
 }
 function selectCanvasRoom(){
  (previewCandidate?setCandidateSelectedId:setSelectedId)(null);
  showWorkspaceTab('room');
  requestAnimationFrame(()=>document.querySelector('.sidebar-content')?.scrollTo({top:0}));
 }
 function commitSidebar(next:Scene){
  if(!previewCandidate)return commit(next);
  if(busy)return false;
  try{next=reconcileSupports(clone(next),previewCandidate.scene);}
  catch(error){notify(error instanceof Error?error.message:String(error));return false;}
  const choices=previewChoices??candidates;
  previewHistory.current.push({choices,candidate:previewCandidate,selectedId:candidateSelectedId});
  const updated={...previewCandidate,scene:next,validation:{valid:false,issues:[],metrics:{}},requirements:undefined,functionalRelations:undefined,functionalSpaces:undefined};
  setPreviewChoices(choices.map(item=>item.id===updated.id?updated:item));setPreviewCandidate(updated);
  setCandidateCheckFailed(false);setPendingCandidate(next);
  return true;
 }
 function editSidebarItem(id:string,patch:Partial<Item>){
  if(!previewCandidate){editItem(id,patch);return;}
  const next=clone(previewCandidate.scene),item=next.items.find(item=>item.id===id);
  if(!item||item.locked&&['x','z','y','rotation','supportId'].some(key=>key in patch))return;
  Object.assign(item,patch);
  if(!item.locked&&isWallMounted(item)&&['x','z','rotation','y','width','depth','height'].some(key=>key in patch)){
   const snapped=wallPlacement(item,item.x,item.z,next.room);
   if(!snapped){notify('没有避开窗户且可容纳该家具的安装位置');return;}
   Object.assign(item,snapped.placement);
  }
  if(['storage_box','laptop'].includes(item.category)&&!('supportId' in patch)&&['x','z','rotation','width','depth','height'].some(key=>key in patch))Object.assign(item,surfacePlacement(item,item.x,item.z,next));
  commitSidebar(next);
 }
 useEffect(()=>{
  if(!pendingCandidate||!previewCandidate)return;
  let off=false;
  const timer=setTimeout(()=>api<Validation&{functionalRelations?:Candidate['functionalRelations']}>('/validate',{scene:pendingCandidate}).then(checks=>{
   if(off)return;
   const update=(candidate:Candidate)=>candidate.scene===pendingCandidate?{...candidate,validation:checks,requirements:checks.requirements,functionalRelations:checks.functionalRelations,functionalSpaces:checks.functionalSpaces}:candidate;
   setPreviewCandidate(candidate=>candidate?update(candidate):candidate);
   setPreviewChoices(choices=>choices?.map(update)??null);
   setPendingCandidate(null);
  }).catch(error=>{
   if(off)return;
   setCandidateCheckFailed(true);setPendingCandidate(null);notify(error instanceof Error?error.message:String(error));
  }),250);
  return()=>{off=true;clearTimeout(timer)};
 },[pendingCandidate]);
 useEffect(()=>{
  const changed=()=>setFullscreen(document.fullscreenElement===workspaceRef.current);
  document.addEventListener('fullscreenchange',changed);
  return()=>document.removeEventListener('fullscreenchange',changed);
 },[]);
 useEffect(()=>{
  if(!fullscreen)return;
  const overflow=document.documentElement.style.overflow;
  document.documentElement.style.overflow='hidden';
  const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'&&!document.fullscreenElement)setFullscreen(false)};
  document.addEventListener('keydown',escape);
  return()=>{document.documentElement.style.overflow=overflow;document.removeEventListener('keydown',escape)};
 },[fullscreen]);
 useEffect(()=>{if(libraryOpen&&fullscreen){if(document.fullscreenElement)void document.exitFullscreen();else setFullscreen(false);}},[libraryOpen,fullscreen]);
 async function toggleFullscreen(){
  if(fullscreen){if(document.fullscreenElement===workspaceRef.current)await document.exitFullscreen();else setFullscreen(false);return;}
  try{await workspaceRef.current?.requestFullscreen();}catch{setFullscreen(true);}
 }
 const editOverlays=<>
  {editTarget&&<div className="modal-backdrop" onClick={()=>{if(!busy)closeFurnitureEditor();}}><section className="modal furniture-edit-modal" aria-labelledby="furniture-edit-title" onClick={e=>e.stopPropagation()}>
   <div className="modal-heading"><h2 id="furniture-edit-title">编辑{editTarget.label}</h2><button className="icon-btn" aria-label="关闭编辑窗口" disabled={busy} onClick={closeFurnitureEditor}><X size={20}/></button></div>
   <label className="field">名称<input autoFocus value={editTarget.label} onChange={e=>updateFurnitureEditor(editTarget.id,{label:e.target.value})}/></label>
   <label className="field">来源<select value={editTarget.source} onChange={e=>updateFurnitureEditor(editTarget.id,{source:e.target.value as Item['source']})}>{Object.entries(sourceNames).map(([k,l])=><option key={k} value={k}>{l}</option>)}</select></label>
   <div className="field-grid">{([['width','宽'],['depth','深'],['height','高']] as const).map(([key,label])=><label className="field" key={key}>{label} / m<input type="number" min=".01" step=".05" value={editTarget[key]} onChange={e=>{const value=Number(e.target.value);if(value>0)updateFurnitureEditor(editTarget.id,{[key]:value})}}/></label>)}</div>
   <div className="field-grid">{([['x','X'],['z','Z'],['rotation','角度°']] as const).map(([key,label])=><label className="field" key={key}>{label}<input type="number" disabled={editTarget.locked} step={key==='rotation'?15:.1} value={editTarget[key]} onChange={e=>updateFurnitureEditor(editTarget.id,{[key]:Number(e.target.value)})}/></label>)}</div>
   {['wall_tv','air_conditioner'].includes(editTarget.category)&&<label className="field">安装离地高度 / m<input aria-label="安装离地高度" type="number" min="0.1" step="0.05" disabled={editTarget.locked} value={editTarget.y??0} onChange={e=>updateFurnitureEditor(editTarget.id,{y:Number(e.target.value)})}/><small>解锁后在三维视图沿墙左右、上下拖动，靠近其他墙面自动换墙；可直接生成布局；需要保持原位时再锁定。</small></label>}<div className="toggle-row"><span>必须保留这件家具</span><button aria-label="切换保留状态" aria-pressed={editTarget.keep} className={`toggle ${editTarget.keep?'on':''}`} onClick={()=>updateFurnitureEditor(editTarget.id,{keep:!editTarget.keep})}><span/></button></div>
   <div className="toggle-row"><span>锁定位置与朝向</span><button aria-label="切换位置锁定" aria-pressed={editTarget.locked} className={`toggle ${editTarget.locked?'on':''}`} onClick={()=>updateFurnitureEditor(editTarget.id,{locked:!editTarget.locked})}><span/></button></div>
   <div className="inspector-actions"><button className="btn" disabled={editTarget.locked} onClick={()=>updateFurnitureEditor(editTarget.id,{rotation:(editTarget.rotation+90)%360})}><RotateCw size={14}/>旋转90°</button>{!draftFurniture&&<button className="btn" disabled={uploadBusy} onClick={()=>assetRef.current?.click()}><Box size={14}/>绑定模型/照片</button>}</div>
   {editTarget.photoUrl&&<img className="item-photo" src={editTarget.photoUrl} alt={editTarget.label}/>}
   <div className="modal-actions"><button className="btn" disabled={busy} onClick={finishFurnitureEditor}>完成</button></div>
  </section></div>}
  {deleteTarget&&<div className="modal-backdrop" onClick={()=>setDeleteTargetId(null)}><section className="modal delete-confirm-modal" role="alertdialog" aria-modal="true" aria-labelledby="delete-title" onClick={e=>e.stopPropagation()}><div className="modal-heading"><div><h2 id="delete-title">{deleteTarget.keep?'这件家具必须保留':'删除这件家具？'}</h2></div><button className="icon-btn" aria-label="取消删除" onClick={()=>setDeleteTargetId(null)}><X size={20}/></button></div><p className="hint">{deleteTarget.keep?`“${deleteTarget.label}”当前设置为必须保留。取消保留并删除后，此操作可以撤销。`:`确定删除“${deleteTarget.label}”吗？此操作可以撤销。`}</p><div className="modal-actions"><button className="btn" onClick={()=>setDeleteTargetId(null)}>取消</button><button className="btn danger-action" onClick={()=>deleteFurniture(deleteTarget.id,deleteTarget.keep)}>{deleteTarget.keep?'取消保留并删除':'删除家具'}</button></div></section></div>}
  {contextMenu&&<><button className="context-menu-dismiss" aria-label="关闭菜单" onClick={()=>setContextMenu(null)}/><div className="furniture-context-menu" style={{left:contextMenu.x,top:contextMenu.y}} role="menu"><button role="menuitem" onClick={()=>openFurnitureEditor(contextMenu.id)}><Settings2 size={15}/>编辑家具</button>{!previewCandidate&&<button role="menuitem" className="danger" onClick={()=>{const id=contextMenu.id;setContextMenu(null);removeFurniture(id)}}><Trash2 size={15}/>删除家具</button>}</div></>}
  {notice&&<div className="toast" role="status"><CheckCircle2 size={17}/><span>{notice}</span><button aria-label="关闭提示" onClick={()=>setNotice('')}><X size={15}/></button></div>}
  <input hidden ref={assetRef} type="file" accept=".glb,.gltf,.jpg,.jpeg,.png,.webp" onChange={e=>{const f=e.target.files?.[0];if(f)uploadAsset(f);e.target.value=''}}/>
 </>;
 const workspaceModal=modal&&<div className="modal-backdrop" onClick={()=>setModal(null)}><section className={`modal ${modal==='experiments'?'wide':''}`} onClick={e=>e.stopPropagation()}><div className="modal-heading"><div><h2>{{add:'添加家具',suggest:'补充家具建议',saved:'本机保存的方案',experiments:'训练与验证记录'}[modal]}</h2></div><button className="icon-btn" onClick={()=>setModal(null)}><X size={20}/></button></div>{modal==='add'&&videoDraft?<><p className="hint">???????????????????????????????????????????????????0.30?????????????????????????????????????????????????????????????????????????????????????</p><img className="item-photo" src={videoDraft.photoUrl} alt="??????"/><label className="field">??<select value={videoDraft.category} onChange={e=>{const c=catalog.find(c=>c.category===e.target.value)!;setVideoDraft({...c,photoUrl:videoDraft.photoUrl})}}>{catalog.map(c=><option key={c.category} value={c.category}>{c.label}</option>)}</select></label><label className="field">??<input value={videoDraft.label} onChange={e=>setVideoDraft({...videoDraft,label:e.target.value})}/></label><div className="field-grid">{[['width','???'],['depth','???'],['height','???']].map(([k,l])=><label className="field" key={k}>{l} / m<input min=".04" type="number" step=".05" value={videoDraft[k as 'width']} onChange={e=>setVideoDraft({...videoDraft,[k]:Number(e.target.value)})}/></label>)}</div><button className="btn primary full" onClick={()=>{if([videoDraft.width,videoDraft.depth,videoDraft.height].some(x=>!Number.isFinite(x)||x<=.03))return notify('?????????????????');addItem(videoDraft,'existing',videoDraft.photoUrl);setVideoDraft(null)}}>??????????????????</button></>:modal==='add'&&<><p className="hint">模型为尺寸示意。添加后请按实测修改参数，再确认保留和锁定状态。</p><div className="catalog-grid">{catalog.map(c=><button key={c.category} onClick={()=>addItem(c,'brought')}><span>{catIcon(c.category)}</span><strong>{c.label}</strong><small>{c.width} × {c.depth} × {c.height} m</small><Plus size={15}/></button>)}</div></>}{modal==='suggest'&&<><p className="hint">候选清单尚未对应具体商品。接受后，会按确认尺寸重新检查能否摆放。</p>{suggestions.map((s,i)=><div className="suggestion" key={i}><div><h3>{s.label}</h3><p>{s.reason}</p><small>{s.width} × {s.depth} × {s.height} m · 新增示意模型</small></div><button className="btn" onClick={()=>addItem(s)}>接受<Plus size={14}/></button></div>)}{!suggestions.length&&<p>已有家具可以满足该需求，暂不推荐新增。</p>}</>}{modal==='saved'&&<>{saved.map(s=><button className="saved-row" key={s.id} onClick={()=>load(s.id)}><FolderOpen size={18}/><span><strong>{s.name}</strong><small>版本 {s.version} {s.updatedAt||''}</small></span><ChevronRight size={17}/></button>)}{!saved.length&&<p className="hint">暂无保存的方案。可先编辑示例，再点击保存。</p>}</>}{modal==='experiments'&&<><p className="hint">当前电脑训练出的轻量模型，用于家具位置与朝向重排。以下为实际文件中的结果，不代表任意新组合或家庭场景的准确率。</p><pre className="experiment-json">{JSON.stringify(experiment,null,2)}</pre></>}</section></div>;
 return <div className="app-shell" onPointerDownCapture={()=>{startupUntouched.current=false}} onKeyDownCapture={()=>{startupUntouched.current=false}}>
  {libraryOpen&&<FurnitureLibrary catalog={catalog} initialDraftId={initialFurnitureDraft} onClose={()=>setLibraryOpen(false)} onAdd={asset=>{if(previewCandidate)return notify('请先退出预览或应用方案');const next=clone(current.current),item=furnitureInstance(asset,next.room.width/2,next.room.depth/2);Object.assign(item,initialAppliancePlacement(item,next));next.items.push(item);commit(next,'已加入自有家具，请核对摆放位置；与现有家具重叠会显示空间警告。');setSelectedId(item.id);setLibraryOpen(false)}}/>}
  <header className="app-header"><a className="brand" href="#"><span className="brand-mark"><House size={23}/></span><span>归置</span></a><div className="header-actions"><button className="icon-btn" title="打开已保存方案" onClick={showSaved}><FolderOpen size={18}/></button><button className="icon-btn" title="导入JSON" onClick={()=>importRef.current?.click()} disabled={!!previewCandidate}><ArrowUpFromLine size={18}/></button><button className="icon-btn" title="导出JSON" onClick={()=>downloadJSON(scene,`${scene.name}.json`)} disabled={!!previewCandidate}><ArrowDownToLine size={18}/></button><button className="btn quiet" disabled={!!previewCandidate} onClick={()=>save(true)}><Copy size={15}/>另存</button><button className="btn primary" disabled={!!previewCandidate} onClick={()=>save()}><Save size={16}/>保存方案</button><button className="btn" disabled={!!previewCandidate} onClick={()=>setLibraryOpen(true)}><FileImage size={16}/>自有家具库</button></div></header>
  <main ref={workspaceRef} className={'workspace editor-workspace'+(fullscreen?' is-fullscreen':'')}>
   <div className="canvas-header">
    <div className="workspace-title"><h1 title={scene.name}>{scene.name}</h1><RoomDetails scene={scene}/></div>

   </div>
   <div className="editor-tools">
   <nav className="tabs tool-rail" aria-label="工作台工具">{[['room','房间',House],['furniture','家具',Armchair],['video','视频录入',Film],['results','检查',ShieldCheck]].map(([key,label,Icon])=>{const I=Icon as typeof House;return <button aria-controls="workspace-tool-panel" id={key==='results'?'workspace-checks-tab':undefined} aria-current={tab===key?'page':undefined} title={String(label)} key={String(key)} className={tab===key?'active':''} onClick={()=>showWorkspaceTab(key as Tab)}><span className="tool-icon"><I size={20}/></span><span>{String(label)}</span>{key==='results'&&errors>0&&<i>{errors}</i>}</button>})}</nav>
   <aside className="sidebar" id="workspace-tool-panel">
    <fieldset className="sidebar-content" data-tool={tab} disabled={busy}>
     {tab==='room'&&<><div className="room-form-group"><div className="section-heading"><h2>房间参数</h2><span>单位：米</span></div><label className="field room-inline-field">方案名称<input value={displayScene.name} onChange={e=>commitSidebar({...displayScene,name:e.target.value})}/></label><div className="field-grid">{[['width','宽度'],['depth','进深'],['height','净高']].map(([k,l])=><label className="field" key={k}>{l}<input aria-label={`房间${l}`} type="number" min="1" max="20" step=".1" value={displayScene.room[k as 'width']} onChange={e=>{const v=Number(e.target.value);if(v>0)commitSidebar({...displayScene,room:resizeRoom(displayScene.room,{width:displayScene.room.width,depth:displayScene.room.depth,height:displayScene.room.height,[k]:v})})}}/></label>)}</div></div><div className="room-reference"><div><button className="btn full" disabled={!!previewCandidate} onClick={()=>floorRef.current?.click()}><Plus size={16}/>上传户型参考图</button><p className="hint">仅作参考，尺寸需手动输入。</p></div>{(displayScene.room.referenceImageUrl||floorImg)&&<img className="floor-reference" src={displayScene.room.referenceImageUrl||floorImg||undefined} alt="用户上传的户型参考"/>}</div><div className="room-form-group"><div className="room-section-heading"><h3>门口与净空</h3><label className="field room-inline-field">门所在墙<select value={displayScene.room.door?.wall||'south'} onChange={e=>commitSidebar({...displayScene,room:{...displayScene.room,door:{offset:.45,width:.9,clearance:.9,...displayScene.room.door,wall:e.target.value as 'south'}}})}><option value="south">前墙</option><option value="north">后墙</option><option value="west">左墙</option><option value="east">右墙</option></select></label></div><div className="field-grid">{[['offset','距墙角'],['width','门宽'],['clearance','门内净空']].map(([k,l])=><label className="field" key={k}>{l}<input type="number" min="0" step=".1" value={displayScene.room.door?.[k as 'width']||0} onChange={e=>commitSidebar({...displayScene,room:{...displayScene.room,door:{wall:'south',offset:.45,width:.9,clearance:.9,...displayScene.room.door,[k]:Number(e.target.value)}}})}/></label>)}</div></div><div className="room-form-group"><div className="room-section-heading"><h3>窗户参考</h3><p className="hint">窗户位于后墙。</p></div><div className="field-grid room-window-fields"><label className="field">距墙角<input type="number" step=".1" value={displayScene.room.windows[0]?.offset||0} onChange={e=>commitSidebar({...displayScene,room:{...displayScene.room,windows:[{...(displayScene.room.windows[0]||{id:'window-1',wall:'north',width:1.5,sillHeight:.9}),offset:Number(e.target.value)},...displayScene.room.windows.slice(1)]}})}/></label><label className="field">窗宽<input type="number" min=".1" step=".1" value={displayScene.room.windows[0]?.width||1.5} onChange={e=>commitSidebar({...displayScene,room:{...displayScene.room,windows:[{...(displayScene.room.windows[0]||{id:'window-1',wall:'north',offset:2.3,sillHeight:.9}),width:Number(e.target.value)},...displayScene.room.windows.slice(1)]}})}/></label><label className="field">窗台高<input aria-label="窗台高度" type="number" min="0" step=".05" value={displayScene.room.windows[0]?.sillHeight??.9} onChange={e=>commitSidebar({...displayScene,room:{...displayScene.room,windows:[{...(displayScene.room.windows[0]||{id:'window-1',wall:'north',offset:2.3,width:1.5}),sillHeight:Number(e.target.value)},...displayScene.room.windows.slice(1)]}})}/></label><label className="field">窗高<input aria-label="窗户高度" type="number" min=".11" step=".05" value={displayScene.room.windows[0]?.height??1.05} onChange={e=>commitSidebar({...displayScene,room:{...displayScene.room,windows:[{...(displayScene.room.windows[0]||{id:'window-1',wall:'north',offset:2.3,width:1.5,sillHeight:.9}),height:Number(e.target.value)},...displayScene.room.windows.slice(1)]}})}/></label></div></div></>}
     {tab==='furniture'&&<><div className="section-heading"><h2>我的家具 <span className="count">{displayScene.items.length}</span></h2><button className="text-btn" disabled={!!previewCandidate} onClick={()=>{setVideoDraft(null);setModal('add')}}><Plus size={15}/>添加</button></div><div className="inventory-layout"><div className="inventory-list"><div className="items-list">{!displayScene.items.length&&<div className="empty-state"><Armchair size={24}/><strong>还没有家具</strong><p>从下方录入家具，或从图片生成家具。</p></div>}{displayScene.items.map(it=><button key={it.id} className={`item-card ${previewSelection===it.id?'selected':''}`} aria-pressed={previewSelection===it.id} onClick={()=>selectCanvasItem(it.id)}><span className={`item-symbol ${it.source}`}><FurnitureThumb item={it}/></span><span className="item-card-text"><strong>{it.label}</strong><small>{it.width.toFixed(2)} × {it.depth.toFixed(2)} m</small></span>{it.locked?<LockKeyhole size={15} className="lock-icon"/>:<ChevronRight size={15}/>}</button>)}</div><button className="add-outline" disabled={!!previewCandidate} onClick={()=>{setVideoDraft(null);setModal('add')}}><Plus size={17}/>录入一件家具</button><button className="btn full" disabled={!!previewCandidate} onClick={()=>setLibraryOpen(true)}><FileImage size={16}/>从图片生成家具</button><div className="suggest-box"><span><Sparkles size={16}/>补充家具</span><div>{[['work','办公'],['storage','收纳'],['reading','阅读']].map(([k,l])=><button key={k} disabled={!!previewCandidate} onClick={()=>suggest(k)}>{l}<ArrowUpRight size={12}/></button>)}</div></div></div>{selected&&<div className="inventory-inspector"><details className="inspector-fold" open={inspectorOpen} onToggle={e=>setInspectorOpen(e.currentTarget.open)}><summary className="inspector-heading"><strong>编辑选中家具</strong><span><ChevronDown size={15}/></span></summary><label className="field">名称<input value={selected.label} onChange={e=>editSidebarItem(selected.id,{label:e.target.value})}/></label><label className="field">来源<select value={selected.source} onChange={e=>editSidebarItem(selected.id,{source:e.target.value as Item['source']})}>{Object.entries(sourceNames).map(([k,l])=><option key={k} value={k}>{l}</option>)}</select></label><div className="field-grid">{[['width','宽'],['depth','深'],['height','高']].map(([k,l])=><label className="field" key={k}>{l} / m<input aria-label={`家具${l}`} type="number" min=".01" step=".05" value={selected[k as 'width']} onChange={e=>{const v=Number(e.target.value);if(v>0)editSidebarItem(selected.id,{[k]:v})}}/></label>)}</div><div className="field-grid">{[['x','X'],['z','Z'],['rotation','角度°']].map(([k,l])=><label className="field" key={k}>{l}<input type="number" disabled={selected.locked} step={k==='rotation'?15:.1} value={selected[k as 'x']} onChange={e=>editSidebarItem(selected.id,{[k]:Number(e.target.value)})}/></label>)}</div>{['wall_tv','air_conditioner'].includes(selected.category)&&<label className="field">安装离地高度 / m<input aria-label="安装离地高度" type="number" min="0.1" step="0.05" disabled={selected.locked} value={selected.y??0} onChange={e=>editSidebarItem(selected.id,{y:Number(e.target.value)})}/><small>解锁后在三维视图沿墙左右、上下拖动，靠近其他墙面自动换墙；可直接生成布局；需要保持原位时再锁定。</small></label>}<div className="toggle-row"><span>必须保留这件家具</span><button aria-label="切换保留状态" aria-pressed={selected.keep} className={`toggle ${selected.keep?'on':''}`} onClick={()=>editSidebarItem(selected.id,{keep:!selected.keep})}><span/></button></div><div className="toggle-row"><span>锁定位置与朝向</span><button aria-label="切换位置锁定" aria-pressed={selected.locked} className={`toggle ${selected.locked?'on':''}`} onClick={()=>editSidebarItem(selected.id,{locked:!selected.locked})}><span/></button></div><div className="inspector-actions"><button className="btn" disabled={selected.locked} onClick={()=>editSidebarItem(selected.id,{rotation:(selected.rotation+90)%360})}><RotateCw size={14}/>旋转90°</button><button className="btn" disabled={uploadBusy||!!previewCandidate} onClick={()=>assetRef.current?.click()}><Box size={14}/>绑定模型/照片</button></div></details>{['storage_box','laptop'].includes(selected.category)&&<p className="support-inspector-note">{selected.supportId?`已放在${displayScene.items.find(item=>item.id===selected.supportId)?.label||'家具'}台面（离地 ${(selected.y??0).toFixed(2)} m），可在台面上拖动或拖离。`:'拖近尺寸合适的桌面或低柜顶部可自动吸附；继续拖远会放回地面。'}</p>}{selected.photoUrl&&<img className="item-photo" src={selected.photoUrl} alt={selected.label}/>}<button className="text-btn danger" disabled={!!previewCandidate} onClick={()=>removeFurniture(selected.id)}><Trash2 size={14}/>移除这件家具</button></div>}</div></>}
     {tab==='video'&&<><div className="section-heading"><h2>房内视频录入</h2></div><div className="video-upload" onClick={()=>videoRef.current?.click()} role="button" tabIndex={0} onKeyDown={e=>{if(e.key==='Enter')videoRef.current?.click()}}><Film size={28}/><strong>{uploadBusy?'上传中…':'上传一段房内视频'}</strong><p>MP4 / MOV · 最多100MB、2分钟</p><button className="btn" disabled={uploadBusy||!!jobId}>选择视频</button></div>{jobId&&<div className="progress"><span>本机处理中 {Math.round((video?.progress||0)*100)}%</span><div><i style={{width:`${(video?.progress||.03)*100}%`}}/></div></div>}{video?.error&&<p className="error-message">{video.error}</p>}{video?.status==='complete'&&<><h3>识别候选 <span className="count">{video.candidates.length}</span></h3>{!video.candidates.length&&<p className="hint">未识别到受支持家具，可以从下方截图确认并手工录入。</p>}{video.candidates.map((v,i)=><div className="video-candidate" key={v.trackId||i}><img src={v.frameUrl} alt={`候选${v.label}`}/><div><strong>{v.label}</strong><small>置信度 {Math.round(v.confidence*100)}% · 需人工确认</small><button className="text-btn" onClick={()=>{const c=catalog.find(c=>c.category===v.category);if(c)addItem({...c,label:`房内${v.label}`},'existing',v.frameUrl);else notify('请选择家具类别和实测尺寸后录入')}}>确认并添加<Plus size={14}/></button></div></div>)}<h3>关键画面</h3><div className="video-frames">{video.frames.map(f=><button key={f.id} onClick={()=>{setModal('add');notify('选择类别后录入，请按实测修正尺寸')}}><img src={f.url} alt={`${f.timestamp.toFixed(1)}秒`}/><span>{f.timestamp.toFixed(1)} s</span></button>)}</div></>}</>}
     {tab==='results'&&<><div className="section-heading"><h2>空间检查</h2><span>{previewCandidate?'候选方案':'当前方案'}</span></div><div className={`validation-hero ${displayValidation?.valid&&!requiredUnmet?'pass':'warn'}`}><ShieldCheck size={26}/><strong>{displayValidation?displayValidation.valid?(requiredUnmet?'空间检查通过，功能空间或布局要求未满足':'通过当前空间检查'):`${previewErrors} 项需要调整`:'检查中'}</strong></div>{displayValidation?.issues.map((issue,i)=><button key={i} className={`issue ${issue.severity}`} onClick={()=>selectCanvasItem(issue.itemIds?.[0]||null)}><span className="issue-dot"/><span>{issue.message}</span><ChevronRight size={15}/></button>)}<div className="metric-grid">{Object.entries(displayValidation?.metrics||{}).filter(([,v])=>typeof v!=='object').slice(0,8).map(([k,v])=><div key={k}><span>{{collisions:'碰撞数',outOfBounds:'越界数',doorConflicts:'门口冲突',cabinetDoorConflicts:'柜门净空冲突',reachable:'通路可达',checkedItems:'家具数'}[k]||k}</span><strong>{typeof v==='boolean'?(v?'是':'否'):String(v??'未检查')}</strong></div>)}</div>{displayValidation&&<><FunctionalSpaceChecks candidate={previewCandidate||displayValidation!}/><WallApplianceChecks result={displayValidation?.wallAppliances}/></>}<button className="btn full" onClick={showExperiments}><Layers3 size={16}/>查看模型实验记录</button></>}
    </fieldset><div className="sidebar-footer"><span className={`status-dot ${health?'':'offline'}`}/>{health?'本机服务已连接':'等待本机服务'}<button onClick={showExperiments}>实验记录<ArrowUpRight size={12}/></button></div>
   </aside>
   </div>
   <div className="planning-panel">
  <RoomPreview
   scene={displayScene} validation={displayValidation} selectedId={previewSelection}
   selected={displayScene.items.find(item=>item.id===previewSelection)} onSelect={selectCanvasItem}
   onContextMenu={openItemMenu} onMove={editItem} onEditRoom={selectCanvasRoom}
   candidate={previewCandidate} candidates={previewChoices??candidates} status={previewStatus} valid={!!displayValidation?.valid&&!requiredUnmet}
   canUndo={!!history.current.length} onUndo={undo} onClose={exitPreview} fullscreen={fullscreen} onToggleFullscreen={toggleFullscreen}
   onCheck={showCanvasChecks} onSwitch={preview} onApply={applyCandidate} busy={busy||!!pendingCandidate} applyDisabled={candidateCheckFailed}
   checks={previewCandidate&&<>
    {displayValidation?.issues.map((issue,index)=><button key={index} className={`issue ${issue.severity}`} onClick={()=>setCandidateSelectedId(issue.itemIds?.[0]??null)}><span className="issue-dot"/><span>{issue.message}</span></button>)}
    <RequirementChecks candidate={previewCandidate}/>
    <FunctionalRelationChecks candidate={previewCandidate}/>
    <FunctionalSpaceChecks candidate={previewCandidate||displayValidation!}/><WallApplianceChecks result={displayValidation?.wallAppliances}/>
    {!displayValidation?.issues.length&&!previewCandidate.requirements?.checks.length&&!previewCandidate.functionalRelations?.checks.length&&!previewCandidate.functionalSpaces?.checks.length&&!displayValidation?.wallAppliances?.checks.length&&<p>没有发现问题</p>}
   </>}
  >{editOverlays}{workspaceModal}</RoomPreview>
    <div className="plan-controls">{commandWarning&&<div className="command-warning" role="alert"><div><strong>本次文字要求未应用</strong><p>{commandWarning}</p><small>请修改后重新发送，或忽略本次要求。</small></div><button className="btn" disabled={busy} onClick={()=>{setCommandWarning('');notify('已忽略本次未应用的文字要求；生成只使用已识别的条件')}}>忽略本次要求</button></div>}<section className="generation-bar" aria-busy={busy}><div className="generation-copy"><span className="sparkle-badge"><Sparkles size={18}/></span><div><h3>布局方案</h3></div></div><div className="generation-actions"><select aria-label="布局方法" value={mode} onChange={e=>setMode(e.target.value as typeof mode)}><option value="hybrid">功能组布局</option><option value="rules">规则布局</option><option value="model" disabled={!health?.modelLoaded}>仅重排模型</option></select><button className="btn primary" disabled={busy||!!previewCandidate||!!commandWarning} onClick={()=>generate()}><Sparkles size={16}/>{busy?'计算中…':'生成布局'}</button></div><div className="generation-disclosures"><button type="button" className="btn plans-toggle" aria-expanded={plansExpanded} aria-controls="layout-candidates" aria-label={plansExpanded?'折叠方案':'展开方案'} onClick={()=>setPlansExpanded(open=>!open)}><span>方案</span><span>{plansExpanded?'折叠':'展开'}</span><ChevronDown size={15} aria-hidden="true"/></button><button type="button" className="btn requirements-toggle" aria-expanded={requirementsExpanded} aria-controls="identified-layout-requirements" aria-label={requirementsExpanded?'折叠已识别的布局要求':'展开已识别的布局要求'} onClick={()=>setRequirementsExpanded(open=>!open)}><span>布局要求</span><span>{requirementsExpanded?'折叠':'展开'}</span><ChevronDown size={15} aria-hidden="true"/></button></div></section>
    <section id="layout-candidates" className="candidate-panel" hidden={!plansExpanded} aria-label="方案">
     {visibleCandidates.length>0?<div className="candidate-strip">{visibleCandidates.map((candidate,index)=><div key={candidate.id} className={'candidate-card'+(previewCandidate?.id===candidate.id?' active':'')}>
      <span className="candidate-number">{String(index+1).padStart(2,'0')}</span>
      <div className="candidate-overview"><h4>方案 {index+1}</h4><span className={`candidate-status ${candidate.validation.valid?'passed':'needs-adjustment'}`}>{candidate.validation.valid?'空间通过':'需要检查'}</span><small className="candidate-difference">{candidate.diversity?.reasons?.length?candidate.diversity.reasons.slice(0,2).join('；'):'基准方案'}</small></div>
      <button className="btn preview-action" aria-label={`预览方案 ${index+1}`} aria-pressed={previewCandidate?.id===candidate.id} disabled={busy||!!pendingCandidate} onClick={()=>preview(candidate)}><Eye size={15}/>预览</button>
     </div>)}</div>:<p className="plans-empty">暂无方案，生成布局后可在这里查看。</p>}
    </section>
    <section id="identified-layout-requirements" className="identified-requirements" hidden={!requirementsExpanded} aria-label="已识别的布局要求"><div className="requirements-heading"><h3>已识别的布局要求</h3></div>{scene.preferences.length?<ul>{scene.preferences.map((p,index)=><li key={`${p.kind}-${p.itemId}-${index}`}><span className={`requirement-tag ${p.required?'required':''}`}>{p.required?'必须':'尽量'}</span><span>{preferenceLabel(p,scene)}</span><button aria-label={`移除要求：${preferenceLabel(p,scene)}`} disabled={busy||!!previewCandidate} onClick={()=>commit({...current.current,preferences:current.current.preferences.filter((_,i)=>i!==index)},'已移除这项布局要求')}><X size={13}/></button></li>)}</ul>:<p>暂无要求</p>}{scene.items.some(i=>i.locked)&&<p>保持原位与朝向：{scene.items.filter(i=>i.locked).map(i=>i.label).join('、')}</p>}{!previewCandidate&&!!validation?.requirements?.checks.length&&<div className="current-requirement-status"><p>当前布局</p><RequirementChecks candidate={validation}/></div>}</section>
    <div className="editor-conversation"><LayoutConversation compact draft={cmd} onDraft={setCmd} onSend={command} busy={busy||!!pendingCandidate} messages={messages}/></div>

    </div>
   </div>
  </main>
  <input hidden ref={importRef} type="file" accept=".json" onChange={e=>{const f=e.target.files?.[0];if(f)importFile(f);e.target.value=''}}/>
  <input hidden ref={floorRef} type="file" accept="image/*" onChange={e=>{const f=e.target.files?.[0];if(f)uploadFloor(f);e.target.value=''}}/>
  <input hidden ref={videoRef} type="file" accept="video/*,.mp4,.mov,.avi" onChange={e=>{const f=e.target.files?.[0];if(f)analyzeVideo(f);e.target.value=''}}/>
 </div>;
}
