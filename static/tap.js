'use strict';
let tapData=null,tapImage=null,tapPlaying=false,tapTimer=null,tapRequest=0,tapFrameRequest=0,tapPlaySerial=0;
let tapSelection={tap_node:null,probe_a:null,probe_b:null};
let tapAutoPlay=false;
function pauseTap(){tapPlaying=false;tapPlaySerial++;$('tapPlay').textContent=Number($('tapTime').value)>0?'▶ Resume':plateMotion==='mode'?'▶ Animate':'▶ Tap';}
function resetTap(){
  tapAutoPlay=false;
  pauseTap();clearTimeout(tapTimer);tapRequest++;tapFrameRequest++;tapData=null;tapImage?.close();tapImage=null;
  tapSelection={tap_node:null,probe_a:null,probe_b:null};$('tapTime').value='0';
  for(const id of ['tapNode','tapProbeA','tapProbeB'])$(id).replaceChildren(new Option('Choose a usable sample…',''));
  $('tapSummary').textContent='Choose Virtual tap after analyzing the response.';
  $('tapModelSummary').textContent='A one-mode approximation will be built from the selected original displacement response.';notes('tapAssumptions',[]);drawTapTrace();
}
function readTapSettings(){return {...tapSelection,...readPlateSettings(),damping_percent:finiteInput('tapDamping','Damping'),strength:finiteInput('tapStrength','Tap strength'),direction:Number($('tapDirection').value),cycles:finiteInput('tapCycles','Simulation cycles'),display_cps:finiteInput('tapDisplayCps','Display cycles per second'),cursor_cycle:Number($('tapTime').value)};}
function applyTapDisplay(ui={}){
  applyPlateDisplay(ui);
  for(const [id,key,fallback] of [['tapDamping','damping_percent',1],['tapStrength','strength',1],['tapDirection','direction',1],['tapCycles','cycles',40],['tapDisplayCps','display_cps',2],['tapTime','cursor_cycle',0]])$(id).value=ui[key]??fallback;
  $('tapTime').max=ui.cycles??40;tapSelection={tap_node:ui.tap_node??null,probe_a:ui.probe_a??null,probe_b:ui.probe_b??null};pauseTap();updateTapLabels();
}
function updateTapLabels(){
  if(!tapPlaying){const cycle=Number($('tapTime').value);$('tapPlay').textContent=cycle>=Number($('tapCycles').value)?'↻ Replay':cycle>0?'▶ Resume':plateMotion==='mode'?'▶ Animate':'▶ Tap';}
  $('tapDampingValue').textContent=Number($('tapDamping').value).toFixed(1)+'%';$('tapStrengthValue').textContent=Number($('tapStrength').value).toFixed(1)+'×';
  const f=tapData?.clock_hz||tapData?.model.frequency_hz||spatialField?.frequency_hz||Number($('frequency').value);
  $('tapTimeLabel').textContent=(Number($('tapTime').value)/f).toFixed(4)+' simulation s';
  $('tapTiming').textContent=Number.isFinite(f)?`${f.toFixed(3)} Hz ${['plate','string'].includes(tapData?.model.kind)?'predicted':'assumed'} · ${(tapData?.playback_slowdown||f/Number($('tapDisplayCps').value)).toFixed(1)}× slower playback`:'';
}
function populateTapSelectors(){
  for(const [id,key] of [['tapNode','tap_node'],['tapProbeA','probe_a'],['tapProbeB','probe_b']]){
    $(id).replaceChildren(...tapData.model.nodes.filter(n=>n.shape!==null).map(n=>new Option(n.label?`${n.label}${key==='tap_node'?' · u='+n.u.toFixed(3):''}`:`${tapData.model.sample_label||'Grid'} ${n.index+1} (${n.x.toFixed(0)}, ${n.y.toFixed(0)})`,String(n.index))));$(id).value=tapSelection[key];
  }
}
async function prepareTap(){
  if(!spatialField||$('responseView').value!=='tap')return;
  if($('tapModelSource').value==='plate'&&!plateConfig.corners){$('tapSummary').textContent='Set four plate corners under Advanced, then apply geometry to generate predicted modes.';return;}
  if($('tapModelSource').value==='string'&&!hasStringGeometry()){$('tapSummary').textContent='Mark one or more visible string segments under Advanced, then apply their assumptions.';return;}
  const serial=++tapRequest,e=epoch,key=spatialField.key;
  await flushSettings();
  const data=await api('/api/tap',{id:clip.id,revision,key,tap:readTapSettings()});
  if(serial!==tapRequest||e!==epoch||key!==spatialField?.key||$('responseView').value!=='tap')return;
  tapData=data;tapSelection={tap_node:data.settings.tap_node,probe_a:data.settings.probe_a,probe_b:data.settings.probe_b};
  installPlateModel(data);
  $('tapTime').max=data.settings.cycles;$('tapTime').value=data.settings.cursor_cycle;populateTapSelectors();updateTapLabels();
  const m=data.model,c=data.settings;
  if(m.strings){
    const solo=m.modes[c.solo_mode],activeStrings=new Set(c.active_modes.map(i=>m.modes[i].string_index));
    $('tapSummary').textContent=c.motion==='mode'?`Animating ${solo.string_name}, harmonic ${solo.harmonic}, at ${c.clock_hz.toFixed(2)} Hz.`:`Simultaneous relative plucks on ${activeStrings.size} string${activeStrings.size===1?'':'s'} at u=${c.tap_fraction.toFixed(3)} · ${c.active_modes.length} harmonics · one physical clock. A/B probes can be on different strings.`;
    $('tapModelSummary').textContent=m.strings.map(s=>`${s.name}: ${s.frequency_hz.toFixed(2)} Hz anchor; ${s.reference_amplitude_source_px.toPrecision(3)} source px (${s.amplitude_basis}); ${s.fit_samples} patches; shape correlation ${s.fit_mac===null?'unavailable':s.fit_mac.toFixed(3)}.`).join(' ')+ ' Independent strings; chosen total mass 1 per string, modal mass 0.5. Shared pluck fraction and assumed damping; no bridge/body coupling or force calibration.';
  }else if(m.kind==='string'){
    $('tapSummary').textContent=c.motion==='mode'?`Animating string M${c.solo_mode+1} at ${c.clock_hz.toFixed(2)} Hz. The video ribbon follows this predicted standing wave.`:`Combined string tap at point ${c.tap_node+1} · ${c.active_modes.map(i=>m.modes[i].frequency_hz.toFixed(1)+' Hz').join(' + ')}. Local nodes suppress participation in the corresponding harmonic.`;
    $('tapModelSummary').textContent=`Fixed-end uniform string · assumed anchor harmonic ${m.anchor_mode+1} · visible fractions ${m.string.span_start}–${m.string.span_end} · B=${m.string.inharmonicity}. Antinode scale ${m.reference_amplitude_source_px.toPrecision(3)} source px (${m.amplitude_basis}). ${m.fit_samples} accepted original patches; complex shape correlation ${m.fit_mac===null?'unavailable':m.fit_mac.toFixed(3)} is descriptive, not confidence. Modal mass = 0.5 with chosen total mass 1. The guitar body and neighboring strings are omitted.`;
  }else if(m.kind==='plate'){
    $('tapSummary').textContent=c.motion==='mode'?`Animating predicted M${c.solo_mode+1} at ${c.clock_hz.toFixed(2)} Hz. Continuous motion; tap location and damping do not apply.`:`Combined tap at Grid ${c.tap_node+1} · ${c.active_modes.map(i=>'M'+(i+1)+' '+m.modes[i].frequency_hz.toFixed(1)+' Hz').join(' + ')}. Each mode responds according to its shape at the tap. Slowest envelope reaches 10% in ${data.seconds_to_ten_percent.toFixed(3)} simulation s.`;
    $('tapModelSummary').textContent=`Flat thin-plate Ritz model · ${m.plate.mounting} · assumed span/root chord ${m.plate.aspect_ratio}, tip/root chord ${m.plate.taper_ratio??1}, tip leading-edge offset/root chord ${m.plate.sweep_offset??0}. M${m.anchor_mode+1}: visible MAC ${m.fit_mac.toFixed(3)} at ${m.fit_samples} patches. ${(100*m.standing_phase_fraction).toFixed(1)}% standing projection; ${(100*m.interpolated_support_fraction).toFixed(1)}% image coverage is model-predicted. Ritz order ${m.basis_order}; frequency ratios changed up to ${m.max_basis_change_percent.toFixed(2)}% with refinement. Chosen total mass 1; uniform isotropic plate, no spars, ribs, composites, fuel, pretwist or aeroelasticity.`;
  }else{
    $('tapSummary').textContent=`Tap: Grid ${c.tap_node+1} · signed participation ${c.participation.toFixed(3)} · envelope reaches 10% in ${data.seconds_to_ten_percent.toFixed(3)} simulation s. ${Math.abs(c.participation)<.05?'This location couples weakly to the retained shape. ':''}Changing location changes participation, not bending shape.`;
    $('tapModelSummary').textContent=`Standing projection retains ${(100*m.standing_phase_fraction).toFixed(1)}% of selected-axis complex-response energy; descriptive, not mode confidence. ${(100*m.interpolated_support_fraction).toFixed(1)}% image warp support. Normalized M = 1, C = ${data.normalized_matrices.C[0][0].toPrecision(5)}, K = ${data.normalized_matrices.K[0][0].toPrecision(6)}. ${m.standing_phase_fraction<.8?'Substantial quadrature motion is omitted by this one-standing-mode approximation.':''}`;
  }
  notes('tapAssumptions',m.assumptions);await refreshTapFrame();drawTapTrace();saveDisplay();updateUI();
  status(['plate','string'].includes(m.kind)?`Predicted ${c.motion==='mode'?'mode animation':'combined tap'} ready. Geometry and mounting assumptions are under Advanced.`:`Virtual tap ready at ${m.frequency_hz.toFixed(3)} Hz. Damping and impulse strength are assumed.`);
  if(tapAutoPlay){tapAutoPlay=false;await $('tapPlay').onclick();}
}
async function refreshTapFrame(){
  if(!tapData||$('responseView').value!=='tap')return;
  const data=tapData,seq=++tapFrameRequest,e=epoch,time=Number($('tapTime').value)/(data.clock_hz||data.model.frequency_hz);
  const params=new URLSearchParams({view:'tap',key:data.key,revision,time,gain:$('modalGain').value});
  params.set('tap',JSON.stringify(data.settings));params.set('model_key',data.model.key);
  const bitmap=await getImage(`/api/frame/${clip.id}/0?${params}`);
  if(seq!==tapFrameRequest||e!==epoch||tapData!==data||$('responseView').value!=='tap'){bitmap.close();return;}
  tapImage?.close();tapImage=bitmap;drawVideos();drawTapTrace();updateTapLabels();
}
function scheduleTap(autoPlay=false){
  tapAutoPlay=autoPlay===true;
  pauseTap();clearVideoDownload();clearTimeout(tapTimer);tapRequest++;tapFrameRequest++;tapData=null;tapImage?.close();tapImage=null;$('tapTime').value=0;
  updateTapLabels();$('tapSummary').textContent='Updating the assumed model…';drawTapTrace();drawVideos();saveDisplay();updateExports();
  updatePlateControls();if($('responseView').value==='tap')tapTimer=setTimeout(()=>prepareTap().catch(showError),180);
}
for(const id of ['tapDamping','tapStrength','tapCycles','tapDisplayCps'])$(id).addEventListener('input',scheduleTap);
$('tapDirection').onchange=scheduleTap;
for(const [id,key] of [['tapNode','tap_node'],['tapProbeA','probe_a'],['tapProbeB','probe_b']])$(id).onchange=()=>{tapSelection[key]=$(id).value===''?null:Number($(id).value);if(key==='tap_node'){tapSelection.probe_a=tapSelection.tap_node;if(tapSelection.probe_b===tapSelection.probe_a)tapSelection.probe_b=null;}scheduleTap();};
$('tapTime').oninput=()=>{pauseTap();updateTapLabels();refreshTapFrame().catch(showError);saveDisplay();};
$('tapReset').onclick=()=>{pauseTap();$('tapTime').value=0;updateTapLabels();refreshTapFrame().catch(showError);saveDisplay();status('Virtual tap reset. Press Tap to run the assumed model.');};
$('tapPlay').onclick=async()=>{
  if(tapPlaying){pauseTap();saveDisplay();status('Virtual tap paused.');return;}
  if(!tapData)await task('Preparing the assumed virtual tap model…',prepareTap);
  if(!tapData)return;
  pause();const data=tapData;if(Number($('tapTime').value)>=data.settings.cycles)$('tapTime').value=0;
  tapPlaying=true;const serial=++tapPlaySerial,initial=Number($('tapTime').value),start=performance.now();let last=0,fetching=false;
  $('tapPlay').textContent='Ⅱ Pause';status(['plate','string'].includes(data.model.kind)&&data.settings.motion==='mode'?'Predicted mode animation running. The video texture and point traces share the same motion.':'Virtual tap running. Point traces show simulated source-pixel motion.');
  async function tick(now){
    if(!tapPlaying||serial!==tapPlaySerial)return;
    if(!fetching&&now-last>70){last=now;fetching=true;$('tapTime').value=Math.min(data.settings.cycles,initial+(now-start)/1000*(data.settings.effective_display_cps||data.settings.display_cps));
      try{await refreshTapFrame();}catch(e){pauseTap();showError(e);}finally{fetching=false;}
      if(Number($('tapTime').value)>=data.settings.cycles){pauseTap();$('tapPlay').textContent='↻ Replay';saveDisplay();status(['plate','string'].includes(data.model.kind)&&data.settings.motion==='mode'?'Mode animation finished. Replay or animate another predicted mode.':'Virtual tap finished. Replay or adjust the assumed damping and strength.');return;}}
    if(tapPlaying&&serial===tapPlaySerial)requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
};
function drawTap(ctx,c){
  if(tapImage)ctx.drawImage(tapImage,0,0,c.width,c.height);
  else{if(referenceImage)ctx.drawImage(referenceImage,0,0,c.width,c.height);centeredMessage(ctx,c,tapData?'Preparing virtual tap frame…':'Preparing assumed virtual tap model…');}
  return true;
}
function drawTapTrace(){
  const c=$('tapTrace');c.width=Math.max(280,Math.round(c.clientWidth||1100));
  const {ctx,W,H,L,R,T,B,xw,yh}=plotBase(c,'Simulation time / s','Simulated source px');
  if(!tapData)return;
  const data=tapData,duration=data.duration_s;
  const peak=data.traces.reduce((p,tr)=>tr.displacement_source_px.reduce((a,v)=>Math.max(a,Math.abs(v)),p),1e-6)*1.1;
  const x=t=>L+t/duration*xw,y=v=>T+yh/2-v/(2*peak)*yh;
  for(const v of [-peak,0,peak]){ctx.fillStyle=plotColor('--plot-label');ctx.fillText(v.toPrecision(2),3,y(v)+3);ctx.strokeStyle=plotColor('--plot-grid');ctx.beginPath();ctx.moveTo(L,y(v));ctx.lineTo(W-R,y(v));ctx.stroke();}
  for(let i=0;i<=4;i++){ctx.fillStyle=plotColor('--plot-label');ctx.fillText((i*duration/4).toFixed(3),x(i*duration/4)-15,H-B+17);}
  data.traces.forEach((trace,j)=>{ctx.strokeStyle=j?'#ffc986':'#36cfee';ctx.lineWidth=1.5;ctx.beginPath();trace.displacement_source_px.forEach((v,i)=>{i?ctx.lineTo(x(data.time_s[i]),y(v)):ctx.moveTo(x(data.time_s[i]),y(v));});ctx.stroke();});
  ctx.strokeStyle='#e9f0f3';ctx.beginPath();ctx.moveTo(x(Number($('tapTime').value)/(data.clock_hz||data.model.frequency_hz)),T);ctx.lineTo(x(Number($('tapTime').value)/(data.clock_hz||data.model.frequency_hz)),H-B);ctx.stroke();
}
const originalResponseClick=$('amplified').onclick;
$('amplified').onclick=e=>{
  if($('responseView').value!=='tap'){originalResponseClick(e);return;}
  if(!tapData||busy)return;
  if(plateMotion==='mode'&&['plate','string'].includes(tapData.model.kind)){status('Choose Combined tap to change the excitation location.');return;}
  const c=$('amplified'),r=c.getBoundingClientRect(),x=(e.clientX-r.left)/r.width*c.width,y=(e.clientY-r.top)/r.height*c.height;
  let nearest=null,distance=tapData.model.pick_radius_px||spatialField.grid.step*.75;
  for(const n of tapData.model.nodes){const d=Math.hypot(n.x-x,n.y-y);if(n.shape!==null&&d<distance){nearest=n;distance=d;}}
  if(!nearest){$('tapSummary').textContent='Choose a visible usable dot. Unsupported locations are not extrapolated.';return;}
  tapSelection.tap_node=nearest.index;tapSelection.probe_a=nearest.index;if(tapSelection.probe_b===nearest.index)tapSelection.probe_b=null;scheduleTap();
};
window.addEventListener('resize',drawTapTrace);
