'use strict';
const stringDefaults={endpoints:null,span_start:0,span_end:1,half_width_px:3,anchor_harmonic:1,inharmonicity:0,amplitude_source_px:null};
let stringConfig={...stringDefaults},stringPicking=false,stringDraft=[];
const stringInputs={stringSpanStart:'span_start',stringSpanEnd:'span_end',stringWidth:'half_width_px',stringHarmonic:'anchor_harmonic',stringB:'inharmonicity'};
function applyStringDisplay(ui={}){stringConfig={...stringDefaults,...ui.string};stringPicking=false;stringDraft=[];syncStringInputs();}
function syncStringInputs(){
  for(const [id,key] of Object.entries(stringInputs))$(id).value=stringConfig[key];
  $('stringAmplitude').value=stringConfig.amplitude_source_px??'';
  for(let i=0;i<2;i++)for(let j=0;j<2;j++)$(`stringPoint${i}${j}`).value=stringConfig.endpoints?.[i][j]??'';
  $('stringGeometryStatus').textContent=stringConfig.endpoints?'Applied segment shown on Original. Edit its full-string fractions if a support is offscreen. Apply to regenerate.':'Choose two points along one visible string, then set their positions along its full vibrating length.';
}
$('stringPick').onclick=()=>{
  if(!clip||busy)return;pause();stringPicking=!stringPicking;stringDraft=[];platePicking=false;plateDraft=[];mode='inspect';drag=null;
  $('stringPick').textContent=stringPicking?'Cancel string selection':'Pick visible string segment on Original';
  $('stringGeometryStatus').textContent=stringPicking?'Click A then B along the same string on Original. Fractions below define where this cropped segment lies on the full string. Escape cancels.':'String selection canceled.';
  if(stringPicking){$('original').scrollIntoView({behavior:'smooth',block:'center'});$('original').focus();}drawVideos();
};
function pickStringEndpoint(p){
  stringDraft.push([Math.max(0,Math.min(clip.metadata.width-.1,p[0])),Math.max(0,Math.min(clip.metadata.height-.1,p[1]))].map(v=>Math.round(v*10)/10));
  if(stringDraft.length===2){
    for(let i=0;i<2;i++)for(let j=0;j<2;j++)$(`stringPoint${i}${j}`).value=stringDraft[i][j];
    stringPicking=false;$('stringPick').textContent='Pick visible string segment on Original';$('stringGeometryStatus').textContent='Segment selected. Set the full-string fractions, then apply assumptions.';$('stringApply').scrollIntoView({behavior:'smooth',block:'center'});
  }else status('String endpoint A selected. Click B farther along the same string.');
  drawVideos();
}
function drawStringOutline(ctx){
  if(!stringPicking&&($('responseView').value!=='tap'||$('tapModelSource').value!=='string'))return;
  const points=stringDraft.length?stringDraft:stringConfig.endpoints;if(!points)return;
  ctx.strokeStyle='#36cfee';ctx.fillStyle='#36cfee';ctx.lineWidth=1;ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(...p):ctx.moveTo(...p));ctx.stroke();
  points.forEach((p,i)=>{ctx.beginPath();ctx.arc(...p,3,0,2*Math.PI);ctx.stroke();ctx.font='8px sans-serif';ctx.fillText(i?'B':'A',p[0]+4,p[1]-5);});
}
$('stringApply').onclick=()=>{
  try{
    const next={};for(const [id,key] of Object.entries(stringInputs))next[key]=finiteInput(id,key);
    next.endpoints=Array.from({length:2},(_,i)=>[finiteInput(`stringPoint${i}0`,'String X'),finiteInput(`stringPoint${i}1`,'String Y')]);
    next.amplitude_source_px=$('stringAmplitude').value.trim()===''?null:finiteInput('stringAmplitude','Assumed antinode amplitude');
    task('Fitting the tensioned-string model…',async()=>{
      await flushSettings();await api('/api/tap',{id:clip.id,revision,key:spatialField?.key,tap:{...readTapSettings(),model_source:'string',string:next,enabled_modes:null,solo_mode:null,motion:'tap',tap_node:null,probe_a:null,probe_b:null,cursor_cycle:0}});
      stringConfig=next;stringDraft=[];plateEnabled=null;plateSolo=null;plateMotion='tap';tapSelection={tap_node:null,probe_a:null,probe_b:null};$('tapModelSource').value='string';$('responseView').value='tap';syncStringInputs();scheduleTap();
    });
  }catch(e){showError(e);}
};
