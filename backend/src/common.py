"""Utilidades compartidas: DynamoDB, respuestas HTTP, identidad multiempresa y Groq."""
import datetime
import json
import os
from decimal import Decimal

import boto3

_ddb = boto3.resource("dynamodb")
_secrets = boto3.client("secretsmanager")
_groq_key_cache = None

TIPOS_METRICA = [
    "experiencia", "sector", "formacion", "herramientas", "idiomas",
    "certificaciones", "logros", "blandas", "otra",
]


def table():
    return _ddb.Table(os.environ["TABLE_NAME"])


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def ttl_epoch(days=None):
    days = days or int(os.getenv("RETENCION_DIAS", "180"))
    return int((datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days)).timestamp())


def clean(v):
    """Convierte Decimal de DynamoDB a int/float para JSON."""
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [clean(x) for x in v]
    return v


def to_ddb(v):
    """Convierte float a Decimal para DynamoDB."""
    if isinstance(v, float):
        return Decimal(str(round(v, 4)))
    if isinstance(v, dict):
        return {k: to_ddb(x) for k, x in v.items()}
    if isinstance(v, list):
        return [to_ddb(x) for x in v]
    return v


def reply(status, data, content_type="application/json", extra_headers=None):
    body = data if isinstance(data, str) else json.dumps(clean(data), ensure_ascii=False, default=str)
    headers = {"content-type": content_type}
    headers.update(extra_headers or {})
    return {"statusCode": status, "headers": headers, "body": body}


# ---------- Claves de la tabla única ----------
def pk_tenant(t):
    return f"T#{t}"


def pk_proceso(t, p):
    return f"T#{t}#P#{p}"


def nota_sk(nota, cv_id):
    """Nota 0-100 -> '06667#<cvId>' para ordenar el ranking en el GSI1."""
    return f"{int(round(nota * 100)):05d}#{cv_id}"


# ---------- Identidad (claims del JWT de Cognito) ----------
class Identidad:
    def __init__(self, claims):
        self.sub = claims.get("sub", "")
        self.email = claims.get("email", "")
        self.tenant = claims.get("custom:tenant_id", "")
        self.area = claims.get("custom:area", "")
        grupos = claims.get("cognito:groups", "")
        if isinstance(grupos, list):
            self.grupos = grupos
        else:  # HTTP API entrega arrays como "[a b]"
            self.grupos = [g for g in str(grupos).strip("[]").replace(",", " ").split() if g]

    @property
    def rol(self):
        for r in ("admin", "reclutador", "lider"):
            if r in self.grupos:
                return r
        return "lider"

    def puede_editar(self):
        return self.rol in ("admin", "reclutador")

    def puede_ver_proceso(self, proceso):
        # Opción A: admin y reclutador ven todo lo de su empresa; líder solo su área.
        if self.rol in ("admin", "reclutador"):
            return True
        return bool(self.area) and proceso.get("area", "").strip().lower() == self.area.strip().lower()


def identidad(event):
    claims = (((event.get("requestContext") or {}).get("authorizer") or {}).get("jwt") or {}).get("claims") or {}
    return Identidad(claims)


# ---------- Groq ----------
class GroqRateLimit(Exception):
    """Groq respondió 429; Step Functions reintenta con espera exponencial."""


class RespuestaIAInvalida(Exception):
    """El modelo no devolvió la estructura esperada."""


def groq_key():
    global _groq_key_cache
    if _groq_key_cache:
        return _groq_key_cache
    raw = _secrets.get_secret_value(SecretId=os.environ["GROQ_SECRET_ARN"])["SecretString"]
    try:
        raw = json.loads(raw).get("GROQ_API_KEY", raw)
    except (json.JSONDecodeError, AttributeError):
        pass
    _groq_key_cache = raw.strip()
    return _groq_key_cache


def estado_proceso(p):
    """Estado derivado de la rúbrica y los contadores (evita carreras al actualizar)."""
    if p.get("cerrado"):
        return "CERRADO"
    if not (p.get("rubrica") or {}).get("aprobada"):
        return "BORRADOR"
    recibidos = int(p.get("cvs_recibidos", 0))
    procesados = int(p.get("cvs_procesados", 0))
    if recibidos == 0:
        return "RECIBIENDO_CVS"
    if procesados < recibidos:
        return "PROCESANDO"
    return "LISTO"
