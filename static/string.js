'use strict';
const stringDefaults={endpoints:null,span_start:0,span_end:1,half_width_px:3,anchor_harmonic:1,inharmonicity:0,amplitude_source_px:null};
const newString=(i=0)=>({...stringDefaults,name:`String ${i+1}`,enabled:true,anchor_hz:null});
let stringConfig={strings:[newString()]},stringEdits=[newString()],stringEditor=0,stringModeString=null,stringPicking=false,stringDraft=[];
const stringInputs={stringSpanStart:'span_start',stringSpanEnd:'span_end',stringWidth:'half_width_px',stringHarmonic:'anchor_harmonic',stringB:'inharmonicity'};
function applyStringDisplay(ui={}){
  const stored=ui.string||{};
  stringConfig=structuredClone(stored.strings?stored:{strings:[{...newString(),...stored}]});
  stringEdits=structuredClone(stringConfig.strings);stringEditor=0;stringModeString=null;stringPicking=false;stringDraft=[];syncStringInputs();syncStringRoster();
}
function hasStringGeometry(){return stringConfig.strings.some(s=>s.enabled&&s.endpoints);}
function syncStringRoster(){
  const enabled=stringConfig.strings.filter(s=>s.enabled);
  $('stringRoster').textContent=enabled.filter(s=>s.endpoints).map(s=>`${s.name}: ${s.anchor_hz??(spatialField?.frequency_hz||'selected response')} Hz`).join(' · ')||'Mark one or more strings under Advanced.';
  $('stringSelectionPanel').hidden=$('tapModelSource').value!=='string';
}
function syncStringInputs(){
  const cfg=stringEdits[stringEditor];
  $('stringEditor').replaceChildren(...stringEdits.map((s,i)=>new Option(`${i+1} · ${s.name}${s.enabled?'':' (disabled)'}`,String(i))));$('stringEditor').value=stringEditor;
  $('stringName').value=cfg.name;$('stringEnabled').checked=cfg.enabled;$('stringAnchorHz').value=cfg.anchor_hz??'';
  for(const [id,key] of Object.entries(stringInputs))$(id).value=cfg[key];
  $('stringAmplitude').value=cfg.amplitude_source_px??'';
  for(let i=0;i<2;i++)for(let j=0;j<2;j++)$(`stringPoint${i}${j}`).value=cfg.endpoints?.[i][j]??'';
  $('stringRemove').disabled=stringEdits.length===1;$('stringAdd').disabled=stringEdits.length===6;
  $('stringPick').textContent='Pick visible string segment on Original';
  $('stringGeometryStatus').textContent=`Editing ${cfg.name}. ${cfg.endpoints?'Edit the line or its full-string fractions.':'Click A then B along this string.'} ${stringEdits.length} selected; Apply updates all strings together.`;
}
function storeStringEditor(){
  const cfg=stringEdits[stringEditor];
  cfg.name=$('stringName').value.trim();cfg.enabled=$('stringEnabled').checked;
  cfg.anchor_hz=$('stringAnchorHz').value.trim()===''?null:finiteInput('stringAnchorHz','String anchor frequency');
  for(const [id,key] of Object.entries(stringInputs))cfg[key]=finiteInput(id,key);
  const coords=Array.from({length:2},(_,i)=>[0,1].map(j=>$(`stringPoint${i}${j}`).value.trim()));
  cfg.endpoints=coords.flat().every(v=>v==='')?null:coords.map((p,i)=>p.map((_,j)=>finiteInput(`stringPoint${i}${j}`,'String endpoint')));
  cfg.amplitude_source_px=$('stringAmplitude').value.trim()===''?null:finiteInput('stringAmplitude','Assumed antinode amplitude');
}
function openStringEditor(){if(!clip||busy)return;$('advanced').open=true;$('stringGeometry').scrollIntoView({behavior:'smooth',block:'start'});}
$('stringEditOpen').onclick=openStringEditor;
$('stringEditor').onchange=()=>{try{const next=Number($('stringEditor').value);storeStringEditor();stringEditor=next;stringPicking=false;stringDraft=[];syncStringInputs();drawVideos();}catch(e){$('stringEditor').value=stringEditor;showError(e);}};
$('stringAdd').onclick=()=>{
  try{storeStringEditor();if(stringEdits.length>=6)return;const prior=stringEdits[stringEditor];let n=0;while(stringEdits.some(s=>s.name===`String ${n+1}`))n++;stringEdits.push({...newString(n),span_start:prior.span_start,span_end:prior.span_end});stringEditor=stringEdits.length-1;stringPicking=false;stringDraft=[];syncStringInputs();drawVideos();}catch(e){showError(e);}
};
$('stringRemove').onclick=()=>{if(stringEdits.length===1)return;stringEdits.splice(stringEditor,1);stringEditor=Math.min(stringEditor,stringEdits.length-1);stringPicking=false;stringDraft=[];syncStringInputs();drawVideos();};
$('stringPick').onclick=()=>{
  if(!clip||busy)return;pause();stringPicking=!stringPicking;stringDraft=[];platePicking=false;plateDraft=[];mode='inspect';drag=null;
  $('stringPick').textContent=stringPicking?'Cancel string selection':'Pick visible string segment on Original';
  $('stringGeometryStatus').textContent=stringPicking?`Click A then B along ${$('stringName').value||'this string'} on Original. Escape cancels.`:'String selection canceled.';
  if(stringPicking){$('original').scrollIntoView({behavior:'smooth',block:'center'});$('original').focus();}drawVideos();
};
function pickStringEndpoint(p){
  stringDraft.push([Math.max(0,Math.min(clip.metadata.width-.1,p[0])),Math.max(0,Math.min(clip.metadata.height-.1,p[1]))].map(v=>Math.round(v*10)/10));
  if(stringDraft.length===2){
    for(let i=0;i<2;i++)for(let j=0;j<2;j++)$(`stringPoint${i}${j}`).value=stringDraft[i][j];
    stringEdits[stringEditor].endpoints=structuredClone(stringDraft);
    stringPicking=false;$('stringPick').textContent='Pick visible string segment on Original';$('stringGeometryStatus').textContent='Segment selected. Set its frequency and full-string fractions, add more strings, then Apply all strings.';$('stringGeometry').scrollIntoView({behavior:'smooth',block:'start'});
  }else status('String endpoint A selected. Click B farther along the same string.');
  drawVideos();
}
function drawStringOutline(ctx){
  if(!stringPicking&&($('responseView').value!=='tap'||$('tapModelSource').value!=='string'))return;
  const entries=stringPicking||$('advanced').open?stringEdits:stringConfig.strings;
  entries.forEach((cfg,index)=>{
    const points=stringPicking&&index===stringEditor&&stringDraft.length?stringDraft:cfg.endpoints;if(!points||!cfg.enabled)return;
    ctx.strokeStyle=colors[index%colors.length];ctx.fillStyle=ctx.strokeStyle;ctx.lineWidth=1;ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.stroke();
    points.forEach((p,i)=>{ctx.beginPath();ctx.arc(...p,3,0,2*Math.PI);ctx.stroke();ctx.font='8px sans-serif';ctx.fillText(`S${index+1}${i?'B':'A'}`,p[0]+4,p[1]-5);});
  });
}
$('stringApply').onclick=()=>{
  try{
    storeStringEditor();const next={strings:structuredClone(stringEdits)};
    task('Fitting the selected strings…',async()=>{
      await flushSettings();const data=await api('/api/tap',{id:clip.id,revision,key:spatialField?.key,tap:{...readTapSettings(),model_source:'string',string:next,enabled_modes:null,solo_mode:null,motion:'tap',tap_node:null,probe_a:null,probe_b:null,cursor_cycle:0}});
      stringConfig=data.model.string;stringEdits=structuredClone(stringConfig.strings);stringDraft=[];stringModeString=null;plateEnabled=data.settings.enabled_modes;plateSolo=null;plateMotion='tap';tapSelection={tap_node:null,probe_a:null,probe_b:null};$('tapModelSource').value='string';$('responseView').value='tap';syncStringInputs();syncStringRoster();scheduleTap();
    });
  }catch(e){showError(e);}
};
$('stringModeString').onchange=()=>{stringModeString=Number($('stringModeString').value);if(tapData)installPlateModel(tapData);};
