import {test,expect} from '@playwright/test';

test('many model-only library cards render on scroll without losing the room canvas',async({page})=>{
 await page.goto('/');
 const binary=await page.evaluate(async()=>{
  const module=await import('/src/furnitureMesh.ts' as string);
  const blob=await module.exportFurnitureGLB({id:'fixture',label:'测试椅',category:'armchair',width:.6,height:.9,depth:.7,
   x:0,z:0,rotation:0,locked:false,keep:true,source:'brought'});
  return Array.from(new Uint8Array(await blob.arrayBuffer()));
 });
 const properties={label:'模型椅',category:'armchair',subtype:null,width:.6,depth:.7,height:.9,
  dimensionSources:{width:'user',depth:'user',height:'user'},evidence:{width:'模型尺寸',depth:'模型尺寸',height:'模型尺寸'},
  parameters:{},styleTags:['模型尺寸'],frontDirection:'positive_z'};
 const assets=Array.from({length:20},(_,index)=>({id:'asset-'+index,version:1,properties:{...properties,label:'模型椅'+index},photoUrls:[],
  assetUrl:'/uploads/assets/preview.glb',snapshot:{...properties,label:'模型椅'+index,version:1,dimensionsConfirmed:true,photoUrls:[]},
  modelSource:{kind:'imported_glb',note:'test fixture'},updatedAt:'2026-11-22'}));
 await page.route('**/api/furniture',r=>r.fulfill({json:{assets,drafts:[]}}));
 await page.route('**/uploads/assets/preview.glb',r=>r.fulfill({body:Buffer.from(binary),contentType:'model/gltf-binary'}));
 await page.evaluate(()=>{(window as any).roomContextLost=false;document.querySelector('.scene-canvas canvas')!
  .addEventListener('webglcontextlost',()=>{(window as any).roomContextLost=true})});
 await page.getByRole('button',{name:'自有家具库',exact:true}).click();
 const cards=page.locator('.owned-furniture-card');await expect(cards).toHaveCount(20);
 for(const index of [0,9,19]){
  await cards.nth(index).scrollIntoViewIfNeeded();await expect(cards.nth(index).locator('canvas')).toBeVisible();
  await expect.poll(()=>page.locator('.owned-furniture-card canvas').count()).toBeLessThan(16);
 }
 expect(await page.evaluate(()=>(window as any).roomContextLost)).toBe(false);
 await page.getByRole('button',{name:'关闭自有家具库'}).click();await expect(page.locator('.scene-canvas canvas')).toBeVisible();
});
