import {test,expect} from '@playwright/test';

test('bookshelf wall instruction has a real execution path and independent acceptance',async({page})=>{
 await page.goto('/');
 await page.locator('canvas').waitFor();
 await page.locator('.section-heading .text-btn').first().click();
 await page.locator('.catalog-grid').getByRole('button',{name:/书架/}).click();
 await expect(page.locator('.item-card')).toHaveCount(6);
 const generated=page.waitForResponse(r=>r.url().endsWith('/api/generate')&&r.request().method()==='POST');
 await page.getByLabel('输入修改要求').fill('书架靠墙');
 await page.getByLabel('发送要求').click();
 const result=await (await generated).json();
 expect(result.candidates.length).toBeGreaterThan(0);
 const requestList=page.getByLabel('已识别的布局要求');
 await expect(requestList).toContainText('书架：背面靠');
 for(const candidate of result.candidates){
  expect(candidate.validation.valid).toBe(true);
  const wall=candidate.requirements.checks.find((check:{kind:string})=>check.kind==='near_wall');
  expect(wall.required&&wall.satisfied).toBe(true);
  expect(wall.metrics.distanceMeters).toBeLessThanOrEqual(.15);
  expect(wall.metrics.backAlignmentErrorDegrees).toBeLessThanOrEqual(20);
 }
 await page.getByLabel('预览方案 1').click();
 await page.locator('.canvas-validation button').click();
 await expect(page.locator('.preview-check-details')).toContainText('距墙');
 await expect(page.locator('.preview-check-details .unmet')).toHaveCount(0);
 await expect(page.locator('.header-actions .btn.primary')).toBeDisabled();
});
