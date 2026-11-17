"""Crea empresas y usuarios de demostración en Cognito + DynamoDB.

Uso:  python scripts/crear_empresas_demo.py --profile eyatech
Lee los IDs desde build/outputs.json (generado por `cdk deploy --outputs-file`).
Las contraseñas se guardan en build/credenciales_demo.txt (no versionar).
"""
import argparse
import json
import os
import secrets
import string

import boto3

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

EMPRESAS = [
    {"id": "nova-talent", "nombre": "Nova Talent Services", "usuarios": [
        ("admin@nova.example.com", "admin", ""),
        ("analista@nova.example.com", "reclutador", ""),
        ("lider.bi@nova.example.com", "lider", "BI"),
    ]},
    {"id": "andes-retail", "nombre": "Andes Retail (demo de aislamiento)", "usuarios": [
        ("analista@andes.example.com", "reclutador", ""),
    ]},
]


def clave():
    alf = string.ascii_letters + string.digits
    return "Tf-" + "".join(secrets.choice(alf) for _ in range(12)) + "9a"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="eyatech")
    ap.add_argument("--region", default="us-east-1")
    args = ap.parse_args()
    out = json.load(open(os.path.join(ROOT, "build", "outputs.json"), encoding="utf-8"))["TalentFlowAI"]
    ses = boto3.Session(profile_name=args.profile, region_name=args.region)
    idp = ses.client("cognito-idp")
    tabla = ses.resource("dynamodb").Table("talentflow")
    pool = out["UserPoolId"]
    lineas = []
    for emp in EMPRESAS:
        tabla.put_item(Item={"PK": f"T#{emp['id']}", "SK": "META", "nombre": emp["nombre"], "plan": "demo"})
        for email, grupo, area in emp["usuarios"]:
            pwd = clave()
            attrs = [{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"},
                     {"Name": "custom:tenant_id", "Value": emp["id"]}]
            if area:
                attrs.append({"Name": "custom:area", "Value": area})
            try:
                idp.admin_create_user(UserPoolId=pool, Username=email, UserAttributes=attrs, MessageAction="SUPPRESS")
            except idp.exceptions.UsernameExistsException:
                idp.admin_update_user_attributes(UserPoolId=pool, Username=email, UserAttributes=attrs)
            idp.admin_set_user_password(UserPoolId=pool, Username=email, Password=pwd, Permanent=True)
            idp.admin_add_user_to_group(UserPoolId=pool, Username=email, GroupName=grupo)
            lineas.append(f"{emp['nombre']:<36} {grupo:<11} {email:<30} {pwd}")
    path = os.path.join(ROOT, "build", "credenciales_demo.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lineas) + "\n")
    print("\n".join(lineas))
    print(f"\nGuardado en {path}")


if __name__ == "__main__":
    main()
