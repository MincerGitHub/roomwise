// Exact bedside requests have a tested local path even when DeepSeek is enabled.
// Use a self-made fixture, never overwrite saved projects or call other commands.
import {chromium} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const output=path.join(root,'artifacts/interaction_checks');
const fixture=JSON.parse(await readFile(path.join(output,'bedside_after.json'),'utf8')).input;
const commandText='床头柜放床头的右侧';
const browser=await chromium.launch({channel:'msedge',headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try{
 const page=await browser.newPage({viewport:{width:1600,height:1150}});
 const errors=[];
 let commandRequests=0;
 page.on('pageerror',error=>errors.push(error.message));
 await page.route('**/api/command',route=>{
  const data=route.request().postDataJSON();
  if(data.text!==commandText)return route.abort();
  commandRequests++;
  return route.continue();
 });
 await page.goto('http://127.0.0.1:8765');
 await page.locator('canvas').waitFor();
 await page.locator('input[type="file"][accept=".json"]').setInputFiles({
  name:'bedside-regression.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(fixture))});
 const commandResponse=page.waitForResponse(r=>r.url().endsWith('/api/command')&&r.request().method()==='POST');
 const generatedResponse=page.waitForResponse(r=>r.url().endsWith('/api/generate')&&r.request().method()==='POST',{timeout:45000});
 await page.getByLabel('输入修改要求').fill(commandText);
 await page.getByLabel('发送要求').click();
 const command=await (await commandResponse).json();
 assert.equal(command.parser,'offline_restricted_chinese');
 assert.equal(command.action,'generate');
 const generation=await (await generatedResponse).json();
 assert.ok(generation.candidates.length>0);
 const independentChecks=[];
 for(const candidate of generation.candidates){
  assert.equal(candidate.validation.valid,true);
  assert.equal(candidate.requirements.satisfied,true);
  assert.equal(candidate.functionalRelations.satisfied,true);
  const bed=candidate.scene.items.find(i=>i.id==='bed-1');
  const stand=candidate.scene.items.find(i=>i.id==='nightstand-1');
  const angle=bed.rotation*Math.PI/180,dx=stand.x-bed.x,dz=stand.z-bed.z;
  const localX=Math.cos(angle)*dx-Math.sin(angle)*dz;
  const localZ=Math.sin(angle)*dx+Math.cos(angle)*dz;
  assert.ok(localX>bed.width/2);
  assert.ok(Math.abs(localZ-(-bed.depth/2+stand.depth/2+.08))<=.30);
  independentChecks.push({localX,localZ,right:true,atHead:true});
 }
 await page.getByLabel('预览方案 1').click();
 await page.getByRole('button',{name:'应用此方案',exact:true}).waitFor();
 await page.getByTestId('bed-head-marker').waitFor();
 await page.locator('canvas').scrollIntoViewIfNeeded();
 await page.screenshot({path:path.join(output,'bedside_screenshot_scene_preview.png'),fullPage:true});
 assert.equal(commandRequests,1);
 assert.deepEqual(errors,[]);
 await writeFile(path.join(output,'bedside_production_check.json'),JSON.stringify({
  checkedAt:new Date().toISOString(),url:'http://127.0.0.1:8765',commandText,command,generation,
  independentChecks,languageApiCalls:0,commandRequests,pageErrors:errors,previewAvailable:true},null,2),'utf8');
 console.log(JSON.stringify({candidates:generation.candidates.length,
  elapsedSeconds:generation.diagnostics.elapsedSeconds,languageApiCalls:0,pageErrors:errors,previewAvailable:true}));
}finally{await browser.close();}
