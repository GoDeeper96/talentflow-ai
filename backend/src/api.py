"""API REST de TalentFlow AI (API Gateway HTTP API + JWT de Cognito)."""
import csv
import io
import json
import os
import re
import uuid

import boto3
from boto3.dynamodb.conditions import Key

from common import (TIPOS_METRICA, clean, estado_proceso, identidad, now, pk_proceso, pk_tenant,
                    reply, table, ttl_epoch)

s3 = boto3.client("s3", config=boto3.session.Config(signature_version="s3v4"))
BUCKET = os.environ.get("BUCKET_NAME", "")
EXT_PERMITIDAS = {"pdf": "application/pdf", "txt": "text/plain", "md": "text/markdown"}
MAX_ARCHIVOS_LOTE = 200


class HttpError(Exception):
    def __init__(self, status, msg):
        self.status, self.msg = status, msg


def _body(event):
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise HttpError(400, "JSON inválido")


def _txt(v, maxlen, campo, requerido=False):
    s = str(v or "").strip()
    if requerido and not s:
        raise HttpError(400, f"El campo '{campo}' es obligatorio")
    return s[:maxlen]


def _get_proceso(ident, pid):
    item = table().get_item(Key={"PK": pk_tenant(ident.tenant), "SK": f"PROC#{pid}"}).get("Item")
    if not item or not ident.puede_ver_proceso(item):
        raise HttpError(404, "Proceso no encontrado")
    return item


def _vista_proceso(p, detalle=False):
    p = clean(p)
    procesados = p.get("cvs_procesados", 0)
    completados = procesados - p.get("cvs_revision", 0)
    out = {
        "id": p["id"], "titulo": p["titulo"], "area": p.get("area", ""), "apertura": p.get("apertura"),
        "cierre": p.get("cierre"), "estado": estado_proceso(p), "umbral": p.get("umbral", 50),
        "cvs_recibidos": p.get("cvs_recibidos", 0), "cvs_procesados": procesados,
        "cvs_revision": p.get("cvs_revision", 0), "cvs_sobre_umbral": p.get("cvs_sobre_umbral", 0),
        "mejor_nota": p.get("mejor_nota"),
        "nota_promedio": round(p.get("suma_notas", 0) / completados, 1) if completados > 0 else None,
        "rubrica_aprobada": bool((p.get("rubrica") or {}).get("aprobada")),
        "responsable": p.get("creado_por", ""), "creado_en": p.get("creado_en"), "actualizado_en": p.get("actualizado_en"),
    }
    if detalle:
        out.update({"funciones": p.get("funciones", ""), "cv_modelo": p.get("cv_modelo", ""),
                    "rubrica": p.get("rubrica") or {"version": 0, "aprobada": False, "metricas": []}})
    return out


def _validar_metricas(metricas, estricto=False):
    if not isinstance(metricas, list) or len(metricas) > 15:
        raise HttpError(400, "La rúbrica admite hasta 15 métricas")
    out = []
    for i, m in enumerate(metricas):
        if not isinstance(m, dict):
            raise HttpError(400, f"Métrica {i + 1} inválida")
        nombre = _txt(m.get("nombre"), 120, f"métrica {i + 1}: nombre", requerido=True)
        tipo = m.get("tipo") if m.get("tipo") in TIPOS_METRICA else "otra"
        try:
            imp = int(m.get("importancia", m.get("importancia_sugerida", 0)))
        except (TypeError, ValueError):
            imp = 0
        if estricto and not 1 <= imp <= 5:
            raise HttpError(400, f"Asigna una importancia de 1 a 5 a la métrica '{nombre}'")
        niveles = [str(x).strip()[:300] for x in (m.get("niveles") or [])][:5]
        if estricto and (len(niveles) != 5 or not all(niveles)):
            raise HttpError(400, f"La métrica '{nombre}' necesita los 5 descriptores de nivel (0 a 4)")
        out.append({"id": str(m.get("id") or f"m{uuid.uuid4().hex[:8]}"), "nombre": nombre,
                    "descripcion": _txt(m.get("descripcion"), 400, "descripcion"), "tipo": tipo,
                    "importancia": max(0, min(5, imp)), "excluyente": bool(m.get("excluyente")),
                    "niveles": niveles, "origen": m.get("origen", "empresa")})
    return out


# ---------------- Rutas ----------------
def me(ident, **_):
    emp = table().get_item(Key={"PK": pk_tenant(ident.tenant), "SK": "META"}).get("Item") or {}
    return 200, {"email": ident.email, "rol": ident.rol, "area": ident.area, "empresa_id": ident.tenant,
                 "empresa": emp.get("nombre", ident.tenant)}


def listar_procesos(ident, event, **_):
    items, kwargs = [], {"KeyConditionExpression": Key("PK").eq(pk_tenant(ident.tenant)) & Key("SK").begins_with("PROC#")}
    while True:
        res = table().query(**kwargs)
        items += res.get("Items", [])
        if "LastEvaluatedKey" not in res:
            break
        kwargs["ExclusiveStartKey"] = res["LastEvaluatedKey"]
    q = (event.get("queryStringParameters") or {})
    vistas = [_vista_proceso(p) for p in items if ident.puede_ver_proceso(p)]
    if q.get("estado"):
        vistas = [v for v in vistas if v["estado"] == q["estado"]]
    if q.get("area"):
        vistas = [v for v in vistas if v["area"].lower() == q["area"].lower()]
    vistas.sort(key=lambda v: v.get("creado_en") or "", reverse=True)
    return 200, {"items": vistas}


def crear_proceso(ident, event, **_):
    if not ident.puede_editar():
        raise HttpError(403, "Tu rol no puede crear procesos")
    b = _body(event)
    pid = uuid.uuid4().hex[:12]
    item = {
        "PK": pk_tenant(ident.tenant), "SK": f"PROC#{pid}", "id": pid,
        "titulo": _txt(b.get("titulo"), 150, "titulo", True), "area": _txt(b.get("area"), 80, "area"),
        "apertura": _txt(b.get("apertura"), 10, "apertura") or now()[:10], "cierre": _txt(b.get("cierre"), 10, "cierre") or None,
        "funciones": _txt(b.get("funciones"), 6000, "funciones", True), "cv_modelo": _txt(b.get("cv_modelo"), 20000, "cv_modelo"),
        "umbral": 50, "rubrica": {"version": 0, "aprobada": False, "metricas": []},
        "creado_por": ident.email, "creado_en": now(), "actualizado_en": now(),
    }
    if len(item["funciones"]) < 30:
        raise HttpError(400, "Describe las funciones del puesto (mínimo 30 caracteres)")
    table().put_item(Item=item)
    return 201, _vista_proceso(item, detalle=True)


def ver_proceso(ident, pid, **_):
    return 200, _vista_proceso(_get_proceso(ident, pid), detalle=True)


def editar_proceso(ident, event, pid, **_):
    if not ident.puede_editar():
        raise HttpError(403, "Tu rol no puede editar procesos")
    p = _get_proceso(ident, pid)
    b = _body(event)
    sets, vals = ["actualizado_en=:t"], {":t": now()}
    for campo, maxlen in (("titulo", 150), ("area", 80), ("apertura", 10), ("cierre", 10), ("funciones", 6000), ("cv_modelo", 20000)):
        if campo in b:
            sets.append(f"{campo}=:{campo}")
            vals[f":{campo}"] = _txt(b[campo], maxlen, campo) or None
    if "umbral" in b:
        try:
            u = int(b["umbral"])
        except (TypeError, ValueError):
            raise HttpError(400, "Umbral inválido")
        if not 0 <= u <= 100:
            raise HttpError(400, "El umbral debe estar entre 0 y 100")
        sets.append("umbral=:u")
        vals[":u"] = u
    if "metricas" in b:
        if (p.get("rubrica") or {}).get("aprobada"):
            raise HttpError(409, "La rúbrica ya está aprobada; crea un proceso nuevo o duplícalo para cambiarla")
        sets.append("rubrica.metricas=:m")
        vals[":m"] = _validar_metricas(b["metricas"])
    if "cerrado" in b:
        sets.append("cerrado=:c")
        vals[":c"] = bool(b["cerrado"])
    res = table().update_item(Key={"PK": p["PK"], "SK": p["SK"]}, UpdateExpression="SET " + ", ".join(sets),
                              ExpressionAttributeValues=vals, ReturnValues="ALL_NEW")
    return 200, _vista_proceso(res["Attributes"], detalle=True)


def proponer_rubrica(ident, pid, **_):
    if not ident.puede_editar():
        raise HttpError(403, "Tu rol no puede editar la rúbrica")
    p = _get_proceso(ident, pid)
    if (p.get("rubrica") or {}).get("aprobada"):
        raise HttpError(409, "La rúbrica ya está aprobada")
    import agents
    from common import GroqRateLimit
    try:
        propuestas = agents.proponer_rubrica(p["titulo"], p.get("area", ""), p["funciones"], p.get("cv_modelo", ""))
    except GroqRateLimit:
        raise HttpError(429, "El servicio de IA está ocupado; intenta en unos segundos")
    for m in propuestas:
        m["importancia"] = max(1, min(5, int(m.get("importancia_sugerida") or 3)))
        m["origen"] = "ia"
    metricas = _validar_metricas(propuestas)
    table().update_item(Key={"PK": p["PK"], "SK": p["SK"]}, UpdateExpression="SET rubrica.metricas=:m, actualizado_en=:t",
                        ExpressionAttributeValues={":m": metricas, ":t": now()})
    return 200, {"metricas": metricas}


def aprobar_rubrica(ident, pid, **_):
    if not ident.puede_editar():
        raise HttpError(403, "Tu rol no puede aprobar la rúbrica")
    p = _get_proceso(ident, pid)
    rub = clean(p.get("rubrica") or {})
    if rub.get("aprobada"):
        raise HttpError(409, "La rúbrica ya está aprobada")
    metricas = _validar_metricas(rub.get("metricas", []), estricto=True)
    if len(metricas) < 3:
        raise HttpError(400, "La rúbrica necesita al menos 3 métricas")
    nueva = {"version": int(rub.get("version", 0)) + 1, "aprobada": True, "aprobada_en": now(),
             "aprobada_por": ident.email, "metricas": metricas}
    res = table().update_item(Key={"PK": p["PK"], "SK": p["SK"]}, UpdateExpression="SET rubrica=:r, actualizado_en=:t",
                              ExpressionAttributeValues={":r": nueva, ":t": now()}, ReturnValues="ALL_NEW")
    return 200, _vista_proceso(res["Attributes"], detalle=True)


def crear_lote(ident, event, pid, **_):
    if not ident.puede_editar():
        raise HttpError(403, "Tu rol no puede cargar CVs")
    p = _get_proceso(ident, pid)
    if estado_proceso(p) in ("BORRADOR", "CERRADO"):
        raise HttpError(409, "Aprueba la rúbrica (y no cierres el proceso) antes de cargar CVs")
    archivos = _body(event).get("archivos") or []
    if not isinstance(archivos, list) or not 1 <= len(archivos) <= MAX_ARCHIVOS_LOTE:
        raise HttpError(400, f"Envía entre 1 y {MAX_ARCHIVOS_LOTE} archivos")
    lote_id = uuid.uuid4().hex[:10]
    t = table()
    subidas, rechazados = [], []
    with t.batch_writer() as bw:
        for a in archivos:
            nombre = str((a or {}).get("nombre", ""))[:200]
            ext = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
            if ext not in EXT_PERMITIDAS:
                rechazados.append({"nombre": nombre, "motivo": "Formato no permitido (usa PDF, TXT o MD)"})
                continue
            if int((a or {}).get("tamano", 0) or 0) > 5 * 1024 * 1024:
                rechazados.append({"nombre": nombre, "motivo": "Supera 5 MB"})
                continue
            cv_id = uuid.uuid4().hex
            key = f"cvs/tenant={ident.tenant}/proceso={pid}/lote={lote_id}/{cv_id}.{ext}"
            url = s3.generate_presigned_url("put_object", ExpiresIn=900, HttpMethod="PUT",
                                            Params={"Bucket": BUCKET, "Key": key, "ContentType": EXT_PERMITIDAS[ext]})
            bw.put_item(Item={"PK": pk_proceso(ident.tenant, pid), "SK": f"CV#{cv_id}", "cv_id": cv_id, "lote_id": lote_id,
                              "archivo": re.sub(r"[^\w.\- ]", "_", nombre), "estado": "PENDIENTE_SUBIDA",
                              "creado_en": now(), "expira_en": ttl_epoch()})
            subidas.append({"nombre": nombre, "cv_id": cv_id, "url": url, "content_type": EXT_PERMITIDAS[ext]})
        bw.put_item(Item={"PK": pk_proceso(ident.tenant, pid), "SK": f"LOTE#{lote_id}", "id": lote_id,
                          "total": len(subidas), "recibidos": 0, "procesados": 0, "creado_por": ident.email,
                          "creado_en": now(), "expira_en": ttl_epoch()})
    return 201, {"lote_id": lote_id, "subidas": subidas, "rechazados": rechazados}


def _query_all(**kwargs):
    items = []
    while True:
        res = table().query(**kwargs)
        items += res.get("Items", [])
        if "LastEvaluatedKey" not in res:
            return items
        kwargs["ExclusiveStartKey"] = res["LastEvaluatedKey"]


def listar_lotes(ident, pid, **_):
    _get_proceso(ident, pid)
    items = _query_all(KeyConditionExpression=Key("PK").eq(pk_proceso(ident.tenant, pid)) & Key("SK").begins_with("LOTE#"))
    lotes = sorted((clean({k: v for k, v in i.items() if k not in ("PK", "SK", "expira_en")}) for i in items),
                   key=lambda x: x.get("creado_en", ""), reverse=True)
    return 200, {"items": lotes}


_CAMPOS_LISTA = ("cv_id", "lote_id", "archivo", "estado", "nota", "banda", "cobertura", "candidato", "titular",
                 "requiere_revision", "motivo", "metricas", "actualizado_en", "creado_en")


def _resumen_postulante(i):
    out = {k: i.get(k) for k in _CAMPOS_LISTA if k in i}
    if "metricas" in out:  # versión liviana para el dashboard
        out["metricas"] = [{"metrica_id": m["metrica_id"], "nombre": m["nombre"], "nivel": m["nivel"],
                            "importancia": m["importancia"], "aporte": m.get("aporte", 0), "estado": m.get("estado")}
                           for m in out["metricas"]]
    return clean(out)


def listar_postulantes(ident, event, pid, **_):
    p = _get_proceso(ident, pid)
    q = event.get("queryStringParameters") or {}
    pk = pk_proceso(ident.tenant, pid)
    if q.get("min") is not None:
        # Ranking directo desde el GSI1: notas >= min, de mayor a menor.
        try:
            minimo = float(q["min"])
        except ValueError:
            raise HttpError(400, "Parámetro min inválido")
        items = _query_all(IndexName="GSI1", ScanIndexForward=False,
                           KeyConditionExpression=Key("GSI1PK").eq(pk) & Key("GSI1SK").gte(f"{int(round(minimo * 100)):05d}"))
        items = [table().get_item(Key={"PK": pk, "SK": f"CV#{i['cv_id']}"}).get("Item") or i for i in items] \
            if items and "metricas" not in items[0] else items
    else:
        items = _query_all(KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with("CV#"))
        items.sort(key=lambda i: float(i.get("nota", -1)), reverse=True)
    return 200, {"umbral": clean(p.get("umbral", 50)), "items": [_resumen_postulante(i) for i in items]}


def ver_postulante(ident, pid, cid, **_):
    _get_proceso(ident, pid)
    item = table().get_item(Key={"PK": pk_proceso(ident.tenant, pid), "SK": f"CV#{cid}"}).get("Item")
    if not item:
        raise HttpError(404, "Postulante no encontrado")
    out = clean({k: v for k, v in item.items() if k not in ("PK", "SK", "GSI1PK", "GSI1SK", "expira_en")})
    if item.get("perfil_key"):
        try:
            out["perfil"] = json.loads(s3.get_object(Bucket=BUCKET, Key=item["perfil_key"])["Body"].read())
        except Exception:
            out["perfil"] = None
    return 200, out


def exportar(ident, pid, **_):
    p = _get_proceso(ident, pid)
    items = _query_all(KeyConditionExpression=Key("PK").eq(pk_proceso(ident.tenant, pid)) & Key("SK").begins_with("CV#"))
    items.sort(key=lambda i: float(i.get("nota", -1)), reverse=True)
    metricas = clean((p.get("rubrica") or {}).get("metricas", []))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["posicion", "candidato", "archivo", "estado", "nota_%", "banda", "cobertura_%", "revision_humana"]
               + [f"{m['nombre']} (L{m['importancia']})" for m in metricas])
    for pos, i in enumerate(clean(items), 1):
        niveles = {m["metrica_id"]: m["nivel"] for m in i.get("metricas", [])}
        w.writerow([pos, i.get("candidato", ""), i.get("archivo", ""), i.get("estado", ""), i.get("nota", ""),
                    i.get("banda", ""), i.get("cobertura", ""), "sí" if i.get("requiere_revision") else "no"]
                   + [niveles.get(m["id"], "") for m in metricas])
    nombre = re.sub(r"[^\w]+", "_", p["titulo"]).strip("_").lower() or "proceso"
    return 200, ("﻿" + buf.getvalue(), "text/csv; charset=utf-8",
                 {"content-disposition": f'attachment; filename="talentflow_{nombre}.csv"'})


RUTAS = [
    ("GET", r"/v1/me", me),
    ("GET", r"/v1/procesos", listar_procesos),
    ("POST", r"/v1/procesos", crear_proceso),
    ("GET", r"/v1/procesos/(?P<pid>[\w-]+)", ver_proceso),
    ("PUT", r"/v1/procesos/(?P<pid>[\w-]+)", editar_proceso),
    ("POST", r"/v1/procesos/(?P<pid>[\w-]+)/rubrica/proponer", proponer_rubrica),
    ("POST", r"/v1/procesos/(?P<pid>[\w-]+)/rubrica/aprobar", aprobar_rubrica),
    ("POST", r"/v1/procesos/(?P<pid>[\w-]+)/lotes", crear_lote),
    ("GET", r"/v1/procesos/(?P<pid>[\w-]+)/lotes", listar_lotes),
    ("GET", r"/v1/procesos/(?P<pid>[\w-]+)/postulantes", listar_postulantes),
    ("GET", r"/v1/procesos/(?P<pid>[\w-]+)/postulantes/(?P<cid>[\w-]+)", ver_postulante),
    ("GET", r"/v1/procesos/(?P<pid>[\w-]+)/export", exportar),
]


def handler(event, context):
    path = event.get("rawPath", "")
    method = ((event.get("requestContext") or {}).get("http") or {}).get("method", "GET")
    if path == "/health":
        return reply(200, {"service": "talentflow-ai", "status": "ok"})
    ident = identidad(event)
    if not ident.tenant:
        return reply(403, {"error": "Usuario sin empresa asignada"})
    try:
        for m, patron, fn in RUTAS:
            match = re.fullmatch(patron, path)
            if match and m == method:
                status, data = fn(ident, event=event, **match.groupdict())
                if isinstance(data, tuple):
                    return reply(status, data[0], content_type=data[1], extra_headers=data[2])
                return reply(status, data)
        return reply(404, {"error": "Ruta no encontrada"})
    except HttpError as e:
        return reply(e.status, {"error": e.msg})
    except Exception as e:
        print("Error interno:", type(e).__name__, str(e)[:300])
        return reply(500, {"error": "Error interno; revisar CloudWatch"})
