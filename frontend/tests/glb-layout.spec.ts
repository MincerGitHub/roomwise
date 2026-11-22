import {test,expect} from '@playwright/test';

test('GLB layouts generate preview apply and save while retaining locked assets',async({page})=>{
 await page.goto('/');
 const binary=await page.evaluate(async()=>{
  const mesh=await import('/src/furnitureMesh.ts' as string);
  const blob=await mesh.exportFurnitureGLB({id:'fixture',label:'测试椅',category:'armchair',width:.5,height:.8,depth:.5,
   x:0,z:0,rotation:0,locked:false,keep:true,source:'brought'});
  return Array.from(new Uint8Array(await blob.arrayBuffer()));
 });
 const uploaded=await page.request.post('/api/assets',{multipart:{file:{name:'chair.glb',mimeType:'model/gltf-binary',buffer:Buffer.from(binary)}}});
 expect(uploaded.ok()).toBe(true);const assetUrl=(await uploaded.json()).url;
 const scene=await(await page.request.get('/api/demo')).json();scene.preferences=[];
 const snapshot={version:1,label:'GLB布局回归椅',category:'armchair',width:.5,depth:.5,height:.8,
  dimensionsConfirmed:true,photoUrls:[],frontDirection:'positive_z',dimensionSources:{width:'template',depth:'template',height:'template'},
  subtype:null,styleTags:[],parameters:{primaryColor:null,secondaryColor:null,material:'unknown',hasBack:null,hasArms:null,
   hasLegs:null,drawerCount:null,doorCount:null,shelfCount:null,seatCount:null,seatHeightRatio:null}};
 const fixed={id:'glb-fixed',label:snapshot.label,category:'armchair',width:.5,depth:.5,height:.8,
  x:1.5,z:2.,rotation:25,locked:true,keep:true,source:'brought',assetUrl,furnitureAssetId:'test-glb-asset',furnitureSnapshot:snapshot};
 scene.items=[fixed,{...fixed,id:'glb-movable',locked:false}];
 await page.locator('input[type=file][accept=".json"]').setInputFiles({name:'glb-layout.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(scene))});
 const canvas=page.locator('.scene-canvas');
 await expect.poll(()=>canvas.getAttribute('data-layout')).toContain('glb-movable');
 const original=await canvas.getAttribute('data-layout');
 await page.getByLabel('布局方法').selectOption('hybrid');
 const generatedResponse=page.waitForResponse('**/api/generate',{timeout:20000});
 await page.locator('.generation-actions button.primary').click();
 const response=await generatedResponse;expect(response.ok()).toBe(true);const generated=await response.json();
 expect(generated.candidates.length).toBeGreaterThan(0);
 expect(generated.diagnostics.meshCollision.finalValidation).toBe('original_mesh');
 expect(generated.diagnostics.modelError).toBeUndefined();
 expect(await canvas.getAttribute('data-layout')).toBe(original);
 for(const candidate of generated.candidates){
  expect(candidate.validation.valid).toBe(true);
  const retained=candidate.scene.items.find((value:{id:string})=>value.id===fixed.id);
  for(const key of ['x','z','rotation','assetUrl','width','depth','height','furnitureAssetId','furnitureSnapshot'] as const)expect(retained[key]).toEqual(fixed[key]);
  const movable=candidate.scene.items.find((value:{id:string})=>value.id==='glb-movable');
  expect(movable.assetUrl).toBe(assetUrl);expect(movable.furnitureSnapshot).toEqual(retained.furnitureSnapshot);
 }
 await page.locator('.candidate-card').first().locator('button').first().click();
 await expect(page.locator('.preview-banner')).toBeVisible();
 await page.locator('.preview-banner button').nth(1).click();
 const savedResponse=page.waitForResponse('**/api/scenes/save');await page.getByRole('button',{name:'另存',exact:true}).click();
 const saved=await(await savedResponse).json();
 const restored=await(await page.request.get('/api/scenes/'+saved.id)).json();
 expect(restored.items).toHaveLength(2);
 expect(restored.items.every((value:{assetUrl:string})=>value.assetUrl===assetUrl)).toBe(true);
 expect(restored.items.find((value:{id:string})=>value.id===fixed.id).rotation).toBe(fixed.rotation);
});
