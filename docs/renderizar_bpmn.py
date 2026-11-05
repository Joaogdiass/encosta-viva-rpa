"""Desenha docs/processo_to_be.bpmn em assets/fluxo_bpmn.png com o bpmn-js e o Edge sem janela."""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
NAVEGADOR = os.environ.get("NAVEGADOR", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
LARGURA, ALTURA = 1680, 1050

xml = (RAIZ / "docs" / "processo_to_be.bpmn").read_text(encoding="utf-8")
pagina = f"""<!doctype html><html><head><meta charset="utf-8">
<style>html,body,#tela{{margin:0;height:100%;background:#fff}}</style>
<script src="https://unpkg.com/bpmn-js@17.11.1/dist/bpmn-viewer.production.min.js"></script></head>
<body><div id="tela"></div><pre id="resultado" style="display:none"></pre><script>
new BpmnJS({{container:"#tela"}}).importXML({json.dumps(xml)}).then(({{warnings}})=>{{
  document.getElementById("resultado").textContent="AVISOS:"+JSON.stringify(warnings.map(w=>w.message));
}}).catch(e=>{{document.getElementById("resultado").textContent="ERRO:"+e.message;}});
</script></body></html>"""

with tempfile.TemporaryDirectory() as pasta:
    html = Path(pasta) / "bpmn.html"
    html.write_text(pagina, encoding="utf-8")
    base = [NAVEGADOR, "--headless=new", "--disable-gpu", f"--user-data-dir={pasta}/perfil",
            f"--window-size={LARGURA},{ALTURA}", "--force-device-scale-factor=2", "--virtual-time-budget=15000"]
    dom = subprocess.run([*base, "--dump-dom", html.as_uri()], capture_output=True, text=True, encoding="utf-8", timeout=120).stdout
    achado = re.search(r'id="resultado"[^>]*>(.*?)</pre>', dom, re.S)
    print(achado.group(1) if achado else "sem resultado do bpmn-js")
    destino = RAIZ / "assets" / "fluxo_bpmn.png"
    subprocess.run([*base, f"--screenshot={destino}", html.as_uri()], capture_output=True, timeout=120)
    print(destino, destino.stat().st_size)
    if achado is None or achado.group(1).startswith("ERRO"):
        sys.exit(1)
