import {test,expect,type Page,type Route} from '@playwright/test';

const photo={name:'draft-chair.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64')};

async function createDraft(page:Page,label?:string){
 const response=await page.request.post('/api/furniture/analyze',{multipart:{consent:'true',files:photo}});
 expect(response.ok()).toBe(true);
 const task=await response.json();
 await expect.poll(async()=>(await (await page.request.get(`/api/furniture/jobs/${task.jobId}`)).json()).status).toBe('failed');
 const draft=await (await page.request.get(`/api/furniture/drafts/${task.draftId}`)).json();
 if(!label)return draft;
 const saved=await page.request.post(`/api/furniture/drafts/${draft.id}/save`,{data:{expectedVersion:draft.version,properties:{...draft.properties,label}}});
 expect(saved.ok()).toBe(true);return saved.json();
}

test('draft deletion can be cancelled and persists without changing another draft or the room',async({page})=>{
 const draft=await createDraft(page,'待删除的草稿'),other=await createDraft(page);
 await page.goto('/');
 const canvas=page.locator('.scene-canvas');await expect(canvas.locator('canvas')).toBeVisible();
 const layout=await canvas.getAttribute('data-layout');
 await page.getByRole('button',{name:'自有家具库',exact:true}).click();
 const dialog=page.getByRole('dialog'),section=dialog.locator('.furniture-draft-section');
 const row=section.locator('.furniture-draft').filter({hasText:draft.id.slice(0,8)});
 const count=await section.locator('.furniture-draft').count();
 await row.locator('.furniture-draft-open').click();
 const label=dialog.getByLabel('家具名称',{exact:true});
 await expect(label).toHaveValue(draft.properties.label);
 await label.fill('尚未保存的修改');
 let deletions=0;page.on('request',request=>{if(request.method()==='DELETE'&&request.url().includes(`/drafts/${draft.id}`))deletions++});
 page.once('dialog',confirmation=>confirmation.dismiss());
 await row.getByRole('button',{name:/删除草稿/}).click();
 await expect(label).toHaveValue('尚未保存的修改');expect(deletions).toBe(0);
 page.once('dialog',confirmation=>confirmation.accept());
 const deleted=page.waitForResponse(response=>response.request().method()==='DELETE'&&response.url().includes(`/drafts/${draft.id}`));
 await row.getByRole('button',{name:/删除草稿/}).click();
 expect((await deleted).status()).toBe(200);
 await expect(row).toHaveCount(0);await expect(label).toHaveCount(0);
 await expect(section.locator('.furniture-count')).toHaveText(String(count-1));
 expect((await page.request.get(`/api/furniture/drafts/${draft.id}`)).status()).toBe(404);
 expect(await (await page.request.get(`/api/furniture/drafts/${other.id}`)).json()).toEqual(other);
 await dialog.getByRole('button',{name:'关闭自有家具库'}).click();
 expect(await canvas.getAttribute('data-layout')).toBe(layout);
 await page.reload();await page.getByRole('button',{name:'自有家具库',exact:true}).click();
 await expect(page.locator('.furniture-draft').filter({hasText:draft.id.slice(0,8)})).toHaveCount(0);
 await expect(page.locator('.furniture-draft').filter({hasText:other.id.slice(0,8)})).toBeVisible();
});

test('a pending draft reply cannot reopen an editor after deletion',async({page})=>{
 const draft=await createDraft(page,'延迟加载的草稿');
 let pending:Route|undefined;
 await page.route(`**/api/furniture/drafts/${draft.id}`,route=>{pending=route});
 await page.goto('/');await page.getByRole('button',{name:'自有家具库',exact:true}).click();
 const row=page.locator('.furniture-draft').filter({hasText:draft.id.slice(0,8)});
 await row.locator('.furniture-draft-open').click();await expect.poll(()=>!!pending).toBe(true);
 page.once('dialog',confirmation=>confirmation.accept());
 await row.getByRole('button',{name:/删除草稿/}).click();await expect(row).toHaveCount(0);
 const lateReply=page.waitForResponse(`**/api/furniture/drafts/${draft.id}`);
 await pending!.fulfill({json:draft});await (await lateReply).finished();
 await page.evaluate(()=>new Promise<void>(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve()))));
 await expect(page.getByLabel('家具名称',{exact:true})).toHaveCount(0);
});

test('an active recognition draft can be deleted without late polling restoring it',async({page})=>{
 const draft=await createDraft(page,'识别中的草稿');
 let jobs=0;
 await page.route(`**/api/furniture/jobs/${draft.jobId}`,route=>{jobs++;return route.fulfill({json:{id:draft.jobId,draftId:draft.id,status:'processing',error:null,errorCode:null}})});
 await page.goto('/');await page.getByRole('button',{name:'自有家具库',exact:true}).click();
 const row=page.locator('.furniture-draft').filter({hasText:draft.id.slice(0,8)});
 await row.locator('.furniture-draft-open').click();
 await expect.poll(()=>jobs).toBeGreaterThan(0);
 await expect(row.locator('.furniture-draft-open')).toBeDisabled();
 await expect(row.getByRole('button',{name:/删除草稿/})).toBeEnabled();
 page.once('dialog',confirmation=>confirmation.accept());
 await row.getByRole('button',{name:/删除草稿/}).click();
 await expect(row).toHaveCount(0);await expect(page.getByLabel('家具名称',{exact:true})).toHaveCount(0);
 await expect(page.getByLabel('选择家具图片')).toBeEnabled();
 expect((await page.request.get(`/api/furniture/drafts/${draft.id}`)).status()).toBe(404);
});
