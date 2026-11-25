import {test,expect,type Page} from '@playwright/test';

const validation={valid:true,issues:[],metrics:{}};
async function setup(page:Page){
 await page.route('**/api/**',async route=>{
  const endpoint=new URL(route.request().url()).pathname;
  if(endpoint==='/api/health')return route.fulfill({json:{status:'ok',modelLoaded:true}});
  if(endpoint==='/api/startup-scene')return route.fulfill({json:{scene:null}});
  if(endpoint==='/api/catalog')return route.fulfill({json:{items:[]}});
  if(endpoint==='/api/validate')return route.fulfill({json:validation});
  if(endpoint==='/api/generate'){
   const {scene}=route.request().postDataJSON();
   return route.fulfill({json:{candidates:[2.8,4.1].map((x,index)=>({id:'candidate-'+index,scene:{...scene,items:scene.items.map((item:{id:string})=>item.id==='bed-1'?{...item,x}:item)},validation})),diagnostics:{}}});
  }
  return route.continue();
 });
 await page.goto('/');
 await expect(page.locator('.scene-canvas canvas')).toBeVisible();
 await expect(page.getByRole('button',{name:'预览房间'})).toHaveCount(0);
 await expect(page.locator('.preview-guide')).toHaveCount(0);
 await page.getByRole('button',{name:'俯视',exact:true}).click();
}
async function point(page:Page,x:number,z:number,width=5.2,depth=4.2){
 const canvas=page.locator('.scene-canvas canvas');
 await canvas.scrollIntoViewIfNeeded();
 const bounds=(await canvas.boundingBox())!;
 const scale=Math.min(bounds.width,bounds.height)/(2*Math.max(width,depth)*.72);
 return {x:bounds.x+bounds.width/2+(x-width/2)*scale,y:bounds.y+bounds.height/2+(z-depth/2)*scale};
}
async function clickAt(page:Page,x:number,z:number){
 const target=await point(page,x,z);await page.mouse.click(target.x,target.y);
}

test('canvas stays mounted, clicks open the matching sidebar, and fullscreen keeps editing available',async({page})=>{
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));
 await setup(page);
 const canvas=page.locator('.scene-canvas canvas'),panel=page.locator('.sidebar-content');
 await canvas.evaluate(el=>el.setAttribute('data-instance','original'));
 await clickAt(page,1.3,1.8);
 await expect(panel.getByRole('heading',{name:'房间参数'})).toBeVisible();
 await expect(page.getByRole('dialog')).toHaveCount(0);
 await clickAt(page,3.8,2.4);
 await expect(panel.locator('.inspector-fold')).toHaveAttribute('open','');
 await expect(panel.getByLabel('名称',{exact:true})).toHaveValue('旧双人床');
 await panel.getByLabel('家具宽',{exact:true}).fill('1.9');
 await expect(panel.getByLabel('家具宽',{exact:true})).toHaveValue('1.9');
 await page.getByRole('button',{name:'全屏预览',exact:true}).click();
 await expect(page.locator('.editor-workspace')).toHaveClass(/is-fullscreen/);
 await expect.poll(()=>page.evaluate(()=>document.fullscreenElement?.tagName)).toBe('MAIN');
 await expect(page.locator('.editor-tools')).toBeVisible();
 await clickAt(page,1.3,1.8);
 await expect(panel.getByRole('heading',{name:'房间参数'})).toBeVisible();
 await expect(canvas).toHaveAttribute('data-instance','original');
 await page.screenshot({path:'../artifacts/permanent-preview/fullscreen.png'});
 await page.getByRole('button',{name:'退出全屏',exact:true}).click();
 await expect(page.locator('.editor-workspace')).not.toHaveClass(/is-fullscreen/);
 await expect(canvas).toHaveAttribute('data-instance','original');
 await page.screenshot({path:'../artifacts/permanent-preview/desktop.png',fullPage:true});
 expect(errors).toEqual([]);
});

test('candidate sidebar edits stay isolated until Apply',async({page})=>{
 await setup(page);
 const panel=page.locator('.sidebar-content');
 await page.getByRole('button',{name:'生成布局',exact:true}).click();
 await page.getByRole('button',{name:'预览方案 1',exact:true}).click();
 await clickAt(page,2.8,2.4);
 await panel.getByLabel('家具宽',{exact:true}).fill('2.1');
 await expect(page.getByRole('button',{name:'应用此方案'})).toBeEnabled();
 await page.getByRole('button',{name:'编辑房间参数'}).click();
 await panel.getByLabel('房间宽度').fill('6');
 await expect(page.getByRole('button',{name:'应用此方案'})).toBeEnabled();
 await page.getByRole('button',{name:'返回当前布局'}).click();
 await expect(panel.getByLabel('房间宽度')).toHaveValue('5.2');
 await page.getByRole('button',{name:'家具',exact:true}).click();
 await page.locator('.item-card').first().click();
 await expect(panel.getByLabel('家具宽',{exact:true})).toHaveValue('1.8');
 await page.getByRole('button',{name:'预览方案 1',exact:true}).click();
 await page.locator('.item-card').first().click();
 await panel.getByLabel('家具宽',{exact:true}).fill('2');
 await expect(page.getByRole('button',{name:'应用此方案'})).toBeEnabled();
 await page.getByRole('button',{name:'应用此方案'}).click();
 await expect(panel.getByLabel('家具宽',{exact:true})).toHaveValue('2');
 await expect(page.locator('.scene-canvas canvas')).toBeVisible();
 await expect(page.getByRole('button',{name:'返回当前布局'})).toHaveCount(0);
});

for(const width of [390,320]){
 test('permanent preview fits narrow viewport '+width,async({page})=>{
  await page.setViewportSize({width,height:844});
  await setup(page);
  await page.getByRole('button',{name:'三维',exact:true}).click();
  const canvas=page.locator('.scene-canvas canvas');
  const before=await canvas.boundingBox();
  await expect(page.locator('.room-preview .conversation')).toHaveCount(0);
  await expect(page.locator('.editor-conversation')).toBeVisible();
  expect(await canvas.boundingBox()).toEqual(before);
  await page.getByRole('button',{name:'进入室内'}).click();
  await expect(page.locator('.preview-adjustments')).toHaveCount(0);
  expect(await canvas.boundingBox()).toEqual(before);
  await page.getByRole('button',{name:'退出室内'}).click();
  await page.getByRole('button',{name:'全屏预览',exact:true}).click();
  await expect(page.locator('.editor-workspace')).toHaveClass(/is-fullscreen/);
  await page.getByRole('button',{name:'编辑房间参数'}).click();
  await expect(page.getByRole('spinbutton',{name:'房间宽度'})).toBeVisible();
  await page.screenshot({path:'../artifacts/permanent-preview/fullscreen-'+width+'.png'});
  await page.getByRole('button',{name:'退出全屏',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:'../artifacts/permanent-preview/mobile-'+width+'.png',fullPage:true});
 });
}
