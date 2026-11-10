"""Local dark dashboard for the Goldshell SC5 Pro II.

Reads the miner (cgminer + web API) and, when started with --control, also exposes
a small set of allowlisted, reversible actions (mode, LED, temp control, reboot).
No login, so bind it to 127.0.0.1 or a trusted LAN only. Firmware flashing and
factory reset are never reachable; see sc5/control.py.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .collect import collect
from .control import ACTIONS, Miner, ControlError
from . import curve as curvemod
from .history import History, sample_from_snapshot

PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SC5 Pro II</title>
<style>
:root{--bg:#0c0e13;--fg:#e8e8ea;--mut:#8b8f98;--card:#161922;--line:#262a33;--acc:#5aa9ff;--ok:#3fb950;--fan:#b18cff;--warn:#d29922;--bad:#f85149}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,sans-serif}
main{max-width:1000px;margin:auto;padding:16px}
h1{font-size:18px;margin:0 0 2px}.mut{color:var(--mut)}.sub{color:var(--mut);font-size:12px;margin-bottom:12px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:12px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.big{font-size:26px;font-weight:650;letter-spacing:-.5px}
table{width:100%;border-collapse:collapse}td,th{padding:7px 6px;text-align:left;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-weight:500;font-size:12px}
.o{color:var(--ok)}.w{color:var(--warn)}.b{color:var(--bad)}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.5px;color:var(--mut);margin:22px 0 8px}
.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
button{font:inherit;color:var(--fg);background:#20242e;border:1px solid var(--line);border-radius:9px;padding:9px 14px;cursor:pointer}
button:hover{border-color:var(--acc)}button:disabled{opacity:.5;cursor:default}
button.on{background:var(--acc);border-color:var(--acc);color:#04121f;font-weight:600}
button.warn{border-color:var(--warn)}button.danger{border-color:var(--bad)}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:9px;overflow:hidden}
.seg button{border:0;border-radius:0;border-right:1px solid var(--line)}.seg button:last-child{border-right:0}
.toast{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);background:#20242e;border:1px solid var(--line);border-radius:9px;padding:10px 14px;opacity:0;transition:opacity .2s;pointer-events:none;max-width:90vw}
.toast.show{opacity:1}
.lg{cursor:pointer;user-select:none;font-size:12px;border:1px solid var(--line);border-radius:999px;padding:2px 9px}
.lg.off{opacity:.38;text-decoration:line-through}
.pm{padding:3px 8px;font-size:12px;border-radius:7px;margin-right:3px}.lbl{color:var(--mut);font-size:12px;margin-right:6px}
</style></head><body><main>
<h1 id="dev">SC5 Pro II</h1><div class="sub" id="sub">cargando…</div>

<div class="grid" id="kpi"></div>

<div class="card">
 <div class="row" style="justify-content:space-between;gap:8px">
  <div class="row" style="gap:12px"><b>Hashrate</b>
   <span class="lg" data-s="ths" title="Mostrar/ocultar" style="color:var(--acc)"><b id="lvThs">—</b> TH/s</span>
   <span class="lg" data-s="temp" title="Mostrar/ocultar" style="color:var(--warn)"><b id="lvTemp">—</b> chip °C</span>
   <span class="lg" data-s="fan" title="Mostrar/ocultar" style="color:var(--fan)"><b id="lvFan">—</b> rpm ventiladores</span>
  </div>
  <div class="seg" id="chartWin">
   <button data-w="3600" class="on">1 h</button><button data-w="21600">6 h</button><button data-w="86400">24 h</button>
  </div>
 </div>
 <div class="mut" id="chartInfo" style="font-size:12px;margin:4px 0 2px"></div>
 <canvas id="chart" height="190" style="width:100%;display:block"></canvas></div>

<div class="card"><table><thead><tr><th>Placa</th><th>Estado</th><th>TH/s</th><th>MHz</th><th>V</th><th>Chip °C</th><th>Placa °C</th><th>Ventiladores</th><th>HW %</th></tr></thead><tbody id="boards"></tbody></table>
<div class="mut" style="font-size:12px;margin-top:8px">«Chip» = sensor del ASIC (el que calienta). «Placa» = sensor de la placa, el que muestra el panel oficial de Goldshell.</div></div>

<div id="controls" style="display:none">
<h2>Control</h2>
<div class="card">
 <div class="row" style="margin-bottom:12px"><span class="lbl">Modo</span>
  <div class="seg" id="modes">
   <button data-mode="hash">Hash · 700 MHz</button>
   <button data-mode="eco">Eco · 513 MHz</button>
   <button data-mode="idle" class="warn">Reposo · 0 MHz</button>
  </div>
 </div>
 <div class="row" style="margin-bottom:6px"><span class="lbl">Ventiladores</span>
  <div class="seg" id="fans">
   <button data-fan="auto">Auto</button>
   <button data-fan="50">50%</button>
   <button data-fan="75">75%</button>
   <button data-fan="100">100%</button>
  </div>
  <span class="mut" id="fanpct" style="font-size:12px;margin-left:4px"></span>
 </div>
 <div class="mut" style="font-size:12px;margin-bottom:12px">Auto = curva de fábrica (objetivo ~85 °C de chip, corte de seguridad a 105 °C). Un % fijo pone un suelo de ventilador sin tocar frecuencia ni voltaje.</div>
 <div class="row" style="margin-bottom:12px"><span class="lbl">De fábrica</span>
  <button id="factory" class="warn">Dejar de fábrica</button>
  <span class="mut" style="font-size:12px">Ventilador en Auto y desactiva la curva propia.</span>
 </div>

 <div class="card" style="background:#12151c;border-color:var(--line)">
  <div class="row" style="margin-bottom:8px"><b>Curva propia</b>
   <button id="curveToggle">—</button>
   <span id="curveState" style="font-size:22px;font-weight:700;margin-left:6px"></span>
  </div>
  <div class="mut" style="font-size:12px;margin-bottom:8px">Puntos chip °C → ventilador %. Entre puntos el ventilador sube/baja solo, interpolando. Nunca toca frecuencia ni voltaje.</div>
  <table style="width:auto"><thead><tr><th>Chip °C</th><th>Ventilador %</th><th></th></tr></thead><tbody id="curveRows"></tbody></table>
  <div class="row" style="margin-top:8px">
   <button id="curveAdd">+ punto</button>
   <button id="curveSave">Guardar curva</button>
  </div>
 </div>
 <div class="row" style="margin-bottom:12px"><span class="lbl">LED de identificación</span>
  <button id="led" data-act="led">—</button>
 </div>
 <div class="row"><span class="lbl">Reiniciar el minero (~1-2 min sin minar)</span>
  <button id="reboot" class="danger">Reiniciar…</button>
 </div>
</div>
</div>

<h2>Pools</h2>
<div class="card"><table><thead><tr><th></th><th>Pool</th><th>Usuario</th><th>Estado</th><th>Acept.</th><th>Rech.</th><th class="pc" style="display:none">Prioridad</th></tr></thead><tbody id="pools"></tbody></table>
<div class="mut pc" style="font-size:12px;margin-top:8px;display:none">El minero mina en el primer pool vivo de la lista; los demás son de reserva, por orden. Subir uno arriba del todo cambia dónde mina (lo mismo que arrastrarlo en el panel de Goldshell).</div></div>

<div id="warn" style="margin-top:12px"></div>
<p class="mut" style="margin-top:18px">Solo acciones reversibles y de fábrica. Nunca firmware ni reset de fábrica.</p>
</main>
<div class="toast" id="toast"></div>
<script>
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const tc=t=>t>=90?"b":t>=80?"w":"o";
const cssv=n=>(getComputedStyle(document.documentElement).getPropertyValue(n)||"#888").trim();
let chartWin=3600;
const SHOW={ths:true,temp:true,fan:true};
try{Object.assign(SHOW,JSON.parse(localStorage.getItem("sc5show")||"{}"));}catch(e){}
const hhmm=t=>{const d=new Date(t*1000);return String(d.getHours()).padStart(2,"0")+":"+String(d.getMinutes()).padStart(2,"0");};
async function drawChart(){
 const c=document.getElementById("chart");if(!c)return;
 let all;try{all=(await (await fetch("api/history",{cache:"no-store"})).json()).samples||[];}catch(e){return;}
 const dpr=window.devicePixelRatio||1,W=c.clientWidth||600,H=190;
 c.width=W*dpr;c.height=H*dpr;const x=c.getContext("2d");x.scale(dpr,dpr);x.clearRect(0,0,W,H);
 const info=document.getElementById("chartInfo");
 if(all.length<2){x.fillStyle=cssv("--mut");x.font="12px system-ui";x.fillText("Recogiendo datos…",10,22);info.textContent="";return;}
 // x domain = the chosen window, anchored to the latest sample (so the axis
 // always shows e.g. 24 h even while it is still filling from the right).
 const ref=all[all.length-1][0],x0=ref-chartWin,x1=ref;
 const data=all.filter(d=>d[0]>=x0-30);
 const pad={l:42,r:38,t:12,b:22};
 const PX=W-pad.l-pad.r,PY=H-pad.t-pad.b;
 const ths=data.map(d=>d[1]).filter(v=>v!=null);
 const temps=data.map(d=>d[3]).filter(v=>v!=null);
 const fans=data.map(d=>d[4]).filter(v=>v!=null);
 let fmn=fans.length?Math.min(...fans):0,fmx=fans.length?Math.max(...fans):1;
 if(fmx-fmn<200){fmx+=100;fmn-=100;}fmn=Math.max(0,fmn-100);fmx+=100;
 let mn=Math.min(...ths),mx=Math.max(...ths);
 if(mx-mn<0.5){mx+=0.25;mn-=0.25;}let sp=mx-mn;mn=Math.max(0,mn-sp*0.12);mx+=sp*0.12;
 let tmn=temps.length?Math.min(...temps):60,tmx=temps.length?Math.max(...temps):90;
 if(tmx-tmn<6){tmx+=3;tmn-=3;}tmn-=2;tmx+=2;
 const px=t=>pad.l+PX*Math.max(0,Math.min(1,(t-x0)/((x1-x0)||1)));
 const py=v=>pad.t+PY*(1-(v-mn)/((mx-mn)||1));
 const pyt=v=>pad.t+PY*(1-(v-tmn)/((tmx-tmn)||1));
 const pyf=v=>pad.t+PY*(1-(v-fmn)/((fmx-fmn)||1));
 // horizontal grid + left (TH/s) axis
 x.font="11px system-ui";x.lineWidth=1;
 for(let i=0;i<=3;i++){const yy=pad.t+PY*(1-i/3);x.strokeStyle=cssv("--line");x.beginPath();x.moveTo(pad.l,yy);x.lineTo(W-pad.r,yy);x.stroke();}
 // left axis: TH/s; when hashrate is hidden it shows the fans' rpm instead
 x.textAlign="right";
 if(SHOW.ths){x.fillStyle=cssv("--mut");for(let i=0;i<=3;i++){const v=mn+(mx-mn)*i/3;x.fillText(v.toFixed(1),pad.l-4,py(v)+3);}}
 else if(SHOW.fan&&fans.length){x.fillStyle=cssv("--fan");for(let i=0;i<=3;i++){const v=fmn+(fmx-fmn)*i/3;x.fillText((v/1000).toFixed(1)+"k",pad.l-4,pyf(v)+3);}}
 // right axis: °C; when temperature is hidden it shows the fans' rpm
 x.textAlign="left";
 if(SHOW.temp){x.fillStyle=cssv("--warn");for(let i=0;i<=3;i++){const v=tmn+(tmx-tmn)*i/3;x.fillText(v.toFixed(0)+"°",W-pad.r+4,pyt(v)+3);}}
 else if(SHOW.fan&&fans.length&&SHOW.ths){x.fillStyle=cssv("--fan");for(let i=0;i<=3;i++){const v=fmn+(fmx-fmn)*i/3;x.fillText((v/1000).toFixed(1)+"k",W-pad.r+4,pyf(v)+3);}}
 // x axis (hours)
 const N=W<520?3:6;x.fillStyle=cssv("--mut");x.textAlign="center";
 for(let i=0;i<=N;i++){const t=x0+(x1-x0)*i/N,X=px(t);x.strokeStyle=cssv("--line");x.globalAlpha=.5;x.beginPath();x.moveTo(X,pad.t);x.lineTo(X,H-pad.b);x.stroke();x.globalAlpha=1;x.fillText(hhmm(t),X,H-6);}
 // no readings (idle: cgminer stopped, or miner off): shade it instead of a flat/missing line
 {let st=null;const nod=d=>d[3]==null&&(d[4]==null)&&!(d[1]>0);
  const shade=(a,b)=>{const X0=px(a),X1=Math.max(px(b),X0+2);x.fillStyle=cssv("--mut");x.globalAlpha=.13;x.fillRect(X0,pad.t,X1-X0,H-pad.t-pad.b);x.globalAlpha=.85;
   if(X1-X0>70){x.textAlign="center";x.fillText("reposo · sin lecturas",(X0+X1)/2,pad.t+12);}x.globalAlpha=1;};
  data.forEach((d,i)=>{if(nod(d)){if(st==null)st=d[0];}else if(st!=null){shade(st,d[0]);st=null;}});
  if(st!=null)shade(st,data[data.length-1][0]);}
 const draw=idx=>{x.beginPath();let on=false;data.forEach(d=>{const v=d[idx];if(v==null){on=false;return;}const X=px(d[0]),Y=idx===3?pyt(v):idx===4?pyf(v):py(v);on?x.lineTo(X,Y):x.moveTo(X,Y);on=true;});};
 if(SHOW.ths){
  // area under ths
  x.beginPath();let on=false;data.forEach(d=>{const X=px(d[0]),Y=py(d[1]);on?x.lineTo(X,Y):x.moveTo(X,Y);on=true;});
  x.lineTo(px(data[data.length-1][0]),py(mn));x.lineTo(px(data[0][0]),py(mn));x.closePath();
  const g=x.createLinearGradient(0,pad.t,0,H-pad.b);g.addColorStop(0,"rgba(90,169,255,.28)");g.addColorStop(1,"rgba(90,169,255,0)");x.fillStyle=g;x.fill();
 }
 // fans' average rpm (own scale)
 if(SHOW.fan&&fans.length){draw(4);x.strokeStyle=cssv("--fan");x.lineWidth=1.3;x.stroke();}
 // chip temp (right axis)
 if(SHOW.temp){draw(3);x.strokeStyle=cssv("--warn");x.lineWidth=1.4;x.stroke();}
 if(SHOW.ths){
  // ths (main)
  draw(1);x.strokeStyle=cssv("--acc");x.lineWidth=1.8;x.stroke();
 }
 const last=ths[ths.length-1],lt=temps.length?temps[temps.length-1]:null,lf=fans.length?fans[fans.length-1]:null;
 info.textContent=`${last.toFixed(2)} TH/s · mín ${Math.min(...ths).toFixed(2)} · máx ${Math.max(...ths).toFixed(2)}`+(lt!=null?` · chip ${lt.toFixed(0)}°`:"")+(lf!=null?` · ventiladores ${lf} rpm (${Math.min(...fans)}–${Math.max(...fans)})`:"");
}
function wireLegend(){document.querySelectorAll(".lg").forEach(e=>{const k=e.dataset.s;e.classList.toggle("off",!SHOW[k]);e.onclick=()=>{SHOW[k]=!SHOW[k];e.classList.toggle("off",!SHOW[k]);try{localStorage.setItem("sc5show",JSON.stringify(SHOW));}catch(_){}drawChart();};});}
function wireChartWin(){document.querySelectorAll("#chartWin button").forEach(b=>b.onclick=()=>{chartWin=+b.dataset.w;document.querySelectorAll("#chartWin button").forEach(o=>o.classList.toggle("on",o===b));drawChart();});}
const CONTROL=__CONTROL__;
let busy=false,lastMode=null,lastPools=[];
function movePool(i,m){
 const p=lastPools[i];if(!p)return;
 const j=m==="top"?0:m==="up"?i-1:i+1;
 let msg=`¿Cambiar la prioridad de ${p.url}?\n\nPara aplicarla el minero se reinicia: estará ~2-3 min sin minar.`;
 if(j===0||i===0){const nt=j===0?p:lastPools[1];msg+=`\n\nCAMBIA EL POOL DONDE MINA:\nAhora: ${lastPools[0].url}\nPasará a: ${nt.url} (si está vivo)\n\nSi es un alquiler o un mercado, el comprador dejará de recibir el hashrate.`;}
 send("pool",{url:p.url,move:m},msg);
}
function toast(m){const t=document.getElementById("toast");t.textContent=m;t.classList.add("show");clearTimeout(t._h);t._h=setTimeout(()=>t.classList.remove("show"),3500);}
async function tick(){
 try{
  const s=await (await fetch("api/snapshot",{cache:"no-store"})).json();
  const d=s.device||{},su=s.summary||{};
  document.getElementById("dev").textContent=`${d.model||"?"} · fw ${d.firmware||"?"} · ${d.board||"?"}`;
  const up=su.uptime_s||0;
  document.getElementById("sub").textContent=`${d.miner||""} · encendido ${Math.floor(up/3600)} h ${Math.floor(up%3600/60)} min · ${s.algorithm||""} · ${s.power?.level===3&&!s.power?.manual?"Reposo (0 MHz)":(s.power?.plan||"")}`;
  const _f={};(s.boards||[]).forEach(b=>(b.fans_rpm||[]).forEach((r,i)=>{if(typeof r==="number"&&!(i in _f))_f[i]=r;}));const _fv=Object.values(_f);
  const _fa=_fv.length?Math.round(_fv.reduce((a,b)=>a+b,0)/_fv.length):null;
  const _fpc=s.power?.fan_pct,_fp=_fpc==null?"":(s.power?.manual?`al ${_fpc} %`:`auto · mín ${_fpc} %`);
  const k=[["Hashrate 20 s",(su.ths_20s||0).toFixed(2)+" TH/s"],["Ventiladores (media)",_fa!=null?_fa+" rpm":(s.power?.level===3&&!s.power?.manual?"— · reposo":"—"),_fa!=null?_fp:""],["Errores HW",(su.hw_pct??"?")+" %"],["Rechazadas",(su.reject_pct??"?")+" %"]];
  document.getElementById("kpi").innerHTML=k.map(([a,b,c])=>`<div class="card"><div class="mut">${a}</div><div class="big">${esc(b)}</div>${c?`<div style="font-size:20px;font-weight:700;color:#b89cff;margin-top:2px">${esc(c)}</div>`:""}</div>`).join("");
  const _ct=(s.boards||[]).map(b=>b.temp_chip_c).filter(v=>v!=null),_mt=_ct.length?Math.max(..._ct):null;
  const lv=(id,v)=>{const e=document.getElementById(id);if(e)e.textContent=v;};
  lv("lvFan",_fa!=null?_fa:"—");
  lv("lvThs",(su.ths_20s||0).toFixed(2));lv("lvTemp",_mt!=null?_mt.toFixed(0):"—");
  const cell=t=>t==null?"—":`<span class="${tc(t)}">${t.toFixed(0)}</span>`;
  document.getElementById("boards").innerHTML=(s.boards||[]).map(b=>`<tr><td>${esc(b.id)}</td><td class="${b.status==="Alive"?"o":"b"}">${esc(b.status)}</td><td>${b.ths_20s.toFixed(2)}</td><td>${esc(b.clock_mhz)}</td><td>${((b.voltage_mv||0)/1000).toFixed(2)}</td><td>${cell(b.temp_chip_c)}</td><td>${cell(b.temp_board_c)}</td><td>${esc(b.fans_rpm.join(" "))}</td><td>${esc(b.hw_pct)}</td></tr>`).join("");
  const _pl=[...(s.pools||[])].sort((a,b)=>(a.priority??0)-(b.priority??0));lastPools=_pl;
  const mv=(i,m,t,dis)=>`<button class="pm" data-i="${i}" data-m="${m}" title="${t}"${dis?" disabled":""}>${{top:"⇈",up:"↑",down:"↓"}[m]}</button>`;
  document.getElementById("pools").innerHTML=_pl.map((p,i)=>`<tr><td>${p.active?"●":""}</td><td>${esc(p.url)}</td><td>${esc(p.user)}</td><td>${esc(p.status)}</td><td>${esc(p.accepted)}</td><td>${esc(p.rejected)}</td>`+
   (CONTROL?`<td class="pc" style="white-space:nowrap">${mv(i,"top","Arriba del todo (minar aquí)",i===0)}${mv(i,"up","Subir",i===0)}${mv(i,"down","Bajar",i===_pl.length-1)}</td>`:"")+`</tr>`).join("");
  if(CONTROL){document.querySelectorAll(".pc").forEach(e=>e.style.display="");document.querySelectorAll("#pools .pm").forEach(b=>b.onclick=()=>movePool(+b.dataset.i,b.dataset.m));}
  document.getElementById("warn").innerHTML=[...(s.notes||[]).map(n=>`<div class="mut">ℹ ${esc(n)}</div>`),...(s.warnings||[]).map(w=>`<div class="w">⚠ ${esc(w)}</div>`),...(s.errors||[]).map(e=>`<div class="b">✖ ${esc(e)}</div>`)].join("");
  if(CONTROL){
   document.getElementById("controls").style.display="block";
   const sel=s.power?.level;lastMode=sel;
   document.querySelectorAll("#modes button").forEach(x=>x.classList.toggle("on",{hash:0,eco:2,idle:3}[x.dataset.mode]===sel));
   const manual=!!s.power?.manual, pct=s.power?.fan_pct;
   document.querySelectorAll('#fans button').forEach(x=>{const f=x.dataset.fan;x.classList.toggle("on",f==="auto"?!manual:(manual&&String(pct)===f));});
   document.getElementById("fanpct").textContent=pct!=null?`plan: ${pct}%`:"";
   const led=document.getElementById("led");led.textContent=s.power?.led?"Encendido":"Apagado";led.classList.toggle("on",!!s.power?.led);
  }
 }catch(e){document.getElementById("sub").textContent="sin datos: "+e}
}
async function send(action,arg,confirmMsg){
 if(busy)return; if(confirmMsg&&!confirm(confirmMsg))return;
 busy=true;document.querySelectorAll("button").forEach(b=>b.disabled=true);
 try{
  const r=await fetch("api/control",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action,arg})});
  const j=await r.json();
  toast(j.ok?(j.note||"Hecho ✓"):("Error: "+(j.error||r.status)));
 }catch(e){toast("Error: "+e);}
 finally{busy=false;document.querySelectorAll("button").forEach(b=>b.disabled=false);setTimeout(tick,1200);}
}
async function factory(){
 if(!confirm("¿Dejar el minero de fábrica? Ventilador en Auto (curva del firmware, objetivo ~85 °C de chip, corte de seguridad a 105 °C) y se desactiva la curva propia."))return;
 try{await curvePost({enabled:false});}catch(e){}
 send("fan","auto");
}
function wire(){
 document.querySelectorAll("#modes button").forEach(b=>b.onclick=()=>send("mode",b.dataset.mode,
   b.dataset.mode==="idle"?"¿Poner el minero en REPOSO? Dejará de minar hasta que lo saques de reposo.":null));
 document.querySelectorAll("#fans button").forEach(b=>b.onclick=()=>send("fan",b.dataset.fan,null));
 wireCurve();
 document.getElementById("factory").onclick=factory;
 const led=document.getElementById("led");led.onclick=()=>send("led",!led.classList.contains("on"));
 document.getElementById("reboot").onclick=()=>send("reboot",null,"¿Reiniciar el minero? Estará ~1-2 min sin minar y volverá solo.");
}
let curveCfg=null,curveEditing=false;
function curveRow(t,p){
 const tr=document.createElement("tr");
 tr.innerHTML=`<td><input type="number" class="ct" min="50" max="95" value="${t}" style="width:64px"></td>`+
  `<td><input type="number" class="cp" min="40" max="100" step="5" value="${p}" style="width:64px"></td>`+
  `<td><button class="cx">✕</button></td>`;
 tr.querySelector(".cx").onclick=()=>{tr.remove();};
 ["input"].forEach(ev=>tr.querySelectorAll("input").forEach(i=>i.addEventListener("focus",()=>curveEditing=true)));
 return tr;
}
function readPoints(){return [...document.querySelectorAll("#curveRows tr")].map(tr=>[+tr.querySelector(".ct").value,+tr.querySelector(".cp").value]);}
async function curveRefresh(){
 try{const s=await (await fetch("api/curve",{cache:"no-store"})).json();curveCfg=s.cfg;
  const on=!!s.cfg.enabled;const t=document.getElementById("curveToggle");
  t.textContent=on?"Activada":"Desactivada";t.classList.toggle("on",on);
  if(!curveEditing){const tb=document.getElementById("curveRows");tb.innerHTML="";(s.cfg.points||[]).forEach(([a,b])=>tb.appendChild(curveRow(a,b)));}
  document.getElementById("curveState").textContent=on?`${s.applied!=null?s.applied+" %":"—"} · chip ${s.last_temp!=null?s.last_temp.toFixed(0)+" °C":"—"}${s.last_error?" · "+s.last_error:""}`:"";
 }catch(e){}
}
async function curvePost(cfg){
 const r=await fetch("api/curve",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(cfg)});
 const j=await r.json();toast(j.cfg?"Curva guardada ✓":("Error: "+(j.error||r.status)));curveEditing=false;curveRefresh();
}
function wireCurve(){
 document.getElementById("curveToggle").onclick=()=>curvePost({enabled:!(curveCfg&&curveCfg.enabled)});
 document.getElementById("curveAdd").onclick=()=>{curveEditing=true;document.getElementById("curveRows").appendChild(curveRow(75,75));};
 document.getElementById("curveSave").onclick=()=>curvePost({points:readPoints()});
 curveRefresh();setInterval(curveRefresh,5000);
}
if(CONTROL)wire();
wireChartWin();wireLegend();
tick();setInterval(tick,10000);
drawChart();setInterval(drawChart,20000);
let _rz;addEventListener("resize",()=>{clearTimeout(_rz);_rz=setTimeout(drawChart,200);});
</script></body></html>"""


class _Cache:
    def __init__(self, host, ttl=8):
        self.host, self.ttl, self.at, self.data = host, ttl, 0, None
        self.lock = threading.Lock()

    def get(self):
        with self.lock:
            if self.data is None or time.time() - self.at > self.ttl:
                self.data, self.at = collect(self.host), time.time()
            return self.data

    def invalidate(self):
        with self.lock:
            self.at = 0


def serve(host, bind="127.0.0.1", port=8099, control=False, sample_interval=20):
    cache = _Cache(host)
    miner = Miner(host) if control else None
    page = PAGE.replace("__CONTROL__", "true" if control else "false")
    supervisor = None
    if control:
        supervisor = curvemod.Supervisor(miner, cache.get)
        if supervisor.cfg.get("enabled"):
            supervisor.start()

    # Background hashrate sampler: records history even with no browser open,
    # so the graph is continuous. Read-only; just reads the shared snapshot.
    history = History()

    def _sampler():
        while True:
            try:
                history.add(sample_from_snapshot(cache.get()))
            except Exception:
                pass
            time.sleep(sample_interval)

    threading.Thread(target=_sampler, daemon=True).start()

    class H(BaseHTTPRequestHandler):
        def _send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self._send(200, page.encode(), "text/html; charset=utf-8")
            elif self.path == "/api/snapshot":
                self._send(200, json.dumps(cache.get(), ensure_ascii=False).encode(), "application/json")
            elif self.path == "/api/history":
                self._send(200, json.dumps({"samples": history.samples()}).encode(), "application/json")
            elif self.path == "/api/curve" and control:
                self._send(200, json.dumps(supervisor.state()).encode(), "application/json")
            else:
                self.send_error(404)

        def do_POST(self):
            if not control or self.path not in ("/api/control", "/api/curve"):
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/curve":
                    cfg = {k: req[k] for k in ("enabled", "points", "step") if k in req}
                    state = supervisor.update(cfg)
                    cache.invalidate()
                    self._send(200, json.dumps(state).encode(), "application/json")
                    return
                action = req.get("action")
                if action not in ACTIONS:
                    raise ControlError(f"Unknown action {action!r}")
                # A manual fan/mode choice overrides and disables the software curve.
                if action in ("fan", "mode") and supervisor.cfg.get("enabled"):
                    supervisor.update({"enabled": False})
                result = miner.do(action, req.get("arg"))
                cache.invalidate()
                self._send(200, json.dumps(result).encode(), "application/json")
            except ControlError as exc:
                self._send(400, json.dumps({"ok": False, "error": str(exc)}).encode(), "application/json")
            except Exception as exc:
                self._send(502, json.dumps({"ok": False, "error": str(exc)}).encode(), "application/json")

        def log_message(self, *a):
            pass

    mode = "control" if control else "solo lectura"
    print(f"Panel ({mode}) de {host} en http://{bind}:{port}/")
    ThreadingHTTPServer((bind, port), H).serve_forever()
