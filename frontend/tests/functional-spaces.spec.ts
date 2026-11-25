import {test,expect,type Page} from '@playwright/test';
import {readFileSync} from 'node:fs';

const item=(id:string,category:string,x:number,z:number,extra={})=>({id,label:id,category,x,z,width:.5,depth:.5,height:.9,rotation:0,locked:false,keep:true,source:'brought',...extra});
const scene=(items:unknown[])=>({id:'functional-ui',name:'功能空间回归',version:0,room:{width:7,depth:7,height:3,door:null,windows:[]},items,preferences:[]});
async function load(page:Page,fixture:unknown){
 await page.goto('/');
 await page.locator('input[type=file][accept=".json"]').setInputFiles({name:'functional.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture))});
 await expect(page.locator('.canvas-header')).toContainText('功能空间回归');
 await page.locator('.tabs button').filter({hasText:'检查'}).click();
}

test('declared height conflict is visible and cannot produce accepted candidates',async({page})=>{
 await load(page,scene([
  item('desk','desk',3,2,{width:1.2,depth:.6,height:1.16,locked:true,functionalProfile:{surfaceHeight:.76}}),
  item('chair','chair',3,2.75,{rotation:180,locked:true,functionalProfile:{seatHeight:.7,rearUseDepth:.55}}),
 ]));
 const checks=page.getByRole('region',{name:'功能空间检查'});
 await expect(checks).toContainText('台面与chair座面高度差');
 await expect(checks).toContainText('未满足 · 已声明参数');
 await expect(page.locator('.validation-hero')).toContainText('功能空间或布局要求未满足');
 await page.getByLabel('布局方法').selectOption('rules');
 const response=page.waitForResponse('**/api/generate');
 await page.locator('.generation-actions button.primary').click();
 const result=await(await response).json();
 expect(result.candidates).toEqual([]);
 await expect(page.locator('.generation-info')).toHaveCount(0);
 await expect(page.locator('.toast')).toContainText('未找到满足当前要求的方案');
});

test('functional repair is checked in preview and profiles survive apply and save',async({page})=>{
 const fixture=scene([
  item('sofa','sofa',3,2,{width:1.8,depth:.8,locked:true,functionalProfile:{frontUseDepth:.6,note:'自制回归参数'}}),
  item('coffee','coffee_table',5,4,{width:.9,height:.4}),
 ]);
 await load(page,fixture);
 await page.getByLabel('布局方法').selectOption('rules');
 const response=page.waitForResponse('**/api/generate');
 await page.locator('.generation-actions button.primary').click();
 const result=await(await response).json();
 expect(result.candidates.length).toBeGreaterThan(0);
 expect(result.candidates.every((c:{functionalSpaces:{satisfied:boolean}})=>c.functionalSpaces.satisfied)).toBe(true);
 await page.getByLabel('预览方案 1',{exact:true}).click();
 await page.locator('.preview-inspection summary').click();
 await expect(page.locator('.preview-check-details').getByRole('region',{name:'功能空间检查'})).toContainText('通过 · 已声明参数');
 await page.locator('.preview-banner').getByRole('button',{name:'应用此方案'}).click();
 const saving=page.waitForResponse('**/api/scenes/save');
 await page.getByRole('button',{name:'另存',exact:true}).click();
 const saved=await(await saving).json();
 const restored=await(await page.request.get('/api/scenes/'+saved.id)).json();
 expect(restored.items.find((i:{id:string})=>i.id==='sofa')).toMatchObject(fixture.items[0]);
});

test('two tables with added furniture produce usable candidates through preview and apply',async({page})=>{
 const fixture=JSON.parse(readFileSync(new URL('../../backend/tests/fixtures/crowded-functional-room.json',import.meta.url),'utf8'));
 fixture.name='功能空间回归';
 await load(page,fixture);
 await page.getByLabel('布局方法').selectOption('hybrid');
 const response=page.waitForResponse('**/api/generate');
 await page.locator('.generation-actions button.primary').click();
 const result=await(await response).json();
 // The bounded search can return fewer than three distinct arrangements.
 // It must find a usable result and every returned result must revalidate.
 expect(result.candidates.length).toBeGreaterThan(0);
 for(const candidate of result.candidates){
  expect(candidate.scene.items).toHaveLength(fixture.items.length);
  const check=await(await page.request.post('/api/validate',{data:{scene:candidate.scene}})).json();
  expect(check.valid).toBe(true);
  expect(check.requirements.satisfied).toBe(true);
  expect(check.functionalSpaces.satisfied).toBe(true);
  expect(check.functionalSpaces.warnings.every((warning:{required:boolean})=>!warning.required)).toBe(true);
 }
 await page.getByLabel('预览方案 1',{exact:true}).click();
 await expect(page.locator('.preview-inspection summary')).toContainText('空间检查通过');
 await page.locator('.preview-inspection summary').click();
 await expect(page.locator('.preview-check-details').getByRole('region',{name:'功能空间检查'})).not.toContainText('未满足');
 const recheck=page.waitForResponse('**/api/validate');
 await page.locator('.preview-banner').getByRole('button',{name:'应用此方案'}).click();
 const applied=await(await recheck).json();
 expect(applied.valid).toBe(true);
 expect(applied.functionalSpaces.satisfied).toBe(true);
 await expect(page.locator('.validation-hero')).toContainText('通过当前空间检查');
});
