import {test,expect,type Page} from '@playwright/test';

type Pose={id:string;x:number;z:number;y:number;rotation:number;supportId:string|null};
const poses=async(page:Page)=>JSON.parse((await page.locator('.scene-canvas').getAttribute('data-placement'))!) as Pose[];
const fixture=(category='air_conditioner',locked=false)=>({id:'wall-snap',name:'四面墙吸附回归',version:0,
 room:{width:6,depth:5,height:2.7,door:null,windows:[]},preferences:[],items:[
  {id:'device',label:'测试壁挂设备',category,width:.9,depth:.2,height:.3,x:3,z:4.88,y:2.1,rotation:180,locked,keep:true,source:'brought'},
 ]});

async function load(page:Page,category='air_conditioner',locked=false,top=true){
 await page.goto('/');
 const scene=fixture(category,locked);
 await page.locator('input[type=file][accept=".json"]').setInputFiles({name:'walls.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(scene))});
 await expect(page.locator('.canvas-header')).toContainText(scene.name);
 if(top)await page.getByRole('button',{name:'俯视',exact:true}).click();
 await expect(page.locator('.scene-canvas')).toHaveAttribute('data-camera');
}

async function point(page:Page,x:number,z:number,y=2.25){
 const bounds=(await page.locator('.scene-canvas canvas').boundingBox())!;
 return page.evaluate(async({bounds,x,z,y})=>{
  const THREE=await import('/node_modules/.vite/deps/three.js' as string);
  const camera=JSON.parse(document.querySelector('.scene-canvas')!.getAttribute('data-camera')!);
  const p=new THREE.Vector3(x,y,z).applyMatrix4(new THREE.Matrix4().fromArray(camera.view)).applyMatrix4(new THREE.Matrix4().fromArray(camera.projection));
  return {x:bounds.x+(p.x+1)*bounds.width/2,y:bounds.y+(1-p.y)*bounds.height/2};
 },{bounds,x,z,y});
}

async function drag(page:Page,x:number,z:number){
 const original=(await poses(page))[0];
 const from=await point(page,original.x,original.z),to=await point(page,x,z);
 await page.mouse.move(from.x,from.y);await page.mouse.down();await page.mouse.move(to.x,to.y,{steps:18});
 await expect(page.locator('.surface-snap-hint')).toContainText('已吸附到');
 await page.mouse.up();
}

for(const category of ['air_conditioner','wall_tv']){
 test(`${category} snaps to all four walls, preserves height and supports undo/save`,async({page})=>{
  await load(page,category);
  for(const [x,z,rotation,expectedX,expectedZ] of [[.15,2.5,90,.12,2.5],[3,.15,0,3,.12],[5.85,2.5,270,5.88,2.5],[3,4.85,180,3,4.88]]){
   await drag(page,x,z);
   await expect.poll(async()=>(await poses(page))[0].rotation).toBe(rotation);
   const value=(await poses(page))[0];expect(value.x).toBeCloseTo(expectedX,2);expect(value.z).toBeCloseTo(expectedZ,2);expect(value.y).toBe(2.1);
  }
  await page.getByRole('button',{name:'撤销',exact:true}).click();
  await expect.poll(async()=>(await poses(page))[0].rotation).toBe(270);
  const savedResponse=page.waitForResponse('**/api/scenes/save');await page.getByRole('button',{name:'另存',exact:true}).click();
  const id=(await(await savedResponse).json()).id;
  const restored=await(await page.request.get('/api/scenes/'+id)).json();
  expect(restored.items[0]).toMatchObject({rotation:270,y:2.1,x:5.88});
  const check=await(await page.request.post('/api/validate',{data:{scene:restored}})).json();expect(check.valid).toBe(true);
 });
}

test('locked wall device stays put, and size edits keep an unlocked device against its wall',async({page})=>{
 await load(page,'air_conditioner',true);
 const from=await point(page,3,4.88),to=await point(page,.2,2.5);
 await page.mouse.move(from.x,from.y);await page.mouse.down();await page.mouse.move(to.x,to.y,{steps:10});await page.mouse.up();
 expect((await poses(page))[0]).toMatchObject({x:3,z:4.88,rotation:180});
 await page.getByRole('button',{name:'切换位置锁定'}).click();
 await page.getByLabel('家具深',{exact:true}).fill('.3');await page.getByLabel('家具深',{exact:true}).blur();
 await expect.poll(async()=>(await poses(page))[0].z).toBe(4.83);
});

test('snap clamps corners and ignores absent wall spans in a polygon room',async({page})=>{
 await page.goto('/');
 const result=await page.evaluate(async()=>{
  const {wallPlacement}=await import('/src/wallPlacement.ts' as string);
  const item={id:'tv',label:'tv',category:'wall_tv',width:1,depth:.2,height:.6,x:3,z:4.88,y:1.2,rotation:180,locked:false,keep:true,source:'brought'};
  const room={width:6,depth:5,height:2.7,door:null,windows:[]};
  const corner=wallPlacement(item,0,5,room);
  const cut={...room,polygon:[[0,0],[6,0],[6,3],[3,5],[0,5]]};
  const cutSnap=wallPlacement(item,5.8,4.9,cut);
  const oversized=wallPlacement({...item,width:7},3,2.5,room);
  return {corner,cutSnap,oversized};
 });
 expect(result.corner.placement.x).toBeGreaterThanOrEqual(.53);
 expect(result.corner.placement.z).toBe(4.88);
 expect(result.cutSnap.wall==='north'?result.cutSnap.placement.x<=2.47:result.cutSnap.placement.z<=2.47).toBe(true);
 expect(result.oversized).toBeNull();
});

for(const category of ['air_conditioner','wall_tv']){
 test(`${category} moves vertically and across a corner in 3D, with undo and saved height`,async({page})=>{
  await load(page,category,false,false);
  async function moveTo(x:number,z:number,y:number){
   const current=(await poses(page))[0],from=await point(page,current.x,current.z,current.y+.15),to=await point(page,x,z,y+.15);
   await page.mouse.move(from.x,from.y);await page.mouse.down();await page.mouse.move(to.x,to.y,{steps:18});
   await expect(page.locator('.surface-snap-hint')).toContainText('可上下拖动');await page.mouse.up();
  }
  await moveTo(4,4.88,1.6);
  await expect.poll(async()=>(await poses(page))[0].y).toBeCloseTo(1.6,2);
  expect((await poses(page))[0].x).toBeCloseTo(4,2);
  expect((await poses(page))[0].rotation).toBe(180);
  await moveTo(.12,3,1.4);
  await expect.poll(async()=>(await poses(page))[0].rotation).toBe(90);
  expect((await poses(page))[0].y).toBeCloseTo(1.4,2);
  expect((await poses(page))[0].z).toBeCloseTo(3,2);
  await page.getByRole('button',{name:'撤销',exact:true}).click();
  await expect.poll(async()=>(await poses(page))[0].rotation).toBe(180);
  expect((await poses(page))[0].y).toBeCloseTo(1.6,2);
  const response=page.waitForResponse('**/api/scenes/save');await page.getByRole('button',{name:'另存',exact:true}).click();
  const {id}=await(await response).json(),restored=await(await page.request.get('/api/scenes/'+id)).json();
  expect(restored.items[0].y).toBeCloseTo(1.6,2);
  const validation=await(await page.request.post('/api/validate',{data:{scene:restored}})).json();expect(validation.valid).toBe(true);
 });
}

test('vertical wall dragging stops at floor and ceiling and locks still protect height',async({page})=>{
 await load(page,'air_conditioner',false,false);
 async function moveTo(y:number){
  const current=(await poses(page))[0],from=await point(page,current.x,current.z,current.y+.15),to=await point(page,current.x,current.z,y+.15);
  await page.mouse.move(from.x,from.y);await page.mouse.down();await page.mouse.move(to.x,to.y,{steps:14});await page.mouse.up();
 }
 await moveTo(2.5);
 await expect.poll(async()=>(await poses(page))[0].y).toBe(2.4);
 await moveTo(-.05);
 await expect.poll(async()=>(await poses(page))[0].y).toBe(.1);
 await page.getByRole('button',{name:'切换位置锁定'}).click();
 await moveTo(1.3);
 expect((await poses(page))[0].y).toBe(.1);
 await page.getByRole('button',{name:'切换位置锁定'}).click();
 const original=(await poses(page))[0],from=await point(page,original.x,original.z,original.y+.15),to=await point(page,original.x,original.z,1.5);
 await page.mouse.move(from.x,from.y);await page.mouse.down();await page.mouse.move(to.x,to.y,{steps:12});
 await page.locator('.scene-canvas canvas').dispatchEvent('pointercancel');await page.mouse.up();
 expect((await poses(page))[0].y).toBe(.1);
});

test('all four wall planes accept vertical pointer motion without projecting to the floor',async({page})=>{
 await page.goto('/');
 const results=await page.evaluate(async()=>{
  const THREE=await import('/node_modules/.vite/deps/three.js' as string);
  const {beginWallDrag,moveWallDrag}=await import('/src/wallDrag.ts' as string);
  const room={width:6,depth:5,height:2.7,door:null,windows:[]};
  const planes=[[3,.12,0],[.12,2.5,90],[3,4.88,180],[5.88,2.5,270]];
  return planes.map(([x,z,rotation])=>{
   const item={id:'tv',label:'tv',category:'wall_tv',width:.9,depth:.2,height:.3,x,z,y:1.1,rotation,locked:false,keep:true,source:'brought'};
   const origin=new THREE.Vector3(3,1.5,2.5),ray=(height:number)=>new THREE.Ray(origin,new THREE.Vector3(x,height,z).sub(origin).normalize());
   const drag=beginWallDrag(item,ray(1.25),room),result=moveWallDrag(drag,ray(1.85),room);
   return result.placement;
  });
 });
 for(const [index,pose] of results.entries()){
  expect(pose.y).toBeCloseTo(1.7,4);expect(pose.rotation).toBe(index*90);
 }
});
