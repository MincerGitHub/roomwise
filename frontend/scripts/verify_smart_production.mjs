// Verify the built local UI and ordinary layout generation without paid calls.
import {chromium} from '@playwright/test';
import {mkdir,writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const output=path.join(root,'artifacts/interaction_checks');
await mkdir(output,{recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1100}});
 const errors=[];
 let commandRequests=0;
 page.on('pageerror',error=>errors.push(error.message));
 await page.route('**/api/command',route=>{commandRequests++;return route.abort();});
 await page.goto('http://127.0.0.1:8765');
 await page.locator('canvas').waitFor();
 await page.locator('.language-status.connected').waitFor();
 const languageText=await page.locator('.conversation-heading').innerText();
 assert.match(languageText,/deepseek-flash/);
 const generated=page.waitForResponse(r=>r.url().endsWith('/api/generate')&&r.request().method()==='POST');
 await page.getByRole('button',{name:'生成布局',exact:true}).click();
 const result=await (await generated).json();
 assert.equal(result.candidates.length,3);
 for(const candidate of result.candidates){
  assert.equal(candidate.validation.valid,true);
  assert.equal(candidate.provenance.initialization,'functional_group_template');
  assert.equal(candidate.provenance.layoutNetwork,false);
 }
 await page.getByLabel('预览方案 1').click();
 await page.getByRole('button',{name:'应用此方案',exact:true}).waitFor();
 await page.locator('canvas').scrollIntoViewIfNeeded();
 await page.screenshot({path:path.join(output,'functional_group_preview.png'),fullPage:true});
 assert.equal(commandRequests,0);
 assert.deepEqual(errors,[]);
 const report={checkedAt:new Date().toISOString(),url:'http://127.0.0.1:8765',
  paidCommandRequests:commandRequests,languageText,generation:result,previewAvailable:true,pageErrors:errors};
 await writeFile(path.join(output,'smart_production_check.json'),JSON.stringify(report,null,2),'utf8');
 console.log(JSON.stringify({candidates:result.candidates.length,elapsedSeconds:result.diagnostics.elapsedSeconds,
  paidCommandRequests:commandRequests,pageErrors:errors,previewAvailable:true}));
}finally{await browser.close();}
