import {chromium} from '@playwright/test';
import fs from 'node:fs';import path from 'node:path';
const output=path.resolve('../artifacts/demo');fs.mkdirSync(output,{recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const context=await browser.newContext({viewport:{width:1440,height:1000},recordVideo:{dir:output,size:{width:1440,height:1000}}});
const page=await context.newPage();const started=Date.now();const chapters=[];
await page.goto('http://127.0.0.1:8765');await page.getByText('本机服务已连接').waitFor();
async function caption(title,body,seconds){
 chapters.push({timeSeconds:Math.round((Date.now()-started)/1000),title,body});
 await page.evaluate(({title,body})=>{
  let d=document.getElementById('demo-caption');if(!d){d=document.createElement('div');d.id='demo-caption';d.style.cssText='position:fixed;right:32px;top:87px;z-index:200;max-width:570px;background:#314c3eee;color:white;padding:11px 18px;border-radius:8px;box-shadow:0 4px 15px #18392820;pointer-events:none;font-family:Microsoft YaHei,sans-serif';document.body.append(d)}
  d.replaceChildren();const h=document.createElement('strong');h.textContent=title;h.style.cssText='display:block;font-size:13px;margin-bottom:4px';const p=document.createElement('span');p.textContent=body;p.style.cssText='display:block;font-size:11px;line-height:1.8;color:#e0e9d6';d.append(h,p)
 },{title,body});await page.waitForTimeout(seconds*1000);
}
try{
 await caption('归置 Roomwise｜保留旧家具的三维布局助手','实机操作录屏。输入是房间参数、已有家具和保留要求；输出是可编辑方案。',12);
 await page.getByRole('button',{name:'房间',exact:false}).first().click();
 await caption('01 确认房间与尺寸','首期单房间。门口净空与窗户由用户确认；户型图只作参考，不假装自动精确建模。',13);
 await page.getByRole('button',{name:'家具',exact:true}).click();await page.getByRole('button',{name:'房内衣柜',exact:false}).first().click();await page.locator('.inspector-heading').scrollIntoViewIfNeeded();
 await caption('02 保留家具，锁定位置','保留这件物品与锁住它的位置分开。房内衣柜已锁定，其他旧家具允许重新摆放。',14);
 await page.getByLabel('布局方法').selectOption('rules');await page.getByRole('button',{name:'生成布局',exact:true}).click();await page.locator('.candidate-card').first().waitFor({timeout:30000});
 await caption('03 规则基线生成','候选通过占地、门内净空和近似通路检查。系统保持家具身份和实测尺寸。',13);
 await page.locator('.candidate-card').first().getByRole('button',{name:'应用'}).click();await page.getByRole('button',{name:'俯视',exact:true}).click();
 await caption('04 查看与修改','应用方案后仍可编辑。切换俯视方便检查位置，三维用于空间示意。',12);
 await page.getByRole('button',{name:'三维',exact:true}).click();await page.getByRole('button',{name:'旧书桌',exact:false}).first().click();
 await page.getByLabel('布局方法').selectOption('hybrid');await page.getByLabel('输入修改要求').fill('书桌尽量靠窗');await page.getByRole('button',{name:'发送要求'}).click();await page.locator('.candidate-card').first().waitFor({timeout:30000});
 await caption('05 文字输入与模型重排','当前采用离线限定中文指令。靠窗是位置偏好；卡片明确区分模型与几何修正。',15);
 await page.locator('.candidate-card').first().getByRole('button',{name:'应用'}).click();await page.getByRole('button',{name:'俯视',exact:true}).click();
 await page.getByLabel('输入修改要求').fill('把选中的书桌旋转90度');await page.getByRole('button',{name:'发送要求'}).click();await page.waitForTimeout(800);
 await caption('06 旋转与撤销','明确操作可以直接执行。检查仍会提示冲突；撤销恢复上一版位置与条件。',12);
 await page.getByRole('button',{name:'撤销',exact:true}).click();await page.getByRole('button',{name:'另存',exact:true}).click();await page.waitForTimeout(800);
 await caption('07 保存与导出','保存到本机SQLite并管理版本，也可导入导出JSON；生成中的旧请求不覆盖后来修改。',10);
 await page.getByRole('button',{name:'旧双人床',exact:false}).first().click();await page.getByLabel('家具宽').fill('9');await page.getByLabel('家具宽').blur();await page.getByLabel('布局方法').selectOption('rules');await page.getByRole('button',{name:'生成布局',exact:true}).click();await page.waitForTimeout(1600);await page.getByRole('button',{name:'检查',exact:false}).first().click();
 await caption('08 失败明确展示','床比房间还宽时找不到方案。系统不会为了成功而缩小旧床或悄悄删除物品。',15);
 await page.getByRole('button',{name:'撤销',exact:true}).click();await page.getByRole('button',{name:'查看模型实验记录'}).click();
 await caption('09 实际训练与独立评价','73,604参数模型；682个独立测试卧室。人为扰动的位置误差降低，但越界仍需修复。',15);
 await page.locator('.modal-heading').getByRole('button').click();await page.getByRole('button',{name:'视频录入',exact:false}).click();
 await page.locator('input[type=file]').last().setInputFiles(path.resolve('../artifacts/detectors/integration_evidence/generated_engineering_clip.avi'));await page.getByRole('heading',{name:'关键画面'}).waitFor({timeout:30000});
 await caption('10 视频辅助录入','此处是自制工程样片，没有家具，所以返回0候选；检测器真实运行，不作为家具识别准确率。',13);
 await page.getByRole('button',{name:'家具',exact:true}).click();await page.getByRole('button',{name:'三维',exact:true}).click();
 const remaining=185-(Date.now()-started)/1000;
 await caption('完成范围与后续','可运行的单房间原型，自训练布局模型、独立检查和可编辑结果。真实视频准确率与用户研究尚未完成。',Math.max(8,remaining));
 const video=page.video();await page.close();await context.close();const source=await video.path();const dest=path.join(output,'Roomwise_demo.webm');if(source!==dest)fs.renameSync(source,dest);
 fs.writeFileSync(path.join(output,'chapters.json'),JSON.stringify({date:'2026-10-11',durationSeconds:(Date.now()-started)/1000,chapters,note:'Real browser UI recording with explanatory captions, no fake simulation or user-study claims'},null,2));console.log(dest);
}finally{await browser.close()}
