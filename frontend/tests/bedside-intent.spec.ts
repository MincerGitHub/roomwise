import {test,expect,type Page} from '@playwright/test';

const makeItem=(id:string,label:string,category:string,width:number,depth:number,height:number,x:number,z:number,rotation=0,locked=false)=>({id,label,category,width,depth,height,x,z,rotation,locked,keep:true,source:'brought'});
const fixture=(rotation=0)=>({id:'bedside-ui-fixture',name:'床头关系自制测试',version:0,room:{width:5.2,depth:4.2,height:2.7,polygon:null,door:{wall:'south',offset:.4,width:.9,clearance:.9},windows:[{id:'window-1',wall:'north',offset:2.3,width:1.5,sillHeight:.9}]},items:[
 makeItem('bed-1','旧双人床','double_bed',1.8,2,.55,2.4,2.2,rotation,true),
 // Keep the locked wardrobe on the north wall so its door-use zone does not
 // occupy the requested bed-head right side. The south-wall location blocked
 // every valid right-side nightstand pose after cabinet clearance became hard.
 makeItem('wardrobe-1','房内衣柜','wardrobe',1.5,.6,2.1,4.35,3.7,180,true),
 makeItem('desk-1','旧书桌','desk',1.2,.6,.75,.9,3.7),
 makeItem('chair-1','办公椅','chair',.48,.5,.85,.9,3.1,0),
 makeItem('nightstand-1','床头柜','nightstand',.45,.4,.5,2.4,3.65),
],preferences:[]});

async function loadFixture(page:Page,rotation=0){
 await page.goto('/');
 await expect(page.locator('.scene-canvas canvas')).toBeVisible();
 await page.locator('input[type="file"][accept=".json"]').setInputFiles({name:'bedside-fixture.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture(rotation)))});
 await expect(page.locator('.canvas-header')).toContainText('床头关系自制测试');
 await page.getByLabel('布局方法').selectOption('hybrid');
}

test('bedside request means head-right in bed coordinates and remains a preview until applied',async({page},testInfo)=>{
 await loadFixture(page);
 const canvas=page.locator('.scene-canvas');
 const original=JSON.parse((await canvas.getAttribute('data-layout'))!);
 // The selected bed exposes its actual head end, matching pillows at local -z.
 await expect(page.getByTestId('bed-head-marker')).toBeVisible();
 const head=JSON.parse((await canvas.getAttribute('data-bed-head'))!);
 expect(head.localDirection).toBe('-z');
 expect(head.rightLocalDirection).toBe('+x');
 expect(head.z).toBeCloseTo(1.2,5);
 const commandResponse=page.waitForResponse(r=>r.url().endsWith('/api/command')&&r.request().method()==='POST');
 const generateResponse=page.waitForResponse(r=>r.url().endsWith('/api/generate')&&r.request().method()==='POST',{timeout:45000});
 await page.getByLabel('输入修改要求').fill('床头柜放床头的右侧');
 await page.getByLabel('发送要求').click();
 const command=await (await commandResponse).json();
 expect(command.action).toBe('generate');
 expect(command.scene.preferences).toEqual(expect.arrayContaining([expect.objectContaining({kind:'bedside',itemId:'nightstand-1',targetId:'bed-1',side:'right',required:true})]));
 const recognized=page.getByLabel('已识别的布局要求');
 await expect(recognized).toContainText('床头柜：旧双人床的床头右侧（站在床尾看床头）');
 await expect(page.getByRole('alert')).toHaveCount(0);
 const generated=await (await generateResponse).json();
 expect(generated.candidates.length).toBeGreaterThan(0);
 for(const candidate of generated.candidates){
  expect(candidate.validation.valid).toBe(true);
  expect(candidate.validation.metrics.cabinetDoorConflicts).toBe(0);
  const check=candidate.requirements.checks.find((c:{kind:string})=>c.kind==='bedside');
  expect(check).toMatchObject({targetId:'bed-1',side:'right',required:true,satisfied:true});
  const bed=candidate.scene.items.find((i:{id:string})=>i.id==='bed-1');
  const stand=candidate.scene.items.find((i:{id:string})=>i.id==='nightstand-1');
  const angle=bed.rotation*Math.PI/180,dx=stand.x-bed.x,dz=stand.z-bed.z;
  const localX=Math.cos(angle)*dx-Math.sin(angle)*dz;
  const localZ=Math.sin(angle)*dx+Math.cos(angle)*dz;
  // Independent geometry, not merely the backend's satisfied flag.
  expect(localX).toBeGreaterThan(bed.width/2);
  expect(localZ).toBeLessThan(0);
  expect(Math.abs(localZ-(-bed.depth/2+stand.depth/2))).toBeLessThanOrEqual(.3001);
  for(const before of fixture().items){
   const after=candidate.scene.items.find((i:{id:string})=>i.id===before.id);
   expect([after.width,after.depth,after.height,after.locked,after.keep]).toEqual([before.width,before.depth,before.height,before.locked,before.keep]);
   if(before.id!=='nightstand-1')expect([after.x,after.z,after.rotation]).toEqual([before.x,before.z,before.rotation]);
  }
 }
 await page.getByLabel('预览方案 1').click();
 await expect(page.locator('.preview-banner')).toBeVisible();
 await expect(page.locator('.preview-requirements')).toContainText('床侧间距');
 await expect(page.locator('.preview-requirements')).toContainText('床头位置偏差');
 await expect(page.locator('.preview-requirements')).toContainText(' m');
 await expect(page.locator('.preview-requirements')).not.toContainText('距窗');
 await expect(page.locator('.preview-requirements .unmet')).toHaveCount(0);
 await expect(page.locator('.header-actions .btn.primary')).toBeDisabled();
 await expect(page.getByLabel('家具搭配检查')).toContainText('不能只看是否靠近床');
 await page.getByRole('button',{name:'俯视',exact:true}).click();
 await expect(page.getByTestId('bed-head-marker')).toBeVisible();
 await page.screenshot({path:testInfo.outputPath('bedside-right-preview.png'),fullPage:true});
 await page.locator('.preview-banner').getByRole('button',{name:'退出预览'}).click();
 await expect.poll(async()=>JSON.parse((await canvas.getAttribute('data-layout'))!)).toEqual(original);
});

test('rotating the bed preserves head-side meaning independently of the camera',async({page})=>{
 await loadFixture(page,90);
 const response=page.waitForResponse(r=>r.url().endsWith('/api/generate')&&r.request().method()==='POST',{timeout:45000});
 await page.getByLabel('输入修改要求').fill('床头柜放床头的右侧');
 await page.getByLabel('发送要求').click();
 const generated=await (await response).json();
 expect(generated.candidates.length).toBeGreaterThan(0);
 const candidate=generated.candidates[0];
 expect(candidate.validation.valid).toBe(true);
 expect(candidate.validation.metrics.cabinetDoorConflicts).toBe(0);
 const bed=candidate.scene.items.find((i:{id:string})=>i.id==='bed-1');
 const stand=candidate.scene.items.find((i:{id:string})=>i.id==='nightstand-1');
 expect(bed.rotation).toBe(90);
 // At yaw90, bed-local +x points toward world -z; the head lies toward -x.
 expect(stand.z).toBeLessThan(bed.z-bed.width/2);
 expect(stand.x).toBeLessThan(bed.x);
 await page.getByLabel('预览方案 1').click();
 const canvas=page.locator('.scene-canvas');
 const before=await canvas.getAttribute('data-layout');
 await page.getByRole('button',{name:'俯视',exact:true}).click();
 await expect(canvas).toHaveAttribute('data-layout',before!);
 const head=JSON.parse((await canvas.getAttribute('data-bed-head'))!);
 expect(head.x).toBeCloseTo(bed.x-bed.depth/2,5);
 expect(head.z).toBeCloseTo(bed.z,5);
 await expect(page.getByLabel('已识别的布局要求')).toContainText('站在床尾看床头');
});
