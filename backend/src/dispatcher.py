"""Consume la cola SQS de CVs subidos a S3 e inicia una ejecución de Step Functions por CV.

Contrapresión: si ya hay MAX_PARALELO ejecuciones en curso, el mensaje vuelve a la cola
(se reintenta tras el visibility timeout). Así se respeta el límite de uso de Groq y
los CVs se procesan en orden de llegada aproximado.
"""
import json
import os
import re
from urllib.parse import unquote_plus

import boto3

from common import now, pk_proceso, pk_tenant, table

sfn = boto3.client("stepfunctions")
SM_ARN = os.environ["STATE_MACHINE_ARN"]
MAX_PARALELO = int(os.getenv("MAX_PARALELO", "4"))
KEY_RE = re.compile(r"^cvs/tenant=([\w-]+)/proceso=([\w-]+)/lote=([\w-]+)/([\w-]+)\.(pdf|txt|md)$", re.I)


class SinCupo(Exception):
    pass


def _en_curso():
    res = sfn.list_executions(stateMachineArn=SM_ARN, statusFilter="RUNNING", maxResults=MAX_PARALELO + 1)
    return len(res.get("executions", []))


def _iniciar(bucket, key):
    m = KEY_RE.match(key)
    if not m:
        print("Clave ignorada:", key)
        return
    tenant, proceso_id, lote_id, cv_id, _ = m.groups()
    if _en_curso() >= MAX_PARALELO:
        raise SinCupo()
    payload = {"tenant": tenant, "proceso_id": proceso_id, "lote_id": lote_id, "cv_id": cv_id,
               "bucket": bucket, "key": key}
    try:
        sfn.start_execution(stateMachineArn=SM_ARN, name=cv_id, input=json.dumps(payload))
    except sfn.exceptions.ExecutionAlreadyExists:
        return  # mensaje duplicado de SQS: ya se procesa
    t = table()
    t.update_item(Key={"PK": pk_proceso(tenant, proceso_id), "SK": f"CV#{cv_id}"},
                  UpdateExpression="SET estado=:s, iniciado_en=:t", ExpressionAttributeValues={":s": "PROCESANDO", ":t": now()})
    t.update_item(Key={"PK": pk_tenant(tenant), "SK": f"PROC#{proceso_id}"},
                  UpdateExpression="ADD cvs_recibidos :uno", ExpressionAttributeValues={":uno": 1})
    t.update_item(Key={"PK": pk_proceso(tenant, proceso_id), "SK": f"LOTE#{lote_id}"},
                  UpdateExpression="ADD recibidos :uno", ExpressionAttributeValues={":uno": 1})


def handler(event, context):
    fallidos = []
    for rec in event.get("Records", []):
        try:
            body = json.loads(rec["body"])
            for s3rec in body.get("Records", []):  # s3:TestEvent no trae Records
                _iniciar(s3rec["s3"]["bucket"]["name"], unquote_plus(s3rec["s3"]["object"]["key"]))
        except SinCupo:
            fallidos.append({"itemIdentifier": rec["messageId"]})
        except Exception as err:
            print("Error despachando:", type(err).__name__, str(err)[:200])
            fallidos.append({"itemIdentifier": rec["messageId"]})
    return {"batchItemFailures": fallidos}
