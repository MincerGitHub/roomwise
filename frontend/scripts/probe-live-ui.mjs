import {chromium} from '@playwright/test';
const browser=await chromium.launch({channel:'msedge',headless:true});
try {
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 await page.goto('http://127.0.0.1:8765/?ui=studio-20261122',{waitUntil:'networkidle'});
 await page.screenshot({path:'../artifacts/ui-refresh/live.png'});
 console.log(JSON.stringify(await page.evaluate(()=>({
 url:location.href,
 rail:!!document.querySelector('.tool-rail'),
 railDirection:document.querySelector('.tool-rail')&&getComputedStyle(document.querySelector('.tool-rail')).flexDirection,
 sidebarHeading:document.querySelector('.sidebar-intro h1')?.textContent,
 styles:[...document.styleSheets].map(s=>s.href),
 meta:document.querySelector('.canvas-room-meta')?.textContent
 }))));
} finally {await browser.close();}