"""Lógica determinista (sin IA): anonimización, verificación de citas y cálculo de la nota."""
import re
import unicodedata

_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_RE_TEL = re.compile(r"(\+?51[\s-]?)?\b9\d{2}[\s-]?\d{3}[\s-]?\d{3}\b")
_RE_DNI = re.compile(r"\b(DNI|D\.N\.I\.?|documento)\s*[:#Nº°n]*\s*\d{8}\b", re.I)
_RE_FECHA_NAC = re.compile(r"(fecha de nacimiento|nacimiento|edad|estado civil|sexo|g[eé]nero)\s*[:\-]?\s*[^\n]{0,40}", re.I)
_RE_URL = re.compile(r"https?://\S+|linkedin\.com/\S+", re.I)


def anonimizar(texto, nombre=None):
    """Quita datos personales directos antes de enviar el CV al agente evaluador."""
    t = _RE_EMAIL.sub("[correo]", texto)
    t = _RE_DNI.sub("[documento]", t)
    t = _RE_TEL.sub("[teléfono]", t)
    t = _RE_FECHA_NAC.sub("[dato personal omitido]", t)
    t = _RE_URL.sub("[enlace]", t)
    if nombre and len(nombre.strip()) >= 4:
        for parte in {nombre.strip(), *[p for p in nombre.split() if len(p) >= 4]}:
            t = re.sub(re.escape(parte), "[postulante]", t, flags=re.I)
    return t


def _norm(s):
    s = unicodedata.normalize("NFKC", s or "").casefold()
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip(" .;,\"'")


def cita_en_texto(cita, texto_norm):
    """True si la cita aparece literal (ignorando mayúsculas, espacios y comillas)."""
    c = _norm(cita)
    if len(c) < 6:
        return False
    if c in texto_norm:
        return True
    # Tolerancia: el modelo a veces une fragmentos con '...'
    partes = [p for p in re.split(r"\s*(?:\.\.\.|…)\s*", c) if len(p) >= 12]
    return bool(partes) and all(p in texto_norm for p in partes)


def banda(nota, umbral=50):
    if nota >= 75:
        return "ALTA"
    if nota >= umbral:
        return "MEDIA"
    return "BAJA"


def calcular(metricas, resultados, texto_original, texto_anonimo=None, umbral=50):
    """Verifica citas y calcula la nota ponderada.

    nota = 100 * sum(L_i * n_i) / sum(L_i * 4)
    """
    textos = [_norm(texto_original)]
    if texto_anonimo:
        textos.append(_norm(texto_anonimo))
    por_id = {}
    for r in resultados or []:
        if isinstance(r, dict) and r.get("metrica_id") and r["metrica_id"] not in por_id:
            por_id[r["metrica_id"]] = r

    detalle, alertas = [], []
    suma, maximo, con_evidencia = 0, 0, 0
    for m in metricas:
        L = int(m.get("importancia", 3))
        r = por_id.get(m["id"], {})
        try:
            nivel = max(0, min(4, int(r.get("nivel", 0))))
        except (TypeError, ValueError):
            nivel = 0
        cita = str(r.get("cita") or "").strip()[:300]
        verificada = bool(cita) and any(cita_en_texto(cita, t) for t in textos)
        estado = "evidenciado"
        if nivel > 0 and not verificada:
            nivel, estado = 0, "por verificar"
            alertas.append(f"{m['nombre']}: la IA asignó nivel sin cita literal; queda por verificar")
            cita = ""
        elif nivel == 0:
            estado = "sin evidencia"
            cita = cita if verificada else ""
        if nivel > 0:
            con_evidencia += 1
        declarado = bool(r.get("declarado_sin_verificar")) and nivel > 0
        if declarado:
            estado = "declarado"
        excluyente_falla = bool(m.get("excluyente")) and nivel == 0
        if excluyente_falla:
            alertas.append(f"Excluyente sin evidencia: {m['nombre']} (revisión humana)")
        suma += L * nivel
        maximo += L * 4
        detalle.append({
            "metrica_id": m["id"], "nombre": m["nombre"], "tipo": m.get("tipo", "otra"),
            "importancia": L, "nivel": nivel, "estado": estado, "cita": cita,
            "justificacion": str(r.get("justificacion") or "")[:400],
            "excluyente": bool(m.get("excluyente")), "aporte": round(100 * L * nivel / maximo_total(metricas), 2),
        })
    nota = round(100 * suma / maximo, 2) if maximo else 0.0
    cobertura = round(100 * con_evidencia / len(metricas), 1) if metricas else 0.0
    return {
        "nota": nota, "banda": banda(nota, umbral), "cobertura": cobertura,
        "metricas": detalle, "alertas": alertas,
        "requiere_revision": any(d["excluyente"] and d["nivel"] == 0 for d in detalle),
    }


def maximo_total(metricas):
    return sum(int(m.get("importancia", 3)) * 4 for m in metricas) or 1
