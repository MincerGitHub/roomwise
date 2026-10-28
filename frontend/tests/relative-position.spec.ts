import {test,expect} from '@playwright/test';

const scene={
 id:'relative-position-ui',name:'相对位置回归测试',version:0,
 room:{width:6,depth:6,height:2.7,polygon:null,door:null,windows:[]},
 items:[
  {id:'bed-subject',label:'双人床',category:'double_bed',width:1.8,depth:2,height:.55,x:1,z:1,rotation:0,locked:false,keep:true,source:'brought'},
  {id:'wardrobe-target',label:'衣柜',category:'wardrobe',width:1.5,depth:.6,height:2.1,x:3,z:5,rotation:180,locked:true,keep:true,source:'existing'},
 ],preferences:[],
};

function footprintsOverlap(a:{x:number;z:number;width:number;depth:number;rotation:number},b:{x:number;z:number;width:number;depth:number;rotation:number}){
 const corners=(item:typeof a)=>{
  const angle=item.rotation*Math.PI/180,c=Math.cos(angle),s=Math.sin(angle);
  return [[-1,-1],[-1,1],[1,-1],[1,1]].map(([sx,sz])=>[
   item.x+sx*item.width/2*c+sz*item.depth/2*s,
   item.z-sx*item.width/2*s+sz*item.depth/2*c,
  ] as const);
 };
 const first=corners(a),second=corners(b);
 const axes=[a,b].flatMap(item=>{const angle=item.rotation*Math.PI/180;return [[Math.cos(angle),-Math.sin(angle)],[Math.sin(angle),Math.cos(angle)]]});
 return axes.every(([x,z])=>{
  const av=first.map(point=>point[0]*x+point[1]*z),bv=second.map(point=>point[0]*x+point[1]*z);
  return Math.max(...av)>=Math.min(...bv)&&Math.max(...bv)>=Math.min(...av);
 });
}

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
 await page.locator('.canvas-validation button').click();
 await expect(page.locator('.preview-check-details')).toContainText('前方');
 await expect(page.locator('.preview-check-details')).toContainText('家具间距上限');
 await expect(page.locator('.header-actions .btn.primary')).toBeDisabled();
 await page.locator('.preview-banner .btn.primary').click();
 await expect(page.locator('.preview-banner')).toHaveCount(0);
 const applied=JSON.parse((await canvas.getAttribute('data-layout'))!);
 expect(applied).not.toEqual(original);
 expect(applied.find((item:[string,number,number,number])=>item[0]==='wardrobe-target')).toEqual(['wardrobe-target',3,5,180]);
});

test('the bed can stay left of the wardrobe while every generated nightstand clears its doors',async({page})=>{
 const cabinetScene={
  id:'cabinet-door-clearance',name:'衣柜柜门净空回归',version:0,
  room:{width:5.2,depth:4.2,height:2.7,polygon:null,door:{wall:'south',offset:.45,width:.9,clearance:.9},windows:[{id:'window-1',wall:'north',offset:2.3,width:1.5,sillHeight:.9}]},
  items:[
   {id:'bed-1',label:'旧双人床',category:'double_bed',width:1.8,depth:2,height:.55,x:3.03,z:2.64,rotation:180,locked:false,keep:true,source:'brought'},
   {id:'wardrobe-1',label:'房内衣柜',category:'wardrobe',width:1.8,depth:.6,height:2.1,x:1.15,z:3.8,rotation:180,locked:true,keep:true,source:'existing'},
   {id:'desk-1',label:'旧书桌',category:'desk',width:1.2,depth:.6,height:.75,x:3.7,z:.55,rotation:0,locked:false,keep:true,source:'brought'},
   {id:'chair-1',label:'办公椅',category:'chair',width:.5,depth:.5,height:.85,x:3.7,z:1.1,rotation:180,locked:false,keep:true,source:'brought'},
   {id:'nightstand-1',label:'床头柜',category:'nightstand',width:.5,depth:.45,height:.5,x:1.9,z:3.2,rotation:0,locked:false,keep:true,source:'existing'},
  ],preferences:[],
 };
 await page.goto('/');
 await page.locator('input[type="file"][accept=".json"]').setInputFiles({name:'cabinet-door-clearance.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(cabinetScene))});
 const response=page.waitForResponse(r=>r.url().endsWith('/api/generate')&&r.request().method()==='POST',{timeout:45000});
 await page.getByLabel('输入修改要求').fill('把旧双人床放在房内衣柜左侧');
 await page.getByLabel('发送要求').click();
 const generated=await (await response).json();
 expect(generated.candidates.length).toBeGreaterThan(0);
 for(const candidate of generated.candidates){
  expect(candidate.validation.valid).toBe(true);
  expect(candidate.validation.metrics.cabinetDoorConflicts).toBe(0);
  expect(candidate.validation.issues.some((issue:{type:string})=>issue.type==='cabinet_door_clearance')).toBe(false);
  const wardrobe=candidate.scene.items.find((item:{id:string})=>item.id==='wardrobe-1');
  expect([wardrobe.x,wardrobe.z,wardrobe.rotation,wardrobe.locked]).toEqual([1.15,3.8,180,true]);
 }
});

test('a chair can face a coffee table through command, preview and apply',async({page})=>{
 const faceScene={id:'face-item-ui',name:'朝向关系回归',version:0,room:{width:8,depth:8,height:2.7,polygon:null,door:null,windows:[]},items:[
  {id:'chair-1',label:'木质扶手椅',category:'armchair',width:.8,depth:.8,height:.85,x:1,z:1,rotation:0,locked:false,keep:true,source:'brought'},
  {id:'table-1',label:'茶几',category:'coffee_table',width:1.0,depth:.6,height:.42,x:4,z:4,rotation:0,locked:true,keep:true,source:'existing'},
 ],preferences:[]};
 await page.goto('/');
 await page.locator('input[type="file"][accept=".json"]').setInputFiles({name:'face-item.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(faceScene))});
 const response=page.waitForResponse(r=>r.url().endsWith('/api/generate')&&r.request().method()==='POST',{timeout:45000});
 await page.getByLabel('输入修改要求').fill('木质扶手椅要朝向茶几');
 await page.getByLabel('发送要求').click();
 await expect(page.getByLabel('已识别的布局要求')).toContainText('正面朝向茶几');
 const generated=await (await response).json();
 expect(generated.candidates.length).toBeGreaterThan(0);
 for(const candidate of generated.candidates){
  expect(candidate.validation.valid).toBe(true);
  const check=candidate.requirements.checks.find((value:{kind:string})=>value.kind==='face_item');
  expect(check).toMatchObject({itemId:'chair-1',targetId:'table-1',satisfied:true});
  const table=candidate.scene.items.find((item:{id:string})=>item.id==='table-1')!;
  expect([table.x,table.z,table.rotation,table.locked]).toEqual([4,4,0,true]);
 }
 await page.getByLabel('预览方案 1').click();
 await page.locator('.canvas-validation button').click();
 await expect(page.locator('.preview-check-details')).toContainText('正面需朝向茶几');
 await page.locator('.preview-banner .btn.primary').click();
 await expect(page.locator('.preview-banner')).toHaveCount(0);
});

test('an overlapping unlocked target is staged before placing a chair toward it',async({page})=>{
 const overlapping={
  id:'face-item-overlap',name:'朝向目标先选位',version:0,
  room:{width:8,depth:8,height:2.7,polygon:null,door:null,windows:[]},
  items:[
   {id:'chair-1',label:'木质扶手椅',category:'armchair',width:.8,depth:.8,height:.85,x:4,z:4,rotation:0,locked:false,keep:true,source:'brought'},
   {id:'table-1',label:'茶几',category:'coffee_table',width:1,depth:.6,height:.42,x:4,z:4,rotation:0,locked:false,keep:true,source:'existing'},
  ],preferences:[],
 };
 await page.goto('/');
 await page.locator('input[type="file"][accept=".json"]').setInputFiles({name:'face-item-overlap.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(overlapping))});
 const response=page.waitForResponse(r=>r.url().endsWith('/api/generate')&&r.request().method()==='POST',{timeout:45000});
 await page.getByLabel('输入修改要求').fill('木质扶手椅要朝向茶几');
 await page.getByLabel('发送要求').click();
 const generated=await (await response).json();
 expect(generated.candidates.length).toBeGreaterThan(0);
 for(const candidate of generated.candidates){
  expect(candidate.validation.valid).toBe(true);
  const items=candidate.scene.items as {id:string;x:number;z:number;rotation:number;locked:boolean;width:number;depth:number}[];
  const chair=items.find(item=>item.id==='chair-1')!;
  const table=items.find(item=>item.id==='table-1')!;
  expect(Math.hypot(chair.x-4,chair.z-4)).toBeGreaterThan(.01);
  expect(chair.locked).toBe(false);
  expect(table.locked).toBe(false);
  expect(candidate.requirements.checks).toEqual(expect.arrayContaining([
   expect.objectContaining({kind:'face_item',itemId:'chair-1',targetId:'table-1',satisfied:true}),
  ]));
  expect(footprintsOverlap(chair,table)).toBe(false);
 }
});

for(const relation of [
 {direction:'front',word:'前面',label:'前方',rotation:0,axis:'z',sign:1},
 {direction:'back',word:'后面',label:'后方',rotation:90,axis:'x',sign:-1},
 {direction:'left',word:'左边',label:'左侧（面对正面）',rotation:180,axis:'x',sign:1},
 {direction:'right',word:'右边',label:'右侧（面对正面）',rotation:270,axis:'z',sign:1},
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
  await page.locator('.canvas-validation button').click();
  await expect(page.locator('.preview-check-details')).toContainText(
   relation.direction==='left'?'左侧':relation.direction==='right'?'右侧':relation.label,
  );
  await page.locator('.preview-banner').getByRole('button',{name:'退出预览'}).click();
  await expect(canvas).toHaveAttribute('data-layout',original!);
  await page.getByLabel('预览方案 1').click();
  const preview=await canvas.getAttribute('data-layout');
  await page.locator('.preview-banner .btn.primary').click();
  await expect(page.locator('.preview-banner')).toHaveCount(0);
  await expect(canvas).toHaveAttribute('data-layout',preview!);
 });
}
