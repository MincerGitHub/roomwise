import {test,expect} from '@playwright/test';

const scene={
 id:'relative-position-ui',name:'相对位置回归测试',version:0,
 room:{width:6,depth:6,height:2.7,polygon:null,door:null,windows:[]},
 items:[
  {id:'bed-subject',label:'双人床',category:'double_bed',width:1.8,depth:2,height:.55,x:1,z:1,rotation:0,locked:false,keep:true,source:'brought'},
  {id:'wardrobe-target',label:'衣柜',category:'wardrobe',width:1.5,depth:.6,height:2.1,x:3,z:5,rotation:180,locked:true,keep:true,source:'existing'},
 ],preferences:[],
};

test('bed in front of a locked wardrobe follows its local front and stays a preview until applied',async({page})=>{
 await page.goto('/');
 await page.locator('input[type="file"][accept=".json"]').setInputFiles({
  name:'relative-position.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(scene)),
 });
 await expect(page.locator('.canvas-header')).toContainText('相对位置回归测试');
 const canvas=page.locator('.scene-canvas');
 const original=JSON.parse((await canvas.getAttribute('data-layout'))!);
 const commandResponse=page.waitForResponse(r=>r.url().endsWith('/api/command')&&r.request().method()==='POST');
 const generateResponse=page.waitForResponse(r=>r.url().endsWith('/api/generate')&&r.request().method()==='POST',{timeout:45000});
 await page.locator('.command-box input').fill('\u628a\u5e8a\u653e\u5728\u8863\u67dc\u524d\u9762');
 await page.locator('.command-box button').click();
 const command=await (await commandResponse).json();
 expect(command.action).toBe('generate');
 expect(command.scene.preferences).toEqual(expect.arrayContaining([
  expect.objectContaining({kind:'relative_position',itemId:'bed-subject',targetId:'wardrobe-target',direction:'front',required:true}),
 ]));
 await expect(page.getByLabel('已识别的布局要求')).toContainText('位于衣柜前方');
 const generated=await (await generateResponse).json();
 expect(generated.candidates.length).toBeGreaterThan(0);
 for(const candidate of generated.candidates){
  expect(candidate.validation.valid).toBe(true);
  const check=candidate.requirements.checks.find((value:{kind:string})=>value.kind==='relative_position');
  expect(check).toMatchObject({direction:'front',targetId:'wardrobe-target',required:true,satisfied:true});
  const before=scene.items.find(item=>item.id==='wardrobe-target')!;
  const after=candidate.scene.items.find((item:{id:string})=>item.id===before.id)!;
  expect([after.x,after.z,after.rotation]).toEqual([before.x,before.z,before.rotation]);
  const bed=candidate.scene.items.find((item:{id:string})=>item.id==='bed-subject')!;
  // A wardrobe rotated 180 degrees faces world -z.
  const bedHalfDepth=(Math.abs(Math.sin(bed.rotation*Math.PI/180))*bed.width+Math.abs(Math.cos(bed.rotation*Math.PI/180))*bed.depth)/2;
  expect(bed.z+bedHalfDepth).toBeLessThanOrEqual(after.z-after.depth/2-.025+1e-6);
 }
 await page.getByLabel('预览方案 1').click();
 await expect(page.locator('.preview-banner')).toBeVisible();
 await expect(page.locator('.preview-requirements')).toContainText('前方');
 await expect(page.locator('.preview-requirements')).toContainText('家具间距上限');
 await expect(page.locator('.header-actions .btn.primary')).toBeDisabled();
 await page.locator('.preview-banner .btn.primary').click();
 await expect(page.locator('.preview-banner')).toHaveCount(0);
 const applied=JSON.parse((await canvas.getAttribute('data-layout'))!);
 expect(applied).not.toEqual(original);
 expect(applied.find((item:[string,number,number,number])=>item[0]==='wardrobe-target')).toEqual(['wardrobe-target',3,5,180]);
});

for(const relation of [
 {direction:'front',word:'前面',label:'前方',rotation:0,axis:'z',sign:1},
 {direction:'back',word:'后面',label:'后方',rotation:90,axis:'x',sign:-1},
 {direction:'left',word:'左边',label:'左侧',rotation:180,axis:'x',sign:1},
 {direction:'right',word:'右边',label:'右侧',rotation:270,axis:'z',sign:1},
] as const){
 test(`${relation.direction} follows a wardrobe rotated ${relation.rotation} degrees through command, preview and apply`,async({page})=>{
  const fixture={...scene,room:{...scene.room,width:8,depth:8},items:scene.items.map(item=>item.id==='wardrobe-target'?{...item,x:4,z:4,rotation:relation.rotation}:item)};
  await page.goto('/');
  await page.locator('input[type="file"][accept=".json"]').setInputFiles({name:'relative-direction.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture))});
  await expect(page.locator('.canvas-header')).toContainText(fixture.name);
  const response=page.waitForResponse(r=>r.url().endsWith('/api/generate')&&r.request().method()==='POST',{timeout:45000});
  await page.getByLabel('输入修改要求').fill(`把床放在衣柜${relation.word}`);
  await page.getByLabel('发送要求').click();
  await expect(page.getByLabel('已识别的布局要求')).toContainText(`位于衣柜${relation.label}`);
  const generated=await (await response).json();
  expect(generated.candidates.length).toBeGreaterThan(0);
  for(const candidate of generated.candidates){
   expect(candidate.validation.valid).toBe(true);
   expect(candidate.requirements.checks).toEqual(expect.arrayContaining([expect.objectContaining({kind:'relative_position',direction:relation.direction,satisfied:true})]));
   const bed=candidate.scene.items.find((item:{id:string})=>item.id==='bed-subject');
   const wardrobe=candidate.scene.items.find((item:{id:string})=>item.id==='wardrobe-target');
   expect([wardrobe.x,wardrobe.z,wardrobe.rotation]).toEqual([4,4,relation.rotation]);
   // Independently check the expected world direction and footprint separation.
   const angle=bed.rotation*Math.PI/180;
   const bedSpan=relation.axis==='x'?Math.abs(Math.cos(angle))*bed.width+Math.abs(Math.sin(angle))*bed.depth:Math.abs(Math.sin(angle))*bed.width+Math.abs(Math.cos(angle))*bed.depth;
   const wardrobeSpan=relation.axis==='x'?(relation.rotation%180===0?wardrobe.width:wardrobe.depth):(relation.rotation%180===0?wardrobe.depth:wardrobe.width);
   const gap=relation.sign*(bed[relation.axis]-wardrobe[relation.axis])-(bedSpan+wardrobeSpan)/2;
   expect(gap).toBeGreaterThanOrEqual(.025-1e-6);
   expect(gap).toBeLessThanOrEqual(1.5+1e-6);
  }
  const canvas=page.locator('.scene-canvas');
  const original=await canvas.getAttribute('data-layout');
  await page.getByLabel('预览方案 1').click();
  await expect(page.locator('.preview-banner')).toBeVisible();
  await expect(page.locator('.preview-requirements')).toContainText(relation.label);
  await page.locator('.preview-banner').getByRole('button',{name:'退出预览'}).click();
  await expect(canvas).toHaveAttribute('data-layout',original!);
  await page.getByLabel('预览方案 1').click();
  const preview=await canvas.getAttribute('data-layout');
  await page.locator('.preview-banner .btn.primary').click();
  await expect(page.locator('.preview-banner')).toHaveCount(0);
  await expect(canvas).toHaveAttribute('data-layout',preview!);
 });
}
