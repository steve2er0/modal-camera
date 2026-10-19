'use strict';
const $=id=>document.getElementById(id);
const colors=['#36cfee','#80b7ee','#ffc986','#df9ef6','#fb8eaa','#bbd587','#e9b489','#a4c9cf'];
let clip=null,points=[],roi=null,mode='inspect',analysis=null,analysisKey=null,renderKey=null,frame=0,playing=false,busy=false,epoch=0;
let originalImage=null,amplifiedImage=null,frameRequest=0,fetchingFrame=false,drag=null;
let revision=null,timingConfirmed=false,dirty=false,stopRequested=false,cursor=[32,32];
let displacementSpectrum=null,spectrumIdentity=null;
function currentSpectrumIdentity(){return clip?JSON.stringify([clip.id,clip.metadata.fps,clip.metadata.timing_basis,timingConfirmed,...psdSelectionIdentity()]):null;}
async function runSpectrum(){
  await flushSettings();if(psdSamplingIdentity!==currentSpectrumIdentity())await refreshSampling();
  const result=await api('/api/spectrum',{id:clip.id,revision});
  displacementSpectrum=result;spectrumIdentity=currentSpectrumIdentity();revision=result.revision;if(result.sampling)installSampling(result.sampling);drawSpectrum();
}
const status=message=>{$('status').textContent=message;$('status').title=message;$('operationState').textContent=clip?message:'';};
function showError(e){$('error').hidden=false;$('error').textContent=e.message||String(e);status('Please correct the highlighted setting or try again.');if(e.field){const field=$(e.field);field.setAttribute('aria-invalid','true');if(field.closest('#advanced'))$('advanced').open=true;field.focus();}}
function clearError(){$('error').hidden=true;for(const el of document.querySelectorAll('[aria-invalid]'))el.removeAttribute('aria-invalid');}
async function api(url,data,form=false){
  const response=await fetch(url,{method:'POST',headers:form?{}:{'Content-Type':'application/json'},body:form?data:JSON.stringify(data)});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'Request failed.');return result;
}
async function task(message,work){
  if(busy)return;busy=true;pause();clearError();document.body.classList.add('busy');
  const controls=[...document.querySelectorAll('button,input,select')],disabled=controls.map(control=>control.disabled);
  controls.forEach(control=>control.disabled=true);status(message);
  try{await work();}catch(e){showError(e);}finally{busy=false;document.body.classList.remove('busy');controls.forEach((control,i)=>control.disabled=disabled[i]);$('cancelProcessing').hidden=true;updateUI();}
}
function notes(id,values){$(id).replaceChildren(...values.map(v=>{const p=document.createElement('p');p.textContent=v;return p;}));}
function pause(){playing=false;$('play').textContent='▶ Play';pauseModal();pauseTap();}
function frameUrl(view,index){return `/api/frame/${clip.id}/${index}?view=${view}${view==='amplified'?'&key='+renderKey:''}`;}
async function getImage(url){const response=await fetch(url);if(!response.ok){const error=await response.json();throw new Error(error.error);}return createImageBitmap(await response.blob());}
async function showFrame(index){
  if(!clip)return;const e=epoch,requestId=++frameRequest;index=Math.max(0,Math.min(clip.metadata.frames-1,Math.round(index)));
  const images=await Promise.all([getImage(frameUrl('original',index)),renderKey?getImage(frameUrl('amplified',index)):Promise.resolve(null)]);
  if(e!==epoch||requestId!==frameRequest){images.forEach(i=>i?.close());return;}
  originalImage?.close();amplifiedImage?.close();[originalImage,amplifiedImage]=images;frame=index;
  $('scrub').value=frame;$('timeLabel').textContent=(frame/clip.metadata.fps).toFixed(2)+' analysis s';drawVideos();drawTrace();
}
function drawVideos(){
  for(const id of ['original','amplified']){
    const c=$(id),ctx=c.getContext('2d'),img=id==='original'?originalImage:(amplifiedImage||originalImage);
    ctx.fillStyle='#080d13';ctx.fillRect(0,0,c.width,c.height);if(img)ctx.drawImage(img,0,0,c.width,c.height);
    if(id==='amplified'&&drawResponse(ctx,c))continue;if(!img)continue;
    if(roi){ctx.strokeStyle='#ffd089';ctx.lineWidth=1.5;ctx.setLineDash([5,4]);ctx.strokeRect(...roi);ctx.setLineDash([]);}
    points.forEach((p,j)=>{
      let x=p[0],y=p[1],ok=true;
      if(analysis){const trace=analysis.points[j];if(trace){const dx=(trace.raw_dx||trace.dx)[frame],dy=(trace.raw_dy||trace.dy)[frame];ok=dx!==null&&dy!==null;if(ok){x+=dx/clip.metadata.scale_x;y+=dy/clip.metadata.scale_y;}}}
      ctx.strokeStyle=ok?colors[j]:'#ff9b9b';ctx.lineWidth=1.4;ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);ctx.stroke();ctx.fillStyle='#101820';ctx.fillRect(x+7,y-14,21,13);ctx.fillStyle=ctx.strokeStyle;ctx.font='10px sans-serif';ctx.fillText(`P${j+1}`,x+9,y-4);
    });
    if(id==='original')drawSampling(ctx,c);
    if(id==='original'&&mode==='points'&&document.activeElement===c){ctx.strokeStyle='#fff';ctx.beginPath();ctx.moveTo(cursor[0]-6,cursor[1]);ctx.lineTo(cursor[0]+6,cursor[1]);ctx.moveTo(cursor[0],cursor[1]-6);ctx.lineTo(cursor[0],cursor[1]+6);ctx.stroke();}
  }
}
$('play').onclick=()=>{if(!clip||busy)return;if(playing){pause();saveDisplay();return;}playing=true;$('play').textContent='Ⅱ Pause';const start=performance.now();if(frame===clip.metadata.frames-1)frame=0;const firstFrame=frame;
  async function tick(){if(!playing)return;const desired=(firstFrame+Math.floor((performance.now()-start)/1000*clip.metadata.encoded_fps*Number($('speed').value)))%clip.metadata.frames;if(desired!==frame&&!fetchingFrame){fetchingFrame=true;try{await showFrame(desired);}catch(e){pause();showError(e);}finally{fetchingFrame=false;}}if(playing)requestAnimationFrame(tick);}requestAnimationFrame(tick);
};
$('scrub').oninput=()=>{pause();showFrame(Number($('scrub').value)).then(saveDisplay).catch(showError);};$('speed').onchange=pause;
function setMode(value){mode=mode===value?'inspect':value;$('pointMode').setAttribute('aria-pressed',String(mode==='points'));$('roiMode').setAttribute('aria-pressed',String(mode==='roi'));$('original').classList.toggle('editing',mode!=='inspect');updateSamplingControls();drawVideos();}
$('pointMode').onclick=()=>{setMode('points');if(mode==='points'){$('original').focus();status('Add points: click textured corners, or move with arrows and press Enter.');}};
$('roiMode').onclick=()=>{setMode('roi');if(mode==='roi')$('original').focus();};
function addPoint(x,y){
  if(!clip||busy)return;if(points.length>=8)throw new Error('Up to eight points are supported. Clear points to start again.');
  if(!Number.isFinite(x)||!Number.isFinite(y)||x<16||y<16||x>=clip.metadata.width-16||y>=clip.metadata.height-16)throw new Error('Choose a point at least 16 analysis pixels from each edge.');
  points.push([Math.round(x),Math.round(y)]);settingsChanged();status(`P${points.length} selected. Analyze response to update measurements.`);
}
$('addPoint').onclick=()=>{try{addPoint(Number($('pointX').value),Number($('pointY').value));}catch(e){showError(e);}};
$('clearPoints').onclick=()=>{points=[];settingsChanged();};$('clearRoi').onclick=()=>{roi=null;settingsChanged();};
function imagePosition(e){const r=$('original').getBoundingClientRect();return[(e.clientX-r.left)/r.width*$('original').width,(e.clientY-r.top)/r.height*$('original').height];}
$('original').onpointerdown=e=>{
  if(!clip||busy)return;const p=imagePosition(e);
  if(mode==='inspect'){if(timingConfirmed&&$('psdShowSamples').checked){const sample=nearestPsdSample(p);if(sample)selectPsdPoint([sample.x,sample.y]);}return;}
  pause();if(mode==='psd-point'){selectPsdPoint(p);return;}
  if(mode==='points'){try{addPoint(...p);}catch(error){showError(error);}return;}
  drag={kind:mode==='psd-region'?'psd-region':'roi',start:p};$('original').setPointerCapture(e.pointerId);
};
$('original').onpointermove=e=>{
  if(drag?.kind==='psd-region'){psdDraftRegion=psdRectangle(drag.start,imagePosition(e));drawVideos();return;}
  if(drag?.kind!=='roi')return;const p=imagePosition(e),s=drag.start,w=clip.metadata.width,h=clip.metadata.height;roi=[Math.max(0,Math.min(s[0],p[0])),Math.max(0,Math.min(s[1],p[1])),Math.min(w,Math.abs(s[0]-p[0])),Math.min(h,Math.abs(s[1]-p[1]))].map(Math.round);roi[2]=Math.min(roi[2],w-roi[0]);roi[3]=Math.min(roi[3],h-roi[1]);drawVideos();
};
$('original').onpointerup=e=>{
  if(drag?.kind==='psd-region'){const box=psdRectangle(drag.start,imagePosition(e));drag=null;psdDraftRegion=null;selectPsdRegion(box);drawVideos();return;}
  if(drag?.kind==='roi'){drag=null;if(roi&&Math.min(roi[2],roi[3])<8)roi=null;settingsChanged();}
};
$('original').onpointercancel=()=>{if(drag?.kind==='psd-region'){drag=null;psdDraftRegion=null;drawVideos();}};
$('original').onkeydown=e=>{
  if(!clip||busy)return;
  if(e.key==='Escape'&&mode.startsWith('psd-')){e.preventDefault();drag=null;psdDraftRegion=null;setMode('inspect');return;}
  if(!['points','psd-point'].includes(mode))return;
  const delta=e.shiftKey?10:1;
  if(e.key.startsWith('Arrow')){e.preventDefault();cursor[0]=Math.max(16,Math.min(clip.metadata.width-17,cursor[0]+(e.key==='ArrowRight'?delta:e.key==='ArrowLeft'?-delta:0)));cursor[1]=Math.max(16,Math.min(clip.metadata.height-17,cursor[1]+(e.key==='ArrowDown'?delta:e.key==='ArrowUp'?-delta:0)));$('pointX').value=cursor[0];$('pointY').value=cursor[1];drawVideos();}
  else if(e.key==='Enter'){e.preventDefault();if(mode==='psd-point')selectPsdPoint(cursor);else{try{addPoint(...cursor);}catch(error){showError(error);}}}
};
$('original').onfocus=drawVideos;$('original').onblur=drawVideos;
async function runAnalysis(){
  const result=await api('/api/analyze',{id:clip.id,revision,points,axis:$('axis').value,frequency:Number($('frequency').value),reference_last:$('cameraReference').checked});
  analysis=result;analysisKey=result.key;revision=result.revision;drawResults();drawSpectrum();drawTrace();drawVideos();
}
async function runRender(){
  const result=await api('/api/render',{id:clip.id,revision,low:Number($('low').value),high:Number($('high').value),gain:Number($('gain').value),roi});
  renderKey=result.key;revision=result.revision;await loadResponse(result);notes('renderWarnings',result.warnings);await showFrame(frame);drawSpectrum();updateResponseHelp();
}
function drawResults(){
  const tbody=$('results');tbody.replaceChildren();if(!analysis)return;
  const calibration=Number($('calibration').value),calibrated=Number.isFinite(calibration)&&calibration>0;
  analysis.points.forEach((p,j)=>{const row=document.createElement('tr');let amplitude=p.fit?`${p.fit.amplitude_peak_px.toFixed(4)} px`:'Withheld';if(p.fit&&calibrated)amplitude+=` / ${(p.fit.amplitude_peak_px*calibration).toPrecision(4)} mm`;
    const relative=p.fit?.relative_phase_deg,cells=[`P${p.point} (${p.x}, ${p.y})`,amplitude,relative===null||relative===undefined?'Unavailable':`${relative.toFixed(1)}°`,`${(p.valid_fraction*100).toFixed(1)}%`,p.warnings.length?p.warnings.join(' '):`Good texture / registration. Fit residual ${p.fit?.rms_residual_px.toFixed(4)} px.`];
    cells.forEach((value,i)=>{const td=document.createElement('td');td.textContent=value;if(i===0){td.style.color=colors[j];td.className='badge';}if(i===4&&p.warnings.length)td.className='warn';row.append(td);});tbody.append(row);});
  $('phaseLabel').textContent=`${analysis.axis.toUpperCase()} · ${analysis.frequency_hz.toFixed(3)} ANALYSIS-TIME Hz · PHASE vs P1`;
  $('traceHelp').textContent=`${analysis.units}; fit excludes first/last ${analysis.fit_edge_excluded_s.toFixed(2)} s and rejected samples. ${analysis.reference_last?'Stationary last-point translation subtracted. ':''}Spectra use complete original traces; rejected samples are not filled.`;
}
function plotColor(name){return getComputedStyle(document.documentElement).getPropertyValue(name).trim();}
function plotBase(canvas,xlabel,ylabel){
  const ctx=canvas.getContext('2d'),W=canvas.width,H=canvas.height,L=58,R=18,T=18,B=36;ctx.fillStyle=plotColor('--plot-bg');ctx.fillRect(0,0,W,H);ctx.strokeStyle=plotColor('--line');ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(L,T);ctx.lineTo(L,H-B);ctx.lineTo(W-R,H-B);ctx.stroke();ctx.fillStyle=plotColor('--plot-label');ctx.font='11px sans-serif';ctx.fillText(ylabel,10,12);ctx.fillText(xlabel,W-160,H-7);return {ctx,W,H,L,R,T,B,xw:W-L-R,yh:H-T-B};
}
function drawSpectrum(){
  const spectrum=displacementSpectrum;
  const psd=$('spectrumView').value==='psd';
  const calibration=Number($('calibration').value),calibrated=calibration>0&&Number.isFinite(calibration);
  const scale=calibrated?calibration:1,unit=calibrated?'mm':'source px';
  const logarithmic=psd&&$('spectrumLog').checked;
  $('spectrumLog').disabled=!psd;
  const highpass=spectrum?.highpass?.enabled?spectrum.highpass.cutoff_hz:0;
  $('spectrumUnits').textContent=`${highpass?'High-passed':'Original'} ${spectrum?.axis.toUpperCase()||$('axis').value.toUpperCase()} displacement ${psd?'PSD':'spectrum'}`;
  const c=$('spectrum');c.width=Math.max(240,Math.round(c.clientWidth));c.height=210;
  const p=plotBase(c,'Analysis frequency / Hz',psd?`PSD / ${unit}²/Hz`:`Peak / ${unit}`),{ctx,W,H,L,R,T,B,xw,yh}=p;
  $('spectrumLegend').replaceChildren();
  $('spectrumDetails').replaceChildren();
  if(!clip)return;
  const maxF=clip.metadata.nyquist,toX=f=>L+f/maxF*xw,lo=Number($('low').value),hi=Number($('high').value);
  ctx.fillStyle=plotColor('--cyan')+'18';ctx.fillRect(toX(lo),T,toX(hi)-toX(lo),yh);
  ctx.strokeStyle=plotColor('--cyan');ctx.lineWidth=2;
  for(const edge of [lo,hi]){ctx.beginPath();ctx.moveTo(toX(edge),T);ctx.lineTo(toX(edge),H-B);ctx.stroke();ctx.fillRect(toX(edge)-4,T+8,8,19);}
  ctx.fillStyle=plotColor('--plot-label');for(let i=0;i<=6;i++){const f=i*maxF/6;const label=f.toFixed(1);ctx.fillText(label,Math.min(W-ctx.measureText(label).width-4,toX(f)-8),H-B+17);}
  if(spectrum?.spectrum_available){
    const key=psd?'psd_px2_per_hz':'spectrum_px';
    const factor=psd?scale*scale:scale;
    const all=spectrum.points.flatMap(point=>(point[key]||[]).slice(1).map(v=>v*factor));
    const maxValue=Math.max(1e-20,...all);
    const upper=logarithmic?Math.ceil(Math.log10(maxValue)):Math.max(psd?1e-20:.02,maxValue)*1.2;
    // Six displayed decades; the floor is only for plotting zeros, not a noise estimate.
    const lower=logarithmic?upper-6:0;
    const toY=value=>H-B-(logarithmic?(Math.max(lower,Math.log10(Math.max(1e-30,value)))-lower)/(upper-lower):value/upper)*yh;
    for(let i=0;i<=3;i++){
      const tick=lower+(upper-lower)*i/3,y=H-B-i*yh/3;
      ctx.fillStyle=plotColor('--plot-label');ctx.fillText(logarithmic?`1e${Math.round(tick)}`:psd?tick.toExponential(1):tick.toFixed(2),7,y+3);
      ctx.strokeStyle=plotColor('--plot-grid');ctx.beginPath();ctx.moveTo(L,y);ctx.lineTo(W-R,y);ctx.stroke();
    }
    spectrum.points.forEach((point,j)=>{
      if(point[key]){
        ctx.strokeStyle=colors[j];ctx.lineWidth=1.7;ctx.beginPath();
        point[key].forEach((value,i)=>{if(i===0)return;const x=toX(spectrum.frequencies[i]),y=toY(value*factor);i===1?ctx.moveTo(x,y):ctx.lineTo(x,y);});ctx.stroke();
      }
      const entry=document.createElement('div');entry.className='spectrum-entry';entry.style.color=colors[j];
      const title=document.createElement('strong');title.textContent=`${point.label} · ${point[key]?(highpass?'high-passed ':'original ')+spectrum.axis.toUpperCase():'spectrum withheld'}`;entry.append(title);
      if(psd&&point[key]){
        const detail=document.createElement('div');detail.className='spectrum-detail';detail.textContent=`${highpass?'Filtered':'Integrated'} PSD RMS ${(point.rms_from_psd_px*scale).toPrecision(3)} ${unit}.`;entry.append(detail);
      }else if(!point[key]){const detail=document.createElement('div');detail.className='spectrum-detail';detail.textContent='Rejected samples are not filled.';entry.append(detail);}
      $('spectrumDetails').append(entry);
    });
    const m=spectrum.psd_metadata,peak=psd?spectrum.psd_peak_frequency_hz:spectrum.peak_frequency_hz;
    $('spectrumSummary').textContent=`${spectrum.source==='spatial_grid'?'Spatial mean':'Selected points'} · ${m.accepted_trace_count}/${m.total_trace_count} tracks · Δf ${m.bin_width_hz.toFixed(3)} Hz${highpass?` · HP ${highpass} Hz`:''}${peak===null?' · No nonzero spectral energy':` · peak ${peak.toFixed(2)} Hz`}.`;
    const label=document.createElement('span');label.textContent='PSD peaks:';$('spectrumLegend').append(label);
    for(const peak of spectrum.psd_peaks){const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent=peak.frequency_hz.toFixed(2)+' Hz';button.disabled=busy;button.title='Select this PSD peak as the target frequency';button.onclick=()=>{$('frequency').value=peak.frequency_hz.toFixed(3);targetChanged();};$('spectrumLegend').append(button);}
    $('spectralHelp').textContent=`One-sided full-record Hann periodogram · linear detrend · ${m.duration_s.toFixed(3)} s record · Hann ENBW ${m.enbw_hz.toFixed(3)} Hz. Mean of individual PSDs, so opposite-phase motion does not cancel. No segment averaging, zero padding or gap filling. PSD uses original displacement, independent of target, band and magnification; ${m.timing_basis}. Camera-reference subtraction: ${spectrum.reference_last?'last selected point (excluded from mean)':'off'}. ${highpass?`High-pass ${highpass} Hz: fourth-order Butterworth in SOS form, forward-backward with odd reflection padding, after linear detrending. Zero phase; two-pass gain is −6.02 dB at the cutoff. Edge transients and attenuation near the cutoff remain; this does not establish that suppressed motion was camera jitter. Applied only to PSD and amplitude spectrum; fits, point traces and response videos retain original motion.`:'High-pass off.'} Peak bins guide selection; they do not identify structural modes.`;
  }else{
    ctx.fillStyle=plotColor('--plot-label');ctx.fillText(spectrum?'PSD withheld: incomplete tracks':timingConfirmed?'Measure PSD to see peaks':'Confirm timing to see peaks',L+8,T+52);
    const m=spectrum?.psd_metadata;
    $('spectrumSummary').textContent=m?`PSD withheld: 0/${m.total_trace_count} complete tracks. Choose another point or region on Original.`:timingConfirmed?'Measure the original motion, then click a peak or enter a frequency.':'Confirm timing to measure the frequency content.';
    $('spectralHelp').textContent='PSD uses original tracked X/Y displacement, not image brightness or magnified motion. Traces with rejected samples are withheld.';
  }
  if(highpass){ctx.fillStyle='#ffd08916';ctx.fillRect(L,T,Math.min(xw,highpass/maxF*xw),yh);ctx.strokeStyle='#ffd08980';ctx.setLineDash([2,3]);ctx.beginPath();ctx.moveTo(toX(highpass),T);ctx.lineTo(toX(highpass),H-B);ctx.stroke();ctx.setLineDash([]);}
  const fit=Number($('frequency').value);ctx.strokeStyle='#ffd089';ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(toX(fit),T);ctx.lineTo(toX(fit),H-B);ctx.stroke();ctx.setLineDash([]);
}
$('spectrumView').onchange=drawSpectrum;
$('spectrumLog').onchange=drawSpectrum;
window.addEventListener('resize',drawSpectrum);
function spectrumFrequency(e){const c=$('spectrum'),r=c.getBoundingClientRect(),x=(e.clientX-r.left)/r.width*c.width;return Math.max(0,Math.min(clip.metadata.nyquist,(x-58)/(c.width-58-18)*clip.metadata.nyquist));}
$('spectrum').onpointerdown=e=>{if(!clip||busy)return;const f=spectrumFrequency(e),lo=Number($('low').value),hi=Number($('high').value),tol=Math.min(clip.metadata.nyquist*.018,(hi-lo)*.25);let kind=Math.abs(f-lo)<tol?'low':Math.abs(f-hi)<tol?'high':f>lo&&f<hi?'band':'fit';drag={kind,start:f,low:lo,high:hi,moved:false};$('spectrum').setPointerCapture(e.pointerId);};
$('spectrum').onpointermove=e=>{if(!drag||drag.kind==='roi'||!clip)return;const f=spectrumFrequency(e),df=clip.metadata.resolution_hz,nyq=clip.metadata.nyquist;drag.moved=true;let lo=drag.low,hi=drag.high;if(drag.kind==='low')lo=Math.max(2*df,Math.min(hi-df,f));if(drag.kind==='high')hi=Math.max(lo+df,Math.min(nyq-.01,f));if(drag.kind==='band'){const delta=Math.max(2*df-lo,Math.min(nyq-.01-hi,f-drag.start));lo+=delta;hi+=delta;}if(drag.kind==='fit')$('frequency').value=Math.max(.01,Math.min(nyq-.01,f)).toFixed(3);else{$('low').value=lo.toFixed(3);$('high').value=hi.toFixed(3);}drawSpectrum();};
$('spectrum').onpointerup=e=>{if(!drag||drag.kind==='roi')return;if(!drag.moved){$('frequency').value=Math.max(.01,Math.min(clip.metadata.nyquist-.01,spectrumFrequency(e))).toFixed(3);targetChanged();}else{if(drag.kind==='fit')targetChanged();else{$('linkedBand').checked=false;settingsChanged();}status('Selection changed. Analyze response to update results.');}drag=null;};
function drawTrace(){
  const c=$('tracePlot'),p=plotBase(c,'Analysis time / s','Displacement / source px'),{ctx,W,H,L,R,T,B,xw,yh}=p;if(!analysis||!clip)return;
  const values=analysis.points.flatMap(point=>point['d'+analysis.axis].filter(x=>x!==null));const maxY=Math.max(.1,...values.map(Math.abs))*1.15;
  const toX=t=>L+t/(clip.metadata.duration)*xw,toY=y=>T+yh/2-y/(2*maxY)*yh;
  ctx.strokeStyle=plotColor('--line');ctx.beginPath();ctx.moveTo(L,toY(0));ctx.lineTo(W-R,toY(0));ctx.stroke();
  for(let i=0;i<=4;i++){const t=i*clip.metadata.duration/4;ctx.fillStyle=plotColor('--plot-label');ctx.fillText(t.toFixed(1),toX(t)-5,H-B+17);}
  for(const v of [-maxY,0,maxY]){ctx.fillStyle=plotColor('--plot-label');ctx.fillText(v.toFixed(2),8,toY(v)+3);}
  analysis.points.forEach((point,j)=>{ctx.strokeStyle=colors[j];ctx.lineWidth=1.5;ctx.beginPath();let active=false;point['d'+analysis.axis].forEach((value,i)=>{if(value===null){active=false;return;}const x=toX(analysis.time[i]),y=toY(value);if(active)ctx.lineTo(x,y);else ctx.moveTo(x,y);active=true;});ctx.stroke();});
  ctx.strokeStyle='#e9f0f3';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(toX(frame/clip.metadata.fps),T);ctx.lineTo(toX(frame/clip.metadata.fps),H-B);ctx.stroke();
}
