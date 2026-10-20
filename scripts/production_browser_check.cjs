// Requires Playwright. Local mode uses explicitly labelled synthetic fixtures.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
(async()=>{
 const origin=process.argv[2]||'http://127.0.0.1:8765';
 const out=path.resolve('docs/production'); fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL}:{})});
 const results=[];
 for(const [width,height] of [[390,844],[768,1024],[1280,720],[1440,900],[1920,1080]]){
  const page=await browser.newPage({viewport:{width,height},reducedMotion:'reduce'}); const errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(origin,{waitUntil:'networkidle'});
  await page.locator('#apiState').waitFor();
  const state=await page.locator('#apiState').innerText();
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);
  await page.screenshot({path:path.join(out,`${origin.includes('127.0.0.1')?'local':'live'}-${width}.png`),fullPage:true});
  let investigation=null;
  if(origin.includes('127.0.0.1')||process.env.RUN_PREVIEW==='1'){
   await page.locator('#runInvestigation').click();
   await page.locator('#exportCase').waitFor({timeout:30000});
   investigation=await page.locator('#liveResults').innerText();
   await page.screenshot({path:path.join(out,`${origin.includes('127.0.0.1')?'local':'live'}-result-${width}.png`),fullPage:true});
  }
  results.push({width,height,state,overflow,errors,investigationCompleted:!!investigation,hasSkeptic:investigation?.includes('SKEPTIC REVIEW')||false});
  await page.close();
 }
 await browser.close();
 fs.writeFileSync(path.join(out,origin.includes('127.0.0.1')?'local-browser.json':'live-browser.json'),JSON.stringify(results,null,2));
 console.log(JSON.stringify(results,null,2));
 if(results.some(r=>r.overflow||r.errors.length))process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1});
