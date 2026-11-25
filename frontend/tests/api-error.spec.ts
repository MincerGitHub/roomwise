import {test,expect} from '@playwright/test';

test('a non-JSON command error is reported without rereading its response body',async({page})=>{
 await page.route('**/api/command',route=>route.fulfill({
  status:502,
  contentType:'text/html',
  body:'<html><body>upstream unavailable</body></html>',
 }));
 await page.goto('/');
 await page.locator('.command-box input').fill('\u8bf7\u5e2e\u6211\u8c03\u6574\u4e00\u4e0b');
 await page.locator('.command-box button').click();
 await expect(page.locator('.command-warning')).toContainText('\u8bf7\u6c42\u5931\u8d25\uff08502\uff09\uff1aupstream unavailable');
 await expect(page.locator('.command-warning')).not.toContainText('body stream already read');
});

test('a language gateway policy rejection shows its actual reason and keeps the scene',async({page})=>{
 await page.route('**/api/command',route=>route.fulfill({json:{
  action:'clarify',parser:'language_model',
  message:'语言服务商的内容策略拒绝了本次请求（HTTP 403）；未获得布局计划，未修改场景。',
  languageError:{code:'provider_policy',httpStatus:403},
 }}));
 await page.goto('/');
 const canvas=page.locator('.scene-canvas');
 await expect(canvas.locator('canvas')).toBeVisible();
 const before=await canvas.getAttribute('data-layout');
 let generated=0;
 page.on('request',request=>{if(request.url().endsWith('/api/generate'))generated++});
 await page.getByLabel('输入修改要求').fill('让书桌的采光好一点');
 await page.getByLabel('发送要求',{exact:true}).click();
 await expect(page.locator('.message.warning')).toContainText('内容策略拒绝');
 await expect(page.locator('.command-warning')).toContainText('HTTP 403');
 await expect(page.locator('.generation-actions button.primary')).toBeDisabled();
 expect(await canvas.getAttribute('data-layout')).toBe(before);
 expect(generated).toBe(0);
});

test('a bed in front of a wardrobe reaches the geometry solver without a false success',async({page})=>{
 await page.goto('/');
 const commandResponse=page.waitForResponse(r=>r.url().endsWith('/api/command')&&r.request().method()==='POST');
 const generateResponse=page.waitForResponse(r=>r.url().endsWith('/api/generate')&&r.request().method()==='POST',{timeout:45000});
 await page.locator('.command-box input').fill('\u628a\u5e8a\u653e\u5728\u8863\u67dc\u524d\u9762');
 await page.locator('.command-box button').click();
 const command=await (await commandResponse).json();
 expect(command.action).toBe('generate');
 expect(command.scene.preferences).toEqual(expect.arrayContaining([
  expect.objectContaining({kind:'relative_position',itemId:'bed-1',targetId:'wardrobe-1',direction:'front',required:true}),
 ]));
 const generated=await (await generateResponse).json();
 if(generated.candidates.length){
  for(const candidate of generated.candidates){
   expect(candidate.validation.valid).toBe(true);
   expect(candidate.requirements.checks).toEqual(expect.arrayContaining([
    expect.objectContaining({kind:'relative_position',direction:'front',satisfied:true}),
   ]));
  }
 }else{
  await expect(page.locator('.toast')).toContainText('未找到满足当前要求的方案');
 }
 await expect(page.locator('.command-warning')).toHaveCount(0);
});
