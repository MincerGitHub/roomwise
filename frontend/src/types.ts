export type Wall='south'|'north'|'east'|'west';
export type Item={id:string;label:string;category:string;width:number;depth:number;height:number;x:number;z:number;rotation:number;locked:boolean;keep:boolean;source:'brought'|'existing'|'new';assetUrl?:string|null;photoUrl?:string|null;[key:string]:unknown};
export type Room={referenceImageUrl?:string|null;width:number;depth:number;height:number;polygon?:number[][]|null;door?:{wall:Wall;offset:number;width:number;clearance:number}|null;windows:{id:string;wall:Wall;offset:number;width:number;sillHeight:number}[]};
export type BedsideSide='left'|'right'|'either';
export type Preference={kind:string;itemId:string;targetId?:string|null;wall?:'nearest'|'north'|'south'|'west'|'east'|null;side?:BedsideSide|null;required?:boolean};
export type Scene={id:string;name:string;version:number;room:Room;items:Item[];preferences:Preference[];[key:string]:unknown};
export type Issue={type:string;severity:string;message:string;itemIds?:string[]};
export type Validation={valid:boolean;issues:Issue[];metrics:Record<string,number|boolean|string|null>;requirements?:RequirementResult};
export type CatalogItem={category:string;label:string;width:number;depth:number;height:number;reason?:string};
export type RequirementCheck={kind:string;itemId:string;targetId?:string|null;side?:BedsideSide|null;actualSide?:'left'|'right';required:boolean;satisfied:boolean;blocking?:boolean;source?:'explicit'|'default';message:string;metrics?:Record<string,number|boolean|string|null>};
export type RequirementResult={satisfied:boolean;checks:RequirementCheck[]};
export type FunctionalRelations=RequirementResult&{unsatisfied?:RequirementCheck[];warnings?:RequirementCheck[];note?:string};
export type Candidate={id:string;scene:Scene;validation:Validation;score:number;mode:string;summary:string;requirements?:RequirementResult;functionalRelations?:FunctionalRelations;quality?:{penalty:number;components:Record<string,number>;preferencePenalty:number}};
export type VideoJob={status:string;progress:number;frames:{id:string;url:string;timestamp:number;sharpness:number}[];candidates:{trackId:string;label:string;category:string;confidence:number;frameUrl:string;bbox:number[]}[];detector?:string;limitations?:string[];error?:string};
export const sourceNames={brought:'搬来的旧家具',existing:'房内已有',new:'新增示意'};
export function clone<T>(obj:T):T{return structuredClone(obj)}
export async function api<T>(path:string,body?:unknown):Promise<T>{
 const r=await fetch(`/api${path}`,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
 if(!r.ok){let msg='';try{const j=await r.json();msg=typeof j.detail==='string'?j.detail:Array.isArray(j.detail)?j.detail.map((x:{msg:string})=>x.msg).join('；'):j.detail?.message||'请求未成功，请检查输入'}catch{msg=await r.text()}throw new Error(msg||`请求失败 ${r.status}`)}return r.json();
}
export function downloadJSON(value:unknown,name:string){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
