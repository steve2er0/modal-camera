'use strict';
// Assumptions are applied explicitly; editing a draft does not alter measurements.
const plateDefaults={corners:null,aspect_ratio:2,taper_ratio:1,sweep_offset:0,poisson:.33,mounting:'free',mount_u:.5,mount_v:.5,mount_radius:.08,mount_stiffness:10000,projection_angle_deg:90,anchor_mode:null};
let plateConfig={...plateDefaults},plateEnabled=null,plateSolo=null,plateMotion='tap',platePicking=false,plateDraft=[];
const plateInputs={plateAspect:'aspect_ratio',plateTaper:'taper_ratio',plateSweep:'sweep_offset',platePoisson:'poisson',plateMountU:'mount_u',plateMountV:'mount_v',plateRadius:'mount_radius',plateStiffness:'mount_stiffness',plateProjection:'projection_angle_deg'};
function applyPlateDisplay(ui={}){
  applyStringDisplay(ui);
  plateConfig={...plateDefaults,...ui.plate};plateEnabled=ui.enabled_modes??null;plateSolo=ui.solo_mode??null;plateMotion=ui.motion||'tap';platePicking=false;plateDraft=[];
  $('tapModelSource').value=ui.model_source||'observed';syncPlateInputs();$('plateModes').replaceChildren();updatePlateControls();
}
function syncPlateInputs(){
  for(const [id,key] of Object.entries(plateInputs))$(id).value=plateConfig[key];
  $('plateMounting').value=plateConfig.mounting;$('plateAnchor').value=plateConfig.anchor_mode??'';
  updatePlanformDraft();
  for(let i=0;i<4;i++)for(let j=0;j<2;j++)$(`plateCorner${i}${j}`).value=plateConfig.corners?.[i][j]??'';
  $('plateGeometryStatus').textContent=plateConfig.corners?'Outline and planform ratios are assumptions. Apply changes to regenerate the model.':'Pick root-leading, tip-leading, tip-trailing, root-trailing corners on Original, then apply.';
}
function updatePlanformDraft(){
  const fixed=$('plateMounting').value==='cantilever';
  $('plateRootHelp').textContent=fixed?'Clamped root: edge 4 → 1 has zero displacement and slope; the other three edges are free. Choose the attached edge as the root.':'Corners 1 → 2 follow the span; edge 4 → 1 defines the root chord. Physical taper and sweep are independent of camera perspective.';
  const patch=$('plateMounting').value==='center';
  for(const id of ['plateMountU','plateMountV','plateRadius','plateStiffness'])$(id).disabled=busy||!patch;
}
for(const id of ['plateRectanglePreset','plateWingPreset'])$(id).onclick=()=>{
  const wing=id==='plateWingPreset';
  $('plateAspect').value=wing?3:2;$('plateTaper').value=wing?.5:1;$('plateSweep').value=wing?.5:0;$('plateMounting').value=wing?'cantilever':'free';$('plateAnchor').value='';updatePlanformDraft();
  $('plateGeometryStatus').textContent=wing?'Wing draft: assumed span/root chord 3, tip/root chord 0.5, tip offset/root chord 0.5, clamped root. Adjust to your object and mark its corners before applying.':'Rectangular plate draft: uniform chord, no sweep, free edges. Apply to regenerate.';
};
$('plateMounting').onchange=updatePlanformDraft;
function readPlateSettings(){return {string:stringConfig,model_source:$('tapModelSource').value,plate:plateConfig,enabled_modes:plateEnabled,solo_mode:plateSolo,motion:plateMotion};}
function updatePlateControls(){
  syncStringRoster();
  const predicted=['plate','string'].includes($('tapModelSource').value);
  updatePlanformDraft();
  $('predictedModesHeading').textContent=$('tapModelSource').value==='string'?'Predicted string harmonics':'Predicted bending modes';$('plateBank').hidden=!predicted;
  const solo=predicted&&plateMotion==='mode';$('tapDamping').disabled=busy||solo;$('tapNode').disabled=busy||solo;
  $('tapStrengthCaption').textContent=solo?'Relative animation amplitude':'Relative tap strength';
  $('tapNodeCaption').textContent=tapData?.model.strings?'Shared pluck position (u)':'Tap location';
  $('tapCombined').setAttribute('aria-pressed',String(!solo));$('tapCombined').disabled=busy||!tapData;
  $('plateModeHint').textContent=solo?'Single predicted mode · continuous animation. Choose Combined tap to excite the checked modes together.':tapData?.model.strings?'Combined tap includes checked harmonics on every enabled string. Changing the string shown here only changes this list; all active strings share time and a fractional pluck position.':'Checked modes share one tap and one physical clock. Animate a row to inspect its shape.';
}
function installPlateModel(data){
  $('stringModeSelector').hidden=!(data.model.strings?.length>1);
  if(!['plate','string'].includes(data.model.kind)){updatePlateControls();return;}
  plateEnabled=data.settings.enabled_modes;plateSolo=data.settings.solo_mode;plateMotion=data.settings.motion;
  const strings=data.model.strings;
  if(strings){
    if(!strings.some(s=>s.index===stringModeString))stringModeString=strings[0].index;
    $('stringModeString').replaceChildren(...strings.map(s=>new Option(`${s.name} · ${s.frequency_hz.toFixed(1)} Hz anchor`,String(s.index))));$('stringModeString').value=stringModeString;
  }
  const bank=$('plateModes');bank.replaceChildren();
  for(const m of data.model.modes.filter(m=>!strings||m.string_index===stringModeString)){
    const row=document.createElement('div');row.className='plate-mode'+(plateMotion==='mode'&&plateSolo===m.index?' selected':'');
    const modeName=strings?`${m.string_name} harmonic ${m.harmonic}`:`predicted mode ${m.index+1}`;
    const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.checked=plateEnabled.includes(m.index);check.setAttribute('aria-label',`Include ${modeName} in combined tap`);
    check.onchange=()=>{const selected=new Set(plateEnabled);check.checked?selected.add(m.index):selected.delete(m.index);if(!selected.size){check.checked=true;status('Keep at least one mode enabled for the combined tap.');return;}plateEnabled=[...selected].sort((a,b)=>a-b);plateMotion='tap';scheduleTap();};
    const thumbnail=document.createElement('canvas');thumbnail.width=75;thumbnail.height=39;thumbnail.setAttribute('aria-hidden','true');
    const ctx=thumbnail.getContext('2d');m.thumbnail.forEach((line,y)=>line.forEach((value,x)=>{const t=Math.min(1,Math.abs(value));ctx.fillStyle=value>=0?`rgb(${Math.round(40+215*t)},${Math.round(70+131*t)},${Math.round(91+43*t)})`:`rgb(${Math.round(40+14*t)},${Math.round(70+90*t)},${Math.round(91+147*t)})`;ctx.fillRect(x*3,y*3,3,3);}));
    const text=document.createElement('span');text.textContent=`${strings?'H'+m.harmonic:'M'+(m.index+1)} · ${m.frequency_hz.toFixed(1)} Hz${m.anchor?' · anchor':''}${data.model.kind==='string'&&m.frequency_hz>=clip.metadata.nyquist?' · predicted ≥ Nyquist':''}`;
    label.append(check,thumbnail,text);
    const animate=document.createElement('button');animate.className='secondary';animate.textContent='Animate';animate.setAttribute('aria-label',`Animate ${modeName} at ${m.frequency_hz.toFixed(1)} Hz`);animate.onclick=()=>{plateSolo=m.index;plateMotion='mode';scheduleTap(true);};
    row.append(label,animate);bank.append(row);
  }
  const m=data.model;
  if(strings){
    const s=strings.find(s=>s.index===stringModeString);
    $('plateFit').textContent=`${strings.length} enabled string${strings.length===1?'':'s'} · ${plateEnabled.length} checked harmonics in combined tap. Showing ${s.name}: ${s.fit_samples} usable original patches · shape correlation ${s.fit_mac===null?'unavailable':s.fit_mac.toFixed(3)}. Higher harmonics and full-string supports are assumptions.`;
  }else if(m.kind==='string'){
    $('plateFit').textContent=`M${m.anchor_mode+1} is the assumed anchor at ${m.frequency_hz.toFixed(2)} Hz · ${m.fit_samples} usable original patches · shape correlation ${m.fit_mac===null?'unavailable':m.fit_mac.toFixed(3)}. ${m.fit_mac!==null&&m.fit_mac<.6?'Weak visible-shape agreement; review the selected string and span. ':''}Higher harmonics are predictions; full-string supports and the visible crop are assumptions.`;
  }else{
  $('plateFit').textContent=`M${m.anchor_mode+1} anchored to ${m.frequency_hz.toFixed(3)} Hz · ${m.plate.mounting} · tip/root chord ${m.plate.taper_ratio??1} · visible-shape MAC ${m.fit_mac.toFixed(3)} across ${m.fit_samples} patches. ${m.fit_mac<.6?'Weak match: review geometry and mounting under Advanced. ':''}${m.max_basis_change_percent>2?'Model needs further numerical refinement; see Advanced. ':''}Other frequencies are predictions. A flat plate omits wing internals and aerodynamics.`;
  }
  updatePlateControls();
}
$('tapModelSource').onchange=()=>{
  tapSelection={tap_node:null,probe_a:null,probe_b:null};plateMotion='tap';plateEnabled=null;plateSolo=null;
  if(!plateConfig.corners){plateConfig.projection_angle_deg=spatialField?.axis==='x'?0:90;syncPlateInputs();}
  if($('tapModelSource').value==='plate'&&!plateConfig.corners){$('advanced').open=true;$('plateGeometry').scrollIntoView({behavior:'smooth',block:'center'});}
  if($('tapModelSource').value==='string'&&!hasStringGeometry()){$('advanced').open=true;$('stringGeometry').scrollIntoView({behavior:'smooth',block:'center'});}
  scheduleTap();updatePlateControls();
};
$('tapCombined').onclick=()=>{plateMotion='tap';scheduleTap();};
$('plateGenerate').onclick=()=>scheduleTap();
$('platePick').onclick=()=>{
  if(!clip||busy)return;pause();stringPicking=false;stringDraft=[];platePicking=!platePicking;plateDraft=[];mode='inspect';drag=null;$('platePick').textContent=platePicking?'Cancel corner selection':'Pick four corners on Original';
  $('plateGeometryStatus').textContent=platePicking?'Click root-leading, tip-leading, tip-trailing, root-trailing on Original. The root edge joins 4 → 1. Escape cancels.':'Corner selection canceled.';
  if(platePicking){$('original').scrollIntoView({behavior:'smooth',block:'center'});$('original').focus();}drawVideos();
};
function pickPlateCorner(p){
  plateDraft.push(p.map(v=>Math.round(v*10)/10));
  if(plateDraft.length===4){
    for(let i=0;i<4;i++)for(let j=0;j<2;j++)$(`plateCorner${i}${j}`).value=plateDraft[i][j];
    platePicking=false;$('platePick').textContent='Pick four corners on Original';$('plateGeometryStatus').textContent='Four corners selected. Apply geometry & regenerate under Advanced.';
    $('plateApply').scrollIntoView({behavior:'smooth',block:'center'});
  }else status(`Plate corner ${plateDraft.length}/4 selected. Continue around the plate perimeter.`);
  drawVideos();
}
function drawPlateOutline(ctx){
  if(!platePicking&&($('responseView').value!=='tap'||$('tapModelSource').value!=='plate'))return;
  const corners=plateDraft.length?plateDraft:plateConfig.corners;if(!corners)return;
  ctx.strokeStyle='#36cfee';ctx.fillStyle='#36cfee';ctx.lineWidth=1;ctx.beginPath();corners.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));if(corners.length===4)ctx.closePath();ctx.stroke();
  corners.forEach((p,i)=>{ctx.beginPath();ctx.arc(...p,2,0,2*Math.PI);ctx.fill();ctx.font='7px sans-serif';ctx.fillText(String(i+1),p[0]+3,p[1]-3);});
  if(corners.length===4&&plateConfig.mounting==='cantilever'){
    ctx.strokeStyle='#ffc986';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(...corners[3]);ctx.lineTo(...corners[0]);ctx.stroke();ctx.font='9px sans-serif';ctx.fillStyle='#ffc986';ctx.fillText('ROOT',(corners[3][0]+corners[0][0])/2+5,(corners[3][1]+corners[0][1])/2);
  }
}
$('plateApply').onclick=()=>{
  try{
    const next={};for(const [id,key] of Object.entries(plateInputs))next[key]=finiteInput(id,key);
    next.corners=Array.from({length:4},(_,i)=>[finiteInput(`plateCorner${i}0`,'Corner X'),finiteInput(`plateCorner${i}1`,'Corner Y')]);
    next.mounting=$('plateMounting').value;next.anchor_mode=$('plateAnchor').value===''?null:Number($('plateAnchor').value);
    // Validate on the server before adopting a draft, preserving the last valid model.
    task('Fitting predicted plate modes…',async()=>{
      await flushSettings();const options={...readTapSettings(),plate:next,model_source:'plate',tap_node:null,probe_a:null,probe_b:null,enabled_modes:null,solo_mode:null,motion:'tap',cursor_cycle:0};
      await api('/api/tap',{id:clip.id,revision,key:spatialField?.key,tap:options});
      plateConfig=next;plateDraft=[];plateEnabled=null;plateSolo=null;plateMotion='tap';tapSelection={tap_node:null,probe_a:null,probe_b:null};$('tapModelSource').value='plate';$('responseView').value='tap';syncPlateInputs();scheduleTap();
    });
  }catch(e){showError(e);}
};
