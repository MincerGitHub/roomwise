import {test,expect,type Route} from '@playwright/test';

const photo={name:'owned-chair.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64')};

test('manual furniture publication, independent instances and library deletion preserve saved rooms',async({page})=>{
 await page.goto('/');
 await page.getByRole('button',{name:'自有家具库',exact:true}).click();
 const dialog=page.getByRole('dialog');
 await expect(dialog.getByRole('button',{name:'上传并识别家具'})).toBeDisabled();
 await dialog.getByLabel('选择家具图片').setInputFiles(photo);
 await dialog.locator('.furniture-upload input[type=checkbox]').check();
 await dialog.getByRole('button',{name:'上传并识别家具'}).click();
 await expect(dialog.getByText('视觉服务未启用或配置不完整；未发送图片。', {exact:false})).toBeVisible({timeout:15000});
 await expect(dialog.getByRole('button',{name:'确认并保存到家具库'})).toBeDisabled();
 const name=`浏览器测试自有椅-${Date.now()}`;
 await dialog.getByLabel('家具名称',{exact:true}).fill(name);
 await dialog.getByLabel('家具类别',{exact:true}).selectOption('armchair');
 await dialog.getByLabel('家具宽（米）').fill('0.8');
 await dialog.getByLabel('家具深（米）').fill('0.7');
 await dialog.getByLabel('家具高（米）').fill('0.9');
 const preview=dialog.getByLabel('家具参数化三维预览');
 await expect(preview.locator('canvas')).toBeVisible();
 await expect.poll(async()=>{const bounds=JSON.parse((await preview.getAttribute('data-bounds'))!);return Math.abs(bounds.width-.8)+Math.abs(bounds.depth-.7)+Math.abs(bounds.height-.9)+Math.abs(bounds.minY)}).toBeLessThan(.00001);
 for(const checkbox of await dialog.locator('.furniture-confirmations input').all())await checkbox.check();
 const publish=page.waitForResponse(response=>response.url().includes('/publish')&&response.request().method()==='POST');
 await dialog.getByRole('button',{name:'确认并保存到家具库'}).click();
 const response=await publish;expect(response.status()).toBe(200);
 const asset=await response.json();expect(asset.snapshot.dimensionsConfirmed).toBe(true);expect(asset.snapshot.dimensionSources.width).toBe('user');
 const binary=await page.request.get(asset.assetUrl);expect(binary.ok()).toBe(true);expect((await binary.body()).subarray(0,4).toString()).toBe('glTF');
 const card=dialog.locator('.owned-furniture-card').filter({hasText:name});
 await card.getByRole('button',{name:'加入当前房间'}).click();
 await expect(dialog).toHaveCount(0);
 const canvas=page.locator('.scene-canvas');const before=JSON.parse((await canvas.getAttribute('data-layout'))!);
 await page.getByRole('button',{name:'自有家具库',exact:true}).click();
 await page.locator('.owned-furniture-card').filter({hasText:name}).getByRole('button',{name:'加入当前房间'}).click();
 const after=JSON.parse((await canvas.getAttribute('data-layout'))!);expect(after.length).toBe(before.length+1);
 expect(new Set(after.map((item:[string,number,number,number])=>item[0])).size).toBe(after.length);
 const savedResponse=page.waitForResponse('**/api/scenes/save');
 await page.getByRole('button',{name:'另存',exact:true}).click();
 const saved=await (await savedResponse).json();
 await page.getByRole('button',{name:'自有家具库',exact:true}).click();
 const savedCard=page.locator('.owned-furniture-card').filter({hasText:name});
 let deletes=0;page.on('request',request=>{if(request.method()==='DELETE'&&request.url().includes(`/furniture/${asset.id}`))deletes++});
 page.once('dialog',confirmation=>confirmation.dismiss());
 await savedCard.getByRole('button',{name:`删除${name}`,exact:true}).click();
 await expect(savedCard).toBeVisible();expect(deletes).toBe(0);
 // Removing an asset while editing it must also close its obsolete revision.
 await savedCard.getByRole('button',{name:'修改',exact:true}).click();
 await expect(dialog.getByLabel('家具名称',{exact:true})).toHaveValue(name);
 await dialog.getByLabel('家具名称',{exact:true}).fill(`${name}修订`);
 page.once('dialog',async confirmation=>{expect(confirmation.message()).toContain('已加入房间和已保存方案中的家具会保留');await confirmation.accept()});
 const removed=page.waitForResponse(response=>response.request().method()==='DELETE'&&response.url().includes(`/furniture/${asset.id}`));
 await savedCard.getByRole('button',{name:`删除${name}`,exact:true}).click();
 expect((await removed).status()).toBe(200);
 await expect(savedCard).toHaveCount(0);
 await expect(dialog.getByLabel('家具名称',{exact:true})).toHaveCount(0);
 await expect(dialog.getByRole('status').filter({hasText:'已从家具库删除'})).toBeVisible();
 await page.getByRole('button',{name:'关闭自有家具库'}).click();
 expect(JSON.parse((await canvas.getAttribute('data-layout'))!)).toEqual(after);
 const restored=await (await page.request.get(`/api/scenes/${saved.id}`)).json();
 const placed=restored.items.filter((item:{furnitureAssetId?:string})=>item.furnitureAssetId===asset.id);
 expect(placed).toHaveLength(2);for(const instance of placed)expect(instance.furnitureSnapshot).toEqual(asset.snapshot);
 expect((await page.request.get(asset.assetUrl)).ok()).toBe(true);
 expect((await page.request.get(asset.photoUrls[0])).ok()).toBe(true);
 await page.reload();await page.getByRole('button',{name:'自有家具库',exact:true}).click();
 await expect(page.locator('.owned-furniture-card').filter({hasText:name})).toHaveCount(0);
 const listing=await (await page.request.get('/api/furniture')).json();
 expect(listing.assets.some((value:{id:string})=>value.id===asset.id)).toBe(false);
 expect(listing.drafts.some((value:{editingAssetId?:string})=>value.editingAssetId===asset.id)).toBe(false);
});

test('deleting furniture ignores a late reply when opening its revision',async({page})=>{
 const properties={label:'待删除家具',category:'armchair',subtype:null,width:.8,depth:.7,height:.9,dimensionSources:{width:'user',depth:'user',height:'user'},evidence:{width:'',depth:'',height:''},parameters:{primaryColor:null,secondaryColor:null,material:'unknown',hasBack:null,hasArms:null,hasLegs:null,drawerCount:null,doorCount:null,shelfCount:null,seatCount:null,seatHeightRatio:null},styleTags:[],frontDirection:'positive_z'};
 const asset={id:'delete-race-asset',version:1,properties,photoUrls:[],assetUrl:'/uploads/unused.glb',snapshot:{...properties,version:1,dimensionsConfirmed:true,photoUrls:[]},updatedAt:'2026-10-25'};
 const draft={id:'delete-race-draft',version:1,properties,photoUrls:[],recognition:null,jobId:null,editingAssetId:asset.id,updatedAt:'2026-10-25'};
 let deleted=false,pending:Route|undefined;
 await page.route('**/api/furniture',route=>route.fulfill({json:deleted?{assets:[],drafts:[]}:{assets:[asset],drafts:[draft]}}));
 await page.route(`**/api/furniture/drafts/${draft.id}`,route=>{pending=route});
 await page.route(`**/api/furniture/${asset.id}?expectedVersion=1`,route=>{deleted=true;return route.fulfill({json:{id:asset.id,deleted:true}})});
 await page.goto('/');await page.getByRole('button',{name:'自有家具库',exact:true}).click();
 await page.locator('.furniture-draft-open').click();
 await expect.poll(()=>!!pending).toBe(true);
 page.once('dialog',confirmation=>confirmation.accept());
 await page.getByRole('button',{name:`删除${properties.label}`,exact:true}).click();
 await expect(page.getByRole('status').filter({hasText:'已从家具库删除'})).toBeVisible();
 const lateReply=page.waitForResponse(`**/api/furniture/drafts/${draft.id}`);
 await pending!.fulfill({json:draft});await (await lateReply).finished();
 // Wait until browser fetch handlers and React updates have been rendered.
 await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
 await expect(page.getByLabel('家具名称',{exact:true})).toHaveCount(0);
 await expect(page.locator('.furniture-drafts button')).toHaveCount(0);
});

test('all twenty parameterized categories have exact bounds and compatible GLB output',async({page})=>{
 await page.goto('/');
 const results=await page.evaluate(async()=>{
  const mesh=await import('/src/furnitureMesh.ts' as string);
  const THREE=await import('/node_modules/.vite/deps/three.js' as string);
  const catalog=await (await fetch('/api/catalog')).json();
  const parameters={primaryColor:'#345678',secondaryColor:null,material:'fabric',hasBack:null,hasArms:null,hasLegs:null,drawerCount:null,doorCount:null,shelfCount:null,seatCount:null,seatHeightRatio:null};
  const results=[];
  for(const entry of catalog.items){
   const item={...entry,id:entry.category,x:0,z:0,rotation:0,keep:true,locked:false,source:'brought',furnitureSnapshot:{parameters}};
   const group=mesh.createFurniture(item);const bounds=new THREE.Box3().setFromObject(group),size=bounds.getSize(new THREE.Vector3());
   const blob=await mesh.exportFurnitureGLB(item);const binary=await blob.arrayBuffer();const header=new DataView(binary);
   const metadata=JSON.parse(new TextDecoder().decode(new Uint8Array(binary,20,header.getUint32(12,true))));
   const hasInstanceId=(node:unknown):boolean=>!!node&&typeof node==='object'&&Object.entries(node).some(([key,value])=>key==='itemId'||hasInstanceId(value));
   results.push({category:entry.category,error:Math.abs(size.x-entry.width)+Math.abs(size.y-entry.height)+Math.abs(size.z-entry.depth)+Math.abs(bounds.min.y),rootScale:group.scale.toArray(),magic:header.getUint32(0,true),version:header.getUint32(4,true),hasInstanceId:hasInstanceId(metadata)});
   mesh.disposeFurniture(group);
  }
  return results;
 });
 expect(results).toHaveLength(20);
 for(const result of results){expect(result.error,result.category).toBeLessThan(.00001);expect(result.rootScale).toEqual([1,1,1]);expect(result.magic).toBe(0x46546c67);expect(result.version).toBe(2);expect(result.hasInstanceId,result.category).toBe(false)}
});

test('legacy library model uses independent scene IDs for selection drag rotation and locking',async({page})=>{
 await page.goto('/');
 const parameters={primaryColor:'#A56B32',secondaryColor:null,material:'wood',hasBack:true,hasArms:true,hasLegs:true,drawerCount:null,doorCount:null,shelfCount:null,seatCount:null,seatHeightRatio:.43};
 const snapshot={version:1,label:'旧模型实例回归椅',category:'armchair',width:.8,depth:.5,height:1.2,dimensionsConfirmed:true,parameters,dimensionSources:{width:'user',depth:'user',height:'user'},photoUrls:['/uploads/mock-library-photo.png'],frontDirection:'positive_z',subtype:'官帽椅',styleTags:[]};
 const binary=await page.evaluate(async snapshot=>{
  const mesh=await import('/src/furnitureMesh.ts' as string);
  const {GLTFExporter}=await import('/node_modules/three/examples/jsm/exporters/GLTFExporter.js' as string);
  const model=mesh.createFurniture({...snapshot,id:'furniture-preview',x:0,z:0,rotation:0,locked:false,keep:true,source:'brought',furnitureSnapshot:snapshot});
  const binary=await new GLTFExporter().parseAsync(model,{binary:true});mesh.disposeFurniture(model);
  return Array.from(new Uint8Array(binary));
 },snapshot);
 const asset={id:'legacy-library-chair',version:1,properties:snapshot,photoUrls:snapshot.photoUrls,assetUrl:'/uploads/legacy-library-chair.glb',snapshot,updatedAt:'2026-10-24'};
 await page.route('**/api/furniture',route=>route.fulfill({json:{assets:[asset],drafts:[]}}));
 await page.route('**/legacy-library-chair.glb',route=>route.fulfill({body:Buffer.from(binary),contentType:'model/gltf-binary'}));
 await page.route('**/mock-library-photo.png',route=>route.fulfill({body:photo.buffer,contentType:'image/png'}));
 const canvas=page.locator('.scene-canvas');
 const layout=async()=>JSON.parse((await canvas.getAttribute('data-layout'))!) as [string,number,number,number][];
 const original=await layout();
 async function add(){
  await page.getByRole('button',{name:'自有家具库',exact:true}).click();
  const loaded=page.waitForResponse('**/legacy-library-chair.glb');
  await page.locator('.owned-furniture-card').filter({hasText:snapshot.label}).getByRole('button',{name:'加入当前房间'}).click();
  await (await loaded).finished();await page.waitForTimeout(500);
 }
 await add();
 const first=(await layout()).find(item=>!original.some(previous=>previous[0]===item[0]))!;
 expect(first[0]).not.toBe('furniture-preview');
 await page.locator('.view-switch button').nth(1).click();
 const bounds=(await canvas.locator('canvas').boundingBox())!;
 const scale=bounds.height/(2*5.2*.72);
 const point=(posX:number,posZ:number)=>({x:bounds.x+bounds.width/2+(posX-2.6)*scale,y:bounds.y+bounds.height/2+(posZ-2.1)*scale});
 const blank=point(.3,2);await page.mouse.click(blank.x,blank.y);
 await expect(page.locator('.selected-label')).toHaveCount(0);
 const center=point(first[1],first[2]);await page.mouse.click(center.x,center.y);
 await expect(page.locator('.selected-label')).toContainText(snapshot.label);
 await expect(page.getByLabel('名称',{exact:true})).toHaveValue(snapshot.label);
 await page.mouse.move(center.x,center.y);await page.mouse.down();await page.mouse.move(center.x-65,center.y+20,{steps:12});await page.mouse.up();
 await expect.poll(async()=>(await layout()).find(item=>item[0]===first[0])![1]).not.toBe(first[1]);
 const moved=(await layout()).find(item=>item[0]===first[0])!;
 for(const entry of original)expect((await layout()).find(item=>item[0]===entry[0])).toEqual(entry);
 await page.getByRole('button',{name:'旋转90°'}).click();
 await expect.poll(async()=>(await layout()).find(item=>item[0]===first[0])![3]).toBe(90);
 await page.getByRole('button',{name:'切换位置锁定'}).click();
 const locked=point(moved[1],moved[2]);await page.mouse.move(locked.x,locked.y);await page.mouse.down();await page.mouse.move(locked.x+35,locked.y-20,{steps:8});await page.mouse.up();
 expect((await layout()).find(item=>item[0]===first[0])).toEqual([first[0],moved[1],moved[2],90]);
 await page.getByRole('button',{name:'切换位置锁定'}).click();
 await add();
 const second=(await layout()).find(item=>item[0]!==first[0]&&!original.some(previous=>previous[0]===item[0]))!;
 expect(second[0]).not.toBe(first[0]);
 const secondPoint=point(second[1],second[2]);await page.mouse.move(secondPoint.x,secondPoint.y);await page.mouse.down();await page.mouse.move(secondPoint.x-20,secondPoint.y-45,{steps:10});await page.mouse.up();
 await expect.poll(async()=>(await layout()).find(item=>item[0]===second[0])![2]).not.toBe(second[2]);
 expect((await layout()).find(item=>item[0]===first[0])).toEqual([first[0],moved[1],moved[2],90]);
 const savedResponse=page.waitForResponse('**/api/scenes/save');
 await page.getByRole('button',{name:'另存',exact:true}).click();
 const saved=await savedResponse;expect(saved.ok()).toBe(true);
 const identity=await saved.json();const loaded=await page.request.get(`/api/scenes/${identity.id}`);expect(loaded.ok()).toBe(true);
 const savedScene=await loaded.json();
 for(const identifier of [first[0],second[0]]){
  const instance=savedScene.items.find((item:{id:string})=>item.id===identifier);
  expect(instance.furnitureAssetId).toBe(asset.id);expect(instance.furnitureSnapshot).toEqual(snapshot);
 }
 const importedModel=page.waitForResponse('**/legacy-library-chair.glb');
 await page.locator('input[type=file][accept=".json"]').setInputFiles({name:'library-instances.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(savedScene))});
 await (await importedModel).finished();await page.waitForTimeout(500);
 const restored=(await layout()).find(item=>item[0]===second[0])!;
 const restoredPoint=point(restored[1],restored[2]);await page.mouse.click(restoredPoint.x,restoredPoint.y);
 await expect(page.locator('.selected-label')).toContainText(snapshot.label);
 await page.mouse.move(restoredPoint.x,restoredPoint.y);await page.mouse.down();await page.mouse.move(restoredPoint.x+20,restoredPoint.y-15,{steps:8});await page.mouse.up();
 await expect.poll(async()=>(await layout()).find(item=>item[0]===second[0])![1]).not.toBe(restored[1]);
});

test('unconsented upload makes no model submission and crop stays local',async({page})=>{
 let calls=0;await page.route('**/api/furniture/analyze',route=>{calls++;return route.abort()});
 await page.goto('/');await page.getByRole('button',{name:'从图片生成家具',exact:true}).click();
 await expect(page.getByLabel('我同意将所选图片发送到第三方网关 api.tokenlab.pro（非 OpenAI 官方域名），请求 gpt-6-sol / high 进行识别，可能产生服务费用。服务关闭时仅保存在本机。')).toBeVisible();
 await page.getByLabel('选择家具图片').setInputFiles(photo);
 await expect(page.getByRole('button',{name:'上传并识别家具'})).toBeDisabled();
 const surface=page.locator('.crop-surface');const bounds=(await surface.boundingBox())!;
 await page.mouse.move(bounds.x+2,bounds.y+2);await page.mouse.down();await page.mouse.move(bounds.x+bounds.width*.8,bounds.y+bounds.height*.8);await page.mouse.up();
 await expect(page.getByRole('button',{name:'使用框选区域'})).toBeEnabled();
 await page.getByRole('button',{name:'使用框选区域'}).click();expect(calls).toBe(0);
});

test('model fields are prefilled but conflicting multi-view targets cannot publish',async({page})=>{
 const parameters={primaryColor:'#789167',secondaryColor:null,material:'fabric',hasBack:true,hasArms:true,hasLegs:true,drawerCount:null,doorCount:null,shelfCount:null,seatCount:null,seatHeightRatio:.5};
 const properties={label:'模型识别的扶手椅',category:'armchair',subtype:'软包椅',width:.8,depth:.7,height:.9,dimensionSources:{width:'estimated',depth:'estimated',height:'annotation'},evidence:{width:'估计',depth:'估计',height:'900 mm'},parameters,styleTags:['简约'],frontDirection:'positive_z'};
 const recognition={properties,views:[{imageIndex:0,view:'composite',description:'拼接视图'}],sameObject:false,multipleObjects:false,viewConflict:true,needsCrop:false,warnings:['视图可能来自不同家具'],uncertainFields:['尺寸冲突']};
 const draft={id:'mock-draft',version:2,photoUrls:['/mock-photo.png'],properties,recognition,jobId:'mock-job',updatedAt:'2026-10-23'};
 let submissions=0;
 await page.route(/\/api\/furniture(?:\/|$)/,async route=>{
  const path=new URL(route.request().url()).pathname;
  const body=path.endsWith('/status')?{enabled:true,message:'模拟视觉服务，不进行付费调用'}:path.endsWith('/analyze')?{draftId:draft.id,jobId:draft.jobId}:path.includes('/jobs/')?{id:draft.jobId,draftId:draft.id,status:'complete',error:null,errorCode:null}:path.includes('/drafts/')?draft:{assets:[],drafts:[draft]};
  if(path.endsWith('/analyze'))submissions++;
  await route.fulfill({json:body});
 });
 await page.goto('/');await page.getByRole('button',{name:'自有家具库',exact:true}).click();
 await page.getByLabel('选择家具图片').setInputFiles([photo,{...photo,name:'side.png'},{...photo,name:'back.png'}]);
 await page.locator('.furniture-upload input[type=checkbox]').check();await page.getByRole('button',{name:'上传并识别家具'}).click();
 await expect(page.getByLabel('家具名称',{exact:true})).toHaveValue(properties.label);
 await expect(page.getByLabel('家具宽（米）')).toHaveValue('0.8');
 await expect(page.getByText('模型原值：0.8 m')).toBeVisible();
 await expect(page.getByRole('alert')).toContainText('视图冲突');
 for(const checkbox of await page.locator('.furniture-confirmations input').all())await checkbox.check();
 await expect(page.getByRole('button',{name:'确认并保存到家具库'})).toBeDisabled();
 await page.getByLabel('家具类别',{exact:true}).selectOption('rug');
 await expect(page.locator('.furniture-parameters').getByText('扶手',{exact:true})).toHaveCount(0);
 await expect(page.locator('.furniture-confirmations input:checked')).toHaveCount(0);
 expect(submissions).toBe(1);
});
