'use strict';
let spatialField=null,renderInfo=null,responsePixels=null,heatLayer=null,maskLayer=null;
let referenceImage=null,modalImage=null,modalPlaying=false,modalRequest=0,modalFetching=false,modalTimer=null,hoverNode=null;
const fieldViews=new Set(['amplitude','phase','modal','tap']);
const viewNames={amplified:'Amplified',heatmap:'Frequency heatmap',isolated:'Isolated response',amplitude:'Displacement amplitude',phase:'Relative phase',modal:'Fitted response animation',tap:'Virtual tap · assumed model'};
function pauseModal(){modalPlaying=false;$('modalPlay').textContent='▶ Animate';}
function invalidateField(){
  resetTap();
  pauseModal();modalRequest++;spatialField=null;hoverNode=null;referenceImage?.close();referenceImage=null;modalImage?.close();modalImage=null;
  $('fieldLabel').textContent='NO CURRENT SPATIAL MAP';$('fieldSummary').textContent='Analyze response to update local displacement and phase.';$('sampleSelect').replaceChildren(new Option('Choose a sample…',''));
  notes('fieldWarnings',[]);$('responseInspect').hidden=true;updateResponseHelp();
}
function resetResponse(){
  clearVideoDownload();
  invalidateField();renderInfo=null;responsePixels=null;heatLayer=null;maskLayer=null;
  $('responseView').value='heatmap';$('sensitivity').value='85';$('modalGain').value='10';$('modalPhase').value='0';
  $('modalPhaseLabel').textContent='0°';$('modalGainValue').textContent='10×';updateResponseHelp();
}
function rasterCanvas(width,height){const c=document.createElement('canvas');c.width=width;c.height=height;return c;}
async function loadResponse(info){
  renderInfo=info;const bitmap=await getImage(`/api/response/${clip.id}?key=${renderKey}`);
  const c=rasterCanvas(bitmap.width,bitmap.height),ctx=c.getContext('2d');ctx.drawImage(bitmap,0,0);bitmap.close();
  const rgba=ctx.getImageData(0,0,c.width,c.height).data;responsePixels=new Float32Array(c.width*c.height);
  for(let i=0;i<responsePixels.length;i++)responsePixels[i]=rgba[i*4]/255;
  rebuildResponseLayers();
}
function sensitivityThreshold(){return (1-Number($('sensitivity').value)/100)*.75;}
function softVisibility(value){const t=sensitivityThreshold();if(value<=0||value<=t)return 0;const s=Math.min(1,(value-t)/.12);return s*s*(3-2*s);}
function ramp(value){const low=[36,73,123],mid=[69,204,186],high=[255,191,102];const a=value<.5?low:mid,b=value<.5?mid:high,t=value<.5?value*2:(value-.5)*2;return a.map((v,i)=>Math.round(v+(b[i]-v)*t));}
function rebuildResponseLayers(){
  if(!responsePixels||!clip)return;
  heatLayer=rasterCanvas(clip.metadata.width,clip.metadata.height);maskLayer=rasterCanvas(heatLayer.width,heatLayer.height);
  const heat=heatLayer.getContext('2d').createImageData(heatLayer.width,heatLayer.height),mask=maskLayer.getContext('2d').createImageData(heatLayer.width,heatLayer.height);
  for(let i=0;i<responsePixels.length;i++){
    const v=responsePixels[i],a=Math.round(softVisibility(v)*255),color=ramp(v),j=i*4;
    heat.data[j]=color[0];heat.data[j+1]=color[1];heat.data[j+2]=color[2];heat.data[j+3]=a*.85;
    mask.data[j]=mask.data[j+1]=mask.data[j+2]=255;mask.data[j+3]=a;
  }
  heatLayer.getContext('2d').putImageData(heat,0,0);maskLayer.getContext('2d').putImageData(mask,0,0);
}
function amplitudeText(value){const scale=Number($('calibration').value);return `${value.toFixed(4)} px${scale>0&&Number.isFinite(scale)?' / '+(value*scale).toPrecision(4)+' mm':''}`;}
function clearVideoDownload(){ $('videoDownload').hidden=true;$('videoDownload').removeAttribute('href'); }
function updateExportLinks(){updateExports();}
function updateVideoExportButtons(){updateExports();}
function updateResponseHelp(){
  const view=$('responseView').value,field=fieldViews.has(view);$('visualizationTitle').textContent=viewNames[view];
  $('sensitivityValue').textContent=$('sensitivity').value+'%';$('responseLegend').hidden=view==='amplified'||(field?!spatialField:!renderInfo);$('sensitivityControl').hidden=view==='amplified'||(field?!spatialField:!renderInfo);$('modalGainControl').hidden=!['modal','tap'].includes(view);$('tapSandbox').hidden=view!=='tap';if(view==='tap'){$('responseLegend').hidden=true;$('sensitivityControl').hidden=true;}$('sampleInspector').hidden=view==='tap'||!field||!spatialField;for(const button of document.querySelectorAll('[data-view]'))button.setAttribute('aria-pressed',String(button.dataset.view===view));
  $('videoPlayback').hidden=['modal','tap'].includes(view);$('modalPlayback').hidden=view!=='modal';
  $('responseRamp').className='response-ramp'+(view==='phase'?' phase':view==='modal'?' signed':'');
  if(field){
    $('renderLabel').textContent=spatialField?`${spatialField.frequency_hz.toFixed(3)} Hz · ${spatialField.axis.toUpperCase()} fit`:'ANALYZE RESPONSE';
    const max=spatialField?.amplitude_display_max_px||0,cut=max*sensitivityThreshold();
    $('responseScale').textContent=view==='phase'?'−180° · −90° · 0° · +90° · +180°; relative to '+(spatialField?.reference.label||'reference'):
      view==='modal'?'Blue = negative; orange = positive '+(spatialField?.axis.toUpperCase()||'Y')+' displacement':`Peak amplitude 0–${amplitudeText(max)}; show above ${amplitudeText(cut)}`;
    $('responseHelp').textContent=spatialField?`${spatialField.frequency_hz.toFixed(3)} analysis-time Hz · ${spatialField.axis.toUpperCase()} amplitude / phase · ${spatialField.reference.label}. ${view==='modal'?'Single-frequency synthesis about frame 0; arrows use fitted X/Y motion.':'Circles are measured patches; crosses have insufficient accepted data.'} Weak phases are withheld.`:'Analyze response at the selected target frequency. These views use original displacement measurements.';
  }else{
    $('renderLabel').textContent=renderInfo?`${renderInfo.low.toFixed(2)}–${renderInfo.high.toFixed(2)} Hz · gain ${renderInfo.gain}`:'ANALYZE RESPONSE';
    const reference=renderInfo?.response.display_reference_rms||0;
    $('responseScale').textContent=`0–${reference.toFixed(3)} luminance levels RMS; show above ${(reference*sensitivityThreshold()).toFixed(3)}. Colors saturate at the 99th percentile.`;
    $('responseHelp').textContent=view==='amplified'?'Magnified images are visualization only. Measurements use original frames.':`${renderInfo?renderInfo.low.toFixed(2)+'–'+renderInfo.high.toFixed(2)+' Hz · ':''}Stable mask from original band-response RMS, independent of gain. Brightness variation is texture-dependent and can include lighting flicker; dark does not prove stationary.`;
  }
  if(view==='tap'){$('renderLabel').textContent=spatialField?`${spatialField.frequency_hz.toFixed(3)} Hz · ASSUMED MODEL`:'ANALYZE RESPONSE';$('responseHelp').textContent='One standing-mode approximation with assumed damping and relative impulse scaling. Simulated source-pixel motion is not a measured impulse response.';}
  updateExports();if(hoverNode!==null&&spatialField)inspectNode(hoverNode);
}
function centeredMessage(ctx,c,text){ctx.fillStyle='#101820dc';ctx.fillRect(0,c.height/2-22,c.width,44);ctx.fillStyle='#c0d1df';ctx.font='11px sans-serif';ctx.textAlign='center';ctx.fillText(text,c.width/2,c.height/2+4);ctx.textAlign='left';}
function drawResponse(ctx,c){
  const view=$('responseView').value;
  if(view==='amplified')return false;
  if(view==='tap')return drawTap(ctx,c);
  if(view==='heatmap'||view==='isolated'){
    if(!heatLayer||!renderKey){centeredMessage(ctx,c,'Analyze response to reveal responding regions');return true;}
    ctx.fillStyle='#080d13';ctx.fillRect(0,0,c.width,c.height);
    if(view==='heatmap'){
      ctx.globalAlpha=.5;if(originalImage)ctx.drawImage(originalImage,0,0);ctx.globalAlpha=1;ctx.drawImage(heatLayer,0,0);
    }else{
      const isolated=rasterCanvas(c.width,c.height),ic=isolated.getContext('2d');
      if(amplifiedImage)ic.drawImage(amplifiedImage,0,0);ic.globalCompositeOperation='destination-in';ic.drawImage(maskLayer,0,0);ctx.drawImage(isolated,0,0);
    }
    return true;
  }
  if(!spatialField||!referenceImage){centeredMessage(ctx,c,'Analyze response to measure this view');return true;}
  ctx.fillStyle='#080d13';ctx.fillRect(0,0,c.width,c.height);
  ctx.globalAlpha=view==='modal'?.85:.45;ctx.drawImage(view==='modal'&&modalImage?modalImage:referenceImage,0,0);ctx.globalAlpha=1;
  const max=spatialField.amplitude_display_max_px||1,phase=Number($('modalPhase').value),gain=Number($('modalGain').value);
  const theta=(phase-(spatialField.reference.phase_deg||0))*Math.PI/180,radius=Math.max(4,Math.min(8,spatialField.grid.step*.24));
  spatialField.nodes.forEach((node,i)=>{
    const {x,y}=node,a=node.amplitude_peak_px;
    if(a===null){ctx.strokeStyle='#8797a3';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x-3,y-3);ctx.lineTo(x+3,y+3);ctx.moveTo(x+3,y-3);ctx.lineTo(x-3,y+3);ctx.stroke();return;}
    const visibility=softVisibility(a/max);if(!visibility&&hoverNode!==i)return;
    ctx.globalAlpha=Math.max(.25,visibility);ctx.lineWidth=1;
    let color='rgb('+ramp(Math.min(1,a/max)).join(',')+')';
    if(view==='phase')color=node.relative_phase_deg===null?'#788692':`hsl(${(node.relative_phase_deg+180+360)%360} 80% 65%)`;
    if(view==='modal'){
      const xf=node.fit.x,yf=node.fit.y;
      if(xf&&yf&&spatialField.reference.phase_deg!==null&&(xf.phase_deg!==null||yf.phase_deg!==null)){
        const dx=(xf.coefficients_px[0]*Math.cos(theta)+xf.coefficients_px[1]*Math.sin(theta))/clip.metadata.scale_x*gain;
        const dy=(yf.coefficients_px[0]*Math.cos(theta)+yf.coefficients_px[1]*Math.sin(theta))/clip.metadata.scale_y*gain;
        const chosen=node.fit[spatialField.axis],value=chosen.coefficients_px[0]*Math.cos(theta)+chosen.coefficients_px[1]*Math.sin(theta);
        color=value>=0?'#ffbd7e':'#82b6f4';ctx.strokeStyle=color;ctx.lineWidth=1.5;
        ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+dx,y+dy);ctx.stroke();
        const angle=Math.atan2(dy,dx),length=Math.hypot(dx,dy);
        if(length>2){ctx.beginPath();ctx.moveTo(x+dx,y+dy);ctx.lineTo(x+dx-3*Math.cos(angle-.5),y+dy-3*Math.sin(angle-.5));ctx.moveTo(x+dx,y+dy);ctx.lineTo(x+dx-3*Math.cos(angle+.5),y+dy-3*Math.sin(angle+.5));ctx.stroke();}
        ctx.fillStyle=color;ctx.beginPath();ctx.arc(x+dx,y+dy,2.5,0,2*Math.PI);ctx.fill();
      }else{ctx.strokeStyle='#8797a3';ctx.strokeRect(x-2,y-2,4,4);}
    }else{ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y,radius,0,2*Math.PI);ctx.fill();}
    ctx.globalAlpha=1;
    if(hoverNode===i){ctx.strokeStyle='#fff';ctx.lineWidth=1.5;ctx.beginPath();ctx.arc(x,y,radius+3,0,2*Math.PI);ctx.stroke();}
  });
  ctx.globalAlpha=1;
  if(view==='modal'&&spatialField.reference.phase_deg===null)centeredMessage(ctx,c,'Phase reference unavailable; choose a measurable reference');
  return true;
}
function inspectNode(index){
  const node=spatialField.nodes[index],fit=node.fit[spatialField.axis],relative=node.relative_phase_deg;
  $('responseInspect').hidden=false;$('sampleSelect').value=String(index);
  $('responseInspect').textContent=`Grid ${index+1} (${node.x.toFixed(0)}, ${node.y.toFixed(0)} analysis px) · ${spatialField.axis.toUpperCase()} peak ${fit?amplitudeText(fit.amplitude_peak_px):'withheld'} · relative phase ${relative===null?'unavailable':relative.toFixed(1)+'°'} · accepted ${(node.valid_fraction*100).toFixed(1)}%${fit?' · fit residual '+amplitudeText(fit.rms_residual_px)+' · harmonic power fraction '+(fit.harmonic_power_fraction*100).toFixed(1)+'%':''}. ${node.warnings.join(' ')}`;
}
$('amplified').onpointermove=e=>{
  if(!spatialField||!fieldViews.has($('responseView').value)||$('responseView').value==='tap')return;
  const c=$('amplified'),rect=c.getBoundingClientRect(),x=(e.clientX-rect.left)/rect.width*c.width,y=(e.clientY-rect.top)/rect.height*c.height;
  let nearest=null,distance=spatialField.grid.step*.75;
  spatialField.nodes.forEach((p,i)=>{const d=Math.hypot(p.x-x,p.y-y);if(d<distance){nearest=i;distance=d;}});
  hoverNode=nearest;if(nearest!==null)inspectNode(nearest);else $('responseInspect').hidden=true;drawVideos();
};
$('amplified').onclick=$('amplified').onpointermove;
function selectView(view){
  pause();clearVideoDownload();$('responseView').value=view;hoverNode=null;$('responseInspect').hidden=true;updateResponseHelp();drawVideos();
  if(view==='modal'&&spatialField)refreshModal().catch(showError);
  if(view==='tap'&&spatialField)task('Preparing the assumed virtual tap model…',prepareTap);
  $('exportKind').value=['heatmap','isolated','modal','tap'].includes(view)?view:fieldViews.has(view)?'samples':'heatmap';
  saveDisplay();updateExports();
}
$('responseView').onchange=()=>selectView($('responseView').value);
for(const button of document.querySelectorAll('[data-view]'))button.onclick=()=>selectView(button.dataset.view);
$('sensitivity').oninput=()=>{rebuildResponseLayers();updateResponseHelp();drawVideos();if($('responseView').value==='modal')requestModal();clearVideoDownload();saveDisplay();};
async function runField(){
  const result=await api('/api/field',{id:clip.id,revision,frequency:Number($('frequency').value),axis:$('axis').value,roi,points,reference:$('fieldReference').value,reference_last:$('cameraReference').checked});
  invalidateField();spatialField=result;revision=result.revision;referenceImage=await getImage(frameUrl('original',0));showFieldSummary();updateResponseHelp();drawVideos();
}
function showFieldSummary(){
  const result=spatialField;if(!result)return;
  $('fieldLabel').textContent=`${result.frequency_hz.toFixed(3)} Hz · ${result.axis.toUpperCase()} · ORIGINAL DISPLACEMENT`;
  $('fieldSummary').textContent=`${result.accepted_nodes}/${result.nodes.length} accepted patches · ${result.phase_nodes} usable phases · ${(result.interpolated_support_fraction*100).toFixed(1)}% interpolation support · ${result.reference.label}.`;
  notes('fieldWarnings',result.warnings);
  $('sampleSelect').replaceChildren(new Option('Choose a sample…',''),...result.nodes.map((node,i)=>new Option(`Grid ${i+1} (${node.x}, ${node.y}) · ${node.amplitude_peak_px===null?'withheld':amplitudeText(node.amplitude_peak_px)} · phase ${node.relative_phase_deg===null?'unavailable':node.relative_phase_deg.toFixed(1)+'°'}`,String(i))));
}
$('sampleSelect').onchange=()=>{hoverNode=$('sampleSelect').value===''?null:Number($('sampleSelect').value);if(hoverNode===null)$('responseInspect').hidden=true;else inspectNode(hoverNode);drawVideos();};
$('amplified').onkeydown=e=>{
  if(!spatialField||!fieldViews.has($('responseView').value)||!e.key.startsWith('Arrow'))return;
  e.preventDefault();const step=e.key==='ArrowDown'?spatialField.grid.columns:e.key==='ArrowUp'?-spatialField.grid.columns:e.key==='ArrowRight'?1:-1;
  hoverNode=Math.max(0,Math.min(spatialField.nodes.length-1,(hoverNode??0)+step));inspectNode(hoverNode);drawVideos();
};
async function refreshModal(){
  if(!spatialField||spatialField.reference.phase_deg===null||$('responseView').value!=='modal')return;
  const e=epoch,key=spatialField.key,requestId=++modalRequest;
  const url=`/api/frame/${clip.id}/0?view=modal&key=${key}&phase=${$('modalPhase').value}&gain=${$('modalGain').value}&threshold=${sensitivityThreshold()}`;
  const bitmap=await getImage(url);
  if(e!==epoch||key!==spatialField?.key||requestId!==modalRequest){bitmap.close();return;}
  modalImage?.close();modalImage=bitmap;drawVideos();
}
function requestModal(){clearTimeout(modalTimer);modalTimer=setTimeout(()=>refreshModal().catch(showError),45);}
$('modalPhase').oninput=()=>{pauseModal();$('modalPhaseLabel').textContent=Math.round(Number($('modalPhase').value))+'°';drawVideos();requestModal();saveDisplay();};
$('modalGain').oninput=()=>{$('modalGainValue').textContent=$('modalGain').value+'×';updateExports();drawVideos();if($('responseView').value==='tap')refreshTapFrame().catch(showError);else requestModal();clearVideoDownload();saveDisplay();};
$('modalPlay').onclick=()=>{
  if(modalPlaying){pauseModal();saveDisplay();return;}
  if(!spatialField||spatialField.reference.phase_deg===null){showError(new Error('Build a displacement map with a usable phase reference first.'));return;}
  pause();modalPlaying=true;$('modalPlay').textContent='Ⅱ Pause';const start=performance.now(),initial=Number($('modalPhase').value);let last=0;
  async function tick(now){
    if(!modalPlaying)return;
    if(!modalFetching&&now-last>70){last=now;modalFetching=true;$('modalPhase').value=((initial+(now-start)*.36)%360).toFixed(0);$('modalPhaseLabel').textContent=$('modalPhase').value+'°';
      try{await refreshModal();}catch(e){pauseModal();showError(e);}finally{modalFetching=false;}}
    if(modalPlaying)requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
};
