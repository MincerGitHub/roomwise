import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';

test('a window desk with an existing round table generates and previews a usable layout',async({page})=>{
 const fixture=JSON.parse(readFileSync(new URL('../../backend/tests/fixtures/window-desk-round-table.json',import.meta.url),'utf8'));
 fixture.preferences=[];
 await page.goto('/');
 await page.locator('input[type=file][accept=".json"]').setInputFiles({name:'window-desk.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture))});
 await expect(page.locator('.canvas-header')).toContainText(fixture.name);
 const canvas=page.locator('.scene-canvas');
 const original=await canvas.getAttribute('data-layout');
 const commandResponse=page.waitForResponse('**/api/command');
 const generateResponse=page.waitForResponse('**/api/generate',{timeout:45000});
 await page.getByLabel('输入修改要求').fill('书桌靠窗，办公椅面朝窗户方向');
 await page.getByLabel('发送要求',{exact:true}).click();
 const command=await(await commandResponse).json();
 expect(command.action).toBe('generate');
 expect(command.scene.preferences).toEqual(expect.arrayContaining([
  expect.objectContaining({kind:'near_window',itemId:'lowpoly-desk',required:true}),
  expect.objectContaining({kind:'face_window',itemId:'chair-1',required:true}),
 ]));
 const generated=await(await generateResponse).json();
 expect(generated.candidates.length).toBeGreaterThan(0);
 for(const candidate of generated.candidates){
  expect(candidate.scene.items).toHaveLength(7);
  const check=await(await page.request.post('/api/validate',{data:{scene:candidate.scene}})).json();
  expect(check.valid).toBe(true);
  expect(check.requirements.satisfied).toBe(true);
  expect(check.functionalSpaces.satisfied).toBe(true);
 }
 // The current workspace opens command-generated candidates immediately.
 // Returning to the current layout must still restore the unmodified input.
 if(await page.getByRole('button',{name:'返回当前布局',exact:true}).count()){
  await page.getByRole('button',{name:'返回当前布局',exact:true}).click();
 }
 await expect.poll(()=>canvas.getAttribute('data-layout')).toBe(original);
 await page.getByLabel('预览方案 1',{exact:true}).click();
 await expect(page.locator('.preview-banner')).toBeVisible();
 await expect(page.locator('.preview-inspection summary')).toContainText('空间检查通过');
 await page.locator('.preview-inspection summary').click();
 await expect(page.locator('.preview-check-details .requirement-check.unmet')).toHaveCount(0);
 await expect(page.locator('.preview-check-details').getByRole('region',{name:'功能空间检查'})).not.toContainText('未满足');
 await page.locator('.preview-banner').getByRole('button',{name:'应用此方案'}).click();
 await page.getByRole('button',{name:'检查',exact:true}).click();
 await expect(page.locator('.validation-hero')).toContainText('通过当前空间检查');
});

test('multi-seat dining table keeps two chairs while a separate desk uses its specified chair',async({page})=>{
 const fixture={id:'multi-seat-window',name:'多座位窗口工作组',version:0,
  room:{width:8,depth:8,height:3,door:null,windows:[{id:'window-1',wall:'north',offset:2.5,width:3,sillHeight:1}]},preferences:[],items:[
   {id:'dining',label:'圆餐桌',category:'table',width:1.8,depth:.9,height:.75,x:2,z:3,rotation:0,locked:false,keep:true,source:'brought',functionalProfile:{seatCapacity:2}},
   {id:'desk',label:'书桌',category:'desk',width:1.2,depth:.6,height:.75,x:5,z:3,rotation:0,locked:false,keep:true,source:'brought',functionalProfile:{surfaceHeight:.75,frontUseDepth:.55}},
   {id:'seat-a',label:'餐椅一',category:'chair',width:.48,depth:.5,height:.85,x:1.5,z:1.8,rotation:0,locked:false,keep:true,source:'brought'},
   {id:'seat-b',label:'餐椅二',category:'armchair',width:.52,depth:.55,height:.9,x:2.5,z:1.8,rotation:0,locked:false,keep:true,source:'brought'},
   {id:'desk-seat',label:'办公椅',category:'chair',width:.48,depth:.5,height:.85,x:5,z:2.25,rotation:180,locked:false,keep:true,source:'brought',functionalProfile:{seatHeight:.45,rearUseDepth:.55}},
  ]};
 await page.goto('/');
 await page.locator('input[type=file][accept=".json"]').setInputFiles({name:'multi-seat-window.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture))});
 await expect(page.locator('.canvas-header')).toContainText(fixture.name);
 const commandResponse=page.waitForResponse('**/api/command');
 const generationResponse=page.waitForResponse('**/api/generate',{timeout:45000});
 await page.getByLabel('输入修改要求').fill('desk靠窗，desk-seat面朝窗户方向');
 await page.getByLabel('发送要求',{exact:true}).click();
 const command=await(await commandResponse).json();
 expect(command.action).toBe('generate');
 const result=await(await generationResponse).json();
 expect(result.candidates.length).toBeGreaterThan(0);
 for(const candidate of result.candidates){
  const pairs=candidate.functionalSpaces.checks.filter((check:{kind:string})=>check.kind==='work_position').map((check:{itemIds:string[]})=>check.itemIds);
  expect(pairs).toContainEqual(['dining','seat-a']);
  expect(pairs).toContainEqual(['dining','seat-b']);
  expect(pairs).toContainEqual(['desk','desk-seat']);
  expect(candidate.scene.items).toHaveLength(5);
  const validation=await(await page.request.post('/api/validate',{data:{scene:candidate.scene}})).json();
  expect(validation.valid&&validation.requirements.satisfied&&validation.functionalSpaces.satisfied).toBe(true);
 }
 await page.getByLabel('预览方案 1',{exact:true}).click();
 await expect(page.locator('.preview-inspection summary')).toContainText('空间检查通过');
 await page.locator('.preview-inspection summary').click();
 await expect(page.locator('.preview-check-details .requirement-check.unmet')).toHaveCount(0);
});
