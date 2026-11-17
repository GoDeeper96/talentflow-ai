"""Tareas del workflow por CV (AWS Step Functions)."""
import io
import json
import os

import boto3
from botocore.exceptions import ClientError

import agents
from common import clean, now, nota_sk, pk_proceso, pk_tenant, table, to_ddb, ttl_epoch
from scoring import anonimizar, calcular

s3 = boto3.client("s3")
BUCKET = os.environ.get("BUCKET_NAME", "")
MIN_CHARS = 200


def _get_text(key):
    return s3.get_object(Bucket=BUCKET, Key=key)["Body"].read().decode("utf-8")


def _put_json(key, data):
    s3.put_object(Bucket=BUCKET, Key=key, Body=json.dumps(data, ensure_ascii=False).encode("utf-8"),
                  ContentType="application/json")


def _base(key):
    # cvs/tenant=t/proceso=p/lote=l/cvId.ext -> procesados/tenant=t/proceso=p/lote=l/cvId
    return "procesados/" + key.split("/", 1)[1].rsplit(".", 1)[0]


def extraer(e, ctx):
    """Carga la rúbrica aprobada y extrae el texto del CV (PDF o TXT)."""
    proc = table().get_item(Key={"PK": pk_tenant(e["tenant"]), "SK": f"PROC#{e['proceso_id']}"}).get("Item")
    if not proc or not (proc.get("rubrica") or {}).get("aprobada"):
        return {**e, "texto_ok": False, "motivo": "El proceso no tiene una rúbrica aprobada"}
    rub = clean(proc["rubrica"])
    e["metricas"] = rub["metricas"]
    e["rubrica_version"] = rub.get("version", 1)
    e["umbral"] = clean(proc.get("umbral", 50))

    obj = s3.get_object(Bucket=BUCKET, Key=e["key"])
    data = obj["Body"].read()
    ext = e["key"].rsplit(".", 1)[-1].lower()
    texto, paginas = "", None
    try:
        if ext == "pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            paginas = len(reader.pages)
            texto = "\n".join((p.extract_text() or "") for p in reader.pages[:15])
        else:
            texto = data.decode("utf-8", errors="replace")
    except Exception as err:  # PDF dañado o cifrado
        return {**e, "texto_ok": False, "motivo": f"No se pudo leer el archivo ({type(err).__name__})"}

    texto = texto.replace("\x00", "").strip()
    base = _base(e["key"])
    s3.put_object(Bucket=BUCKET, Key=base + ".txt", Body=texto.encode("utf-8"), ContentType="text/plain")
    e.update({"texto_key": base + ".txt", "base_key": base, "n_chars": len(texto), "paginas": paginas})
    if len(texto) < MIN_CHARS:
        e.update({"texto_ok": False, "motivo": "Texto insuficiente: posible PDF escaneado (requiere OCR)"})
    else:
        e["texto_ok"] = True
    return e


def perfilar(e, ctx):
    texto = _get_text(e["texto_key"])
    perfil = agents.perfilar(texto)
    if not (perfil.get("experiencias") or perfil.get("formacion") or perfil.get("herramientas")):
        perfil = agents.perfilar(texto)  # segundo intento antes de enviar a revisión humana
    key = e["base_key"] + ".perfil.json"
    _put_json(key, perfil)
    e.update({"perfil_key": key, "candidato": (perfil.get("nombre") or "").strip()[:120],
              "titular": (perfil.get("titular") or "").strip()[:160],
              "perfil_ok": bool(perfil.get("experiencias") or perfil.get("formacion") or perfil.get("herramientas"))})
    if not e["perfil_ok"]:
        e["motivo"] = "La IA no encontró experiencia, formación ni herramientas en el texto"
    return e


def evaluar(e, ctx):
    texto = _get_text(e["texto_key"])
    perfil = json.loads(_get_text(e["perfil_key"]))
    perfil_anon = {k: v for k, v in perfil.items() if k != "nombre"}
    anon = anonimizar(texto, perfil.get("nombre"))
    resultados = agents.evaluar(anon, perfil_anon, e["metricas"])
    key = e["base_key"] + ".evaluacion.json"
    _put_json(key, {"resultados_ia": resultados})
    e["evaluacion_key"] = key
    return e


def calcular_nota(e, ctx):
    """Verificador + calculadora determinista (sin IA)."""
    texto = _get_text(e["texto_key"])
    perfil = json.loads(_get_text(e["perfil_key"]))
    ev = json.loads(_get_text(e["evaluacion_key"]))
    anon = anonimizar(texto, perfil.get("nombre"))
    calc = calcular(e["metricas"], ev["resultados_ia"], texto, anon, umbral=e.get("umbral", 50))
    _put_json(e["evaluacion_key"], {"resultados_ia": ev["resultados_ia"], "calculo": calc})
    e.update({"nota": calc["nota"], "banda": calc["banda"]})
    return e


def entrevistar(e, ctx):
    perfil = json.loads(_get_text(e["perfil_key"]))
    ev = json.loads(_get_text(e["evaluacion_key"]))
    e["preguntas"] = agents.preguntas(perfil, ev["resultados_ia"], e["metricas"])
    return e


def _contadores(e, estado, nota=None):
    t = table()
    pk_t, sk_p = pk_tenant(e["tenant"]), f"PROC#{e['proceso_id']}"
    expr = "ADD cvs_procesados :uno"
    vals = {":uno": 1}
    if estado != "COMPLETADO":
        expr += ", cvs_revision :uno"
    elif nota is not None:
        expr += ", suma_notas :n"
        vals[":n"] = to_ddb(float(nota))
        if nota >= float(e.get("umbral", 50)):
            expr += ", cvs_sobre_umbral :uno"
    t.update_item(Key={"PK": pk_t, "SK": sk_p}, UpdateExpression=expr, ExpressionAttributeValues=vals)
    t.update_item(Key={"PK": pk_proceso(e["tenant"], e["proceso_id"]), "SK": f"LOTE#{e['lote_id']}"},
                  UpdateExpression="ADD procesados :uno", ExpressionAttributeValues={":uno": 1})
    if nota is not None:
        try:
            t.update_item(Key={"PK": pk_t, "SK": sk_p}, UpdateExpression="SET mejor_nota = :n",
                          ConditionExpression="attribute_not_exists(mejor_nota) OR mejor_nota < :n",
                          ExpressionAttributeValues={":n": to_ddb(float(nota))})
        except ClientError as err:
            if err.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise


def guardar(e, ctx):
    ev = json.loads(_get_text(e["evaluacion_key"]))
    calc = ev["calculo"]
    estado = "COMPLETADO"
    item_pk = pk_proceso(e["tenant"], e["proceso_id"])
    table().update_item(
        Key={"PK": item_pk, "SK": f"CV#{e['cv_id']}"},
        UpdateExpression=("SET estado=:s, nota=:n, banda=:b, cobertura=:c, metricas=:m, alertas=:a, "
                          "requiere_revision=:r, preguntas=:q, candidato=:cand, titular=:tit, rubrica_version=:v, "
                          "paginas=:pg, perfil_key=:pk, GSI1PK=:g1, GSI1SK=:g2, actualizado_en=:t, expira_en=:ttl"),
        ExpressionAttributeValues=to_ddb({
            ":s": estado, ":n": float(calc["nota"]), ":b": calc["banda"], ":c": float(calc["cobertura"]),
            ":m": calc["metricas"], ":a": calc["alertas"], ":r": calc["requiere_revision"],
            ":q": e.get("preguntas", []), ":cand": e.get("candidato") or "Sin nombre en el CV",
            ":tit": e.get("titular", ""), ":v": e.get("rubrica_version", 1), ":pg": e.get("paginas"),
            ":pk": e.get("perfil_key", ""), ":g1": item_pk, ":g2": nota_sk(calc["nota"], e["cv_id"]),
            ":t": now(), ":ttl": ttl_epoch(),
        }),
    )
    _contadores(e, estado, calc["nota"])
    return {"cv_id": e["cv_id"], "estado": estado, "nota": calc["nota"]}


def revision(e, ctx):
    return _cerrar_sin_nota(e, "REVISION", e.get("motivo") or "Requiere revisión humana")


def registrar_error(e, ctx):
    err = e.get("error") or {}
    motivo = "Fallo del workflow"
    if isinstance(err, dict) and err.get("Error"):
        motivo += f": {err['Error']}"
    return _cerrar_sin_nota(e, "ERROR", motivo)


def _cerrar_sin_nota(e, estado, motivo):
    table().update_item(
        Key={"PK": pk_proceso(e["tenant"], e["proceso_id"]), "SK": f"CV#{e['cv_id']}"},
        UpdateExpression="SET estado=:s, motivo=:m, candidato=:c, actualizado_en=:t, expira_en=:ttl",
        ExpressionAttributeValues={":s": estado, ":m": motivo[:300], ":c": e.get("candidato") or "Sin nombre",
                                   ":t": now(), ":ttl": ttl_epoch()},
    )
    _contadores(e, estado)
    return {"cv_id": e["cv_id"], "estado": estado, "motivo": motivo}
