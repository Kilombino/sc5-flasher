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

PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SC5 Pro II</title>
<style>
:root{--bg:#0c0e13;--fg:#e8e8ea;--mut:#8b8f98;--card:#161922;--line:#262a33;--acc:#5aa9ff;--ok:#3fb950;--warn:#d29922;--bad:#f85149}
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
.toast.show{opacity:1}.lbl{color:var(--mut);font-size:12px;margin-right:6px}
</style></head><body><main>
<h1 id="dev">SC5 Pro II</h1><div class="sub" id="sub">cargando…</div>

<div class="grid" id="kpi"></div>

<div class="card"><table><thead><tr><th>Placa</th><th>Estado</th><th>TH/s</th><th>MHz</th><th>V</th><th>°C</th><th>Ventiladores</th><th>HW %</th></tr></thead><tbody id="boards"></tbody></table></div>

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
 <div class="row" style="margin-bottom:12px"><span class="lbl">Ventilador por temperatura</span>
  <button id="tempctl" data-act="tempcontrol">—</button>
  <span class="lbl" style="margin-left:14px">LED de identificación</span>
  <button id="led" data-act="led">—</button>
 </div>
 <div class="row"><span class="lbl">Reiniciar el minero (~1-2 min sin minar)</span>
  <button id="reboot" class="danger">Reiniciar…</button>
 </div>
</div>
</div>

<h2>Pools</h2>
<div class="card"><table><thead><tr><th></th><th>Pool</th><th>Usuario</th><th>Estado</th><th>Acept.</th><th>Rech.</th></tr></thead><tbody id="pools"></tbody></table></div>

<div id="warn" style="margin-top:12px"></div>
<p class="mut" style="margin-top:18px">Solo acciones reversibles y de fábrica. Nunca firmware ni reset de fábrica.</p>
</main>
<div class="toast" id="toast"></div>
<script>
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const tc=t=>t>=90?"b":t>=80?"w":"o";
const CONTROL=__CONTROL__;
let busy=false,lastMode=null;
function toast(m){const t=document.getElementById("toast");t.textContent=m;t.classList.add("show");clearTimeout(t._h);t._h=setTimeout(()=>t.classList.remove("show"),3500);}
async function tick(){
 try{
  const s=await (await fetch("api/snapshot",{cache:"no-store"})).json();
  const d=s.device||{},su=s.summary||{};
  document.getElementById("dev").textContent=`${d.model||"?"} · fw ${d.firmware||"?"} · ${d.board||"?"}`;
  const up=su.uptime_s||0;
  document.getElementById("sub").textContent=`${d.miner||""} · encendido ${Math.floor(up/3600)} h ${Math.floor(up%3600/60)} min · ${s.algorithm||""} · ${s.power?.plan||""}`;
  const k=[["Hashrate 20 s",(su.ths_20s||0).toFixed(2)+" TH/s"],["Media",(su.ths_avg||0).toFixed(2)+" TH/s"],["Errores HW",(su.hw_pct??"?")+" %"],["Rechazadas",(su.reject_pct??"?")+" %"]];
  document.getElementById("kpi").innerHTML=k.map(([a,b])=>`<div class="card"><div class="mut">${a}</div><div class="big">${esc(b)}</div></div>`).join("");
  document.getElementById("boards").innerHTML=(s.boards||[]).map(b=>`<tr><td>${esc(b.id)}</td><td class="${b.status==="Alive"?"o":"b"}">${esc(b.status)}</td><td>${b.ths_20s.toFixed(2)}</td><td>${esc(b.clock_mhz)}</td><td>${((b.voltage_mv||0)/1000).toFixed(2)}</td><td>${b.temps_c.map(t=>`<span class="${tc(t)}">${t.toFixed(0)}</span>`).join(" / ")}</td><td>${esc(b.fans_rpm.join(" "))}</td><td>${esc(b.hw_pct)}</td></tr>`).join("");
  document.getElementById("pools").innerHTML=(s.pools||[]).map(p=>`<tr><td>${p.active?"●":""}</td><td>${esc(p.url)}</td><td>${esc(p.user)}</td><td>${esc(p.status)}</td><td>${esc(p.accepted)}</td><td>${esc(p.rejected)}</td></tr>`).join("");
  document.getElementById("warn").innerHTML=[...(s.warnings||[]).map(w=>`<div class="w">⚠ ${esc(w)}</div>`),...(s.errors||[]).map(e=>`<div class="b">✖ ${esc(e)}</div>`)].join("");
  if(CONTROL){
   document.getElementById("controls").style.display="block";
   const sel=s.power?.select;lastMode=sel;
   document.querySelectorAll("#modes button").forEach(x=>x.classList.toggle("on",{hash:0,eco:2,idle:3}[x.dataset.mode]===sel));
   const tcb=document.getElementById("tempctl");tcb.textContent=s.power?.temp_control?"Activado":"Desactivado";tcb.classList.toggle("on",!!s.power?.temp_control);
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
function wire(){
 document.querySelectorAll("#modes button").forEach(b=>b.onclick=()=>send("mode",b.dataset.mode,
   b.dataset.mode==="idle"?"¿Poner el minero en REPOSO? Dejará de minar hasta que lo saques de reposo.":null));
 const tcb=document.getElementById("tempctl");tcb.onclick=()=>send("tempcontrol",!tcb.classList.contains("on"));
 const led=document.getElementById("led");led.onclick=()=>send("led",!led.classList.contains("on"));
 document.getElementById("reboot").onclick=()=>send("reboot",null,"¿Reiniciar el minero? Estará ~1-2 min sin minar y volverá solo.");
}
if(CONTROL)wire();
tick();setInterval(tick,10000);
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


def serve(host, bind="127.0.0.1", port=8099, control=False):
    cache = _Cache(host)
    miner = Miner(host) if control else None
    page = PAGE.replace("__CONTROL__", "true" if control else "false")

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
            else:
                self.send_error(404)

        def do_POST(self):
            if self.path != "/api/control" or not control:
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(length) or b"{}")
                action = req.get("action")
                if action not in ACTIONS:
                    raise ControlError(f"Unknown action {action!r}")
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
