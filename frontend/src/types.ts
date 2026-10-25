export type Wall='south'|'north'|'east'|'west';
export type FurnitureParameters={primaryColor:string|null;secondaryColor:string|null;material:'wood'|'fabric'|'leather'|'metal'|'plastic'|'glass'|'mixed'|'unknown';hasBack:boolean|null;hasArms:boolean|null;hasLegs:boolean|null;drawerCount:number|null;doorCount:number|null;shelfCount:number|null;seatCount:number|null;seatHeightRatio:number|null};
export type DimensionSources=Record<'width'|'depth'|'height','annotation'|'estimated'|'user'|'unknown'>;
export type FurnitureProperties={label:string|null;category:string|null;subtype:string|null;width:number|null;depth:number|null;height:number|null;dimensionSources:DimensionSources;evidence:Record<'width'|'depth'|'height',string>;parameters:FurnitureParameters;styleTags:string[];frontDirection:'positive_z'|'negative_z'|null};
export type FurnitureSnapshot={version:number;label:string;category:string;width:number;depth:number;height:number;dimensionsConfirmed:true;parameters:FurnitureParameters;dimensionSources:DimensionSources;photoUrls:string[];frontDirection:'positive_z'|'negative_z';subtype:string|null;styleTags:string[]};
export type FurnitureRecognition={properties:FurnitureProperties;views:{imageIndex:number;view:string;description:string}[];sameObject:boolean|null;multipleObjects:boolean;viewConflict:boolean;needsCrop:boolean;warnings:string[];uncertainFields:string[]};
export type FurnitureDraft={id:string;version:number;photoUrls:string[];properties:FurnitureProperties;recognition:FurnitureRecognition|null;jobId:string|null;editingAssetId?:string;publishedAssetId?:string;updatedAt:string};
export type FurnitureAsset={id:string;version:number;properties:FurnitureProperties;photoUrls:string[];assetUrl:string;snapshot:FurnitureSnapshot;updatedAt:string};
export type FurnitureJob={id:string;draftId:string;status:'queued'|'processing'|'complete'|'failed';error:string|null;errorCode:string|null};
export type Item={id:string;label:string;category:string;width:number;depth:number;height:number;x:number;z:number;rotation:number;locked:boolean;keep:boolean;source:'brought'|'existing'|'new';assetUrl?:string|null;photoUrl?:string|null;furnitureAssetId?:string|null;furnitureSnapshot?:FurnitureSnapshot|null;[key:string]:unknown};
export type Room={referenceImageUrl?:string|null;width:number;depth:number;height:number;polygon?:number[][]|null;door?:{wall:Wall;offset:number;width:number;clearance:number}|null;windows:{id:string;wall:Wall;offset:number;width:number;sillHeight:number}[]};
export type BedsideSide='left'|'right'|'either';
export type Preference={kind:string;itemId:string;targetId?:string|null;wall?:'nearest'|'north'|'south'|'west'|'east'|null;side?:BedsideSide|null;direction?:'front'|'back'|'left'|'right'|null;required?:boolean};
export type Scene={id:string;name:string;version:number;room:Room;items:Item[];preferences:Preference[];[key:string]:unknown};
export type Issue={type:string;severity:string;message:string;itemIds?:string[]};
export type Validation={valid:boolean;issues:Issue[];metrics:Record<string,number|boolean|string|null>;requirements?:RequirementResult};
export type CatalogItem={category:string;label:string;width:number;depth:number;height:number;reason?:string};
export type RequirementCheck={kind:string;itemId:string;targetId?:string|null;side?:BedsideSide|null;direction?:'front'|'back'|'left'|'right'|null;actualSide?:'left'|'right';required:boolean;satisfied:boolean;blocking?:boolean;source?:'explicit'|'default';message:string;metrics?:Record<string,number|boolean|string|null>};
export type RequirementResult={satisfied:boolean;checks:RequirementCheck[]};
export type FunctionalRelations=RequirementResult&{unsatisfied?:RequirementCheck[];warnings?:RequirementCheck[];note?:string};
export type Candidate={id:string;scene:Scene;validation:Validation;score:number;mode:string;summary:string;requirements?:RequirementResult;functionalRelations?:FunctionalRelations;quality?:{penalty:number;components:Record<string,number>;preferencePenalty:number}};
export type VideoJob={status:string;progress:number;frames:{id:string;url:string;timestamp:number;sharpness:number}[];candidates:{trackId:string;label:string;category:string;confidence:number;frameUrl:string;bbox:number[]}[];detector?:string;limitations?:string[];error?:string};
export const sourceNames={brought:'搬来的旧家具',existing:'房内已有',new:'新增示意'};
export function clone<T>(obj:T):T{return structuredClone(obj)}
export async function api<T>(path:string,body?:unknown,method?:'GET'|'POST'|'DELETE'):Promise<T>{
 const r=await fetch(`/api${path}`,{method:method??(body===undefined?'GET':'POST'),...(body===undefined?{}:{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})});
 if(!r.ok){const raw=await r.text();let msg='';try{const j=JSON.parse(raw);msg=typeof j.detail==='string'?j.detail:Array.isArray(j.detail)?j.detail.map((x:{msg:string})=>x.msg).join('\uFF1B'):j.detail?.message||j.message||''}catch{}if(!msg)msg=raw.replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').trim().slice(0,240);throw new Error(msg?`\u8bf7\u6c42\u5931\u8d25\uff08${r.status}\uff09\uff1a${msg}`:`\u8bf7\u6c42\u5931\u8d25\uff08${r.status}\uff09`)}return r.json();
}
export function downloadJSON(value:unknown,name:string){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
