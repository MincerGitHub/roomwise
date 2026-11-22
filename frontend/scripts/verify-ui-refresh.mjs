import {chromium} from '@playwright/test';
import setup from '../tests/support/e2e-setup.mjs';
import {frontendUrl} from '../tests/support/e2e-environment.mjs';
const cleanup = await setup();
let browser;
try {
 browser = await chromium.launch({channel:'msedge',headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const page = await browser.newPage({viewport:{width:1440,height:1000},deviceScaleFactor:1});
 const errors=[];
 page.on('pageerror',error=>errors.push(error.message));
 await page.goto(frontendUrl);
 await page.locator('.scene-canvas canvas').waitFor();
 await page.waitForTimeout(1000);
 await page.screenshot({path:'../artifacts/ui-refresh/desktop.png',fullPage:true});
 for(const label of ['房间','视频录入','检查','家具']) {
  await page.locator('.tool-rail button').filter({hasText:label}).click();
  if(!await page.locator('.tool-rail button[aria-current="page"]').count()) throw new Error('Active navigation missing');
 }
 await page.getByRole('button',{name:'俯视',exact:true}).click();
 if(await page.getByRole('button',{name:'俯视',exact:true}).getAttribute('aria-pressed')!=='true') throw new Error('View switch failed');
 await page.getByRole('button',{name:'三维',exact:true}).click();
 await page.locator('.generation-actions select').selectOption('rules');
 const original = await page.locator('.scene-canvas').getAttribute('data-layout');
 await page.locator('.generation-actions button.primary').click();
 await page.locator('.candidate-card').first().waitFor({timeout:45000});
 await page.locator('.candidate-card').first().locator('button').click();
 await page.locator('.preview-banner').waitFor();
 if(!await page.getByRole('button',{name:'保存方案',exact:true}).isDisabled()) throw new Error('Preview save isolation failed');
 await page.getByRole('button',{name:'退出预览',exact:true}).click();
 await page.locator('.preview-banner').waitFor({state:'detached'});
 if(await page.locator('.scene-canvas').getAttribute('data-layout')!==original) throw new Error('Preview changed current layout');
 console.log('Candidate generation, preview isolation and exit passed');
 const desktopOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
 await page.setViewportSize({width:390,height:844});
 await page.screenshot({path:'../artifacts/ui-refresh/mobile.png',fullPage:true});
 const mobileOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
 await page.getByRole('button',{name:'自有家具库',exact:true}).click();
 await page.screenshot({path:'../artifacts/ui-refresh/furniture-library-mobile.png',fullPage:true});
 console.log(JSON.stringify({desktopOverflow,mobileOverflow,pageErrors:errors}));
 if(desktopOverflow||mobileOverflow||errors.length) process.exitCode=1;
} finally {
 await browser?.close();
 await cleanup();
}