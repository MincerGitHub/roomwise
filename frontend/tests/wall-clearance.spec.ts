import {test,expect,type Page} from '@playwright/test';

const object=(id:string,category:string,values={})=>({id,label:id,category,width:1,depth:.4,height:1,x:3,z:2.5,rotation:0,locked:false,keep:true,source:'brought',...values});
const fixture=(items:unknown[],windows:unknown[]=[])=>({id:'wall-clearance',name:'壁挂遮挡回归',version:0,
 room:{width:6,depth:5,height:3,door:null,windows},items,preferences:[]});
const device=()=>object('空调','air_conditioner',{width:.9,depth:.2,height:.3,x:1,z:4.88,y:1.4,rotation:180});
async function load(page:Page,scene:unknown){
 await page.goto('/');
 await page.locator('input[type=file][accept=".json"]').setInputFiles({name:'clearance.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(scene))});
 await expect(page.locator('.canvas-header')).toContainText('壁挂遮挡回归');
 await page.locator('.tabs button').filter({hasText:'检查'}).click();
}

test('television sight obstruction is visible and a low table clears the same path',async({page})=>{
 await load(page,fixture([
  object('电视','wall_tv',{depth:.08,height:.7,z:4.94,y:1.05,rotation:180,locked:true}),
  object('沙发','sofa',{width:1.8,depth:.8,height:.85,z:1}),
  object('阻挡书架','bookshelf',{width:1.2,depth:.3,height:2,z:3}),
 ]));
 await expect(page.getByRole('region',{name:'壁挂家具检查'})).toContainText('视线被阻挡书架遮挡');
 await expect(page.locator('.validation-hero')).toContainText('需要调整');
 await page.locator('.tabs button').filter({hasText:'家具'}).click();
 await page.locator('.item-card').filter({hasText:'阻挡书架'}).click();
 await page.getByLabel('家具高',{exact:true}).fill('.3');await page.getByLabel('家具高',{exact:true}).blur();
 await page.locator('.tabs button').filter({hasText:'检查'}).click();
 await expect(page.getByRole('region',{name:'壁挂家具检查'})).toContainText('采样观看视线通过');
});

test('imported overlap and AC airflow conflict fail validation and generation',async({page})=>{
 const window={id:'window',wall:'north',offset:2,width:2,sillHeight:1,height:1.2};
 await load(page,fixture([
  {...device(),x:3,y:1.5,locked:true},
  object('高柜','bookshelf',{width:.8,depth:.2,height:1.4,x:3,z:4.3,locked:true}),
 ],[window]));
 const check=page.getByRole('region',{name:'壁挂家具检查'});
 await expect(check).toContainText('与窗户重叠');
 await expect(check).toContainText('被高柜占用');
 await page.getByLabel('布局方法').selectOption('rules');
 const response=page.waitForResponse('**/api/generate');await page.locator('.generation-actions button.primary').click();
 expect((await(await response).json()).candidates).toEqual([]);
});

test('3D wall dragging avoids a window while retaining a valid installation',async({page})=>{
 await load(page,fixture([device()],[{id:'w',wall:'north',offset:2,width:2,sillHeight:1,height:1.2}]));
 const canvas=page.locator('.scene-canvas');
 async function point(x:number,y:number,z:number){
  const bounds=(await canvas.locator('canvas').boundingBox())!;
  return page.evaluate(async({bounds,x,y,z})=>{
   const THREE=await import('/node_modules/.vite/deps/three.js' as string);
   const c=JSON.parse(document.querySelector('.scene-canvas')!.getAttribute('data-camera')!);
   const p=new THREE.Vector3(x,y,z).applyMatrix4(new THREE.Matrix4().fromArray(c.view)).applyMatrix4(new THREE.Matrix4().fromArray(c.projection));
   return {x:bounds.x+(p.x+1)*bounds.width/2,y:bounds.y+(1-p.y)*bounds.height/2};
  },{bounds,x,y,z});
 }
 const from=await point(1,1.55,4.88),to=await point(3,1.55,4.88);
 await page.mouse.move(from.x,from.y);await page.mouse.down();await page.mouse.move(to.x,to.y,{steps:18});await page.mouse.up();
 await expect.poll(async()=>{
  const pose=JSON.parse((await canvas.getAttribute('data-placement'))!)[0];
  return pose.y+.3<=.98||pose.y>=2.22||pose.x+.45<=1.98||pose.x-.45>=4.02;
 }).toBe(true);
 const saving=page.waitForResponse('**/api/scenes/save');await page.getByRole('button',{name:'另存',exact:true}).click();
 const {id}=await(await saving).json(),scene=await(await page.request.get('/api/scenes/'+id)).json();
 const check=await(await page.request.post('/api/validate',{data:{scene}})).json();
 expect(check.valid).toBe(true);expect(check.wallAppliances.satisfied).toBe(true);
 expect(scene.room.windows[0].height).toBe(1.2);
});

test('four-wall snapping uses window elevation and refuses a fully covered wall',async({page})=>{
 await page.goto('/');
 const rows=await page.evaluate(async()=>{
  const {wallPlacement}=await import('/src/wallPlacement.ts' as string);
  const room={width:6,depth:5,height:3,door:null,windows:[] as unknown[]};
  const item={id:'tv',label:'tv',category:'wall_tv',width:1,depth:.2,height:.6,x:3,z:4.88,y:1.2,rotation:180,locked:false,keep:true,source:'brought'};
  const answers=[];
  for(const wall of ['north','south','west','east']){
   const window={id:'w',wall,offset:2,width:2,sillHeight:1,height:1.2};
   const horizontal=['north','south'].includes(wall);
   const x=horizontal?3:wall==='west'?.12:5.88,z=horizontal?(wall==='north'?4.88:.12):3;
   const occupied={...room,windows:[window]};
   const snap=wallPlacement(item,x,z,occupied,wall);
   const above=wallPlacement({...item,y:2.3},x,z,occupied,wall);
   answers.push({snap,above});
  }
  const full={...room,windows:['north','south','west','east'].map(wall=>({id:wall,wall,offset:0,width:['north','south'].includes(wall)?6:5,sillHeight:0,height:3}))};
  return {answers,impossible:wallPlacement(item,3,2.5,full)};
 });
 for(const {snap,above} of rows.answers){
  expect(snap.placement.y>=2.22||snap.placement.y+.6<=.98).toBe(true);
  expect(above.placement.y).toBe(2.3);
 }
 expect(rows.impossible).toBeNull();
});
