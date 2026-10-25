import {useEffect,useMemo,useRef,useState} from 'react';
import {X} from 'lucide-react';
import {api,clone,type CatalogItem,type FurnitureAsset,type FurnitureDraft,type FurnitureJob,type FurnitureParameters,type FurnitureProperties,type Item} from './types';
import {exportFurnitureGLB,parameterKeys,resetCategoryParameters} from './furnitureMesh';
import {completeFurnitureProperties} from './furnitureProperties';
import FurniturePreview from './FurniturePreview';
import FurnitureCrop from './FurnitureCrop';

type Props={catalog:CatalogItem[];onClose:()=>void;onAdd:(asset:FurnitureAsset)=>void;initialDraftId?:string|null};
const publishConfirmations={category:true,label:true,dimensions:true,direction:true,structure:true};
const sourceNames={annotation:'图纸标注读取',estimated:'视觉估计，非测量',user:'用户填写',template:'模板尺寸',unknown:'无法判断'};
const parameterNames:Record<keyof FurnitureParameters,string>={primaryColor:'主色',secondaryColor:'辅助色',material:'外观材质',hasBack:'靠背',hasArms:'扶手',hasLegs:'支腿',drawerCount:'抽屉数量',doorCount:'柜门数量',shelfCount:'层板数量',seatCount:'座位数',seatHeightRatio:'座面高度 / 总高'};
const materialNames={unknown:'未知',wood:'木质外观',fabric:'织物外观',leather:'皮革外观',metal:'金属外观',plastic:'塑料外观',glass:'玻璃外观',mixed:'混合'};

export function furnitureInstance(asset:FurnitureAsset,x:number,z:number):Item{
 const snapshot=clone(asset.snapshot);
 return {id:crypto.randomUUID(),label:snapshot.label,category:snapshot.category,width:snapshot.width,depth:snapshot.depth,height:snapshot.height,x,z,rotation:0,keep:true,locked:false,source:'brought',assetUrl:asset.assetUrl,photoUrl:asset.photoUrls[0],furnitureAssetId:asset.id,furnitureSnapshot:snapshot};
}

async function multipart<T>(path:string,form:FormData):Promise<T>{
 const response=await fetch(`/api${path}`,{method:'POST',body:form});
 const body=await response.json();if(!response.ok)throw new Error(typeof body.detail==='string'?body.detail:'文件提交失败，请检查格式和大小');return body;
}

export default function FurnitureLibrary({catalog,onClose,onAdd,initialDraftId}:Props){
 const [assets,setAssets]=useState<FurnitureAsset[]>([]),[drafts,setDrafts]=useState<FurnitureDraft[]>([]),[draft,setDraft]=useState<FurnitureDraft|null>(null),[properties,setProperties]=useState<FurnitureProperties|null>(null);
 const [files,setFiles]=useState<File[]>([]),[consent,setConsent]=useState(false),[busy,setBusy]=useState(false),[message,setMessage]=useState(''),[jobId,setJobId]=useState<string|null>(null),[job,setJob]=useState<FurnitureJob|null>(null);
 const [status,setStatus]=useState<{enabled:boolean;message:string}|null>(null),[dirty,setDirty]=useState(false),[styleText,setStyleText]=useState('');
 const requestId=useRef(crypto.randomUUID()),pendingPublish=useRef<{draftId:string;expectedVersion:number;assetUrl:string;requestId:string}|null>(null),openGeneration=useRef(0),alive=useRef(true),inFlight=useRef(false);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;openGeneration.current++}},[]);
 async function refresh(){const listing=await api<{assets:FurnitureAsset[];drafts:FurnitureDraft[]}>('/furniture');if(alive.current){setAssets(listing.assets);setDrafts(listing.drafts)}}
 useEffect(()=>{refresh().catch(error=>setMessage(String(error)));api<{enabled:boolean;message:string}>('/furniture/status').then(setStatus).catch(error=>setMessage(String(error)))},[]);
 useEffect(()=>{if(initialDraftId)openDraft(initialDraftId)},[initialDraftId]);
 function loadDraft(value:FurnitureDraft){setDraft(value);setProperties(clone(value.properties));setStyleText(value.properties.styleTags.join(','));setChecks({...initialChecks});setDirty(false);requestId.current=crypto.randomUUID();pendingPublish.current=null}
 function clearEditor(){setDraft(null);setProperties(null);setJob(null);setJobId(null);setDirty(false);setStyleText('');setChecks({...initialChecks});pendingPublish.current=null;requestId.current=crypto.randomUUID()}
 async function openDraft(identifier:string){
  if(inFlight.current)return;const generation=++openGeneration.current;setJobId(null);
  try{const value=await api<FurnitureDraft>(`/furniture/drafts/${identifier}`);if(!alive.current||generation!==openGeneration.current)return;loadDraft(value);setMessage('');setJob(null);if(value.jobId)setJobId(value.jobId);else setJobId(null)}catch(error){if(alive.current&&generation===openGeneration.current)setMessage(String(error))}
 }
 useEffect(()=>{
  if(!jobId||busy)return;let cancelled=false,timer:ReturnType<typeof setTimeout>;const generation=openGeneration.current;
  const stale=()=>cancelled||!alive.current||generation!==openGeneration.current;
  const poll=async()=>{
   try{const result=await api<FurnitureJob>(`/furniture/jobs/${jobId}`);if(stale())return;setJob(result);
    if(result.errorCode==='draft_deleted'){clearEditor();setMessage('草稿已删除。');refresh().catch(()=>{});return}
    if(result.status==='complete'||result.status==='failed'){
     const value=await api<FurnitureDraft>(`/furniture/drafts/${result.draftId}`);if(stale())return;loadDraft(value);setJobId(null);if(result.error)setMessage(result.error);refresh().catch(()=>{});
    }else timer=setTimeout(poll,1200);
   }catch(error){if(!stale()){setMessage(`状态查询失败，草稿仍保留。${String(error)}`);timer=setTimeout(poll,3000)}}
  };poll();return()=>{cancelled=true;clearTimeout(timer)};
 },[jobId,busy]);
 function update(patch:Partial<FurnitureProperties>){
  if(!properties)return;let next={...properties,...patch,dimensionSources:{...properties.dimensionSources}};
  for(const key of ['width','depth','height'] as const){
   if(key in patch)next.dimensionSources[key]=draft&&patch[key]===draft.properties[key]?draft.properties.dimensionSources[key]:patch[key]===null?'unknown':'user';
   if('category' in patch&&patch.category!==properties.category&&next.dimensionSources[key]==='template'){next[key]=null;next.dimensionSources[key]='unknown'}
  }
  if('category' in patch)next=completeFurnitureProperties(next,catalog);
  setProperties(next);setDirty(true);pendingPublish.current=null;requestId.current=crypto.randomUUID();
 }
 function updateParameter(key:keyof FurnitureParameters,value:unknown){if(properties)update({parameters:{...properties.parameters,[key]:value}})}
 async function guarded(operation:()=>Promise<void>){if(inFlight.current)return;inFlight.current=true;setBusy(true);setMessage('');try{await operation()}catch(error){if(alive.current)setMessage(error instanceof Error?error.message:String(error))}finally{inFlight.current=false;if(alive.current)setBusy(false)}}
 async function submit(){await guarded(async()=>{
  if(!consent)throw new Error('请先同意云端图片识别和可能的费用');
  if(files.length<1||files.length>3)throw new Error('请选择 1—3 张图片');
  const form=new FormData();files.forEach(file=>form.append('files',file));form.append('consent','true');
  const result=await multipart<{draftId:string;jobId:string}>('/furniture/analyze',form);openGeneration.current++;
  const value=await api<FurnitureDraft>(`/furniture/drafts/${result.draftId}`);if(!alive.current)return;loadDraft(value);setJob(null);setJobId(result.jobId);setFiles([]);await refresh();
 })}
 async function saveDraft(){if(!draft||!properties)return;await guarded(async()=>{const value=await api<FurnitureDraft>(`/furniture/drafts/${draft.id}/save`,{expectedVersion:draft.version,properties:completeFurnitureProperties(properties,catalog)});if(alive.current){setDraft(value);setProperties(clone(value.properties));setDirty(false);pendingPublish.current=null;requestId.current=crypto.randomUUID();setMessage('草稿已保存到本机。')}await refresh()})}
 const modelProperties=useMemo(()=>properties?completeFurnitureProperties(properties,catalog):null,[properties,catalog]);
 const preview=useMemo<Item|null>(()=>{
  if(!modelProperties?.category||!modelProperties.width||!modelProperties.depth||!modelProperties.height)return null;
  const snapshot={...modelProperties,version:1,label:modelProperties.label||'待确认家具',category:modelProperties.category,width:modelProperties.width,depth:modelProperties.depth,height:modelProperties.height,photoUrls:draft?.photoUrls||[],frontDirection:modelProperties.frontDirection||'positive_z',dimensionsConfirmed:true as const};
  return {id:'furniture-preview',label:snapshot.label,category:snapshot.category,width:snapshot.width,depth:snapshot.depth,height:snapshot.height,x:0,z:0,rotation:0,keep:true,locked:false,source:'brought',furnitureSnapshot:snapshot};
 },[modelProperties,draft?.photoUrls]);
 async function publish(){if(!draft||!modelProperties||!preview)return;await guarded(async()=>{
  let pending=pendingPublish.current;
  if(!pending){
   const saved=await api<FurnitureDraft>(`/furniture/drafts/${draft.id}/save`,{expectedVersion:draft.version,properties:modelProperties});
   if(alive.current){setDraft(saved);setProperties(clone(saved.properties));setDirty(false)}
   const blob=await exportFurnitureGLB(preview);const form=new FormData();form.append('file',blob,'furniture.glb');
   const uploaded=await multipart<{url:string}>('/assets',form);
   pending={draftId:draft.id,expectedVersion:saved.version,assetUrl:uploaded.url,requestId:requestId.current};pendingPublish.current=pending;
  }
  await api<FurnitureAsset>(`/furniture/drafts/${pending.draftId}/publish`,{requestId:pending.requestId,expectedVersion:pending.expectedVersion,assetUrl:pending.assetUrl,confirmations:publishConfirmations});
  if(alive.current){setDraft(null);setProperties(null);setJob(null);pendingPublish.current=null}await refresh();
 })}
 async function retry(){if(!draft)return;await guarded(async()=>{if(!consent)throw new Error('请重新勾选同意云端发送与计费');const result=await api<{jobId:string}>(`/furniture/drafts/${draft.id}/retry`,{consent:true});setJob(null);setJobId(result.jobId)})}
 async function editAsset(asset:FurnitureAsset){await guarded(async()=>{const value=await api<FurnitureDraft>(`/furniture/${asset.id}/edit`,{});openGeneration.current++;loadDraft(value);setJob(null);setJobId(null);await refresh()})}
 async function deleteAsset(asset:FurnitureAsset){
  if(!window.confirm(`从家具库删除“${asset.snapshot.label}”？已加入房间和已保存方案中的家具会保留。`))return;
  await guarded(async()=>{
   openGeneration.current++;
   try{await api(`/furniture/${asset.id}?expectedVersion=${asset.version}`,undefined,'DELETE')}catch(error){await refresh().catch(()=>{});throw error}
   if(alive.current){
    setAssets(previous=>previous.filter(value=>value.id!==asset.id));
    setDrafts(previous=>previous.filter(value=>value.editingAssetId!==asset.id&&value.publishedAssetId!==asset.id));
    if(draft?.editingAssetId===asset.id||draft?.publishedAssetId===asset.id){setDraft(null);setProperties(null);setJob(null);setJobId(null);setDirty(false);setChecks({...initialChecks});pendingPublish.current=null}
    setMessage(`已从家具库删除“${asset.snapshot.label}”。已加入房间和已保存方案中的家具仍保留。`);
   }
   await refresh();
  });
 }
 async function deleteDraft(value:FurnitureDraft){
  const name=value.properties.label||'未命名家具';
  if(!window.confirm(`删除草稿“${name} · ${value.id.slice(0,8)}”？该草稿中的未保存修改也会丢弃，已确认家具会保留。`))return;
  await guarded(async()=>{
   // Invalidate pending draft loads and job replies before sending the deletion.
   openGeneration.current++;
   try{await api(`/furniture/drafts/${value.id}?expectedVersion=${value.version}`,undefined,'DELETE')}catch(error){await refresh().catch(()=>{});throw error}
   if(alive.current){setDrafts(previous=>previous.filter(entry=>entry.id!==value.id));if(draft?.id===value.id)clearEditor();setMessage(`草稿“${name}”已删除。`)}
   await refresh();
  });
 }
 function selectFiles(selected:FileList|null){if(!selected)return;const values=Array.from(selected);if(values.length>3||values.some(file=>file.size>10*1024*1024||!(/\.(jpe?g|png|webp)$/i.test(file.name)))){setMessage('请选择 1—3 张 JPEG、PNG、WebP，每张不超过 10 MB。');return}setFiles(values);setMessage('')}
 return <div className="modal-backdrop furniture-backdrop"><section className="modal furniture-library" role="dialog" aria-modal="true" aria-labelledby="furniture-title">
  <div className="modal-heading"><div><span className="eyebrow">OWNED FURNITURE</span><h2 id="furniture-title">自有家具库 · 从图片添加</h2></div><button className="icon-btn" aria-label="关闭自有家具库" disabled={busy} onClick={()=>{if(dirty&&!window.confirm('有未保存的修改，确认关闭？原草稿仍保留。'))return;onClose()}}><X size={20}/></button></div>
  <p className="furniture-intro">上传 1–3 张家具照片。识别后核对类别、尺寸与朝向，再保存到家具库。</p>
  <div className={`furniture-service ${status?.enabled?'ready':'offline'}`} role="status"><span className="furniture-service-dot"/><div><strong>{status?.enabled?'识别服务已就绪':'本地草稿模式'}</strong><span>{status?.enabled?'勾选同意后才会发送图片；识别可能产生费用。':'识别服务未启用。你仍可保留草稿并手动补全信息。'}</span></div></div>
  <fieldset disabled={busy||!!jobId} className="furniture-upload"><legend>1. 选择照片</legend><input aria-label="选择家具图片" type="file" multiple accept=".jpg,.jpeg,.png,.webp" onChange={event=>{selectFiles(event.target.files);event.target.value=''}}/><p className="furniture-upload-note">JPG、PNG 或 WebP · 最多 3 张，每张不超过 10 MB · 建议包含正面和侧面</p>
   <div className="furniture-crops">{files.map((file,index)=><FurnitureCrop key={index} file={file} index={index} onChange={replacement=>setFiles(previous=>previous.map((value,position)=>position===index?replacement:value))}/>)}</div>
   <label className="furniture-check furniture-consent" aria-label="我同意将所选图片发送到第三方网关 api.tokenlab.pro（非 OpenAI 官方域名），请求 gpt-6-sol / high 进行识别，可能产生服务费用。服务关闭时仅保存在本机。"><input type="checkbox" checked={consent} onChange={event=>setConsent(event.target.checked)}/><span>我同意将照片发送到第三方网关 <strong>api.tokenlab.pro</strong>（非 OpenAI 官方域名）进行识别，可能产生费用。</span></label>
   <button className="btn primary" disabled={!files.length||!consent} onClick={submit}>上传并识别家具</button>
  </fieldset>
  {message&&<p className="furniture-message" role="status">{message}</p>}
  {jobId&&<p role="status">{job?.status==='processing'?'正在联合识别视图…':'识别任务已排队…'} 可以关闭窗口；任务和草稿保存在本机。请勿重复提交。</p>}
  {draft&&properties&&<fieldset disabled={busy||!!jobId} className="furniture-editor"><legend>2. 核对属性与三维预览</legend>
   <div className="furniture-photos">{draft.photoUrls.map((url,index)=><a href={url} target="_blank" rel="noreferrer" key={url}><img src={url} alt={`家具原图 ${index+1}`}/></a>)}</div>
   {draft.recognition&&<details className="furniture-evidence"><summary>识别详情</summary><p>{draft.recognition.views.map(view=>`图${view.imageIndex+1} ${view.view}：${view.description}`).join('；')}</p>{[...draft.recognition.warnings,...draft.recognition.uncertainFields].map((text,index)=><p key={index}>{text}</p>)}</details>}
   <div className="furniture-editor-grid"><div>
    <label className="field">家具名称<input value={properties.label||''} onChange={event=>update({label:event.target.value||null})}/></label>
    <label className="field">家具类别<select aria-label="家具类别" value={properties.category||''} onChange={event=>{const category=event.target.value||null;update({category,parameters:resetCategoryParameters(category,properties.parameters),frontDirection:category?(category.includes('bed')?'negative_z':'positive_z'):null})}}><option value="">未知 / 请选择受支持的近似类别</option>{catalog.map(value=><option key={value.category} value={value.category}>{value.label}</option>)}</select></label>
    <label className="field">细分类别<input value={properties.subtype||''} onChange={event=>update({subtype:event.target.value||null})}/></label>
    <div className="field-grid">{(['width','depth','height'] as const).map(key=><label className="field" key={key}>{{width:'宽',depth:'深',height:'高'}[key]} / m<input aria-label={`家具${{width:'宽',depth:'深',height:'高'}[key]}（米）`} type="number" step="0.01" min={key==='height'?.011:.031} max={key==='height'?10:20} value={properties[key]??''} onChange={event=>update({[key]:event.target.value===''?null:Number(event.target.value)})}/><small>{sourceNames[properties.dimensionSources[key]]}{properties.evidence[key]&&` · ${properties.evidence[key]}`}</small>{draft.recognition&&<small>模型原值：{draft.recognition.properties[key]??'未知'} m</small>}</label>)}</div>
    <label className="field">规范正面 / 床头方向<select value={properties.frontDirection||''} onChange={event=>update({frontDirection:(event.target.value||null) as FurnitureProperties['frontDirection']})}><option value="">无法判断，请核对</option><option value="positive_z">其他家具：使用面 +z</option><option value="negative_z">床：床头 -z</option></select></label>
    <label className="field">风格标签（逗号分隔，外观判断）<input value={styleText} onChange={event=>{setStyleText(event.target.value);update({styleTags:event.target.value.split(/[,，]/).map(value=>value.trim()).filter(Boolean)})}}/></label>
   </div><div><FurniturePreview item={preview}/><p className="hint">参数化近似模型，不是实物重建。未知颜色与结构采用模板默认值；画面正面在 +z，床头在 -z。碰撞按确认的矩形占地检查。</p></div></div>
   <div className="furniture-parameters">{parameterKeys(properties.category).map(key=>{
    const value=properties.parameters[key];
    if(key==='material')return <label className="field" key={key}>{parameterNames[key]}<select value={properties.parameters.material} onChange={event=>updateParameter(key,event.target.value)}>{Object.entries(materialNames).map(([code,name])=><option value={code} key={code}>{name}</option>)}</select></label>;
    if(key==='primaryColor'||key==='secondaryColor')return <label className="field" key={key}>{parameterNames[key]}{value===null?'（模板默认）':''}<input aria-label={parameterNames[key]} type="color" value={typeof value==='string'?value:key==='primaryColor'?'#b28c65':'#e8e2d6'} onChange={event=>updateParameter(key,event.target.value)}/><button className="btn quiet" onClick={()=>updateParameter(key,null)}>使用模板</button></label>;
    if(key.startsWith('has'))return <label className="field" key={key}>{parameterNames[key]}<select value={value===null?'':String(value)} onChange={event=>updateParameter(key,event.target.value===''?null:event.target.value==='true')}><option value="">未知，模板补全</option><option value="true">有</option><option value="false">无</option></select></label>;
    return <label className="field" key={key}>{parameterNames[key]}{value===null?'（模板默认）':''}<input type="number" step={key==='seatHeightRatio'?.01:1} min={key==='seatHeightRatio'?.15:key==='shelfCount'||key==='seatCount'?1:0} max={key==='seatHeightRatio'?.8:key==='seatCount'||key==='doorCount'?8:12} value={typeof value==='number'?value:''} placeholder="未知，模板补全" onChange={event=>updateParameter(key,event.target.value===''?null:Number(event.target.value))}/></label>;
   })}</div>
   <div className="furniture-actions"><button className="btn" onClick={saveDraft}>保存草稿</button>{!draft.editingAssetId&&<button className="btn" disabled={!consent} onClick={retry}>同意计费并重新识别</button>}<button className="btn primary" disabled={!preview} onClick={publish}>确认并保存到家具库</button></div>
  </fieldset>}
  <section className="furniture-saved"><div className="furniture-section-heading"><div><span className="furniture-section-kicker">LIBRARY</span><h3>已确认家具 <span className="furniture-count">{assets.length}</span></h3></div><p>选择家具即可加入房间</p></div>
   <div className="owned-furniture-grid">{assets.map(asset=><article key={asset.id} className="owned-furniture-card">
    <img src={asset.photoUrls[0]} alt={asset.snapshot.label}/><div className="owned-furniture-meta"><strong>{asset.snapshot.label}</strong><span>v{asset.version}</span></div><small>{asset.snapshot.width} × {asset.snapshot.depth} × {asset.snapshot.height} m</small>
    <div className="furniture-actions"><button className="btn primary" aria-label="加入当前房间" disabled={busy||!!jobId} onClick={()=>onAdd(asset)}>加入房间</button><button className="btn" disabled={busy||!!jobId} onClick={()=>editAsset(asset)}>修改</button><button className="btn furniture-delete" aria-label={`删除${asset.snapshot.label}`} disabled={busy||!!jobId} onClick={()=>deleteAsset(asset)}>删除</button></div>
   </article>)}</div>{!assets.length&&<p className="furniture-empty">保存后的家具会显示在这里</p>}
  </section>
  <section className="furniture-draft-section"><div className="furniture-section-heading"><div><span className="furniture-section-kicker">DRAFTS</span><h3>待确认草稿 <span className="furniture-count">{drafts.length}</span></h3></div></div>
   <div className="furniture-drafts">{drafts.map(value=><div className="furniture-draft" key={value.id}>
    <button className="btn furniture-draft-open" disabled={busy||!!jobId} onClick={()=>{if(dirty&&!window.confirm('放弃未保存修改并打开其他草稿？'))return;openDraft(value.id)}}>{value.properties.label||'未命名家具'} · {value.id.slice(0,8)}</button>
    <button className="btn furniture-delete" aria-label={`删除草稿${value.properties.label||'未命名家具'} · ${value.id.slice(0,8)}`} disabled={busy||!!jobId&&draft?.id!==value.id} onClick={()=>deleteDraft(draft?.id===value.id?draft:value)}>删除</button>
   </div>)}</div>
  </section>
 </section></div>;
}
