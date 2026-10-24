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
  await expect(page.locator('.generation-info')).toBeVisible();
 }
 await expect(page.locator('.command-warning')).toHaveCount(0);
});
