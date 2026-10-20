import {chromium} from '../frontend/node_modules/playwright-core/index.mjs';
import {mkdir, writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';

const directory = fileURLToPath(new URL('../artifacts/interaction_checks/', import.meta.url));
await mkdir(directory, {recursive:true});
const browser = await chromium.launch({channel:'msedge', headless:true,
  args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:8765/', {waitUntil:'networkidle'});
  await page.locator('canvas').waitFor();
  const generated = page.waitForResponse(response => response.url().endsWith('/api/generate') && response.request().method()==='POST');
  await page.getByLabel('输入修改要求').fill('桌子靠窗，椅子面朝窗户方向');
  await page.getByLabel('发送要求').click();
  const response = await generated;
  const result = await response.json();
  if (!response.ok() || !result.candidates?.length) throw new Error('No checked candidates from the production application');
  for (const candidate of result.candidates) {
    if (!candidate.validation.valid || !candidate.requirements.satisfied) throw new Error('Production returned an unchecked candidate');
    if (candidate.provenance.layoutNetwork !== false || candidate.mode !== 'rules') throw new Error('Incorrect generation attribution');
  }
  await page.getByLabel('预览方案 1').click();
  await page.locator('.preview-banner').waitFor();
  if (await page.locator('.preview-requirements .unmet').count()) throw new Error('Required condition unmet in preview');
  await page.screenshot({path:directory+'window_request_production.png', fullPage:true});
  const record = {checkedAt:new Date().toISOString(), url:page.url(),
    scriptUrls:await page.locator('script[src]').evaluateAll(scripts=>scripts.map(script=>script.src)),
    candidates:result.candidates.length, checks:result.candidates[0].requirements.checks,
    originalSceneUnchangedUntilApply:await page.locator('.header-actions .btn.primary').isDisabled(),
    pageErrors:errors, note:'Actual production port 8765; no save, upload or database mutation.'};
  if (errors.length) throw new Error(errors.join('\n'));
  await writeFile(directory+'window_request_production.json', JSON.stringify(record,null,2), 'utf8');
  process.stdout.write(JSON.stringify(record)+'\n');
} finally {
  await browser.close();
}
