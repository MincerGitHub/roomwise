import {test,expect} from '@playwright/test';

test('window command is recognized and preview satisfies both requests without moving locks',async({page})=>{
 await page.goto('/');
 const canvas=page.locator('.scene-canvas');
 await expect(canvas.locator('canvas')).toBeVisible();
 const original=JSON.parse((await canvas.getAttribute('data-layout'))!);
 await page.getByLabel('布局方法').selectOption('hybrid');
 const commandResponse=page.waitForResponse(r=>r.url().endsWith('/api/command')&&r.request().method()==='POST');
 const generatedResponse=page.waitForResponse(r=>r.url().endsWith('/api/generate')&&r.request().method()==='POST',{timeout:45000});
 await page.getByLabel('输入修改要求').fill('桌子靠窗，椅子面朝窗户方向');
 await page.getByLabel('发送要求').click();
 const command=await (await commandResponse).json();
 expect(command.action).toBe('generate');
 expect(command.scene.preferences).toEqual(expect.arrayContaining([
  expect.objectContaining({kind:'near_window',itemId:'desk-1',required:true}),
  expect.objectContaining({kind:'face_window',itemId:'chair-1',required:true}),
 ]));
 const recognized=page.getByLabel('已识别的布局要求');
 await expect(recognized).toContainText('旧书桌：靠近');
 await expect(recognized).toContainText('办公椅：面朝');
 await expect(page.getByRole('alert')).toHaveCount(0);
 const generated=await (await generatedResponse).json();
 expect(generated.candidates.length).toBeGreaterThan(0);
 for(const candidate of generated.candidates){
  expect(candidate.validation.valid).toBe(true);
  expect(candidate.mode).toBe('rules');
  expect(candidate.provenance.layoutNetwork).toBe(false);
  expect(candidate.requirements.checks.filter((c:{required:boolean})=>c.required).every((c:{satisfied:boolean})=>c.satisfied)).toBe(true);
 }
 const candidate=generated.candidates[0];
 await page.getByLabel('预览方案 1').click();
 await expect(page.locator('.preview-banner')).toBeVisible();
 await expect(page.locator('main .preview-requirements, main .functional-relations')).toHaveCount(0);
 await expect(page.locator('.preview-check-details')).toHaveCount(0);
 await page.locator('.canvas-validation button').click();
 await expect(page.locator('.preview-check-details')).toContainText('距窗');
 await expect(page.locator('.preview-check-details')).toContainText('朝向偏差');
 await expect(page.locator('.preview-check-details .requirement-check.unmet')).toHaveCount(0);
 await page.evaluate(()=>window.scrollTo(0,0));
 await page.screenshot({path:'../artifacts/interaction_checks/window_request_preview.png',fullPage:true});
 await page.locator('.view-switch button').nth(1).click();
 await page.screenshot({path:'../artifacts/interaction_checks/window_request_top.png',fullPage:true});
 const preview=JSON.parse((await canvas.getAttribute('data-layout'))!);
 // The original scene is unchanged until the user explicitly applies.
 await expect(page.locator('.header-actions .btn.primary')).toBeDisabled();
 for(const locked of command.scene.items.filter((i:{locked:boolean})=>i.locked)){
  const item=candidate.scene.items.find((i:{id:string})=>i.id===locked.id);
  expect([item.x,item.z,item.rotation]).toEqual([locked.x,locked.z,locked.rotation]);
 }
 const desk=candidate.scene.items.find((i:{id:string})=>i.id==='desk-1');
 const chair=candidate.scene.items.find((i:{id:string})=>i.id==='chair-1');
 const window=candidate.scene.room.windows[0];
 expect(window.wall).toBe('north');
 // Independent checks against the known north window, rather than trusting
 // only the backend's satisfied flag.
 const angle=desk.rotation*Math.PI/180;
 const corners=[[-1,-1],[-1,1],[1,-1],[1,1]].map(([sx,sz])=>({x:desk.x+Math.cos(angle)*sx*desk.width/2+Math.sin(angle)*sz*desk.depth/2,z:desk.z-Math.sin(angle)*sx*desk.width/2+Math.cos(angle)*sz*desk.depth/2}));
 expect(candidate.scene.room.depth-Math.max(...corners.map((p:{z:number})=>p.z))).toBeLessThanOrEqual(.6001);
 expect(Math.max(...corners.map((p:{x:number})=>p.x))).toBeGreaterThanOrEqual(window.offset-.1501);
 expect(Math.min(...corners.map((p:{x:number})=>p.x))).toBeLessThanOrEqual(window.offset+window.width+.1501);
 const dx=window.offset+window.width/2-chair.x,dz=candidate.scene.room.depth-chair.z;
 const forwardX=Math.sin(chair.rotation*Math.PI/180),forwardZ=Math.cos(chair.rotation*Math.PI/180);
 const error=Math.acos(Math.max(-1,Math.min(1,(forwardX*dx+forwardZ*dz)/Math.hypot(dx,dz))))*180/Math.PI;
 expect(error).toBeLessThanOrEqual(20.001);
 await page.locator('.preview-banner').getByRole('button',{name:'退出预览'}).click();
 await expect.poll(async()=>JSON.parse((await canvas.getAttribute('data-layout'))!)).toEqual(original);
 expect(preview).not.toEqual(original);
});

test('unrecognized command removes stale candidates and requires explicit acknowledgement',async({page})=>{
 await page.goto('/');
 await page.getByLabel('布局方法').selectOption('rules');
 const generateButton=page.locator('.generation-actions button.primary');
 await generateButton.click();
 await expect(page.locator('.candidate-card').first()).toBeVisible({timeout:45000});
 let generatedAfterRejection=0;
 page.on('request',request=>{if(request.url().endsWith('/api/generate'))generatedAfterRejection++});
 await page.route('**/api/command',route=>route.fulfill({json:{action:'unsupported',message:'当前尚未支持这个颜色要求，本次未修改。'}}));
 await page.getByLabel('输入修改要求').fill('所有家具换成红色');
 await page.getByLabel('发送要求').click();
 await expect(page.getByRole('alert')).toContainText('本次文字要求未应用');
 await expect(page.locator('.message.warning')).toContainText('本次未修改');
 await expect(page.locator('.candidate-card')).toHaveCount(0);
 await expect(page.locator('.generation-info')).toHaveCount(0);
 await expect(generateButton).toBeDisabled();
 expect(generatedAfterRejection).toBe(0);
 await page.getByRole('button',{name:'忽略本次要求'}).click();
 await expect(page.getByRole('alert')).toHaveCount(0);
 await expect(generateButton).toBeEnabled();
 expect(generatedAfterRejection).toBe(0);
});

test('no accepted candidate explains requirements instead of claiming the plan passed',async({page})=>{
 await page.goto('/');
 await page.route('**/api/generate',route=>route.fulfill({json:{candidates:[],diagnostics:{message:'必须靠窗要求未满足；请检查锁定家具。'}}}));
 await page.locator('.generation-actions button.primary').click();
 await expect(page.locator('.generation-info')).toContainText('未找到同时满足空间检查和必须要求的候选');
 await expect(page.locator('.generation-info')).toContainText('必须靠窗要求未满足');
 await expect(page.locator('.generation-info')).toContainText('不表示一定无解');
 await expect(page.locator('.candidate-card')).toHaveCount(0);
});
