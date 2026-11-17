"""Prueba de extremo a extremo contra la API desplegada.

Uso: python scripts/prueba_e2e.py [--sin-ia] [--esperar]
 1. Login en Cognito (empresa Nova) y verificación de aislamiento con Andes.
 2. Crea el proceso 'Analista de Datos' con funciones y CV modelo.
 3. Pide a la IA la propuesta de métricas, ajusta importancias y aprueba la rúbrica.
 4. Sube los CVs de samples/cvs a S3 (URLs prefirmadas) y espera el ranking.
"""
import argparse
import glob
import json
import os
import time
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT = json.load(open(os.path.join(ROOT, "build", "outputs.json"), encoding="utf-8"))["TalentFlowAI"]
CREDS = {l.split()[-2]: l.split()[-1] for l in open(os.path.join(ROOT, "build", "credenciales_demo.txt"), encoding="utf-8") if l.strip()}
CT = {"pdf": "application/pdf", "txt": "text/plain", "md": "text/markdown"}


def http(method, url, body=None, headers=None, raw=False):
    data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            content = r.read()
            return r.status, (content if raw else json.loads(content or b"{}"))
    except urllib.error.HTTPError as e:
        txt = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(txt)
        except json.JSONDecodeError:
            return e.code, {"raw": txt[:300]}


def login(email):
    s, d = http("POST", "https://cognito-idp.us-east-1.amazonaws.com/",
                {"AuthFlow": "USER_PASSWORD_AUTH", "ClientId": OUT["ClientId"],
                 "AuthParameters": {"USERNAME": email, "PASSWORD": CREDS[email]}},
                {"Content-Type": "application/x-amz-json-1.1", "X-Amz-Target": "AWSCognitoIdentityProviderService.InitiateAuth"})
    assert s == 200, d
    return d["AuthenticationResult"]["IdToken"]


def cliente(token):
    def call(method, path, body=None):
        h = {"Authorization": f"Bearer {token}"}
        if body is not None:
            h["Content-Type"] = "application/json"
        return http(method, OUT["ApiUrl"] + path, body, h)
    return call


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sin-ia", action="store_true", help="No llama a Groq (rúbrica manual)")
    ap.add_argument("--esperar", action="store_true", help="Espera a que termine la evaluación")
    a = ap.parse_args()

    nova = cliente(login("analista@nova.example.com"))
    andes = cliente(login("analista@andes.example.com"))
    print("me:", nova("GET", "/v1/me"))

    vac = json.load(open(os.path.join(ROOT, "samples", "vacante_analista_datos.json"), encoding="utf-8"))
    s, p = nova("POST", "/v1/procesos", vac)
    assert s == 201, p
    pid = p["id"]
    print("proceso creado:", pid)

    s, d = andes("GET", f"/v1/procesos/{pid}")
    print("aislamiento (Andes pide proceso de Nova):", s, d)
    assert s == 404

    if a.sin_ia:
        metricas = [
            {"nombre": "Experiencia en análisis de datos", "tipo": "experiencia", "importancia": 5},
            {"nombre": "Power BI y SQL", "tipo": "herramientas", "importancia": 5},
            {"nombre": "Logros cuantificados", "tipo": "logros", "importancia": 4},
            {"nombre": "Inglés", "tipo": "idiomas", "importancia": 2},
        ]
        for m in metricas:
            m["niveles"] = ["Sin evidencia", "Mencionado", "Aplicado en un trabajo", "Aplicado con responsabilidad", "Con logro cuantificado o certificación"]
        s, d = nova("PUT", f"/v1/procesos/{pid}", {"metricas": metricas})
    else:
        t0 = time.time()
        s, d = nova("POST", f"/v1/procesos/{pid}/rubrica/proponer")
        print(f"propuesta IA ({time.time() - t0:.1f}s):", s)
        assert s == 200, d
        for m in d["metricas"]:
            print(f"  - [{m['tipo']}] {m['nombre']} (L{m['importancia']}){' EXCLUYENTE' if m['excluyente'] else ''}")
    s, d = nova("POST", f"/v1/procesos/{pid}/rubrica/aprobar")
    assert s == 200, d
    print("rúbrica aprobada v", d["rubrica"]["version"])

    archivos = sorted(glob.glob(os.path.join(ROOT, "samples", "cvs", "*")))
    s, lote = nova("POST", f"/v1/procesos/{pid}/lotes",
                   {"archivos": [{"nombre": os.path.basename(f), "tamano": os.path.getsize(f)} for f in archivos]})
    assert s == 201, lote
    por_nombre = {os.path.basename(f): f for f in archivos}
    for sub in lote["subidas"]:
        st, _ = http("PUT", sub["url"], open(por_nombre[sub["nombre"]], "rb").read(), {"Content-Type": sub["content_type"]}, raw=True)
        assert st == 200, st
    print(f"lote {lote['lote_id']}: {len(lote['subidas'])} CVs subidos")

    if not a.esperar:
        print("PROCESO_ID", pid)
        return
    for _ in range(90):
        time.sleep(10)
        _, p = nova("GET", f"/v1/procesos/{pid}")
        print(f"  estado {p['estado']}: {p['cvs_procesados']}/{p['cvs_recibidos']}")
        if p["estado"] == "LISTO" and p["cvs_recibidos"] >= len(lote["subidas"]):
            break
    _, todos = nova("GET", f"/v1/procesos/{pid}/postulantes")
    _, rk = nova("GET", f"/v1/procesos/{pid}/postulantes?min={p['umbral']}")
    print(f"\nRanking >= {p['umbral']}% ({len(rk['items'])} de {len(todos['items'])}):")
    for i in todos["items"]:
        print(f"  {i.get('nota', '-'):>6} {i.get('banda', ''):<6} {i.get('estado'):<11} {i.get('candidato', '')[:30]:<30} {i.get('motivo', '')}")
    print("PROCESO_ID", pid)


if __name__ == "__main__":
    main()
