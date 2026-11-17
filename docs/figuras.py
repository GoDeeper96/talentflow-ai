"""Genera las figuras del informe (arquitectura AWS y workflow de Step Functions) en docs/img."""
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = os.path.join(os.path.dirname(__file__), "img")
os.makedirs(OUT, exist_ok=True)

C = {"front": "#E8F1FB", "api": "#FDEBD7", "data": "#E6F4EA", "flow": "#F3E8FD", "ext": "#FCE8E6", "sec": "#EEF0F2"}
B = {"front": "#1A73E8", "api": "#E8710A", "data": "#188038", "flow": "#8430CE", "ext": "#C5221F", "sec": "#5F6368"}


def caja(ax, x, y, w, h, titulo, sub, k):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.12",
                                fc=C[k], ec=B[k], lw=1.6))
    ax.text(x + w / 2, y + h * 0.63, titulo, ha="center", va="center", fontsize=9.5, weight="bold", color="#202124")
    if sub:
        ax.text(x + w / 2, y + h * 0.28, sub, ha="center", va="center", fontsize=7.4, color="#3C4043")
    return (x, y, w, h)


def flecha(ax, a, b, txt="", lado="r", color="#5F6368", rad=0.0, dy=0.0):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=12, lw=1.3, color=color,
                                 connectionstyle=f"arc3,rad={rad}"))
    if txt:
        mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + dy
        ax.text(mx, my, txt, fontsize=7, color="#3C4043", ha="center", va="bottom",
                bbox=dict(fc="white", ec="none", pad=0.6))


def arquitectura():
    fig, ax = plt.subplots(figsize=(13, 7.4))
    ax.set_xlim(0, 13); ax.set_ylim(0, 7.4); ax.axis("off")
    ax.add_patch(FancyBboxPatch((2.05, 0.15), 10.8, 6.55, boxstyle="round,pad=0.02,rounding_size=0.15",
                                fc="none", ec="#9AA0A6", lw=1.2, ls="--"))
    ax.text(2.2, 6.55, "AWS · us-east-1 (N. Virginia) · serverless", fontsize=9, color="#5F6368", weight="bold")

    ax.text(0.95, 6.1, "Usuarios", ha="center", fontsize=9, weight="bold")
    caja(ax, 0.15, 4.95, 1.6, 0.95, "Analista RR. HH.", "reclutador / admin", "sec")
    caja(ax, 0.15, 3.75, 1.6, 0.95, "Líder de área", "solo su área", "sec")
    caja(ax, 0.15, 0.35, 1.6, 0.95, "Groq API", "openai/gpt-oss-120b\nsin memoria", "ext")

    caja(ax, 2.4, 5.35, 2.0, 0.95, "Amplify Hosting", "React + Vite (SPA)", "front")
    caja(ax, 2.4, 3.95, 2.0, 0.95, "Amazon Cognito", "JWT · tenant_id · grupos", "front")
    caja(ax, 4.9, 5.35, 2.1, 0.95, "API Gateway HTTP", "autorizador JWT", "api")
    caja(ax, 7.5, 5.35, 2.0, 0.95, "Lambda API", "12 rutas /v1", "api")
    caja(ax, 10.2, 5.35, 2.4, 0.95, "DynamoDB", "tabla única talentflow\n+ GSI1 ranking", "data")
    caja(ax, 4.9, 3.75, 2.1, 0.95, "Amazon S3", "cvs/tenant=…/proceso=…", "data")
    caja(ax, 7.5, 3.75, 2.0, 0.95, "Amazon SQS", "talentflow-cvs + DLQ", "api")
    caja(ax, 10.2, 3.75, 2.4, 0.95, "Lambda despachador", "máx. 4 en paralelo", "api")
    caja(ax, 4.9, 0.45, 7.7, 2.75, "", "", "flow")
    ax.text(8.75, 2.95, "AWS Step Functions · talentflow-evaluacion-cv (1 ejecución por CV)", ha="center",
            fontsize=9.3, weight="bold", color="#5B1F99")
    pasos = [("Extraer\ntexto", "pypdf"), ("Agente\nPerfilador", "Groq"), ("Agente\nEvaluador", "Groq"),
             ("Verificar y\ncalcular", "código"), ("Agente\nEntrevistador", "Groq"), ("Guardar\nexpediente", "DynamoDB")]
    xs = [5.05 + i * 1.26 for i in range(6)]
    for x, (t, s) in zip(xs, pasos):
        ax.add_patch(FancyBboxPatch((x, 1.55), 1.08, 0.95, boxstyle="round,pad=0.02,rounding_size=0.08",
                                    fc="white", ec=B["flow"], lw=1.2))
        ax.text(x + 0.54, 2.12, t, ha="center", va="center", fontsize=7.4, weight="bold")
        ax.text(x + 0.54, 1.68, s, ha="center", va="center", fontsize=6.6, color="#5F6368")
    for a, b in zip(xs[:-1], xs[1:]):
        flecha(ax, (a + 1.08, 2.02), (b, 2.02), color=B["flow"])
    ax.text(8.75, 0.95, "Retry 429 (15 s, ×2, 6 intentos) · Catch → RegistrarError · sin texto / perfil inválido → Revisión humana",
            ha="center", fontsize=7.3, color="#5B1F99")
    caja(ax, 2.4, 2.35, 2.0, 0.85, "Secrets Manager", "clave de Groq", "sec")
    caja(ax, 2.4, 1.15, 2.0, 0.85, "CloudWatch", "logs y métricas", "sec")

    flecha(ax, (1.75, 5.45), (2.4, 5.8), "HTTPS")
    flecha(ax, (1.75, 4.2), (2.4, 4.4))
    flecha(ax, (3.4, 5.35), (3.4, 4.9), "login", dy=-0.1)
    flecha(ax, (4.4, 5.82), (4.9, 5.82), "JWT")
    flecha(ax, (7.0, 5.82), (7.5, 5.82))
    flecha(ax, (9.5, 5.82), (10.2, 5.82), "CRUD / query")
    flecha(ax, (4.4, 5.55), (4.9, 4.45), "PUT prefirmado", rad=0.0, dy=0.05)
    flecha(ax, (7.0, 4.22), (7.5, 4.22), "evento")
    flecha(ax, (9.5, 4.22), (10.2, 4.22), "mensaje")
    flecha(ax, (11.4, 3.75), (11.4, 3.2), "StartExecution", dy=-0.05)
    flecha(ax, (8.5, 5.35), (6.2, 4.7), "URL prefirmada", rad=0.15)
    flecha(ax, (12.3, 1.55), (12.3, 5.35), "", color=B["data"], rad=-0.25)
    ax.text(12.85, 3.45, "notas y\nexpediente", fontsize=6.8, color=B["data"], ha="center")
    flecha(ax, (5.6, 1.55), (5.6, 3.75), "", color=B["data"])
    ax.text(5.15, 3.4, "texto/perfil", fontsize=6.6, color=B["data"])
    flecha(ax, (4.9, 0.8), (1.75, 0.8), "inferencia (LangChain)", color=B["ext"])
    fig.savefig(os.path.join(OUT, "arquitectura.png"), dpi=300, bbox_inches="tight")
    plt.close(fig)


def workflow():
    fig, ax = plt.subplots(figsize=(8.6, 11))
    ax.set_xlim(0, 8.6); ax.set_ylim(0, 11); ax.axis("off")
    def nodo(y, t, s, k="flow", x=2.0, w=4.6):
        return caja(ax, x, y, w, 0.82, t, s, k)
    def rombo(y, t):
        cx, cy = 4.3, y + 0.4
        ax.add_patch(plt.Polygon([(cx, cy + 0.45), (cx + 1.6, cy), (cx, cy - 0.45), (cx - 1.6, cy)],
                                 fc="#FFF8E1", ec="#F9AB00", lw=1.4))
        ax.text(cx, cy, t, ha="center", va="center", fontsize=8.2, weight="bold")
    ax.text(4.3, 10.75, "Inicio: mensaje SQS → despachador → StartExecution(name = cvId)", ha="center", fontsize=8.5)
    nodo(9.65, "ExtraerTexto (Lambda)", "carga rúbrica aprobada · pypdf ≤ 15 págs. · guarda .txt en S3")
    rombo(8.55, "¿TextoUtilizable? (≥ 200 car.)")
    nodo(7.35, "AgentePerfilador (Groq)", "CV → JSON PerfilCV (LangChain + Pydantic)")
    rombo(6.25, "¿PerfilValido?")
    nodo(5.05, "AgenteEvaluador (Groq)", "texto anonimizado · nivel 0–4 + cita literal por métrica")
    nodo(3.85, "VerificarYCalcular (código)", "cita no encontrada → nivel 0 · nota ponderada · banda", "data")
    nodo(2.65, "AgenteEntrevistador (Groq)", "preguntas para validar lo declarado")
    nodo(1.45, "GuardarExpediente (Lambda)", "CV COMPLETADO · GSI1 ranking · contadores", "data")
    caja(ax, 6.75, 7.9, 1.75, 0.82, "Revisión", "requiere OCR /\nrevisión humana", "sec")
    caja(ax, 0.1, 4.45, 1.75, 0.82, "RegistrarError", "Catch de\ncualquier paso", "ext")
    for y1, y2 in [(9.65, 9.35), (8.55, 8.17), (7.35, 7.1), (6.25, 5.87), (5.05, 4.67), (3.85, 3.47), (2.65, 2.27)]:
        flecha(ax, (4.3, y1), (4.3, y2))
    ax.text(4.45, 8.25, "sí", fontsize=7.5); ax.text(4.45, 6.0, "sí", fontsize=7.5)
    flecha(ax, (5.9, 8.95), (6.75, 8.4), "no", dy=0.02)
    flecha(ax, (5.9, 6.65), (7.6, 7.9), "no", dy=0.02)
    flecha(ax, (6.3, 3.06), (6.3, 1.9), "falla → continúa", rad=-0.4)
    flecha(ax, (2.3, 5.45), (1.85, 4.95), "", color=B["ext"])
    ax.text(1.0, 3.9, "Retry GroqRateLimit:\n15 s · backoff 2 · 6 intentos", fontsize=7.2, ha="center", color="#5B1F99")
    ax.text(4.3, 1.0, "Fin: el dashboard consulta GSI1 (nota ≥ umbral, descendente)", ha="center", fontsize=8.5)
    fig.savefig(os.path.join(OUT, "workflow.png"), dpi=300, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    arquitectura()
    workflow()
    print("ok", os.listdir(OUT))
