import {test,expect,type Page} from '@playwright/test';

const makeItem=(id:string,category:string,x:number,z:number,width:number,depth:number,height:number,extra={})=>({id,label:id,category,x,z,width,depth,height,rotation:0,locked:false,keep:true,source:'brought',...extra});
const fixture=(extra={})=>({id:'stacking-browser',name:'箱子台面拖动',version:0,
 room:{width:6,depth:5,height:2.7,door:null,windows:[],polygon:null},preferences:[],items:[
  makeItem('table','table',3,2.5,1.6,1,.75,{locked:true}),
  makeItem('box','storage_box',1.2,2.5,.4,.3,.3,extra),
  makeItem('sofa','sofa',1.1,4.1,1.3,.7,.8),
  makeItem('small-top','nightstand',5,1,.3,.25,.5),
 ]});
type Pose={id:string;x:number;z:number;y:number;rotation:number;supportId:string|null};
async function poses(page:Page){return JSON.parse((await page.locator('.scene-canvas').getAttribute('data-placement'))!) as Pose[]}
async function load(page:Page,value=fixture(),top=true){
 await page.goto('/');
 await page.locator('input[type=file][accept=".json"]').setInputFiles({name:'surface.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(value))});
 await expect(page.locator('.canvas-header')).toContainText(value.name);
 if(top)await page.getByRole('button',{name:'俯视',exact:true}).click();
 await expect(page.locator('.scene-canvas canvas')).toBeVisible();
}
async function point(page:Page,x:number,z:number,y=0,top=true){
 const bounds=(await page.locator('.scene-canvas canvas').boundingBox())!;
 if(top){const scale=bounds.height/(2*6*.72);return {x:bounds.x+bounds.width/2+(x-3)*scale,y:bounds.y+bounds.height/2+(z-2.5)*scale}}
 return page.evaluate(async({bounds,x,z,y})=>{
  const THREE=await import('/node_modules/.vite/deps/three.js' as string);
  const camera=new THREE.PerspectiveCamera(38,bounds.width/bounds.height,.05,150);
  camera.position.set(3+6*1.13,6*1.13,2.5-5*1.15);camera.lookAt(3,.1,2.5);camera.updateMatrixWorld();
  const p=new THREE.Vector3(x,y,z).project(camera);
  return {x:bounds.x+(p.x+1)*bounds.width/2,y:bounds.y+(1-p.y)*bounds.height/2};
 },{bounds,x,z,y});
}
async function drag(page:Page,from:{x:number;y:number},to:{x:number;y:number}){
 await page.mouse.move(from.x,from.y);await page.mouse.down();await page.mouse.move(to.x,to.y,{steps:16});await page.mouse.up();
}

test('a box snaps near the table, slides on it, detaches and can be restored with undo and save',async({page})=>{
 await load(page);
 const original=await poses(page),initial=original.find(item=>item.id==='box')!;
 await drag(page,await point(page,initial.x,initial.z),await point(page,2.35,2.5));
 await expect.poll(async()=>(await poses(page)).find(item=>item.id==='box')!.supportId).toBe('table');
 let box=(await poses(page)).find(item=>item.id==='box')!;
 expect(box.y).toBe(.75);expect(box.x).toBeGreaterThanOrEqual(2.43-.00001);
 await expect(page.locator('.support-inspector-note')).toContainText('台面');
 await drag(page,await point(page,box.x,box.z),await point(page,3.25,2.7));
 box=(await poses(page)).find(item=>item.id==='box')!;
 expect(box.supportId).toBe('table');expect(box.x).toBeCloseTo(3.25,2);expect(box.z).toBeCloseTo(2.7,2);
 const supported=box;
 await drag(page,await point(page,box.x,box.z),await point(page,4.4,3));
 box=(await poses(page)).find(item=>item.id==='box')!;
 expect(box.supportId).toBeNull();expect(box.y).toBe(0);expect(box.x).toBeCloseTo(4.4,2);
 await page.getByRole('button',{name:'撤销',exact:true}).click();
 await expect.poll(async()=>(await poses(page)).find(item=>item.id==='box')).toEqual(supported);
 const saving=page.waitForResponse('**/api/scenes/save');await page.getByRole('button',{name:'另存',exact:true}).click();
 const identity=await (await saving).json(),saved=await (await page.request.get(`/api/scenes/${identity.id}`)).json();
 expect(saved.items.find((item:Pose)=>item.id==='box')).toMatchObject({y:.75,supportId:'table'});
 const validation=await (await page.request.post('/api/validate',{data:{scene:saved}})).json();expect(validation.valid).toBe(true);
 const others=(await poses(page)).filter(item=>item.id!=='box');expect(others).toEqual(original.filter(item=>item.id!=='box'));
});

test('rotated hosts carry boxes and a locked box prevents moving the host',async({page})=>{
 const value=fixture({x:3,z:2.5,y:.75,supportId:'table'});value.items[0].locked=false;
 value.items[0].rotation=37;value.items[1].rotation=37;
 await load(page,value);
 // Grab an empty part of the tabletop, leaving the box on its surface.
 await drag(page,await point(page,3.5,2.3),await point(page,4,2.6));
 let current=await poses(page),host=current.find(item=>item.id==='table')!,box=current.find(item=>item.id==='box')!;
 expect(host.x).toBeCloseTo(3.5,2);expect(box.x).toBeCloseTo(host.x,4);expect(box.z).toBeCloseTo(host.z,4);expect(box.y).toBe(.75);
 await page.locator('.item-card').filter({hasText:'table'}).click();
 await page.getByRole('button',{name:'旋转90°'}).click();
 current=await poses(page);host=current.find(item=>item.id==='table')!;box=current.find(item=>item.id==='box')!;
 expect(host.rotation).toBe(127);expect(box.rotation).toBe(127);expect(box.supportId).toBe('table');
 await page.locator('.item-card').filter({hasText:'box'}).click();await page.getByRole('button',{name:'切换位置锁定'}).click();
 const before=await poses(page);
 await page.locator('.item-card').filter({hasText:'table'}).click();await page.getByRole('button',{name:'旋转90°'}).click();
 expect(await poses(page)).toEqual(before);
});

test('soft seats, undersized tops, occupied surfaces and ceiling conflicts do not attract boxes',async({page})=>{
 await load(page);
 await drag(page,await point(page,1.2,2.5),await point(page,1.1,4.1));
 let box=(await poses(page)).find(item=>item.id==='box')!;expect(box.supportId).toBeNull();expect(box.y).toBe(0);
 await drag(page,await point(page,box.x,box.z),await point(page,5,1));
 box=(await poses(page)).find(item=>item.id==='box')!;expect(box.supportId).toBeNull();
 const occupied=fixture();occupied.items.push(makeItem('other-box','storage_box',3,2.5,.4,.3,.3,{y:.75,supportId:'table'}));
 await load(page,occupied);
 await drag(page,await point(page,1.2,2.5),await point(page,3,2.5));
 box=(await poses(page)).find(item=>item.id==='box')!;expect(box.supportId).toBeNull();
 const low=fixture();low.room.height=1;
 await load(page,low);await drag(page,await point(page,1.2,2.5),await point(page,3,2.5));
 expect((await poses(page)).find(item=>item.id==='box')!.supportId).toBeNull();
});

test('perspective dragging can lift a box onto the surface and drag it away again',async({page})=>{
 await load(page,fixture(),false);
 await drag(page,await point(page,1.2,2.5,.3,false),await point(page,3,2.5,.3,false));
 await expect.poll(async()=>(await poses(page)).find(item=>item.id==='box')!.supportId).toBe('table');
 const box=(await poses(page)).find(item=>item.id==='box')!;
 await drag(page,await point(page,box.x,box.z,1.05,false),await point(page,4.6,3.3,1.05,false));
 const detached=(await poses(page)).find(item=>item.id==='box')!;expect(detached.supportId).toBeNull();expect(detached.y).toBe(0);
});
