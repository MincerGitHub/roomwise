import {test,expect} from '@playwright/test';

test('the fallback north-wall wardrobe faces into the room',async({page})=>{
 await page.goto('/');
 const layout=JSON.parse((await page.locator('.scene-canvas').getAttribute('data-layout'))!);
 const wardrobe=layout.find((item:[string,number,number,number])=>item[0]==='wardrobe-1');

 // The fallback wardrobe sits against the north wall (large z), so its local
 // +z front must point south, into the usable room.
 expect(wardrobe).toEqual(['wardrobe-1',1.15,3.8,180]);
});

test('candidate preview is isolated until explicitly applied',async({page})=>{
 await page.goto('/');
 const canvas=page.locator('.scene-canvas');
 await expect(canvas.locator('canvas')).toBeVisible();
 const original=JSON.parse((await canvas.getAttribute('data-layout'))!);
 const x=page.locator('.sidebar-content .field-grid').nth(1).locator('input').nth(0);
 const originalX=await x.inputValue();
 await page.locator('.generation-actions select').selectOption('rules');
 await page.locator('.generation-actions button.primary').click();
 const first=page.locator('.candidate-card').first();
 await expect(first).toBeVisible({timeout:40000});
 await first.locator('button').first().click();
 await expect(page.locator('.preview-banner')).toBeVisible();
 await expect.poll(async()=>JSON.parse((await canvas.getAttribute('data-layout'))!)).not.toEqual(original);
 await expect(x).toHaveValue(originalX);
 await expect(page.locator('.header-actions button').nth(4)).toBeDisabled();
 const preview=JSON.parse((await canvas.getAttribute('data-layout'))!);
 await page.locator('.preview-banner button').first().click();
 await expect(page.locator('.preview-banner')).toHaveCount(0);
 await expect.poll(async()=>JSON.parse((await canvas.getAttribute('data-layout'))!)).toEqual(original);
 await expect(x).toHaveValue(originalX);
 await first.locator('button').first().click();
 await expect.poll(async()=>JSON.parse((await canvas.getAttribute('data-layout'))!)).toEqual(preview);
 await page.locator('.preview-banner button').nth(1).click();
 await expect(page.locator('.preview-banner')).toHaveCount(0);
 await expect.poll(async()=>JSON.parse((await canvas.getAttribute('data-layout'))!)).toEqual(preview);
 await expect(x).not.toHaveValue(originalX);
});

test('invalid furniture size yields no candidates and current plan can be exported',async({page})=>{
 await page.goto('/');
 await page.locator('.item-card').first().click();
 const width=page.locator('.sidebar-content .field-grid').first().locator('input').first();
 await width.fill('9');await width.blur();
 await page.locator('.generation-actions select').selectOption('rules');
 await page.locator('.generation-actions button.primary').click();
 await expect(page.locator('.candidate-card')).toHaveCount(0,{timeout:40000});
 const download=page.waitForEvent('download');
 await page.locator('.header-actions .icon-btn').nth(2).click();
 expect((await download).suggestedFilename()).toMatch(/json$/);
});

test('top view drag edits furniture position while locked furniture stays put',async({page})=>{
 await page.goto('/');await page.locator('.view-switch button').nth(1).click();await page.waitForTimeout(600);
 const canvas=page.locator('canvas'),bounds=(await canvas.boundingBox())!;
 const scale=bounds.height/(2*5.2*.72);
 const point=(x:number,z:number)=>({x:bounds.x+bounds.width/2+(x-2.6)*scale,y:bounds.y+bounds.height/2+(z-2.1)*scale});
 const x=page.locator('.sidebar-content .field-grid').nth(1).locator('input').nth(0);
 const bed=point(3.8,2.4);await page.mouse.move(bed.x,bed.y);await page.mouse.down();await page.mouse.move(bed.x-35,bed.y+12,{steps:12});await page.mouse.up();
 await expect(x).not.toHaveValue('3.8');
 const cabinet=point(1.15,3.8);await page.mouse.move(cabinet.x,cabinet.y);await page.mouse.down();await page.mouse.move(cabinet.x+50,cabinet.y-30,{steps:8});await page.mouse.up();
 await expect(x).toHaveValue('1.15');
});

test('video extraction shows frames without inventing furniture candidates',async({page})=>{
 await page.goto('/');await page.locator('.tabs button').nth(2).click();
 await page.locator('input[type=file]').last().setInputFiles('../artifacts/detectors/integration_evidence/generated_engineering_clip.avi');
 await expect(page.locator('.video-frames img').first()).toBeVisible({timeout:45000});
 await expect(page.locator('.video-candidate')).toHaveCount(0);
});
