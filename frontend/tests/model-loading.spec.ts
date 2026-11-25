import {test,expect,type Page} from '@playwright/test';

async function fixture(page:Page){
 await page.goto('/');
 const binary=await page.evaluate(async()=>{
  const {exportFurnitureGLB}=await import('/src/furnitureMesh.ts' as string);
  const blob=await exportFurnitureGLB({id:'generated-bed',label:'模型',category:'double_bed',width:1.8,depth:2,height:.9,
   x:0,z:0,rotation:0,locked:false,keep:true,source:'brought'});
  return Array.from(new Uint8Array(await blob.arrayBuffer()));
 });
 const body=Buffer.from(binary),upload=await page.request.post('/api/assets',{multipart:{file:{name:'bed.glb',mimeType:'model/gltf-binary',buffer:body}}});
 expect(upload.ok()).toBe(true);
 const url=(await upload.json()).url as string;
 const scene={id:'loading-test',name:'模型加载回归',version:0,room:{width:6,depth:5,height:2.7,door:null,windows:[]},preferences:[],
  items:[{id:'bed-1',label:'生成床',category:'double_bed',width:1.8,depth:2,height:.9,x:3,z:2.5,rotation:0,locked:false,keep:true,source:'brought',assetUrl:url}]};
 return {body,url,scene};
}

async function importScene(page:Page,scene:unknown){
 await page.locator('input[type=file][accept=".json"]').setInputFiles({name:'scene.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(scene))});
}

test('pending model shows an outline and survives pose edits without restarting its request',async({page})=>{
 const {body,url,scene}=await fixture(page);
 let requests=0,deliver!:()=>void;
 const gate=new Promise<void>(resolve=>{deliver=resolve});
 await page.route('**'+url,async route=>{requests++;await gate;await route.fulfill({body,contentType:'model/gltf-binary'})});
 await importScene(page,scene);
 const canvas=page.locator('.scene-canvas');
 await expect(canvas.getByRole('status')).toContainText('正在加载家具模型');
 await expect.poll(async()=>JSON.parse((await canvas.getAttribute('data-models'))!)).toEqual([{id:'bed-1',label:'生成床',status:'loading'}]);
 await page.locator('.item-card').first().click();
 const x=page.locator('.sidebar-content .field-grid').nth(1).locator('input').first();
 await x.fill('3.2');await x.blur();
 await expect.poll(()=>canvas.getAttribute('data-layout')).toContain('3.2');
 deliver();
 await expect.poll(()=>canvas.getAttribute('data-models')).toContain('loaded');
 await expect(canvas.getByRole('status')).toHaveCount(0);
 expect(requests).toBe(1);
 await x.fill('3.4');await x.blur();
 await expect.poll(()=>canvas.getAttribute('data-layout')).toContain('3.4');
 await expect.poll(()=>canvas.getAttribute('data-models')).toContain('loaded');
 // Replacing all item objects on import must still retain their loaded mesh.
 await importScene(page,{...scene,items:scene.items.map(item=>({...item,x:3.4,rotation:90,width:1.9}))});
 await expect.poll(()=>canvas.getAttribute('data-layout')).toContain('90');
 await expect.poll(()=>canvas.getAttribute('data-models')).toContain('loaded');
 expect(requests).toBe(1);
});

test('failed asset stays a labeled outline and can retry instead of becoming template furniture',async({page})=>{
 const {body,url,scene}=await fixture(page);let requests=0;
 await page.route('**'+url,route=>{requests++;return requests===1?route.fulfill({status:503}):route.fulfill({body,contentType:'model/gltf-binary'})});
 await importScene(page,scene);
 const canvas=page.locator('.scene-canvas');
 await expect(canvas.getByRole('alert')).toContainText('模型加载失败：生成床');
 await expect.poll(()=>canvas.getAttribute('data-models')).toContain('error');
 await canvas.getByRole('button',{name:'重新加载模型'}).click();
 await expect.poll(()=>canvas.getAttribute('data-models')).toContain('loaded');
 await expect(canvas.getByRole('alert')).toHaveCount(0);
 expect(requests).toBe(2);
});

test('a removed model cannot reappear when its old request finishes',async({page})=>{
 const {body,url,scene}=await fixture(page);let deliver!:()=>void;
 const gate=new Promise<void>(resolve=>{deliver=resolve});
 await page.route('**'+url,async route=>{await gate;await route.fulfill({body,contentType:'model/gltf-binary'})});
 await importScene(page,scene);
 const canvas=page.locator('.scene-canvas');
 await expect(canvas.getByRole('status')).toBeVisible();
 await importScene(page,{...scene,items:[]});
 await expect.poll(()=>canvas.getAttribute('data-models')).toBe('[]');
 const loaded=page.waitForResponse('**'+url);deliver();await loaded;
 await expect.poll(()=>canvas.getAttribute('data-models')).toBe('[]');
 await expect(canvas.getByRole('status')).toHaveCount(0);
});

test('loaded floor lamps match their declared dimensions without inheriting template scale',async({page})=>{
 const {url}=await fixture(page);
 const result=await page.evaluate(async url=>{
  const THREE=await import('/node_modules/.vite/deps/three.js' as string);
  const {FurnitureObjects}=await import('/src/furnitureObjects.ts' as string);
  let finish!:()=>void;
  const ready=new Promise<void>(resolve=>{finish=resolve});
  const parent=new THREE.Group(),objects=new FurnitureObjects(parent,(states:{status:string}[])=>{if(states.some(s=>s.status==='loaded'))finish()});
  const item={id:'lamp',label:'白灯',category:'floor_lamp',width:.598,depth:.415,height:1.4,
   x:2,z:2,rotation:0,keep:true,locked:false,source:'brought',assetUrl:url};
  objects.sync([item]);await ready;
  const root=objects.groups.get('lamp'),content=root.children[0];
  const size=()=>new THREE.Box3().setFromObject(root).getSize(new THREE.Vector3()).toArray();
  const first=size();
  objects.sync([{...item,height:1.2,width:.5,depth:.35}]);
  const second=size(),retained=objects.groups.get('lamp')===root&&root.children[0]===content;
  objects.dispose();return {first,second,retained};
 },url);
 for(const [index,value] of [.598,1.4,.415].entries())expect(result.first[index]).toBeCloseTo(value,5);
 for(const [index,value] of [.5,1.2,.35].entries())expect(result.second[index]).toBeCloseTo(value,5);
 expect(result.retained).toBe(true);
});
