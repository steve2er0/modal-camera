'use strict';
let spatialField=null,renderInfo=null,responsePixels=null,heatLayer=null,maskLayer=null;
let referenceImage=null,modalImage=null,modalPlaying=false,modalRequest=0,modalFetching=false,modalTimer=null,hoverNode=null;
const fieldViews=new Set(['amplitude','phase','modal']);
const viewNames={amplified:'Amplified',heatmap:'Frequency heatmap',isolated:'Isolated response',amplitude:'Displacement amplitude',phase:'Relative phase',modal:'Fitted response animation'};
function pauseModal(){modalPlaying=false;$('modalPlay').textContent='▶ Animate';}
function invalidateField(){
  pauseModal();modalRequest++;spatialField=null;hoverNode=null;referenceImage?.close();referenceImage=null;modalImage?.close();modalImage=null;
  $('fieldLabel').textContent='BUILD / REBUILD THE SPATIAL MAP';$('fieldSummary').textContent='Build the displacement map at the selected fit frequency to show local amplitude, phase and fitted motion.';
  notes('fieldWarnings',[]);$('responseInspect').hidden=true;updateResponseHelp();
}
function resetResponse(){
  clearVideoDownload();
  invalidateField();renderInfo=null;responsePixels=null;heatLayer=null;maskLayer=null;
  $('responseView').value='amplified';$('sensitivity').value='85';$('modalGain').value='10';$('modalPhase').value='0';
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
function updateExportLinks(){
  if(!clip)return;const query=new URLSearchParams({sensitivity:$('sensitivity').value,modal_gain:$('modalGain').value,view:$('responseView').value,calibration:$('calibration').value});
  $('jsonExport').href=`/api/export/${clip.id}?${query}`;$('fieldExport').href=`/api/field-csv/${clip.id}`;
}
function updateVideoExportButtons(){
  const bandReady=Boolean(clip&&renderKey&&renderInfo&&responsePixels);
  $('exportHeatmap').disabled=busy||!bandReady;$('exportIsolated').disabled=busy||!bandReady;
  $('exportModal').disabled=busy||!clip||!spatialField||spatialField.reference.phase_deg===null;
}
function clearVideoDownload(){
  $('videoDownload').hidden=true;$('videoDownload').removeAttribute('href');
}
async function downloadResponseVideo(view){
  if(!clip)throw new Error('Load a video first.');
  clearVideoDownload();
  const data={id:clip.id,view,key:view==='modal'?spatialField?.key:renderKey,
    sensitivity:Number($('sensitivity').value),modal_gain:Number($('modalGain').value),phase_start:Number($('modalPhase').value)};
  const response=await fetch('/api/export-video?prepare=1',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  const result=await response.json();if(!response.ok)throw new Error(result.error||'Video export failed.');
  const link=$('videoDownload');link.href=result.url;link.download=result.filename;link.textContent=`Save ${result.filename}`;link.hidden=false;link.click();
  status(`${viewNames[view]} MP4 ready. Download requested; use the Save MP4 link if your browser does not save it automatically.`);
}
for(const [id,view] of [['exportHeatmap','heatmap'],['exportIsolated','isolated'],['exportModal','modal']]){
  $(id).onclick=()=>task(`Encoding ${viewNames[view].toLowerCase()} MP4 with the current sensitivity and gain…`,()=>downloadResponseVideo(view));
}
function updateResponseHelp(){
  const view=$('responseView').value,field=fieldViews.has(view);$('visualizationTitle').textContent=viewNames[view];
  $('sensitivityValue').textContent=$('sensitivity').value+'%';$('responseLegend').hidden=view==='amplified';
  $('videoPlayback').hidden=view==='modal';$('modalPlayback').hidden=view!=='modal';
  $('responseRamp').className='response-ramp'+(view==='phase'?' phase':view==='modal'?' signed':'');
  if(field){
    $('renderLabel').textContent=spatialField?`${spatialField.frequency_hz.toFixed(3)} Hz · ${spatialField.axis.toUpperCase()} fit`:'BUILD SPATIAL MAP';
    const max=spatialField?.amplitude_display_max_px||0,cut=max*sensitivityThreshold();
    $('responseScale').textContent=view==='phase'?'−180° · −90° · 0° · +90° · +180°; relative to '+(spatialField?.reference.label||'reference'):
      view==='modal'?'Blue = negative; orange = positive '+(spatialField?.axis.toUpperCase()||'Y')+' displacement':`Peak amplitude 0–${amplitudeText(max)}; show above ${amplitudeText(cut)}`;
    $('responseHelp').textContent=spatialField?`${spatialField.frequency_hz.toFixed(3)} analysis-time Hz · ${spatialField.axis.toUpperCase()} amplitude / phase · ${spatialField.reference.label}. ${view==='modal'?'Single-frequency synthesis about frame 0; arrows use fitted X/Y motion.':'Circles are measured patches; crosses have insufficient accepted data.'} Weak phases are withheld.`:'Build the displacement & phase map below using the fit frequency and axis. These views use original displacement measurements.';
  }else{
    $('renderLabel').textContent=renderInfo?`${renderInfo.low.toFixed(2)}–${renderInfo.high.toFixed(2)} Hz · α ${renderInfo.gain}`:'APPLY A BAND';
    const reference=renderInfo?.response.display_reference_rms||0;
    $('responseScale').textContent=`0–${reference.toFixed(3)} luminance levels RMS; show above ${(reference*sensitivityThreshold()).toFixed(3)}. Colors saturate at the 99th percentile.`;
    $('responseHelp').textContent=view==='amplified'?'Magnified images are visualization only. Measurements use original frames.':`${renderInfo?renderInfo.low.toFixed(2)+'–'+renderInfo.high.toFixed(2)+' Hz · ':''}Stable mask from original band-response RMS, independent of gain. Brightness variation is texture-dependent and can include lighting flicker; dark does not prove stationary.`;
  }
  updateExportLinks();updateVideoExportButtons();if(hoverNode!==null&&spatialField)inspectNode(hoverNode);
}
function centeredMessage(ctx,c,text){ctx.fillStyle='#101820dc';ctx.fillRect(0,c.height/2-22,c.width,44);ctx.fillStyle='#c0d1df';ctx.font='11px sans-serif';ctx.textAlign='center';ctx.fillText(text,c.width/2,c.height/2+4);ctx.textAlign='left';}
function drawResponse(ctx,c){
  const view=$('responseView').value;
  if(view==='amplified')return false;
  if(view==='heatmap'||view==='isolated'){
    if(!heatLayer||!renderKey){centeredMessage(ctx,c,'Apply a frequency band to reveal responding regions');return true;}
    ctx.fillStyle='#080d13';ctx.fillRect(0,0,c.width,c.height);
    if(view==='heatmap'){
      ctx.globalAlpha=.5;if(originalImage)ctx.drawImage(originalImage,0,0);ctx.globalAlpha=1;ctx.drawImage(heatLayer,0,0);
    }else{
      const isolated=rasterCanvas(c.width,c.height),ic=isolated.getContext('2d');
      if(amplifiedImage)ic.drawImage(amplifiedImage,0,0);ic.globalCompositeOperation='destination-in';ic.drawImage(maskLayer,0,0);ctx.drawImage(isolated,0,0);
    }
    return true;
  }
  if(!spatialField||!referenceImage){centeredMessage(ctx,c,'Build the displacement & phase map below');return true;}
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
  $('responseInspect').hidden=false;
  $('responseInspect').textContent=`Grid ${index+1} (${node.x.toFixed(0)}, ${node.y.toFixed(0)} analysis px) · ${spatialField.axis.toUpperCase()} peak ${fit?amplitudeText(fit.amplitude_peak_px):'withheld'} · relative phase ${relative===null?'unavailable':relative.toFixed(1)+'°'} · accepted ${(node.valid_fraction*100).toFixed(1)}%${fit?' · fit residual '+amplitudeText(fit.rms_residual_px)+' · harmonic power fraction '+(fit.harmonic_power_fraction*100).toFixed(1)+'%':''}. ${node.warnings.join(' ')}`;
}
$('amplified').onpointermove=e=>{
  if(!spatialField||!fieldViews.has($('responseView').value))return;
  const c=$('amplified'),rect=c.getBoundingClientRect(),x=(e.clientX-rect.left)/rect.width*c.width,y=(e.clientY-rect.top)/rect.height*c.height;
  let nearest=null,distance=spatialField.grid.step*.75;
  spatialField.nodes.forEach((p,i)=>{const d=Math.hypot(p.x-x,p.y-y);if(d<distance){nearest=i;distance=d;}});
  hoverNode=nearest;if(nearest!==null)inspectNode(nearest);else $('responseInspect').hidden=true;drawVideos();
};
$('amplified').onclick=$('amplified').onpointermove;
$('responseView').onchange=()=>{pause();hoverNode=null;$('responseInspect').hidden=true;updateResponseHelp();drawVideos();if($('responseView').value==='modal'&&spatialField)refreshModal().catch(showError);};
$('sensitivity').oninput=()=>{rebuildResponseLayers();updateResponseHelp();drawVideos();if($('responseView').value==='modal')requestModal();};
$('fieldReference').onchange=()=>{invalidateField();drawVideos();};
$('buildField').onclick=()=>task('Tracking original texture patches and fitting the spatial response…',async()=>{
  if(!clip)throw new Error('Load a video first.');
  const result=await api('/api/field',{id:clip.id,frequency:Number($('frequency').value),axis:$('axis').value,roi,points,reference:$('fieldReference').value,reference_last:$('cameraReference').checked});
  invalidateField();spatialField=result;referenceImage=await getImage(frameUrl('original',0));
  $('fieldLabel').textContent=`${result.frequency_hz.toFixed(3)} Hz · ${result.axis.toUpperCase()} · ORIGINAL DISPLACEMENT`;
  $('fieldSummary').textContent=`${result.accepted_nodes}/${result.nodes.length} accepted amplitude fits · ${result.phase_nodes} usable relative phases · ${result.grid.step} analysis px grid spacing · ${result.reference.label} · ${(result.interpolated_support_fraction*100).toFixed(1)}% image support for interpolated warping. ${result.timing_basis}.`;
  notes('fieldWarnings',result.warnings);$('responseView').value='amplitude';updateResponseHelp();drawVideos();status('Spatial response ready. Inspect the amplitude and phase views, or choose Modal animation and press Animate.');
});
async function refreshModal(){
  if(!spatialField||spatialField.reference.phase_deg===null||$('responseView').value!=='modal')return;
  const e=epoch,key=spatialField.key,requestId=++modalRequest;
  const url=`/api/frame/${clip.id}/0?view=modal&key=${key}&phase=${$('modalPhase').value}&gain=${$('modalGain').value}&threshold=${sensitivityThreshold()}`;
  const bitmap=await getImage(url);
  if(e!==epoch||key!==spatialField?.key||requestId!==modalRequest){bitmap.close();return;}
  modalImage?.close();modalImage=bitmap;drawVideos();
}
function requestModal(){clearTimeout(modalTimer);modalTimer=setTimeout(()=>refreshModal().catch(showError),45);}
$('modalPhase').oninput=()=>{pauseModal();$('modalPhaseLabel').textContent=Math.round(Number($('modalPhase').value))+'°';drawVideos();requestModal();};
$('modalGain').oninput=()=>{$('modalGainValue').textContent=$('modalGain').value+'×';updateExportLinks();drawVideos();requestModal();};
$('modalPlay').onclick=()=>{
  if(modalPlaying){pauseModal();return;}
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
