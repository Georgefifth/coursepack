/* Real Firefox business-workflow acceptance. No DOM mutation or application-state shortcuts. */
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {execFileSync} = require('node:child_process');
const assert = require('node:assert/strict');
const {firefox} = require(process.env.COURSEPACK_PLAYWRIGHT || 'playwright');
const {expect} = require((process.env.COURSEPACK_PLAYWRIGHT || 'playwright') + '/test');
const root=path.resolve(__dirname,'..');
const base=process.argv[2] || 'https://georgefifth.github.io/coursepack/';
const label=process.argv[3] || 'public';
const output=path.join(root,'qa-output',label);
fs.mkdirSync(output,{recursive:true});
const fixtures=path.join(root,'qa-output','fixtures');
const results=[];
let browser;
function check(condition,message){assert.ok(condition,message)}
async function ready(p){await expect(p.locator('#workbench')).toBeVisible({timeout:90000});await expect(p.locator('#previewStatus')).toHaveText('Preview is up to date',{timeout:90000});await expect(p.locator('#importButton')).toBeEnabled({timeout:90000});await expect(p.frameLocator('#previewFrame').locator('article').first()).toBeVisible({timeout:15000});}
async function demo(p){await p.locator('#demoButton').click();await ready(p);console.log('Demo ready');}
async function upload(p,name,replace=false){const chooser=p.waitForEvent('filechooser');await p.locator(replace?'#replaceButton':'#importButton').click();await (await chooser).setFiles(path.join(fixtures,name));}
async function download(p,name,source){const event=p.waitForEvent('download',{timeout:30000});await p.getByRole('button',{name:'Download archive',exact:true}).click();const d=await event;assert.equal(await d.failure(),null);const file=path.join(output,name+'.zip');await d.saveAs(file);console.log('ZIP saved '+name);return JSON.parse(execFileSync('python3',[path.join(root,'qa','inspect_archive.py'),file,...(source ? [path.join(fixtures,source)] : [])],{encoding:'utf8',maxBuffer:20*1024*1024}));}
async function screenshot(p,name){console.log('Screenshot '+name);await p.screenshot({path:path.join(output,name+'.png'),fullPage:true,timeout:10000});}
async function test(name,work,options={}){
 const context=await browser.newContext({acceptDownloads:true,viewport:options.viewport || {width:1280,height:900},locale:'en-US',reducedMotion:'reduce'});
 const p=await context.newPage();const errors=[],failed=[],badResponses=[];const requests=[];
 context.on('page', page=>{page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')errors.push(m.text())});});
 p.on('pageerror',e=>errors.push(e.message));p.on('console',m=>{if(m.type()==='error')errors.push(m.text())});
 p.on('request',r=>requests.push({method:r.method(),url:r.url()}));
 p.on('requestfailed',r=>failed.push({url:r.url(),error:r.failure()?.errorText}));
 p.on('response',r=>{if(r.status()>=400)badResponses.push({url:r.url(),status:r.status()});});
 const started=Date.now();let status='Pass',error;console.log('Start '+name);p.setDefaultTimeout(15000);p.setDefaultNavigationTimeout(30000);
 try{
   await p.goto(base,{waitUntil:'load',timeout:60000});
   let timer;
   try { await Promise.race([work(p,context,requests),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Scenario exceeded 120 seconds')),120000);})]); } finally { clearTimeout(timer); }
   check(errors.length===0,'Console/page errors: '+JSON.stringify(errors));
   check(failed.length===0,'Failed requests: '+JSON.stringify(failed));
   const unexpected=badResponses.filter(r=>!(options.negative && r.url.includes('/api/import') && r.status===400));
   check(unexpected.length===0,'Unexpected HTTP errors: '+JSON.stringify(unexpected));
 }catch(e){status='Fail';error=e.stack;await screenshot(p,'FAIL-'+name.replace(/[^a-z0-9]+/gi,'-')).catch(()=>{});}
 results.push({name,status,durationMs:Date.now()-started,error,consoleErrors:errors,failedRequests:failed,httpErrors:badResponses});
 fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({base,browser:browser.version(),results},null,2));
 console.log(status+' '+name+(error?' — '+error.split('\n')[0]:''));
 await context.close();
}
(async()=>{
 browser=await firefox.launch({headless:true});console.log('Firefox '+browser.version()+' '+base);
 await test('First visit, English guidance, help dialog, keyboard escape',async p=>{
  await expect(p.locator('html')).toHaveAttribute('lang','en');await expect(p.getByRole('heading',{name:'A clear course archive. Ready to share.'})).toBeVisible();
  await expect(p.getByRole('button',{name:'Import course package',exact:true})).toBeVisible();
  check(!/[\u3400-\u9fff]/.test(await p.locator('body').innerText()),'Untranslated first-visit copy');
  await p.keyboard.press('Tab');await expect(p.getByRole('link',{name:'CoursePack home'})).toBeFocused();await p.keyboard.press('Tab');await expect(p.getByRole('button',{name:'Import guide'})).toBeFocused();await p.keyboard.press('Enter');
  await expect(p.getByRole('dialog',{name:'Import from Canvas'})).toBeVisible();await expect(p.getByRole('dialog')).toContainText('Offline HTML packages');await screenshot(p,'help');
  await p.keyboard.press('Escape');await expect(p.getByRole('dialog')).toBeHidden();await expect(p.getByRole('button',{name:'Import guide'})).toBeFocused();
  await p.getByRole('button',{name:'Import guide'}).click();await p.getByRole('button',{name:'Close import guide'}).click();await expect(p.getByRole('dialog')).toBeHidden();await screenshot(p,'welcome');
 });
 await test('Loading state blocks duplicate import and then completes',async(p,c)=>{
  const isStatic=await p.locator('html').getAttribute('data-engine')==='browser';
  await c.route(isStatic?'**/engine.py':'**/api/demo',async route=>{await new Promise(resolve=>setTimeout(resolve,1500));await route.continue();});
  await p.locator('#demoButton').click();await expect(p.locator('#demoButton')).toBeDisabled();await expect(p.locator('#importButton')).toHaveText('Reading…');await expect(p.locator('#clearButton')).toBeDisabled();await screenshot(p,'loading');
  await ready(p);await expect(p.locator('#demoButton')).toBeEnabled();await expect(p.locator('#selectionCount')).toHaveText('Selected 6 / 6 items');
 });
 await test('Demo: import, review, issue navigation, and complete ZIP',async(p,c,requests)=>{
  await demo(p);await expect(p.locator('#selectionCount')).toHaveText('Selected 6 / 6 items');await expect(p.locator('#issueCount')).toHaveText('2');
  await expect(p.frameLocator('#previewFrame').getByRole('heading',{name:'Design Research Methods · Fall Course',exact:true})).toBeVisible();
  await p.getByRole('tab',{name:'Review 2'}).click();await expect(p.locator('.issue-row')).toHaveCount(2);await screenshot(p,'review');
  await p.locator('.issue-row').first().getByRole('button',{name:'View material'}).click();await expect(p.getByRole('tab',{name:'Preview',exact:true})).toHaveAttribute('aria-selected','true');
  const before=requests.filter(r=>r.url.includes('/api/render')).length;const archive=await download(p,'demo');
  assert.equal(archive.report.included.length,6);assert.equal(archive.report.notices.length,2);check(archive.files.includes('assets/web_resources/interview.csv'),'Original CSV missing');
  check(!/[\u3400-\u9fff]/.test(archive.body+archive.index),'Untranslated generated/demo content');
  if(base.startsWith('https:'))check(!requests.some(r=>r.method==='POST'),'Static deployment sent course data via POST');
  else assert.equal(requests.filter(r=>r.url.includes('/api/render')).length,before,'Unchanged download rerendered preview');
  await screenshot(p,'demo-workbench');
 });
 await test('Uploaded package: original image, fragments, attachments, sanitization, and offline archive',async(p,c,requests)=>{
  await upload(p,'course.imscc');await ready(p);await expect(p.locator('#selectionCount')).toHaveText('Selected 4 / 4 items');
  const frame=p.frameLocator('#previewFrame');const image=frame.getByRole('img',{name:'Evidence figure'});await expect(image).toBeVisible();check(await image.evaluate(n=>n.complete&&n.naturalWidth===80),'Actual image did not load');
  await frame.getByRole('link',{name:'Continue to details',exact:true}).click();check(await frame.getByRole('heading',{name:'Details to verify'}).evaluate(n=>n.getBoundingClientRect().top>=-1&&n.getBoundingClientRect().top<200),'Fragment did not navigate to lesson');
  const externalPage=c.waitForEvent('page');await frame.getByRole('link',{name:'External reading',exact:true}).click();const external=await externalPage;await expect(external).toHaveURL('https://example.com/');await expect(external.getByRole('heading',{name:'Example Domain',exact:true})).toBeVisible();await expect(p.locator('#selectionCount')).toHaveText('Selected 4 / 4 items');await external.close();
  const archive=await download(p,'uploaded','course.imscc');assert.equal(archive.report.included.length,4);check(archive.files.includes('assets/resources/figure 图.png'),'Unicode image not preserved');check(archive.files.includes('assets/quiz.xml'),'Undeclared-in-module quiz not preserved');check(!archive.files.some(n=>n.includes('unreferenced')),'Unreferenced file leaked');check(!archive.body.includes('<script')&&!archive.body.includes('onclick='),'Active imported HTML survived');
  const reader=await c.newPage();await reader.goto(pathToFileURL(path.join(archive.extracted,'index.html')).href);await reader.getByRole('link',{name:'Read the complete body'}).click();await expect(reader.getByRole('heading',{name:'Welcome to the evidence course'})).toBeVisible();
  check(await reader.getByRole('img',{name:'Evidence figure'}).evaluate(n=>n.complete&&n.naturalWidth===80),'Extracted image failed');await reader.getByRole('link',{name:'Continue to details'}).click();check(await reader.getByRole('heading',{name:'Details to verify'}).evaluate(n=>Math.abs(n.getBoundingClientRect().top)<200),'Offline fragment failed');
  if(base.startsWith('https:'))check(!requests.some(r=>r.method==='POST'),'Uploaded input sent to a server');await screenshot(p,'uploaded');
 });
 await test('Selection, filtered module scope, no-results state, and batch selection',async p=>{
  await demo(p);await p.getByRole('searchbox',{name:'Find materials'}).fill('interview');await expect(p.locator('.item-row')).toHaveCount(2);await expect(p.locator('#selectionCount')).toHaveText('Selected 6 / 6 items');
  await p.getByRole('checkbox',{name:'Select module: Before you begin',exact:true}).uncheck();await expect(p.locator('#selectionCount')).toHaveText('Selected 5 / 6 items');await p.getByRole('searchbox',{name:'Find materials'}).fill('');await expect(p.getByRole('checkbox',{name:'Include: Course overview and learning goals',exact:true})).toBeChecked();
  await p.getByRole('button',{name:'Select all',exact:true}).click();await p.getByRole('button',{name:'Clear selection',exact:true}).click();
  await p.getByRole('searchbox',{name:'Find materials'}).fill('interview');await p.getByRole('button',{name:'Select matches',exact:true}).click();await expect(p.locator('#selectionCount')).toHaveText('Selected 2 / 6 items');
  await p.getByRole('searchbox',{name:'Find materials'}).fill('no-such-material');await expect(p.locator('.item-row')).toHaveCount(0);await expect(p.getByText('No matching materials. Change the search or clear the filters.')).toBeVisible();await expect(p.locator('#selectionCount')).toHaveText('Selected 2 / 6 items');await screenshot(p,'no-results');
  await p.getByRole('searchbox',{name:'Find materials'}).fill('');await expect(p.locator('.item-row')).toHaveCount(6);await p.getByRole('button',{name:'Select all',exact:true}).click();await expect(p.locator('#selectionCount')).toHaveText('Selected 6 / 6 items');
  await p.getByRole('checkbox',{name:'Only items needing review'}).check();await expect(p.locator('.item-row')).toHaveCount(2);await p.getByRole('checkbox',{name:'Only items needing review'}).uncheck();await expect(p.locator('.item-row')).toHaveCount(6);
 });
 await test('Rename, item/module buttons, reset, and exported order',async p=>{
  await demo(p);await p.getByRole('textbox',{name:'Archive name',exact:true}).fill('Evidence handover');
  const name=p.getByRole('textbox',{name:'Module name: Before you begin',exact:true});await name.fill('Start here');await name.press('Enter');
  await p.getByRole('button',{name:'Move item down: Course overview and learning goals',exact:true}).click();await p.getByRole('button',{name:'Move module up: Week 1: Observe real tasks',exact:true}).click();
  await p.getByRole('checkbox',{name:'Include: Further reading',exact:true}).uncheck();const archive=await download(p,'arranged');assert.equal(archive.report.title,'Evidence handover');assert.deepEqual(archive.report.included.map(i=>i.id),['i3','i4','i2','i1','i6']);assert.equal(archive.report.included[2].module,'Start here');assert.equal(archive.report.excluded_count,1);
  await p.getByRole('button',{name:'Restore original outline'}).click();await expect(p.locator('.module-title').first()).toHaveValue('Before you begin');await expect(p.getByRole('checkbox',{name:'Include: Further reading',exact:true})).not.toBeChecked();const reset=await download(p,'reset');assert.deepEqual(reset.report.included.map(i=>i.id),['i1','i2','i3','i4','i6']);
 });
 await test('Dragging item/module and collapse/expand preserve delivery',async p=>{
  await demo(p);const firstModule=p.locator('.module-heading').first();await firstModule.dragTo(p.locator('.module-heading').nth(1));
  await expect(p.locator('.module-title').first()).toHaveValue('Week 1: Observe real tasks');
  await p.locator('[data-drag="item"][data-id="i3"]').dragTo(p.locator('[data-drag="item"][data-id="i4"]'));const archive=await download(p,'dragged');assert.deepEqual(archive.report.included.map(i=>i.id),['i4','i3','i5','i1','i2','i6']);
  const collapse=p.getByRole('button',{name:'Expand or collapse module: Before you begin',exact:true});await collapse.click();await expect(p.getByRole('checkbox',{name:'Include: Course overview and learning goals',exact:true})).toHaveCount(0);await expect(p.locator('#selectionCount')).toHaveText('Selected 6 / 6 items');await collapse.click();await expect(p.getByRole('checkbox',{name:'Include: Course overview and learning goals',exact:true})).toBeChecked();
 });
 await test('Refresh, home navigation, back, reimport recovery, and clear',async p=>{
  await demo(p);await p.getByRole('textbox',{name:'Archive name',exact:true}).fill('Recovered draft');await p.getByRole('checkbox',{name:'Include: Further reading',exact:true}).uncheck();const n=p.getByRole('textbox',{name:'Module name: Before you begin',exact:true});await n.fill('Recovered module');await n.press('Enter');await p.getByRole('button',{name:'Move module up: Week 1: Observe real tasks',exact:true}).click();
  console.log('Refresh: reload');await p.reload({waitUntil:'domcontentloaded',timeout:30000});console.log('Refresh: welcome');await expect(p.locator('#welcome')).toBeVisible();await demo(p);await expect(p.locator('#courseTitle')).toHaveValue('Recovered draft');await expect(p.locator('#selectionCount')).toHaveText('Selected 5 / 6 items');await expect(p.locator('.module-title').first()).toHaveValue('Week 1: Observe real tasks');await expect(p.locator('.module-title').nth(1)).toHaveValue('Recovered module');
  console.log('Refresh: reimport');await upload(p,'demo.imscc',true);await ready(p);console.log('Refresh: reimported');await expect(p.locator('#courseTitle')).toHaveValue('Recovered draft');
  console.log('Refresh: home');await p.getByRole('link',{name:'CoursePack home'}).click();await expect(p.locator('#welcome')).toBeVisible();console.log('Refresh: forward');await p.goto(base+'?qa=back');console.log('Refresh: back');await p.goBack({waitUntil:'domcontentloaded',timeout:15000});console.log('Refresh: returned');await expect(p.locator('#welcome')).toBeVisible();await demo(p);await expect(p.locator('#courseTitle')).toHaveValue('Recovered draft');
  await p.getByRole('button',{name:'Clear course',exact:true}).click();await expect(p.locator('#welcome')).toBeVisible();await expect(p.locator('#message')).toHaveText("Course files and this tab's arrangement draft were cleared.");await demo(p);await expect(p.locator('#courseTitle')).toHaveValue('Design Research Methods · Fall Course');await expect(p.locator('#selectionCount')).toHaveText('Selected 6 / 6 items');
 });
 await test('Rename updates accessible control names',async p=>{
  await demo(p);const name=p.getByRole('textbox',{name:'Module name: Before you begin',exact:true});await name.fill('Accessible renamed module');await name.press('Enter');await expect(p.getByRole('textbox',{name:'Module name: Accessible renamed module',exact:true})).toHaveValue('Accessible renamed module');await expect(p.getByRole('checkbox',{name:'Select module: Accessible renamed module',exact:true})).toBeChecked();await p.getByRole('button',{name:'Move module down: Accessible renamed module',exact:true}).click();const a=await download(p,'accessible-renamed');check(a.report.included.some(i=>i.module==='Accessible renamed module'),'Renamed module absent from archive');
 });
 await test('Empty archive/module names recover with consistent preview and export',async p=>{
  await demo(p);await p.getByRole('textbox',{name:'Archive name',exact:true}).fill('   ');await p.getByRole('textbox',{name:'Archive name',exact:true}).press('Tab');await expect(p.locator('#courseTitle')).toHaveValue('Design Research Methods · Fall Course');await expect(p.locator('#message')).toContainText('Archive name cannot be empty');const name=p.getByRole('textbox',{name:'Module name: Before you begin',exact:true});await name.fill('');await name.press('Enter');await expect(p.locator('.module-title').first()).toHaveValue('Before you begin');const a=await download(p,'empty-name-recovery');assert.equal(a.report.title,'Design Research Methods · Fall Course');assert.equal(a.report.included[0].module,'Before you begin');
 });
 await test('Empty selection blocks exports and restores usable preview',async p=>{
  await demo(p);await p.getByRole('button',{name:'Clear selection',exact:true}).click();await expect(p.locator('#exportButton')).toBeDisabled();await expect(p.locator('#printButton')).toBeDisabled();await expect(p.frameLocator('#previewFrame').getByText('No materials selected. Choose the content to deliver in the outline.')).toBeVisible();await screenshot(p,'empty');await p.getByRole('button',{name:'Select all',exact:true}).click();await ready(p);await download(p,'after-empty');
 });
 for(const [file,feedback] of [['wrong.txt','Choose a Canvas .imscc or .zip course export.'],['oversize.imscc','This file exceeds 50 MB. Export a smaller course package.'],['corrupt.imscc','Could not read this archive. Choose a Canvas .imscc or .zip course export.'],['html-only.zip','Offline HTML packages are not supported.'],['empty.zip','No materials were found.'],['unsafe.zip','unsafe file path']]){
  await test('Invalid '+file+' keeps prior work and recovers',async p=>{
   await demo(p);await p.getByRole('textbox',{name:'Archive name',exact:true}).fill('Keep my work');await upload(p,file,true);await expect(p.locator('#message')).toContainText(feedback,{timeout:90000});await expect(p.locator('#message')).toHaveAttribute('role','alert');await expect(p.locator('#courseTitle')).toHaveValue('Keep my work');await expect(p.locator('#selectionCount')).toHaveText('Selected 6 / 6 items');await expect(p.locator('#replaceButton')).toBeEnabled();await screenshot(p,'error-'+file);const a=await download(p,'recovery-'+file);assert.equal(a.report.title,'Keep my work');await upload(p,'course.imscc',true);await ready(p);await expect(p.locator('#courseTitle')).toHaveValue('QA Evidence Course');await expect(p.locator('#selectionCount')).toHaveText('Selected 4 / 4 items');
  },{negative:true});
 }
 await test('Different-content reimport does not restore old arrangement',async p=>{
  await upload(p,'course.imscc');await ready(p);await p.getByRole('textbox',{name:'Archive name',exact:true}).fill('Old draft');await p.getByRole('checkbox',{name:'Include: Introduction',exact:true}).uncheck();await upload(p,'changed.imscc',true);await ready(p);await expect(p.locator('#courseTitle')).toHaveValue('QA Evidence Course');await expect(p.locator('#selectionCount')).toHaveText('Selected 4 / 4 items');await expect(p.frameLocator('#previewFrame').getByText('Different course content')).toBeVisible();
 });
 await test('Keyboard selection, ordering, tab navigation, and visible focus',async p=>{
  await demo(p);const checkbox=p.getByRole('checkbox',{name:'Include: Further reading',exact:true});await checkbox.focus();await p.keyboard.press('Space');await expect(p.locator('#selectionCount')).toHaveText('Selected 5 / 6 items');await expect(checkbox).not.toBeChecked();await expect(checkbox).toBeFocused();
  await p.getByRole('button',{name:'Move item down: Course overview and learning goals',exact:true}).focus();await p.keyboard.press('Enter');assert.deepEqual(await p.locator('.module-block').first().locator('.item-row').evaluateAll(ns=>ns.map(n=>n.dataset.id)),['i2','i1']);
  await p.getByRole('tab',{name:'Preview',exact:true}).focus();await p.keyboard.press('ArrowRight');await expect(p.locator('#issuesTab')).toHaveAttribute('aria-selected','true');await expect(p.locator('#issuesTab')).toBeFocused();await p.keyboard.press('ArrowLeft');await expect(p.locator('#previewTab')).toBeFocused();check(await p.locator('#previewTab').evaluate(n=>getComputedStyle(n).outlineStyle!=='none'),'No visible keyboard focus');
 });
 await test('Viewport stays anchored after reading and excluding earlier content',async p=>{
  await demo(p);await p.getByRole('button',{name:'Preview: Observation exercise',exact:true}).click();const frame=await p.locator('#previewFrame').contentFrame();const article=p.frameLocator('#previewFrame').locator('#i3');await p.mouse.move(1000,600);await p.mouse.wheel(0,180);await p.waitForTimeout(300);const before=await article.evaluate(n=>n.getBoundingClientRect().top);await p.getByRole('checkbox',{name:'Include: Course overview and learning goals',exact:true}).uncheck();await expect(p.locator('#previewStatus')).toHaveText('Preview is up to date');await p.waitForTimeout(300);const after=await article.evaluate(n=>n.getBoundingClientRect().top);check(Math.abs(before-after)<3,'Reading position moved '+(after-before)+'px');
 });
 await test('Print opens the arranged document and provides save guidance',async(p,c)=>{
  await demo(p);await p.getByRole('checkbox',{name:'Include: Further reading',exact:true}).uncheck();const popupPromise=p.waitForEvent('popup',{timeout:15000});await p.getByRole('button',{name:'Print / Save PDF',exact:true}).click();const popup=await popupPromise;await expect(popup.getByRole('heading',{name:'Design Research Methods · Fall Course',exact:true})).toBeVisible();await expect(popup.locator('article')).toHaveCount(5);await expect(p.locator('#message')).toContainText('Choose Save as PDF');await screenshot(popup,'print-document');await popup.close();await expect(p.locator('#printButton')).toBeEnabled();
 });
 results.push({name:'Save PDF through Firefox native print dialog',status:'Blocked',reason:'Headless Firefox does not expose an automatable OS print/save dialog; no PDF file saving is claimed.'});
 for(const [width,height] of [[1280,900],[768,1024],[390,844],[320,740]]){
  await test('Responsive '+width+'x'+height+': visible controls and usable workflow',async p=>{
   await screenshot(p,'welcome-'+width);let metrics=await p.evaluate(()=>({width:document.documentElement.clientWidth,content:document.documentElement.scrollWidth}));check(metrics.content<=metrics.width+1,'Welcome horizontal overflow '+JSON.stringify(metrics));
   await demo(p);await screenshot(p,'workbench-'+width);metrics=await p.evaluate(()=>({width:document.documentElement.clientWidth,content:document.documentElement.scrollWidth}));check(metrics.content<=metrics.width+1,'Workbench horizontal overflow '+JSON.stringify(metrics));
   for(const id of ['exportButton','printButton','replaceButton']){const rect=await p.locator('#'+id).boundingBox();check(rect&&rect.x>=-1&&rect.x+rect.width<=width+1,id+' outside viewport');}
   await p.getByRole('searchbox',{name:'Find materials'}).fill('worksheet');await expect(p.locator('.item-row')).toHaveCount(1);await p.getByRole('checkbox',{name:'Include: Interview worksheet',exact:true}).uncheck();await expect(p.locator('#selectionCount')).toHaveText('Selected 5 / 6 items');const archive=await download(p,'responsive-'+width);assert.equal(archive.report.included.length,5);check(!archive.report.included.some(i=>i.id==='i4'),'Mobile selection missing from output');
  },{viewport:{width,height}});
 }
 const stats=results.reduce((a,r)=>(a[r.status]++,a),{Pass:0,Fail:0,Blocked:0});fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({base,browser:browser.version(),stats,results},null,2));console.log(JSON.stringify(stats));await browser.close();process.exitCode=stats.Fail?1:0;
})().catch(async e=>{console.error(e);if(browser)await browser.close();process.exit(1)});
