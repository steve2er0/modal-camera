/* Optional browser regression suite. Run against an isolated demo session.
   Install Playwright separately, or set PLAYWRIGHT_MODULE to an approved local
   installation. This script starts its own server on 8770 by default. */
const fs=require('fs');
const path=require('path');
const assert=require('assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..'),checks=[];
const port=process.env.UI_PORT||'8770',url=`http://127.0.0.1:${port}`;
(async()=>{
  let server,browser;
  const errors=[];
  const check=(name,details)=>{checks.push({name,passed:true,details});console.log('PASS '+name);};
  try{
    if(process.env.UI_START_SERVER!=='0'){
      // A live port is an existing session, not an invitation to replace it.
      let occupied=false;try{await fetch(url);occupied=true;}catch{}
      if(occupied)throw new Error(`Port ${port} is occupied. Choose an unused UI_PORT for this test.`);
      const python=process.env.UI_PYTHON_BIN||path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
      server=require('child_process').spawn(python,['-B',path.join(root,'app.py'),'--port',port],{cwd:root,stdio:'ignore'});
      let started=false;
      for(let attempt=0;attempt<80;attempt++){try{const response=await fetch(url);if(response.ok){started=true;break;}}catch{}await new Promise(resolve=>setTimeout(resolve,250));}
      if(!started)throw new Error('Local test server failed to start.');
    }
    browser=await chromium.launch({headless:true});
    const page=await browser.newPage({viewport:{width:1420,height:1000},deviceScaleFactor:1});
    page.on('pageerror',error=>errors.push(error.message));
    const ready=()=>page.waitForFunction(()=>!document.body.classList.contains('busy'),{timeout:60000});
    const clickWork=async id=>{await page.locator('#'+id).click();await ready();};
    const synced=()=>page.waitForFunction(()=>document.getElementById('exportResponse').disabled===false);
    await page.goto(url);await page.getByRole('heading',{name:'Modal Camera',exact:true}).waitFor();
    await clickWork('cleanDemo');
    assert.match(await page.locator('#status').innerText(),/Response ready at 3\.000/);
    assert.match(await page.locator('#results').textContent(),/0\.3977 px/);
    assert.match(await page.locator('#results').textContent(),/60\.2°/);
    assert.equal(await page.locator('#advanced').evaluate(e=>e.open),false);
    check('One action prepares band, point fits and spatial response with Advanced closed');
    const tops=await page.locator('.canvaswrap').evaluateAll(elements=>elements.map(e=>e.getBoundingClientRect().top));
    assert.equal(tops[0],tops[1]);check('Original and response images align');
    await page.locator('#frequency').fill('7');
    assert.equal(await page.locator('#results').textContent(),'');
    assert.equal(await page.locator('#exportResponse').isEnabled(),false);
    await clickWork('processResponse');
    assert.match(await page.locator('#appliedSummary').innerText(),/6\.500–7\.500/);
    assert.match(await page.locator('#results').textContent(),/0\.1228 px/);
    check('Changing target removes old results and updates linked band');
    await page.locator('[data-view="phase"]').click();await synced();
    await page.locator('#sampleSelect').selectOption('39');
    assert.match(await page.locator('#responseInspect').innerText(),/relative phase/);
    await page.locator('#amplified').press('ArrowRight');
    assert.match(await page.locator('#responseInspect').innerText(),/Grid 41/);
    await page.reload();await page.locator('#workspace').waitFor();
    await page.waitForFunction(()=>document.getElementById('resultState').textContent==='Ready');
    assert.equal(await page.locator('#frequency').inputValue(),'7');
    assert.equal(await page.locator('#responseView').inputValue(),'phase');
    check('Refresh recovers active settings and computed results');
    await page.locator('#advanced > summary').click();
    await page.locator('#calibration').fill('2');await clickWork('reloadDropout');
    assert.equal(await page.locator('#calibration').inputValue(),'');
    assert.doesNotMatch(await page.locator('#results').textContent(),/mm/);
    assert.match(await page.locator('#results').textContent(),/Withheld/);
    check('New recording clears calibration and preserves dropout withholding');
    await page.locator('#clearPoints').click();await page.locator('#pointMode').click();
    await page.locator('#original').press('ArrowRight');await page.locator('#original').press('Enter');
    assert.match(await page.locator('#pointSummary').innerText(),/P1:/);
    check('Keyboard-only point selection');
    await page.locator('#gain').fill('21');await clickWork('processResponse');
    assert.match(await page.locator('#error').innerText(),/between 0 and 20/);
    const rect=await page.locator('#error').boundingBox();assert.ok(rect.y>=0&&rect.y+rect.height<=1000);
    await page.locator('#gain').fill('4');await clickWork('reloadDemo');
    check('Validation remains visible and valid retry recovers');
    for(const kind of ['heatmap','isolated','modal','analysis','samples','traces']){
      await page.locator('#exportKind').selectOption(kind);
      const pending=page.waitForEvent('download');await clickWork('exportResponse');
      const download=await pending;
      assert.match(download.suggestedFilename(),kind==='analysis'?/\.json$/:['samples','traces'].includes(kind)?/\.csv$/:/\.mp4$/);
      assert.equal(await page.locator('#workspace').isVisible(),true);
    }
    check('All six export choices download without navigation');
    await page.locator('#editTiming').click();
    await page.locator('#timingMode').selectOption('capture');await page.locator('#captureFps').fill('240');
    await clickWork('setTimebase');assert.match(await page.locator('#error').innerText(),/Confirm one encoded frame/);
    await page.locator('#sampleTiming').check();await clickWork('setTimebase');
    assert.equal(await page.locator('#frequency').inputValue(),'3');
    assert.equal(await page.locator('#exportResponse').isEnabled(),false);
    check('Capture assumption requires confirmation and clears downstream exports');
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
    check('Narrow layout has no document overflow');
    assert.deepEqual(errors,[]);check('No browser JavaScript errors');
    fs.writeFileSync(path.join(root,'evidence/workflow-smoke-validation.json'),JSON.stringify({browser:'Playwright Chromium headless',checks,errors},null,2)+'\n');
  }finally{if(browser)await browser.close();if(server)server.kill();}
})().catch(error=>{console.error(error);process.exitCode=1;});
