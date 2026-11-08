"""Tiny local dashboard. Serves one page and /api/snapshot; only ever reads the miner.

Binds to 127.0.0.1 by default. It has no login, so don't bind it to a public interface.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .collect import collect

PAGE = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>SC5 Pro II</title>
<style>
:root{--bg:#0f1115;--fg:#e8e8ea;--mut:#8b8f98;--card:#181b22;--ok:#3fb950;--warn:#d29922;--bad:#f85149}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,sans-serif}
main{max-width:960px;margin:auto;padding:16px}h1{font-size:18px;margin:0 0 4px}
.mut{color:var(--mut)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:12px 0}
.card{background:var(--card);border-radius:10px;padding:12px}.big{font-size:26px;font-weight:600}
table{width:100%;border-collapse:collapse}td,th{padding:6px;text-align:left;border-bottom:1px solid #262a33}
th{color:var(--mut);font-weight:500}.w{color:var(--warn)}.b{color:var(--bad)}.o{color:var(--ok)}
</style></head><body><main>
<h1 id="dev">SC5 Pro II</h1><div class="mut" id="sub">cargando…</div>
<div class="grid" id="kpi"></div>
<div class="card"><table><thead><tr><th>Placa</th><th>Estado</th><th>TH/s</th><th>MHz</th><th>V</th><th>°C</th><th>Ventiladores</th><th>HW %</th></tr></thead><tbody id="boards"></tbody></table></div>
<div class="card" style="margin-top:12px"><table><thead><tr><th></th><th>Pool</th><th>Usuario</th><th>Estado</th><th>Acept.</th><th>Rech.</th></tr></thead><tbody id="pools"></tbody></table></div>
<div id="warn" style="margin-top:12px"></div>
<p class="mut">Solo lectura: este panel nunca cambia nada en el minero.</p>
</main><script>
const esc=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const tc=t=>t>=90?"b":t>=80?"w":"o";
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
 }catch(e){document.getElementById("sub").textContent="sin datos: "+e}
}
tick();setInterval(tick,10000);
</script></body></html>"""


class _Cache:
    def __init__(self, host, ttl=8):
        self.host, self.ttl, self.at, self.data = host, ttl, 0, None
        self.lock = threading.Lock()

    def get(self):
        with self.lock:  # one miner query at a time, whatever the number of browsers
            if self.data is None or time.time() - self.at > self.ttl:
                self.data, self.at = collect(self.host), time.time()
            return self.data


def serve(host, bind="127.0.0.1", port=8099):
    cache = _Cache(host)

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ("/", "/index.html"):
                body, ctype = PAGE.encode(), "text/html; charset=utf-8"
            elif self.path == "/api/snapshot":
                body, ctype = json.dumps(cache.get(), ensure_ascii=False).encode(), "application/json"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    print(f"Read-only dashboard for {host} on http://{bind}:{port}/")
    ThreadingHTTPServer((bind, port), H).serve_forever()
