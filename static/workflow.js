'use strict';
let draftSerial=0,savedSerial=0,saveTimer=null,syncChain=Promise.resolve(),forceInvalidate=false;
let loaded=false,needsUpdate=false,editingTiming=false;
function fieldError(message,field){return Object.assign(new Error(message),{field});}
function finiteInput(id,label){const text=$(id).value.trim(),value=Number(text);if(!text||!Number.isFinite(value))throw fieldError(`${label} must be a finite number.`,id);return value;}
function readSettings(){
  const frequency=finiteInput('frequency','Target frequency'),bandwidth=finiteInput('bandwidth','Bandwidth'),gain=finiteInput('gain','Magnification gain');
  if(frequency<=0)throw fieldError('Target frequency must be above zero.','frequency');
  if(bandwidth<=0)throw fieldError('Bandwidth must be above zero.','bandwidth');
  if(gain<0||gain>20)throw fieldError('Added magnification gain must be between 0 and 20.','gain');
  const calibration=$('calibration').value.trim()===''?null:finiteInput('calibration','Calibration');
  if(calibration!==null&&calibration<=0)throw fieldError('Calibration must be positive or blank.','calibration');
  const spectrum_highpass_hz=$('spectrumHighpass').checked?finiteInput('highpassCutoff','PSD high-pass cutoff'):0;
  if($('spectrumHighpass').checked&&!(spectrum_highpass_hz>=2*clip.metadata.resolution_hz&&spectrum_highpass_hz<clip.metadata.nyquist))throw fieldError(`PSD cutoff must be at least ${(2*clip.metadata.resolution_hz).toFixed(3)} Hz and below ${clip.metadata.nyquist.toFixed(3)} Hz.`,'highpassCutoff');
  return {frequency,bandwidth,linked:$('linkedBand').checked,low:finiteInput('low','Band low edge'),high:finiteInput('high','Band high edge'),gain,
    axis:$('axis').value,points,roi,reference:$('fieldReference').value,reference_last:$('cameraReference').checked,calibration,spectrum_highpass_hz,spectrum_source:psdSource,spectrum_point:psdPoint,spectrum_region:psdRegion};
}
function readDisplay(){return {view:$('responseView').value,sensitivity:Number($('sensitivity').value),modal_gain:Number($('modalGain').value),phase:Number($('modalPhase').value),frame,timing_mode:$('timingMode').value,timing_confirmed:timingConfirmed};}
function applySettings(settings,ui){
  for(const id of ['frequency','bandwidth','low','high','gain','axis'])$(id).value=settings[id];
  $('linkedBand').checked=settings.linked;$('calibration').value=settings.calibration??'';$('cameraReference').checked=settings.reference_last;$('fieldReference').value=settings.reference;
  $('spectrumHighpass').checked=(settings.spectrum_highpass_hz||0)>0;$('highpassCutoff').value=settings.spectrum_highpass_hz||5;
  points=settings.points.map(p=>[...p]);roi=settings.roi?.slice()||null;psdSource=settings.spectrum_source||'auto';psdPoint=settings.spectrum_point?.slice()||null;psdRegion=settings.spectrum_region?.slice()||null;psdDraftRegion=null;psdSampling=null;psdSamplingIdentity=null;
  $('responseView').value=ui.view;$('sensitivity').value=ui.sensitivity;$('modalGain').value=ui.modal_gain;$('modalPhase').value=ui.phase;
  $('modalPhaseLabel').textContent=Math.round(ui.phase)+'°';$('modalGainValue').textContent=ui.modal_gain+'×';
  $('timingMode').value=ui.timing_mode;timingConfirmed=ui.timing_confirmed;
  $('captureFps').value=clip.metadata.timing_basis.includes('user-assumed')?clip.metadata.fps:'';$('sampleTiming').checked=clip.metadata.timing_basis.includes('user-assumed');
  frame=ui.frame||0;cursor=[Math.round(clip.metadata.width/2),Math.round(clip.metadata.height/2)];$('pointX').value=cursor[0];$('pointY').value=cursor[1];syncRoiInputs();
}
function syncRoiInputs(){
  if(!clip)return;const box=roi||[0,0,clip.metadata.width,clip.metadata.height];
  for(const [i,id] of ['roiX','roiY','roiWidth','roiHeight'].entries())$(id).value=box[i];
  $('pointSummary').textContent=points.length?points.map((p,i)=>`P${i+1}: (${p[0]}, ${p[1]})`).join(' · '):'No manual points. Automatic spatial sampling is available.';
}
function clearResultsLocal(){
  if(spectrumIdentity!==currentSpectrumIdentity()){displacementSpectrum=null;spectrumIdentity=null;psdSampling=null;psdSamplingIdentity=null;}
  pause();frameRequest++;analysis=null;analysisKey=null;renderKey=null;renderInfo=null;responsePixels=null;heatLayer=null;maskLayer=null;
  amplifiedImage?.close();amplifiedImage=null;invalidateField();$('results').replaceChildren();$('phaseLabel').textContent='NEEDS ANALYSIS';$('traceHelp').textContent='';notes('renderWarnings',[]);clearVideoDownload();drawVideos();drawSpectrum();drawTrace();
}
function settingsChanged({compute=true}={}){
  if(!clip)return;draftSerial++;dirty=true;clearError();
  if(compute){needsUpdate=true;forceInvalidate=true;clearResultsLocal();status('Settings changed. Analyze response to update the results.');}
  syncRoiInputs();updateUI();scheduleSave();
}
function saveDisplay(){if(!clip||!loaded)return;draftSerial++;dirty=true;scheduleSave();}
function scheduleSave(){clearTimeout(saveTimer);saveTimer=setTimeout(()=>flushSettings().catch(showError),180);}
function flushSettings(){
  clearTimeout(saveTimer);
  syncChain=syncChain.catch(()=>{}).then(async()=>{
    if(!clip||savedSerial===draftSerial&&!forceInvalidate)return;
    const serial=draftSerial,id=clip.id,settings=readSettings(),ui=readDisplay(),invalidate=forceInvalidate;
    const result=await api('/api/settings',{id,revision,settings,ui,invalidate});
    if(clip?.id!==id)return;revision=result.revision;savedSerial=serial;dirty=draftSerial!==serial;if(!dirty)forceInvalidate=false;if(!dirty&&psdSamplingIdentity!==currentSpectrumIdentity())await refreshSampling();updateUI();
  });
  return syncChain;
}
function targetChanged(){
  if($('linkedBand').checked){const f=Number($('frequency').value),width=Number($('bandwidth').value);$('low').value=Number((f-width/2).toFixed(6));$('high').value=Number((f+width/2).toFixed(6));}
  settingsChanged();
}
function showTimebase(){
  if(!clip)return;const m=clip.metadata,assumed=m.timing_basis.includes('user-assumed');
  $('timebaseSummary').textContent=`${m.encoded_fps.toFixed(3)} encoded fps · ${m.fps.toFixed(3)} analysis fps · usable frequencies below ${m.nyquist.toFixed(2)} Hz.`;
  $('timebaseLabel').textContent=timingConfirmed?(assumed?'Capture rate assumed; frame mapping unverified. Playback speed is unchanged.':'Using encoded video time. Physical Hz requires verified capture timing.'):'Confirm encoded timing or enter the original capture rate before analysis.';
  $('captureControls').hidden=$('timingMode').value!=='capture';$('timingInputs').hidden=timingConfirmed&&!editingTiming;$('editTiming').hidden=!timingConfirmed;$('editTiming').textContent=editingTiming?'Done':'Change';
  document.querySelector('.timing-panel').classList.toggle('compact',timingConfirmed&&!editingTiming);
  $('setTimebase').textContent=timingConfirmed?'Timing confirmed':'Confirm timing';
}
function updateExports(){
  const ready=!!clip&&!busy&&!dirty,band=ready&&!!renderKey&&!!responsePixels,field=ready&&!!spatialField;
  const available={heatmap:band,isolated:band,modal:field&&spatialField.reference.phase_deg!==null,analysis:ready&&!!(analysis||spatialField||displacementSpectrum),samples:field,traces:ready&&!!analysis};
  for(const option of $('exportKind').options)option.disabled=!available[option.value];
  $('exportKind').disabled=busy||!Object.values(available).some(Boolean);$('exportResponse').disabled=!available[$('exportKind').value];
  $('exportHelp').textContent=renderInfo||spatialField?`Exports capture the applied frequency, timing, sensitivity and display gain. Animation contains four slowed cycles.`:displacementSpectrum?'PSD is available in Analysis JSON. Analyze the response to enable video exports.':'Analyze response to enable exports. No download will replace this workspace.';
}
function updateUI(){
  showTimebase();syncRoiInputs();$('targetHelp').textContent=$('linkedBand').checked?'Band follows target ± half the bandwidth.':'Independent band; target sets the displacement fit.';$('low').readOnly=$('linkedBand').checked;$('high').readOnly=$('linkedBand').checked;$('bandwidth').disabled=busy||!$('linkedBand').checked;
  $('processResponse').disabled=busy||!clip||!timingConfirmed;$('setTimebase').disabled=busy||!clip||!$('timingMode').value||timingConfirmed;
  $('measureSpectrum').disabled=busy||!clip||!timingConfirmed;$('measureSpectrum').textContent=displacementSpectrum?'Refresh PSD':$('spectrumHighpass').checked?'Apply PSD':'Measure PSD';
  $('spectrumHighpass').disabled=busy||!clip||!timingConfirmed;$('highpassCutoff').disabled=busy||!$('spectrumHighpass').checked;
  if(clip){$('highpassCutoff').min=2*clip.metadata.resolution_hz;$('highpassCutoff').max=clip.metadata.nyquist;}
  $('play').disabled=busy||!clip;$('modalPlay').disabled=busy||!spatialField||spatialField.reference.phase_deg===null;
  const complete=!!renderKey&&!!spatialField;
  $('resultState').textContent=busy?'Working…':needsUpdate?'Needs update':complete?'Ready':renderKey?'Partial result':'Not analyzed';
  $('resultState').className='state-pill '+(complete&&!dirty?'ready':'pending');
  if(renderInfo||spatialField){$('appliedSummary').textContent=`Applied: ${spatialField?spatialField.frequency_hz.toFixed(3)+' Hz '+spatialField.axis.toUpperCase()+' · ':''}${renderInfo?renderInfo.low.toFixed(3)+'–'+renderInfo.high.toFixed(3)+' Hz band · gain '+renderInfo.gain:''}`;}
  else $('appliedSummary').textContent=timingConfirmed?'Choose the target and analyze. No manual points required.':'Confirm timing, then analyze. No manual points required.';
  if(clip){$('bandHelp').textContent=`Resolution ${clip.metadata.resolution_hz.toFixed(3)} Hz. Band must be wider than one bin and below ${clip.metadata.nyquist.toFixed(2)} Hz; at least two cycles at its low edge.`;}
  for(const button of document.querySelectorAll('[data-view]')){const view=button.dataset.view;button.disabled=busy||!clip||(fieldViews.has(view)?!spatialField:!renderKey);}
  updateResponseHelp();drawSpectrum();updateSamplingControls();
}
async function installInBrowser(data,{restored=false}={}){
  loaded=false;clearTimeout(saveTimer);await syncChain.catch(()=>{});pause();epoch++;frameRequest++;
  originalImage?.close();amplifiedImage?.close();originalImage=null;amplifiedImage=null;clip=data.clip||{id:data.id,metadata:data.metadata};revision=data.revision;
  draftSerial=0;savedSerial=0;forceInvalidate=false;dirty=false;needsUpdate=false;editingTiming=false;resetResponse();applySettings(data.settings,data.ui);
  $('workspace').hidden=false;$('intro').hidden=true;$('clipName').textContent=clip.metadata.name;
  const m=clip.metadata;$('clipMeta').textContent=`${m.source_width}×${m.source_height} source · ${m.frames} frames · ${(m.frames/m.encoded_fps).toFixed(2)} playback s`;
  $('scrub').max=m.frames-1;for(const id of ['original','amplified']){$(id).width=m.width;$(id).height=m.height;}
  mode='inspect';$('pointMode').setAttribute('aria-pressed','false');$('roiMode').setAttribute('aria-pressed','false');$('original').classList.remove('editing');
  analysis=data.analysis||null;analysisKey=data.analysis_key||null;renderKey=data.render_key||null;
  displacementSpectrum=timingConfirmed?(data.spectrum||null):null;spectrumIdentity=displacementSpectrum?currentSpectrumIdentity():null;
  if(data.sampling||displacementSpectrum?.sampling)installSampling(data.sampling||displacementSpectrum.sampling);else await refreshSampling();
  if(data.render_info&&renderKey)await loadResponse({...data.render_info,key:renderKey});
  if(data.field&&data.field_key){spatialField={...data.field,key:data.field_key};referenceImage=await getImage(frameUrl('original',0));showFieldSummary();}
  notes('inputWarnings',m.warnings);notes('renderWarnings',data.render_info?.warnings||[]);drawResults();drawSpectrum();drawTrace();
  await showFrame(frame);loaded=true;updateUI();if($('responseView').value==='modal'&&spatialField)await refreshModal();
  status(restored?'Active session recovered. Settings and available results are restored.':'Video ready. Confirm timing, choose your target, and analyze the response.');
}
async function confirmTiming(){
  if(!clip)throw new Error('Open a recording first.');
  const mode=$('timingMode').value;if(!mode)throw fieldError('Choose encoded timing or the original capture rate.','timingMode');
  const fps=mode==='capture'?finiteInput('captureFps','Capture rate'):null;
  if(fps!==null&&(fps<1||fps>2000))throw fieldError('Capture rate must be between 1 and 2000 fps.','captureFps');
  if(mode==='capture'&&!$('sampleTiming').checked)throw fieldError('Confirm one encoded frame per captured sample before using the capture rate.','sampleTiming');
  await flushSettings();const result=await api('/api/timebase',{id:clip.id,revision,capture_fps:fps,one_frame_per_sample:$('sampleTiming').checked});
  clip.metadata=result.metadata;revision=result.revision;timingConfirmed=true;editingTiming=false;needsUpdate=true;
  $('spectrumHighpass').checked=result.spectrum_highpass_hz>0;if(result.spectrum_highpass_hz>0)$('highpassCutoff').value=result.spectrum_highpass_hz;
  clearResultsLocal();draftSerial++;dirty=true;await flushSettings();
  $('clipMeta').textContent=`${clip.metadata.source_width}×${clip.metadata.source_height} source · ${clip.metadata.frames} frames · ${(clip.metadata.frames/clip.metadata.encoded_fps).toFixed(2)} playback s`;
  status('Timing confirmed. Your target frequency is unchanged; analyze to compute the response.');updateUI();
  status('Measuring the original displacement PSD…');await runSpectrum();status('PSD ready. Click a peak or enter your target, then analyze the response.');
}
function validateAnalysis(){
  if(!clip)throw new Error('Open a recording first.');if(!timingConfirmed)throw fieldError('Confirm the analysis timing first.','timingMode');
  const s=readSettings(),m=clip.metadata;
  if(s.frequency>=m.nyquist)throw fieldError(`Target ${s.frequency} Hz is outside the current range. Confirm the original capture rate, or choose a target below ${m.nyquist.toFixed(2)} Hz.`,'frequency');
  if(!(0<s.low&&s.low<s.high&&s.high<m.nyquist))throw fieldError(`Band must be above zero and below ${m.nyquist.toFixed(2)} Hz. Adjust bandwidth or capture timing.`,$('linkedBand').checked?'bandwidth':'high');
  if(s.high-s.low<m.resolution_hz)throw fieldError(`Bandwidth must be at least ${m.resolution_hz.toFixed(3)} Hz for this clip.`,'bandwidth');
  if(s.low<2*m.resolution_hz)throw fieldError('The recording must contain at least two cycles at the low band edge.','frequency');
  if(s.reference_last&&points.length<2)throw fieldError('Camera subtraction requires at least two points, with the last on stationary structure.','cameraReference');
  if(s.reference==='p1'&&!points.length)throw fieldError('Select P1 under Advanced, or use an automatic phase reference.','fieldReference');
}
async function stopAtBoundary(){
  if(!stopRequested)return false;needsUpdate=true;clearResultsLocal();forceInvalidate=true;draftSerial++;dirty=true;await flushSettings();status('Analysis stopped. Partial results were cleared. Analyze again when ready.');return true;
}
async function analyzeWorkflow(){
  validateAnalysis();await flushSettings();stopRequested=false;$('cancelProcessing').hidden=false;$('cancelProcessing').disabled=false;
  if(!displacementSpectrum){status('Measuring the original displacement PSD…');await runSpectrum();if(await stopAtBoundary())return;}
  status('1 of 3 · Filtering the band and preparing response views…');await runRender();if(await stopAtBoundary())return;
  if(points.length){status('2 of 3 · Fitting selected original points…');await runAnalysis();if(await stopAtBoundary())return;}
  status('3 of 3 · Measuring local displacement and phase…');await runField();if(await stopAtBoundary())return;
  if(!fieldViews.has($('responseView').value))$('responseView').value='heatmap';
  needsUpdate=false;draftSerial++;dirty=true;await flushSettings();
  status(spatialField.accepted_nodes?`Response ready at ${spatialField.frequency_hz.toFixed(3)} Hz. Explore the views or export a result.`:'Band views ready. No patches passed displacement fitting; inspect texture and tracking under Advanced.');updateUI();
}
$('processResponse').onclick=()=>task('Preparing response analysis…',analyzeWorkflow);
async function applySpectrum(){await runSpectrum();status(displacementSpectrum.highpass?.enabled?`PSD high-pass applied at ${displacementSpectrum.highpass.cutoff_hz} Hz. Response fits and videos are unchanged.`:'Original PSD ready. Click a peak or enter your target, then analyze the response.');}
$('measureSpectrum').onclick=()=>task('Updating the displacement PSD…',applySpectrum);
function spectrumFilterChanged(){if(!clip)return;displacementSpectrum=null;spectrumIdentity=null;clearVideoDownload();settingsChanged({compute:false});status('PSD filter changed. Apply PSD to update the spectrum.');}
$('spectrumHighpass').onchange=()=>{spectrumFilterChanged();if(timingConfirmed)task('Updating the displacement PSD…',applySpectrum);};
$('highpassCutoff').oninput=spectrumFilterChanged;
$('cancelProcessing').onclick=()=>{stopRequested=true;$('cancelProcessing').disabled=true;status('Stopping after the current calculation finishes…');};
$('editTiming').onclick=()=>{editingTiming=!editingTiming;showTimebase();};
$('setTimebase').onclick=()=>task('Confirming the analysis timing…',confirmTiming);
for(const id of ['timingMode','captureFps','sampleTiming'])$(id).addEventListener(id==='captureFps'?'input':'change',()=>{timingConfirmed=false;settingsChanged();showTimebase();});
for(const id of ['frequency','bandwidth'])$(id).oninput=targetChanged;
$('linkedBand').onchange=targetChanged;
for(const id of ['low','high','gain'])$(id).oninput=()=>settingsChanged();
for(const id of ['axis','cameraReference','fieldReference'])$(id).onchange=()=>settingsChanged();
$('calibration').oninput=()=>{settingsChanged({compute:false});drawResults();showFieldSummary();updateResponseHelp();drawVideos();};
$('applyRoi').onclick=()=>{try{const box=['roiX','roiY','roiWidth','roiHeight'].map(id=>finiteInput(id,'ROI'));if(box[0]<0||box[1]<0||box[2]<8||box[3]<8||box[0]+box[2]>clip.metadata.width||box[1]+box[3]>clip.metadata.height)throw new Error('ROI must lie inside the image and be at least 8 by 8 analysis pixels.');roi=box;settingsChanged();}catch(e){showError(e);}};
for(const [id,kind] of [['cleanDemo','clean'],['dropoutDemo','dropout'],['reloadDemo','clean'],['reloadDropout','dropout']])$(id).onclick=()=>task('Loading the known-motion demo…',async()=>{await flushSettings().catch(()=>{});await installInBrowser(await api('/api/demo',{kind}));await analyzeWorkflow();});
$('videoFile').onchange=()=>{const file=$('videoFile').files[0];$('videoFile').value='';if(!file)return;task('Decoding the recording and checking frame timing…',async()=>{await flushSettings().catch(()=>{});const form=new FormData();form.append('video',file);await installInBrowser(await api('/api/load',form,true));});};
$('exportKind').onchange=updateExports;
$('exportResponse').onclick=()=>task('Preparing your export…',async()=>{
  clearVideoDownload();await flushSettings();const kind=$('exportKind').value;let result;
  if(['heatmap','isolated','modal'].includes(kind)){result=await api('/api/export-video?prepare=1',{id:clip.id,revision,view:kind,key:kind==='modal'?spatialField?.key:renderKey,sensitivity:Number($('sensitivity').value),modal_gain:Number($('modalGain').value),phase_start:Number($('modalPhase').value)});}
  else result=await api('/api/export-data',{id:clip.id,revision,kind});
  const link=$('videoDownload');link.href=result.url;link.download=result.filename;link.textContent=`Save ${result.filename}`;link.hidden=false;link.click();status('Export ready. Use the Save link if your browser does not start the download.');
});
window.addEventListener('pagehide',()=>{if(!clip||!loaded)return;try{fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:clip.id,revision,settings:readSettings(),ui:readDisplay(),invalidate:forceInvalidate}),keepalive:true}).catch(()=>{});}catch{}});
async function boot(){try{const response=await fetch('/api/session'),data=await response.json();if(!response.ok)throw new Error(data.error);if(data.clip){await installInBrowser(data,{restored:true});if(timingConfirmed&&!displacementSpectrum)await task('Measuring the original displacement PSD…',async()=>{await runSpectrum();status('PSD ready. Click a peak or enter your target, then analyze the response.');});}else{updateUI();drawSpectrum();drawTrace();}}catch(e){showError(e);}}
boot();
