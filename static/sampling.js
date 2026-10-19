'use strict';
let psdSource='auto',psdPoint=null,psdRegion=null,psdSampling=null,psdSamplingIdentity=null,psdDraftRegion=null,samplingRequest=0;
function psdSelectionIdentity(){
  const key=[psdSource,$('axis').value,$('cameraReference').checked,$('spectrumHighpass').checked?Number($('highpassCutoff').value):0];
  if(psdSource==='auto'||$('cameraReference').checked)key.push(points);
  if(psdSource==='auto')key.push(roi);if(psdSource==='point')key.push(psdPoint);if(psdSource==='region')key.push(psdRegion);
  return key;
}
function installSampling(data){psdSampling=data;psdSamplingIdentity=currentSpectrumIdentity();updateSamplingControls(true);drawVideos();}
async function refreshSampling(){
  const id=clip.id,key=currentSpectrumIdentity(),serial=++samplingRequest;
  const response=await fetch(`/api/sampling/${id}?revision=${revision}`),data=await response.json();
  if(!response.ok)throw new Error(data.error);if(clip?.id===id&&key===currentSpectrumIdentity()&&serial===samplingRequest)installSampling(data);
}
function updateSamplingControls(rebuild=false){
  const ready=!!clip&&timingConfirmed&&!busy;
  for(const id of ['psdFullFrame','psdPickPoint','psdSelectRegion','psdSampleSelect','psdApplyRegion'])$(id).disabled=!ready;
  $('psdShowSamples').disabled=busy||!clip;
  $('psdPickPoint').setAttribute('aria-pressed',String(mode==='psd-point'));
  $('psdSelectRegion').setAttribute('aria-pressed',String(mode==='psd-region'));
  $('psdFullFrame').setAttribute('aria-pressed',String(psdSource==='frame'||psdSource==='auto'&&!points.length&&!roi));
  const selection=psdSampling?.label||(psdSource==='point'?'One point':psdSource==='region'?'Selected region':'Automatic samples');
  const location=psdSource==='point'&&psdPoint?` (${psdPoint.join(', ')} analysis px)`:'';
  $('psdSamplingTitle').textContent=`PSD: ${selection}${location}`;
  $('psdSourceSummary').textContent=`PSD source: ${selection}${location}. Selection tools are above the original video.`;
  $('psdSamplingHelp').textContent=mode==='psd-point'?'Click a textured location on Original, or use arrows and Enter. Escape cancels.':mode==='psd-region'?'Drag a rectangle around the plate on Original, or use Region coordinates. At least 32 × 32 analysis pixels; Escape cancels.':'Frame-0 centers · green: usable · ×: incomplete · gray: other locations. Click a dot for its PSD.';
  if(rebuild){
    const select=$('psdSampleSelect');select.replaceChildren(new Option('Click a dot or choose a sample…',''));
    for(const p of psdSampling?.samples||[]){const state=p.reference?'camera reference':p.eligible===false?'incomplete track':p.eligible===true?'complete track':'not measured';select.add(new Option(`${p.label} (${p.x}, ${p.y}) · ${state}`,String(p.index)));}
    if(psdSource==='point'&&psdPoint){const selected=psdSampling?.samples.find(p=>p.x===psdPoint[0]&&p.y===psdPoint[1]);if(selected)select.value=String(selected.index);}
    if(clip){const box=psdRegion||[0,0,clip.metadata.width,clip.metadata.height];for(const [i,id] of ['psdRegionX','psdRegionY','psdRegionWidth','psdRegionHeight'].entries())$(id).value=box[i];}
  }
}
function drawSampling(ctx,c){
  if(!$('psdShowSamples').checked||!psdSampling)return;
  ctx.save();
  const region=psdDraftRegion||(psdSource==='region'?psdRegion:psdSource==='auto'&&!points.length?roi:null);
  if(region){ctx.fillStyle='#76e0c20c';ctx.fillRect(...region);ctx.strokeStyle='#76e0c2';ctx.lineWidth=1.2;ctx.setLineDash([4,3]);ctx.strokeRect(...region);ctx.setLineDash([]);}
  for(const p of psdSampling.samples){
    const selected=psdSource==='point'&&p.x===psdPoint?.[0]&&p.y===psdPoint?.[1];
    ctx.strokeStyle=p.reference?'#ffd089':p.selected&&p.eligible===false?'#ffaaaa':p.used?'#76e0c2':'#9daebc99';
    ctx.fillStyle=p.used?'#76e0c280':'#10182090';ctx.lineWidth=selected?2:1;
    if(p.selected&&p.eligible===false){ctx.beginPath();ctx.moveTo(p.x-2.5,p.y-2.5);ctx.lineTo(p.x+2.5,p.y+2.5);ctx.moveTo(p.x-2.5,p.y+2.5);ctx.lineTo(p.x+2.5,p.y-2.5);ctx.stroke();}
    else{ctx.beginPath();ctx.arc(p.x,p.y,selected?5:2.5,0,2*Math.PI);ctx.fill();ctx.stroke();}
    if(selected){ctx.strokeStyle='#fff';ctx.strokeRect(p.x-15,p.y-15,30,30);}
  }
  if(mode==='psd-point'&&document.activeElement===c){ctx.strokeStyle='#fff';ctx.beginPath();ctx.moveTo(cursor[0]-6,cursor[1]);ctx.lineTo(cursor[0]+6,cursor[1]);ctx.moveTo(cursor[0],cursor[1]-6);ctx.lineTo(cursor[0],cursor[1]+6);ctx.stroke();}
  ctx.restore();
}
function nearestPsdSample(position){
  const radius=14*$('original').width/$('original').getBoundingClientRect().width;
  return (psdSampling?.samples||[]).filter(p=>!p.reference).map(p=>({p,d:Math.hypot(p.x-position[0],p.y-position[1])})).filter(p=>p.d<=radius).sort((a,b)=>a.d-b.d)[0]?.p;
}
async function startPsdSelection(value){
  if(busy||!timingConfirmed)return;pause();await showFrame(0);saveDisplay();setMode(value);$('psdShowSamples').checked=true;$('original').focus();$('original').scrollIntoView({block:'center',behavior:'auto'});updateSamplingControls();drawVideos();
}
function selectPsdPoint(position){
  if(!clip||busy)return;
  const [x,y]=position.map(Math.round);
  if(x<16||y<16||x>=clip.metadata.width-16||y>=clip.metadata.height-16){showError(new Error('Choose a PSD point at least 16 analysis pixels from the image edges.'));return;}
  task('Measuring the selected point PSD…',async()=>{await showFrame(0);psdSource='point';psdPoint=[x,y];setMode('inspect');await applyPsdSelection();});
}
function selectPsdRegion(box){
  if(!clip||busy)return;
  const [x,y,w,h]=box;
  if(!box.every(Number.isFinite)||x<0||y<0||w<32||h<32||x+w>clip.metadata.width||y+h>clip.metadata.height){showError(new Error('Select a PSD region inside the image, at least 32 × 32 analysis pixels.'));return;}
  task('Measuring the selected region PSD…',async()=>{await showFrame(0);psdSource='region';psdRegion=box;setMode('inspect');await applyPsdSelection();});
}
async function applyPsdSelection(){
  displacementSpectrum=null;spectrumIdentity=null;psdSampling=null;psdSamplingIdentity=null;clearVideoDownload();settingsChanged({compute:false});await runSpectrum();
  status(`${psdSampling.label} PSD ${displacementSpectrum.spectrum_available?'ready':'withheld'}. ${psdSampling.accepted_count}/${psdSampling.selected_count} complete tracks; response views keep their existing settings.`);
}
function psdRectangle(a,b){const w=clip.metadata.width,h=clip.metadata.height,x0=Math.max(0,Math.min(w,a[0])),x1=Math.max(0,Math.min(w,b[0])),y0=Math.max(0,Math.min(h,a[1])),y1=Math.max(0,Math.min(h,b[1]));return [Math.min(x0,x1),Math.min(y0,y1),Math.abs(x1-x0),Math.abs(y1-y0)].map(Math.round);}
$('psdFullFrame').onclick=()=>task('Measuring the whole-frame PSD…',async()=>{psdSource='frame';setMode('inspect');await applyPsdSelection();});
$('psdPickPoint').onclick=()=>startPsdSelection('psd-point').catch(showError);
$('psdSelectRegion').onclick=()=>startPsdSelection('psd-region').catch(showError);
$('psdSampleSelect').onchange=()=>{const p=psdSampling?.samples.find(p=>String(p.index)===$('psdSampleSelect').value);if(p)selectPsdPoint([p.x,p.y]);};
$('psdShowSamples').onchange=drawVideos;
$('psdApplyRegion').onclick=()=>{try{selectPsdRegion(['psdRegionX','psdRegionY','psdRegionWidth','psdRegionHeight'].map(id=>finiteInput(id,'PSD region coordinate')));}catch(e){showError(e);}};
