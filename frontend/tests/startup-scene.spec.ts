import {test,expect} from '@playwright/test';

const opening={id:'generated-bedroom-demo',name:'生成模型默认房间',version:0,
 room:{width:5.2,depth:4.2,height:2.7,door:null,windows:[]},preferences:[],items:[
  {id:'generated-bed',label:'生成双人床（估算尺寸）',category:'double_bed',width:1.8,depth:2,height:.9,
   x:3,z:2,rotation:180,locked:false,keep:true,source:'brought',assetUrl:'/uploads/assets/00000000000000000000000000000001.glb'},
 ]};

test('page loads configured generated models and exports their references',async({page})=>{
 await page.route('**/api/startup-scene',route=>route.fulfill({json:{scene:opening}}));
 await page.route('**/uploads/assets/00000000000000000000000000000001.glb',route=>route.fulfill({status:404}));
 await page.goto('/');
 await expect(page.locator('.canvas-header')).toContainText(opening.name);
 await expect(page.locator('.item-card')).toHaveCount(1);
 await expect(page.locator('.item-card')).toContainText('生成双人床');
 const download=page.waitForEvent('download');
 await page.locator('.header-actions .icon-btn').nth(2).click();
 const result=await download;
 const stream=await result.createReadStream();
 const chunks=[];for await(const chunk of stream!)chunks.push(chunk);
 const scene=JSON.parse(Buffer.concat(chunks).toString());
 expect(scene.items[0].assetUrl).toBe(opening.items[0].assetUrl);
 expect(scene.items[0].rotation).toBe(180);
});

test('late startup response cannot overwrite a user import',async({page})=>{
 let deliver!:()=>void;
 const pending=new Promise<void>(resolve=>{deliver=resolve});
 await page.route('**/api/startup-scene',async route=>{await pending;await route.fulfill({json:{scene:opening}})});
 await page.goto('/');
 const imported={...opening,id:'my-room',name:'用户导入房间',items:[]};
 await page.locator('input[type=file][accept=".json"]').setInputFiles({name:'my-room.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(imported))});
 await expect(page.locator('.canvas-header')).toContainText(imported.name);
 const response=page.waitForResponse('**/api/startup-scene');deliver();await response;
 await expect(page.locator('.canvas-header')).toContainText(imported.name);
 await expect(page.locator('.item-card')).toHaveCount(0);
});
