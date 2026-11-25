import {test,expect} from '@playwright/test';

test('existing GLB imports without reconstruction and remains usable after room save',async({page})=>{
 await page.goto('/');
 const model=await page.evaluate(async()=>{
  const mesh=await import('/src/furnitureMesh.ts' as string);
  const blob=await mesh.exportFurnitureGLB({id:'fixture',label:'测试椅',category:'armchair',width:.6,height:.9,depth:.7,
   x:0,z:0,rotation:0,locked:false,keep:true,source:'brought'});
  return Array.from(new Uint8Array(await blob.arrayBuffer()));
 });
 let inferenceRequests=0;
 page.on('request',request=>{if(request.method()==='POST'&&/\/furniture\/(?:analyze|drafts\/[^/]+\/reconstruct)/.test(request.url()))inferenceRequests++});
 await page.getByRole('button',{name:'自有家具库',exact:true}).click();
 const dialog=page.getByRole('dialog');
 await dialog.getByLabel('选择家具GLB模型').setInputFiles({name:'imported-chair.glb',mimeType:'model/gltf-binary',buffer:Buffer.from(model)});
 await expect(dialog.getByLabel('家具名称',{exact:true})).toHaveValue('imported-chair');
 const name='已有GLB测试椅-'+Date.now();await dialog.getByLabel('家具名称',{exact:true}).fill(name);
 await dialog.getByLabel('家具类别',{exact:true}).selectOption('armchair');
 await dialog.getByText('功能尺寸与使用空间（可选）',{exact:true}).click();
 await dialog.getByLabel('座面高度',{exact:true}).fill('0.48');
 await dialog.getByLabel('椅后撤深度',{exact:true}).fill('0.55');
 await expect(dialog.getByRole('button',{name:'确认并保存到家具库'})).toBeEnabled();
 const publication=page.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/publish'));
 await dialog.getByRole('button',{name:'确认并保存到家具库'}).click();
 const response=await publication;expect(response.ok()).toBe(true);const asset=await response.json();
 expect(asset.photoUrls).toEqual([]);expect(asset.modelSource.kind).toBe('imported_glb');
 expect(asset.snapshot.functionalProfile.seatHeight).toBe(.48);
 expect(asset.snapshot.functionalProfile.rearUseDepth).toBe(.55);
 expect(asset.snapshot.dimensionSources.width).toBe('template');
 const card=dialog.locator('.owned-furniture-card').filter({hasText:name});
 await expect(card.locator('canvas')).toBeVisible();
 await expect(card.getByText('含模板尺寸，未实测',{exact:false})).toBeVisible();
 await card.getByRole('button',{name:'加入当前房间'}).click();await expect(dialog).toHaveCount(0);
 const save=page.waitForResponse('**/api/scenes/save');await page.getByRole('button',{name:'另存',exact:true}).click();
 const saved=await(await save).json();
 const scene=await(await page.request.get('/api/scenes/'+saved.id)).json();
 const instance=scene.items.find((item:{furnitureAssetId?:string})=>item.furnitureAssetId===asset.id);
 expect(instance.assetUrl).toBe(asset.assetUrl);expect(instance.furnitureSnapshot).toEqual(asset.snapshot);
 expect((await page.request.get(asset.assetUrl)).ok()).toBe(true);expect(inferenceRequests).toBe(0);
 await page.reload();await page.getByRole('button',{name:'自有家具库',exact:true}).click();
 await expect(page.locator('.owned-furniture-card').filter({hasText:name}).locator('canvas')).toBeVisible();
});
