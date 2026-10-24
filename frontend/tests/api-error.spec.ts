import {test,expect} from '@playwright/test';

test('a non-JSON command error is reported without rereading its response body',async({page})=>{
 await page.route('**/api/command',route=>route.fulfill({
  status:502,
  contentType:'text/html',
  body:'<html><body>upstream unavailable</body></html>',
 }));
 await page.goto('/');
 await page.locator('.command-box input').fill('请帮我调整一下');
 await page.locator('.command-box button').click();
 await expect(page.locator('.command-warning')).toContainText('请求失败（502）：upstream unavailable');
 await expect(page.locator('.command-warning')).not.toContainText('body stream already read');
});

test('a generic bed-in-front-of-wardrobe request reports the unsupported relation',async({page})=>{
 await page.goto('/');
 await page.locator('.command-box input').fill('\u628a\u5e8a\u653e\u5728\u8863\u67dc\u524d\u9762');
 await page.locator('.command-box button').click();
 await expect(page.locator('.command-warning')).toContainText('\u4e00\u822c\u5bb6\u5177\u4e4b\u95f4\u7684\u524d\u540e');
 await expect(page.locator('.command-warning')).toContainText('\u672c\u6b21\u672a\u4fee\u6539');
 await expect(page.locator('.candidate-card')).toHaveCount(0);
});
