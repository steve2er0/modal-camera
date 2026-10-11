/* Optional reproducible browser QA. Install Playwright separately, or point
   PLAYWRIGHT_MODULE at an already approved local Playwright installation. */
const fs=require('fs');
const path=require('path');
const assert=require('assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const root=path.resolve(__dirname,'..');
const checks=[];
const port=process.env.UI_PORT||'8765';
const url=`http://127.0.0.1:${port}`;
(async()=>{
  let server;
  if(process.env.UI_START_SERVER==='1'){
    const python=process.env.UI_PYTHON_BIN||path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
    server=require('child_process').spawn(python,['-B',path.join(root,'app.py'),'--port',port],{cwd:root,stdio:'ignore'});
    let started=false;
    for(let attempt=0;attempt<40;attempt++){try{const response=await fetch(url);if(response.ok){started=true;break;}}catch{}await new Promise(resolve=>setTimeout(resolve,250));}
    if(!started){server.kill();throw new Error('Local test server failed to start.');}
  }
  const browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1420,height:1100},deviceScaleFactor:1});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const check=(name,details)=>{checks.push({name,passed:true,details});console.log('PASS '+name);};
  const ready=()=>page.waitForFunction(()=>!document.body.classList.contains('busy'),{timeout:60000});
  const clickWork=async id=>{await page.locator('#'+id).click();await ready();};
  const point=async(x,y)=>{await page.locator('#original').scrollIntoViewIfNeeded();const box=await page.locator('#original').boundingBox();const dimensions=await page.locator('#original').evaluate(c=>[c.width,c.height]);await page.mouse.click(box.x+x/dimensions[0]*box.width,box.y+y/dimensions[1]*box.height);};
  try{
    await page.goto(url);await page.getByRole('heading',{name:'Modal Camera',exact:true}).waitFor();
    await clickWork('cleanDemo');assert.match(await page.locator('#status').innerText(),/Demo ready/);
    assert.match(await page.locator('#results').innerText(),/0\.3977 px/);assert.match(await page.locator('#results').innerText(),/60\.2°/);
    check('Known demo loads, tracks and renders',{table:await page.locator('#results').innerText()});
    await page.locator('#workspace').screenshot({path:path.join(root,'evidence/ui-known-motion.png')});
    const before=await page.locator('#amplified').evaluate(c=>c.toDataURL());
    await page.locator('#spectrum').scrollIntoViewIfNeeded();const box=await page.locator('#spectrum').boundingBox();
    const sx=f=>box.x+(58+f/30*(900-58-18))/900*box.width;
    await page.mouse.move(sx(3),box.y+box.height*.45);await page.mouse.down();await page.mouse.move(sx(7),box.y+box.height*.45,{steps:15});await page.mouse.up();
    assert.ok(Math.abs(Number(await page.locator('#low').inputValue())-6.5)<.05);assert.ok(Math.abs(Number(await page.locator('#high').inputValue())-7.5)<.05);
    await clickWork('apply');assert.match(await page.locator('#renderLabel').innerText(),/6\.50–7\.50/);
    assert.notEqual(await page.locator('#amplified').evaluate(c=>c.toDataURL()),before);
    await page.locator('#frequency').fill('7');await clickWork('analyze');assert.match(await page.locator('#results').innerText(),/0\.1228 px/);
    check('Draggable band updates filtered frames and independent 7 Hz fit');
    await page.locator('#gain').fill('21');await clickWork('apply');assert.match(await page.locator('#error').innerText(),/between 0 and 20/);
    await page.locator('#gain').fill('2');await clickWork('apply');assert.equal(await page.locator('#error').isVisible(),false);check('Invalid gain is rejected and valid retry recovers');
    await clickWork('roiMode');const vbox=await page.locator('#original').boundingBox();
    await page.mouse.move(vbox.x+40/320*vbox.width,vbox.y+40/200*vbox.height);await page.mouse.down();await page.mouse.move(vbox.x+140/320*vbox.width,vbox.y+150/200*vbox.height,{steps:10});await page.mouse.up();await clickWork('apply');
    await clickWork('clearRoi');await clickWork('apply');check('ROI selection and full-frame reset render successfully');
    await clickWork('play');await page.waitForFunction(()=>Number(document.getElementById('scrub').value)>2);await clickWork('play');
    await page.locator('#scrub').fill('100');await page.locator('#scrub').dispatchEvent('input');await page.waitForFunction(()=>document.getElementById('timeLabel').textContent==='1.67 s');check('Shared replay clock and frame scrubbing');
    await clickWork('dropoutDemo');assert.match(await page.locator('#results').innerText(),/Withheld/);assert.match(await page.locator('#results').innerText(),/72\/360/);check('Dropout warning and withheld fit visible');
    await page.locator('#workspace').screenshot({path:path.join(root,'evidence/ui-tracking-dropout.png')});
    await clickWork('clearPoints');await clickWork('pointMode');await point(160,170);await clickWork('analyze');assert.match(await page.locator('#results').innerText(),/Low texture/);check('Low-texture point produces warning and gaps');
    await page.locator('#videoFile').setInputFiles({name:'broken.mp4',mimeType:'video/mp4',buffer:Buffer.from('not a video')});await ready();await page.waitForFunction(()=>!document.getElementById('error').hidden);assert.match(await page.locator('#error').innerText(),/Cannot decode/);check('Malformed file is rejected in UI');
    const guitar=path.join(root,'data/examples/guitar.mp4');
    if(fs.existsSync(guitar)){
      await page.locator('#videoFile').setInputFiles(guitar);await ready();await page.waitForFunction(()=>document.getElementById('clipName').textContent==='guitar.mp4');
      assert.match(await page.locator('#clipMeta').innerText(),/29\.970 encoded fps/);
      await page.locator('#captureFps').fill('600');await clickWork('setTimebase');assert.match(await page.locator('#error').innerText(),/Confirm one encoded frame/);
      await page.locator('#sampleTiming').check();await clickWork('setTimebase');assert.match(await page.locator('#timebaseLabel').innerText(),/user-assumed capture time/);
      await page.locator('#low').fill('72');await page.locator('#high').fill('92');await page.locator('#gain').fill('2');await clickWork('apply');assert.match(await page.locator('#renderLabel').innerText(),/72\.00–92\.00/);
      await point(200,57);await point(220,91);await point(240,132);await page.locator('#frequency').fill('80');await clickWork('analyze');
      check('Guitar import, explicit assumed 600 fps timebase and band render',{table:await page.locator('#results').innerText(),physical_frequency_validated:false});
      await page.locator('#workspace').screenshot({path:path.join(root,'evidence/ui-guitar-example.png')});
    }
    await clickWork('cleanDemo');await page.locator('#videoFile').setInputFiles(path.join(root,'demo_videos/known_motion.avi'));await ready();await page.waitForFunction(()=>document.getElementById('status').textContent.startsWith('Video ready'));
    assert.equal(await page.locator('#captureFps').inputValue(),'');assert.equal(await page.locator('#results').innerText(),'');
    await page.locator('#videoFile').setInputFiles(path.join(root,'demo_videos/known_motion.avi'));await ready();await page.waitForFunction(()=>document.getElementById('status').textContent.startsWith('Video ready'));check('Repeated same-file imports reset timebase, selections, fits and render');
    await clickWork('cleanDemo');const download=page.waitForEvent('download');await page.locator('#jsonExport').click();const exportFile=await download;assert.equal(exportFile.suggestedFilename(),'modal-camera-analysis.json');await exportFile.saveAs(path.join(root,'evidence/ui-export-analysis.json'));check('Local JSON download');
    assert.deepEqual(errors,[]);check('No browser JavaScript errors');
    await page.screenshot({path:path.join(root,'evidence/ui-final-full-page.png'),fullPage:true});
    fs.writeFileSync(path.join(root,'evidence/ui-validation.json'),JSON.stringify({browser:'Playwright Chromium headless; CUA transport unavailable',checks,errors},null,2)+'\n');
  }finally{await browser.close();if(server)server.kill();}
})().catch(error=>{console.error(error);fs.writeFileSync(path.join(root,'evidence/ui-failure.txt'),String(error.stack));process.exitCode=1;});
