'use strict';
const $=id=>document.getElementById(id);
const colors=['#76e0c2','#80b7ee','#ffc986','#df9ef6','#fb8eaa','#bbd587','#e9b489','#a4c9cf'];
let clip=null,points=[],roi=null,mode='points',analysis=null,renderKey=null,frame=0,playing=false,busy=false,epoch=0;
let originalImage=null,amplifiedImage=null,frameRequest=0,fetchingFrame=false,drag=null;
const status=message=>$('status').textContent=message;
function showError(e){$('error').hidden=false;$('error').textContent=e.message||String(e);status('Could not complete that operation. Adjust the input and try again.');}
function clearError(){$('error').hidden=true;}
async function api(url,data,form=false){
  const response=await fetch(url,{method:'POST',headers:form?{}:{'Content-Type':'application/json'},body:form?data:JSON.stringify(data)});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'Request failed.');return result;
}
async function task(message,work){
  if(busy)return;busy=true;pause();clearError();document.body.classList.add('busy');
  const controls=[...document.querySelectorAll('button,input,select')],disabled=controls.map(control=>control.disabled);
  controls.forEach(control=>control.disabled=true);
  status(message);
  try{await work();}catch(e){showError(e);}finally{busy=false;document.body.classList.remove('busy');controls.forEach((control,i)=>control.disabled=disabled[i]);}
}
function notes(id,values){$(id).replaceChildren(...values.map(v=>{const p=document.createElement('p');p.textContent=v;return p;}));}
function showTimebase(){
  const m=clip.metadata;const assumed=m.timing_basis.includes('user-assumed');
  $('timebaseSummary').textContent=`Analysis rate ${m.fps.toFixed(3)} fps · frequency range 0–${m.nyquist.toFixed(2)} Hz · ${assumed?'capture time assumed; one encoded frame per captured sample':'encoded playback time; set original capture fps for slow-motion footage'}.`;
}
async function load(data,isDemo=false){
  resetResponse();originalImage?.close();amplifiedImage?.close();
  epoch++;frameRequest++;clip=data;points=data.default_points;roi=null;frame=0;analysis=null;renderKey=null;originalImage=null;amplifiedImage=null;
  $('workspace').hidden=false;$('clipName').textContent=data.metadata.name;
  const m=data.metadata;
  $('clipMeta').textContent=`${m.source_width}×${m.source_height} source · ${m.encoded_fps.toFixed(3)} encoded fps · ${m.duration.toFixed(2)} analysis s · ${m.frames} frames`;
  $('scrub').max=m.frames-1;$('scrub').value=0;
  for(const id of ['original','amplified']){$(id).width=m.width;$(id).height=m.height;}
  let [lo,hi]=data.default_band;if(hi<=lo)hi=Math.min(m.nyquist-.01,lo+m.resolution_hz*2);
  $('low').value=lo.toFixed(2);$('high').value=hi.toFixed(2);$('frequency').value=isDemo?'3':Math.min(5,m.nyquist*.6).toFixed(2);
  $('gain').value='4';$('cameraReference').checked=false;
  $('captureFps').value='';$('sampleTiming').checked=false;$('timebaseLabel').textContent=`${m.timing_basis}. Physical Hz requires verified capture/playback timing.`;
  showTimebase();$('phaseLabel').textContent='NO CURRENT FIT';$('traceHelp').textContent='';$('renderLabel').textContent='APPLY A BAND';$('results').replaceChildren();notes('renderWarnings',[]);notes('inputWarnings',m.warnings);
  $('bandHelp').textContent=`Nyquist ${m.nyquist.toFixed(2)} Hz · resolution Δf=${m.resolution_hz.toFixed(3)} Hz · unit passband with one-bin cosine shoulders; ≥2 cycles at low edge.`;
  $('jsonExport').href=`/api/export/${clip.id}`;$('csvExport').href=`/api/csv/${clip.id}`;
  drawSpectrum();drawTrace();await showFrame(0);
  if(points.length){await runAnalysis();await runRender();}
  status(isDemo?'Demo ready. Known input: P2 leads P1 by 60° at 3 Hz before any occlusion. Inspect tracking warnings and change the band.':'Video ready. Click textured locations in the original image, then analyze points. Verify original capture/playback speed before interpreting physical Hz.');
}
$('cleanDemo').onclick=()=>task('Loading and validating the known-motion demo…',async()=>load(await api('/api/demo',{kind:'clean'}),true));
$('dropoutDemo').onclick=()=>task('Loading the tracking dropout demo…',async()=>load(await api('/api/demo',{kind:'dropout'}),true));
$('videoFile').onchange=()=>{const f=$('videoFile').files[0];if(!f)return;task('Decoding local video and checking frame timing…',async()=>{const form=new FormData();form.append('video',f);await load(await api('/api/load',form,true));});$('videoFile').value='';};
function pause(){playing=false;$('play').textContent='▶ Play';pauseModal();}
function frameUrl(view,index){return `/api/frame/${clip.id}/${index}?view=${view}${view==='amplified'?'&key='+renderKey:''}`;}
async function getImage(url){const response=await fetch(url);if(!response.ok){const error=await response.json();throw new Error(error.error);}const blob=await response.blob();return createImageBitmap(blob);}
async function showFrame(index){
  if(!clip)return;const e=epoch,requestId=++frameRequest;index=Math.max(0,Math.min(clip.metadata.frames-1,Math.round(index)));
  const images=await Promise.all([getImage(frameUrl('original',index)),renderKey?getImage(frameUrl('amplified',index)):Promise.resolve(null)]);
  if(e!==epoch||requestId!==frameRequest){images.forEach(i=>i?.close());return;}
  originalImage?.close();amplifiedImage?.close();[originalImage,amplifiedImage]=images;frame=index;
  $('scrub').value=frame;$('timeLabel').textContent=(frame/clip.metadata.fps).toFixed(2)+' s';drawVideos();drawTrace();
}
function drawVideos(){
  for(const id of ['original','amplified']){
    const c=$(id),ctx=c.getContext('2d'),img=id==='original'?originalImage:(amplifiedImage||originalImage);
    ctx.fillStyle='#0b1118';ctx.fillRect(0,0,c.width,c.height);if(img)ctx.drawImage(img,0,0,c.width,c.height);
    if(id==='amplified'&&drawResponse(ctx,c))continue;
    if(!img)continue;
    if(roi){ctx.strokeStyle='#ffd089';ctx.lineWidth=1.5;ctx.setLineDash([5,4]);ctx.strokeRect(...roi);ctx.setLineDash([]);}
    points.forEach((p,j)=>{
      let x=p[0],y=p[1],ok=true;
      if(analysis){const trace=analysis.points[j];if(trace){const dx=(trace.raw_dx||trace.dx)[frame],dy=(trace.raw_dy||trace.dy)[frame];ok=dx!==null&&dy!==null;if(ok){x+=dx/clip.metadata.scale_x;y+=dy/clip.metadata.scale_y;}}}
      ctx.strokeStyle=ok?colors[j]:'#ff9b9b';ctx.lineWidth=1.4;ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);ctx.stroke();ctx.fillStyle='#101820';ctx.fillRect(x+7,y-14,21,13);ctx.fillStyle=ctx.strokeStyle;ctx.font='10px sans-serif';ctx.fillText(`P${j+1}`,x+9,y-4);
    });
    if(id==='amplified'&&!renderKey){ctx.fillStyle='#101820c9';ctx.fillRect(0,c.height/2-18,c.width,36);ctx.fillStyle='#c0d1df';ctx.font='12px sans-serif';ctx.textAlign='center';ctx.fillText('Apply a band to see amplified motion',c.width/2,c.height/2+4);ctx.textAlign='left';}
  }
}
$('play').onclick=()=>{if(!clip||busy)return;if(playing){pause();return;}playing=true;$('play').textContent='Ⅱ Pause';const start=performance.now();if(frame===clip.metadata.frames-1)frame=0;let firstFrame=frame;
  async function tick(){if(!playing)return;const desired=(firstFrame+Math.floor((performance.now()-start)/1000*clip.metadata.encoded_fps*Number($('speed').value)))%clip.metadata.frames;if(desired!==frame&&!fetchingFrame){fetchingFrame=true;try{await showFrame(desired);}catch(e){pause();showError(e);}finally{fetchingFrame=false;}}if(playing)requestAnimationFrame(tick);}requestAnimationFrame(tick);
};
$('scrub').oninput=()=>{pause();showFrame(Number($('scrub').value)).catch(showError);};
$('speed').onchange=pause;
function setMode(value){mode=value;$('pointMode').className=value==='points'?'selected':'secondary';$('roiMode').className=value==='roi'?'selected':'secondary';}
$('pointMode').onclick=()=>setMode('points');$('roiMode').onclick=()=>setMode('roi');
function invalidateAnalysis(){invalidateField();analysis=null;$('phaseLabel').textContent='NO CURRENT FIT';$('results').replaceChildren();drawVideos();drawSpectrum();drawTrace();$('traceHelp').textContent='Point selection changed. Analyze original points to update results.';}
$('clearPoints').onclick=()=>{points=[];invalidateAnalysis();};
$('clearRoi').onclick=()=>{roi=null;invalidateField();drawVideos();status('Full-frame ROI selected. Apply band & gain or build the displacement map to update the visualization.');};
function imagePosition(e){const r=$('original').getBoundingClientRect();return[(e.clientX-r.left)/r.width*$('original').width,(e.clientY-r.top)/r.height*$('original').height];}
$('original').onpointerdown=e=>{if(!clip||busy)return;pause();const p=imagePosition(e);if(mode==='points'){if(points.length>=8){showError(new Error('Up to eight points are supported. Clear points to start again.'));return;}if(p[0]<16||p[1]<16||p[0]>=clip.metadata.width-16||p[1]>=clip.metadata.height-16){showError(new Error('Choose a point at least 16 analysis pixels from the edges.'));return;}points.push(p.map(Math.round));invalidateAnalysis();status(`P${points.length} selected. Analyze original points to measure motion.`);}else{drag={kind:'roi',start:p};$('original').setPointerCapture(e.pointerId);}};
$('original').onpointermove=e=>{if(drag?.kind!=='roi')return;const p=imagePosition(e),s=drag.start;const w=clip.metadata.width,h=clip.metadata.height;roi=[Math.max(0,Math.min(s[0],p[0])),Math.max(0,Math.min(s[1],p[1])),Math.min(w,Math.abs(s[0]-p[0])),Math.min(h,Math.abs(s[1]-p[1]))].map(Math.round);roi[2]=Math.min(roi[2],w-roi[0]);roi[3]=Math.min(roi[3],h-roi[1]);drawVideos();};
$('original').onpointerup=()=>{if(drag?.kind==='roi'){drag=null;if(roi&&Math.min(roi[2],roi[3])<8)roi=null;invalidateField();drawVideos();status('ROI changed. Apply band & gain or rebuild the displacement map.');}};
async function runAnalysis(){
  if(!clip)throw new Error('Load a video first.');if(!points.length)throw new Error('Select at least one textured point in the original image.');
  analysis=await api('/api/analyze',{id:clip.id,points,axis:$('axis').value,frequency:Number($('frequency').value),reference_last:$('cameraReference').checked});
  drawResults();drawSpectrum();drawTrace();drawVideos();
}
async function runRender(){
  if(!clip)throw new Error('Load a video first.');const result=await api('/api/render',{id:clip.id,low:Number($('low').value),high:Number($('high').value),gain:Number($('gain').value),roi});
  renderKey=result.key;await loadResponse(result);$('renderLabel').textContent=`${result.low.toFixed(2)}–${result.high.toFixed(2)} Hz · α ${result.gain}`;notes('renderWarnings',result.warnings);await showFrame(frame);drawSpectrum();updateResponseHelp();
}
$('analyze').onclick=()=>task('Tracking original frames and fitting motion…',async()=>{await runAnalysis();status(`Original-video analysis ready at ${analysis.frequency_hz.toFixed(3)} analysis-time Hz. Peak spectrum bin: ${analysis.peak_frequency_hz?.toFixed(3)||'unavailable'} Hz.`);});
$('apply').onclick=()=>task('Filtering spatial-pyramid levels and reconstructing amplified frames…',async()=>{await runRender();status('Amplification updated. Original-video measurements remain available separately.');});
$('setTimebase').onclick=()=>task('Updating the analysis timebase…',async()=>{
  if(!clip)throw new Error('Load a video first.');const old=clip.metadata.fps;const value=$('captureFps').value.trim();
  const result=await api('/api/timebase',{id:clip.id,capture_fps:value?Number(value):null,one_frame_per_sample:$('sampleTiming').checked});
  clip.metadata=result.metadata;const ratio=clip.metadata.fps/old;for(const id of ['low','high','frequency'])$(id).value=(Number($(id).value)*ratio).toFixed(3);
  resetResponse();renderKey=null;amplifiedImage?.close();amplifiedImage=null;invalidateAnalysis();$('renderLabel').textContent='APPLY UPDATED BAND';
  $('timebaseLabel').textContent=`${clip.metadata.timing_basis}; analysis fps ${clip.metadata.fps}, playback fps ${clip.metadata.encoded_fps}.`;
  $('clipMeta').textContent=`${clip.metadata.source_width}×${clip.metadata.source_height} source · ${clip.metadata.encoded_fps.toFixed(3)} encoded fps · ${clip.metadata.duration.toFixed(2)} analysis s · ${clip.metadata.frames} frames`;
  $('bandHelp').textContent=`Nyquist ${clip.metadata.nyquist.toFixed(2)} Hz · resolution Δf=${clip.metadata.resolution_hz.toFixed(3)} Hz · ≥2 cycles at low edge.`;
  showTimebase();$('timeLabel').textContent=(frame/clip.metadata.fps).toFixed(2)+' s';
  status('Timebase changed; band and fit frequency scaled. Analyze points and apply band to update results.');
});
$('calibration').oninput=()=>{if(analysis)drawResults();drawSpectrum();updateResponseHelp();drawVideos();};
for(const id of ['low','high'])$(id).oninput=()=>{drawSpectrum();if(clip)status('Band selection changed. Apply band & gain to update playback.');};
function measurementSettingsChanged(){invalidateField();if(analysis)status('Measurement settings changed. Analyze original points or rebuild the spatial map.');drawVideos();drawSpectrum();}
for(const id of ['frequency','axis','cameraReference'])$(id).onchange=measurementSettingsChanged;
$('frequency').oninput=measurementSettingsChanged;
function drawResults(){
  const tbody=$('results');tbody.replaceChildren();
  const calibration=Number($('calibration').value);const calibrated=Number.isFinite(calibration)&&calibration>0;
  analysis.points.forEach((p,j)=>{
    const row=document.createElement('tr');let amplitude=p.fit?`${p.fit.amplitude_peak_px.toFixed(4)} px`:'Withheld';if(p.fit&&calibrated)amplitude+=` / ${(p.fit.amplitude_peak_px*calibration).toPrecision(4)} mm`;
    const relative=p.fit?.relative_phase_deg;const cells=[`P${p.point} (${p.x}, ${p.y})`,amplitude,relative===null||relative===undefined?'Unavailable':`${relative.toFixed(1)}°`,`${(p.valid_fraction*100).toFixed(1)}%`,p.warnings.length?p.warnings.join(' '):`Good texture / registration. Fit residual ${p.fit?.rms_residual_px.toFixed(4)} px.`];
    cells.forEach((value,i)=>{const td=document.createElement('td');td.textContent=value;if(i===0){td.style.color=colors[j];td.className='badge';}if(i===4&&p.warnings.length)td.className='warn';row.append(td);});tbody.append(row);
  });
  $('phaseLabel').textContent=`${analysis.axis.toUpperCase()} · ${analysis.frequency_hz.toFixed(3)} ANALYSIS-TIME Hz · PHASE vs P1`;
  $('traceHelp').textContent=`${analysis.units}; fit excludes first/last ${analysis.fit_edge_excluded_s.toFixed(2)} s and all rejected samples. ${analysis.reference_last?'Stationary last-point translation subtracted. ':''}PSD and amplitude spectra use complete original traces; rejected samples are not filled.`;
}
function plotBase(canvas,xlabel,ylabel){
  const ctx=canvas.getContext('2d'),W=canvas.width,H=canvas.height,L=58,R=18,T=18,B=36;ctx.fillStyle='#121e29';ctx.fillRect(0,0,W,H);ctx.strokeStyle='#304453';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(L,T);ctx.lineTo(L,H-B);ctx.lineTo(W-R,H-B);ctx.stroke();ctx.fillStyle='#9ab0c1';ctx.font='11px sans-serif';ctx.fillText(ylabel,10,12);ctx.fillText(xlabel,W-160,H-7);return {ctx,W,H,L,R,T,B,xw:W-L-R,yh:H-T-B};
}
function drawSpectrum(){
  const psd=$('spectrumView').value==='psd';
  const calibration=Number($('calibration').value),calibrated=calibration>0&&Number.isFinite(calibration);
  const scale=calibrated?calibration:1,unit=calibrated?'mm':'source px';
  const logarithmic=psd&&$('spectrumLog').checked;
  $('spectrumLog').disabled=!psd;
  $('spectrumUnits').textContent=`ORIGINAL ${analysis?.axis.toUpperCase()||$('axis').value.toUpperCase()} · ${psd?'PSD '+unit+'²/Hz':'PEAK '+unit}`;
  const c=$('spectrum'),p=plotBase(c,'Analysis frequency / Hz',psd?`PSD / ${unit}²/Hz`:`Peak / ${unit}`),{ctx,W,H,L,R,T,B,xw,yh}=p;
  $('spectrumLegend').replaceChildren();
  if(!clip)return;
  const maxF=clip.metadata.nyquist,toX=f=>L+f/maxF*xw,lo=Number($('low').value),hi=Number($('high').value);
  ctx.fillStyle='#76e0c21e';ctx.fillRect(toX(lo),T,toX(hi)-toX(lo),yh);
  ctx.strokeStyle='#76e0c2';ctx.lineWidth=2;
  for(const edge of [lo,hi]){ctx.beginPath();ctx.moveTo(toX(edge),T);ctx.lineTo(toX(edge),H-B);ctx.stroke();ctx.fillRect(toX(edge)-4,T+8,8,19);}
  ctx.fillStyle='#9ab0c1';for(let i=0;i<=6;i++){const f=i*maxF/6;ctx.fillText(f.toFixed(1),toX(f)-8,H-B+17);}
  if(analysis?.spectrum_available){
    const key=psd?'psd_px2_per_hz':'spectrum_px';
    const factor=psd?scale*scale:scale;
    const all=analysis.points.flatMap(point=>(point[key]||[]).slice(1).map(v=>v*factor));
    const maxValue=Math.max(1e-20,...all);
    const upper=logarithmic?Math.ceil(Math.log10(maxValue)):Math.max(psd?1e-20:.02,maxValue)*1.2;
    // Six displayed decades; the floor is only for plotting zeros, not a noise estimate.
    const lower=logarithmic?upper-6:0;
    const toY=value=>H-B-(logarithmic?(Math.max(lower,Math.log10(Math.max(1e-30,value)))-lower)/(upper-lower):value/upper)*yh;
    for(let i=0;i<=3;i++){
      const tick=lower+(upper-lower)*i/3,y=H-B-i*yh/3;
      ctx.fillStyle='#9ab0c1';ctx.fillText(logarithmic?`1e${Math.round(tick)}`:psd?tick.toExponential(1):tick.toFixed(2),7,y+3);
      ctx.strokeStyle='#243746';ctx.beginPath();ctx.moveTo(L,y);ctx.lineTo(W-R,y);ctx.stroke();
    }
    analysis.points.forEach((point,j)=>{
      if(point[key]){
        ctx.strokeStyle=colors[j];ctx.lineWidth=1.7;ctx.beginPath();
        point[key].forEach((value,i)=>{if(i===0)return;const x=toX(analysis.frequencies[i]),y=toY(value*factor);i===1?ctx.moveTo(x,y):ctx.lineTo(x,y);});ctx.stroke();
      }
      const entry=document.createElement('div');entry.className='spectrum-entry';entry.style.color=colors[j];
      const title=document.createElement('strong');title.textContent=`P${point.point} · ${point[key]?'original '+analysis.axis.toUpperCase():'spectrum withheld'}`;entry.append(title);
      if(psd&&point[key]){
        const detail=document.createElement('div');detail.className='spectrum-detail';detail.textContent=`Integrated PSD RMS ${(point.rms_from_psd_px*scale).toPrecision(3)} ${unit}. Strongest local bins:`;entry.append(detail);
        point.psd_peaks.forEach(peak=>{const button=document.createElement('button');button.type='button';button.textContent=peak.frequency_hz.toFixed(2)+' Hz';button.title='Set the harmonic fit frequency; this does not identify a structural mode';button.onclick=()=>{$('frequency').value=peak.frequency_hz.toFixed(3);invalidateField();drawVideos();drawSpectrum();status('Measured peak bin selected. Analyze original points or rebuild the spatial map.');};entry.append(button);});
      }else if(!point[key]){const detail=document.createElement('div');detail.className='spectrum-detail';detail.textContent='Rejected samples are not filled.';entry.append(detail);}
      $('spectrumLegend').append(entry);
    });
    const peak=psd?analysis.psd_peak_frequency_hz:analysis.peak_frequency_hz;
    ctx.fillStyle='#d9e7ee';ctx.fillText(peak===null?'No nonzero spectral energy':`Strongest mean bin ${peak.toFixed(2)} Hz · Δf ${analysis.resolution_hz.toFixed(3)} Hz`,L+8,T+16);
    const m=analysis.psd_metadata;
    $('spectralHelp').textContent=psd?`One-sided Hann periodogram · linear detrend · ${m.duration_s.toFixed(3)} s record · Δf ${m.bin_width_hz.toFixed(3)} Hz · Hann ENBW ${m.enbw_hz.toFixed(3)} Hz · ${m.accepted_trace_count}/${m.total_trace_count} complete traces. No averaging or gap filling. PSD is from original displacement; ${m.timing_basis}.`:'Detrended, Hann-windowed peak-amplitude spectrum of original displacement; source pixels unless calibrated. No gap filling.';
  }else{
    ctx.fillStyle='#96acbd';ctx.fillText('Select points and Analyze original points to view frequency content',L+10,T+52);
    $('spectralHelp').textContent='PSD uses original tracked X/Y displacement, not image brightness or magnified motion. Traces with rejected samples are withheld.';
  }
  const fit=Number($('frequency').value);ctx.strokeStyle='#ffd089';ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(toX(fit),T);ctx.lineTo(toX(fit),H-B);ctx.stroke();ctx.setLineDash([]);
}
$('spectrumView').onchange=drawSpectrum;
$('spectrumLog').onchange=drawSpectrum;
function spectrumFrequency(e){const r=$('spectrum').getBoundingClientRect(),x=(e.clientX-r.left)/r.width*900;return Math.max(0,Math.min(clip.metadata.nyquist,(x-58)/(900-58-18)*clip.metadata.nyquist));}
$('spectrum').onpointerdown=e=>{if(!clip||busy)return;const f=spectrumFrequency(e),lo=Number($('low').value),hi=Number($('high').value),tol=Math.min(clip.metadata.nyquist*.018,(hi-lo)*.25);let kind=Math.abs(f-lo)<tol?'low':Math.abs(f-hi)<tol?'high':f>lo&&f<hi?'band':'fit';drag={kind,start:f,low:lo,high:hi,moved:false};$('spectrum').setPointerCapture(e.pointerId);};
$('spectrum').onpointermove=e=>{if(!drag||drag.kind==='roi'||!clip)return;const f=spectrumFrequency(e),df=clip.metadata.resolution_hz,nyq=clip.metadata.nyquist;drag.moved=true;let lo=drag.low,hi=drag.high;if(drag.kind==='low')lo=Math.max(2*df,Math.min(hi-df,f));if(drag.kind==='high')hi=Math.max(lo+df,Math.min(nyq-.01,f));if(drag.kind==='band'){const delta=Math.max(2*df-lo,Math.min(nyq-.01-hi,f-drag.start));lo+=delta;hi+=delta;}if(drag.kind==='fit')$('frequency').value=Math.max(.01,Math.min(nyq-.01,f)).toFixed(3);else{$('low').value=lo.toFixed(3);$('high').value=hi.toFixed(3);}drawSpectrum();};
$('spectrum').onpointerup=e=>{if(!drag||drag.kind==='roi')return;if(!drag.moved){$('frequency').value=Math.max(.01,Math.min(clip.metadata.nyquist-.01,spectrumFrequency(e))).toFixed(3);invalidateField();drawSpectrum();status('Measurement frequency selected. Analyze original points or rebuild the spatial map.');}else{if(drag.kind==='fit')invalidateField();status('Band or fit selection changed. Apply the band or analyze points to update the result.');}drag=null;};
function drawTrace(){
  const c=$('tracePlot'),p=plotBase(c,'Analysis time / s','Displacement / source px'),{ctx,W,H,L,R,T,B,xw,yh}=p;if(!analysis||!clip)return;
  const values=analysis.points.flatMap(point=>point['d'+analysis.axis].filter(x=>x!==null));const maxY=Math.max(.1,...values.map(Math.abs))*1.15;
  const toX=t=>L+t/(clip.metadata.duration)*xw,toY=y=>T+yh/2-y/(2*maxY)*yh;
  ctx.strokeStyle='#304453';ctx.beginPath();ctx.moveTo(L,toY(0));ctx.lineTo(W-R,toY(0));ctx.stroke();
  for(let i=0;i<=4;i++){const t=i*clip.metadata.duration/4;ctx.fillStyle='#9ab0c1';ctx.fillText(t.toFixed(1),toX(t)-5,H-B+17);}
  for(const v of [-maxY,0,maxY]){ctx.fillStyle='#9ab0c1';ctx.fillText(v.toFixed(2),8,toY(v)+3);}
  analysis.points.forEach((point,j)=>{ctx.strokeStyle=colors[j];ctx.lineWidth=1.5;ctx.beginPath();let active=false;point['d'+analysis.axis].forEach((value,i)=>{if(value===null){active=false;return;}const x=toX(analysis.time[i]),y=toY(value);if(active)ctx.lineTo(x,y);else ctx.moveTo(x,y);active=true;});ctx.stroke();});
  ctx.strokeStyle='#e9f0f3';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(toX(frame/clip.metadata.fps),T);ctx.lineTo(toX(frame/clip.metadata.fps),H-B);ctx.stroke();
}
drawSpectrum();drawTrace();
