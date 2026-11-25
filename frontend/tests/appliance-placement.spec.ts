import {test,expect} from '@playwright/test';

test('new library appliances start mounted or supported and save their placement',async({page})=>{
 test.setTimeout(120000);
 await page.goto('/');
 const binary=await page.evaluate(async()=>{
  const {exportFurnitureGLB}=await import('/src/furnitureMesh.ts' as string);
  return [...new Uint8Array(await(await exportFurnitureGLB({id:'fixture',label:'设备',category:'air_conditioner',width:.9,depth:.2,height:.3,x:0,z:0,rotation:0,keep:true,locked:false,source:'brought'})).arrayBuffer())];
 });
 const uploaded=await page.request.post('/api/assets',{multipart:{file:{name:'device.glb',mimeType:'model/gltf-binary',buffer:Buffer.from(binary)}}});
 const url=(await uploaded.json()).url;
 const categories=[['laptop','测试笔记本',.34,.25,.24],['wall_tv','测试壁挂电视',1.1,.08,.65],['air_conditioner','测试空调',.9,.2,.3]] as const;
 const assets=categories.map(([category,label,width,depth,height],index)=>{
  const snapshot={version:1,category,label,width,depth,height,dimensionsConfirmed:true,parameters:{material:'mixed'},dimensionSources:{width:'user',depth:'user',height:'user'},photoUrls:[],frontDirection:'positive_z',subtype:null,styleTags:[]};
  return {id:'device-'+index,version:1,snapshot,properties:snapshot,assetUrl:url,photoUrls:[],updatedAt:'2026-11-25T00:00:00Z'};
 });
 await page.route('**/api/furniture',route=>route.fulfill({json:{assets,drafts:[]}}));
 const fixture={id:'devices-ui',name:'设备摆放回归',version:0,room:{width:6,depth:5,height:2.7,door:null,windows:[]},preferences:[],
  items:[{id:'table',label:'桌子',category:'table',width:1.2,depth:.8,height:.75,x:3,z:2.5,rotation:0,keep:true,locked:false,source:'brought'}]};
 await page.locator('input[type=file][accept=".json"]').setInputFiles({name:'fixture.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture))});
 await expect(page.locator('.canvas-header')).toContainText(fixture.name);
 for(const asset of assets){
  await page.getByRole('button',{name:'自有家具库',exact:true}).click();
  await page.locator('.owned-furniture-card').filter({hasText:asset.snapshot.label}).getByRole('button',{name:'加入当前房间'}).click();
 }
 const response=page.waitForResponse('**/api/scenes/save');await page.getByRole('button',{name:'另存',exact:true}).click();
 const saved=await(await response).json();const scene=await(await page.request.get('/api/scenes/'+saved.id)).json();
 const laptop=scene.items.find((i:{category:string})=>i.category==='laptop');expect(laptop.supportId).toBe('table');expect(laptop.y).toBe(.75);
 for(const category of ['wall_tv','air_conditioner']){
  const device=scene.items.find((i:{category:string})=>i.category===category);
  expect(device.locked).toBe(false);expect(device.keep).toBe(false);expect(device.y).toBeGreaterThan(0);expect(device.rotation).toBe(180);
 }
 const check=await(await page.request.post('/api/validate',{data:{scene}})).json();expect(check.issues.filter((i:{type:string})=>i.type==='support'||i.type==='wall_mount')).toEqual([]);
 expect(laptop.keep).toBe(false);
 // Newly added library furniture can be removed immediately, without changing protection first.
 await page.locator('.item-card').filter({hasText:'测试空调'}).click();
 await expect(page.getByRole('button',{name:'切换保留状态'})).toHaveAttribute('aria-pressed','false');
 await page.getByRole('button',{name:'移除这件家具'}).click();
 await expect(page.locator('.item-card').filter({hasText:'测试空调'})).toHaveCount(0);
 await page.getByRole('button',{name:'撤销',exact:true}).click();
 await expect(page.locator('.item-card').filter({hasText:'测试空调'})).toHaveCount(1);
 await page.getByLabel('布局方法').selectOption('rules');
 const generated=page.waitForResponse('**/api/generate');await page.locator('.generation-actions button.primary').click();
 const result=await(await generated).json();expect(result.candidates.length).toBeGreaterThan(0);
 for(const candidate of result.candidates){
  expect(candidate.validation.valid).toBe(true);
  expect(candidate.scene.items.filter((i:{category:string})=>['wall_tv','air_conditioner'].includes(i.category)).every((i:{locked:boolean})=>!i.locked)).toBe(true);
 }
});

test('catalogue furniture can be deleted immediately and explicitly protected furniture remains protected',async({page})=>{
 await page.goto('/');
 const scene={id:'empty',name:'删除默认值',version:0,room:{width:6,depth:5,height:2.7,door:null,windows:[]},items:[],preferences:[]};
 await page.locator('input[type=file][accept=".json"]').setInputFiles({name:'empty.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(scene))});
 await expect(page.locator('.canvas-header')).toContainText(scene.name);
 await page.getByRole('button',{name:'录入一件家具',exact:true}).click();
 await page.locator('.catalog-grid button').filter({hasText:'落地灯'}).click();
 await expect(page.getByRole('button',{name:'切换保留状态'})).toHaveAttribute('aria-pressed','false');
 await page.getByRole('button',{name:'切换保留状态'}).click();
 await page.getByRole('button',{name:'移除这件家具'}).click();
 await expect(page.locator('.item-card')).toHaveCount(1);
 await expect(page.getByRole('status')).toContainText('必须保留');
 await page.getByRole('button',{name:'切换保留状态'}).click();
 await page.getByRole('button',{name:'移除这件家具'}).click();
 await expect(page.locator('.item-card')).toHaveCount(0);
});
