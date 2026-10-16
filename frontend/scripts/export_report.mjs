import {chromium} from '@playwright/test';
import {pathToFileURL} from 'node:url';import path from 'node:path';
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage();
const source=path.resolve('../docs/技术报告.html');
await page.goto(pathToFileURL(source).href);await page.pdf({path:'../docs/技术报告.pdf',format:'A4',printBackground:true,preferCSSPageSize:true,displayHeaderFooter:true,headerTemplate:'<span></span>',footerTemplate:'<div style="width:100%;text-align:center;font-size:9px;color:#7d8b72"><span class="pageNumber"></span> / <span class="totalPages"></span></div>'});
await browser.close();console.log('技术报告.pdf 已生成');
