# TalentFlow AI — Evaluación masiva de CVs por rúbrica

Plataforma multiempresa (Nivel 4, autonomía moderada) que evalúa lotes de CVs contra una rúbrica por rol y muestra en un dashboard a los postulantes con nota ≥ umbral (50% por defecto). La IA extrae y razona; el código calcula; la decisión es humana.

- **Web:** https://main.d3fk1eh5p88ntj.amplifyapp.com
- **API:** https://ayg9ckxdz4.execute-api.us-east-1.amazonaws.com
- **Región:** us-east-1 · **Cuenta/perfil:** `eyatech`

## Arquitectura

```
React (Amplify Hosting) ──JWT──▶ API Gateway HTTP API ──▶ Lambda API ──▶ DynamoDB (tabla única + GSI1 ranking)
        │                                   └─ Groq vía LangChain (propuesta de rúbrica)
        └─ PUT URL prefirmada ─▶ S3 cvs/tenant=…/proceso=…/lote=…/ ─evento─▶ SQS (+DLQ)
                                                   ─▶ Lambda despachador (máx. 4 en paralelo)
                                                   ─▶ Step Functions (1 ejecución por CV):
   ExtraerTexto ─▶ ¿texto? ─▶ AgentePerfilador ─▶ ¿perfil? ─▶ AgenteEvaluador ─▶ VerificarYCalcular ─▶ AgenteEntrevistador ─▶ Guardar
                 └─ Revisión ◀────────────────────┘          Retry 429 (GroqRateLimit) · Catch ─▶ RegistrarError
```

Nota = 100 × Σ(importancia × nivel) ÷ Σ(importancia × 4), con importancia Likert 1–5 y nivel 0–4. Un nivel sin cita literal del CV baja a 0.

## Estructura

| Carpeta | Contenido |
| --- | --- |
| `backend/src` | `api.py` (rutas REST), `dispatcher.py` (SQS → Step Functions), `steps.py` (tareas del workflow), `agents.py` (LangChain + Groq), `scoring.py` (anonimización, verificación de citas, nota) |
| `backend/tests` | Pruebas unitarias de la nota (`pytest`) |
| `infra` | AWS CDK (Python): DynamoDB, S3, SQS, Step Functions, Lambda, Cognito, API Gateway, Secrets Manager |
| `frontend` | React + Vite: procesos, rúbrica con Likert, carga de lotes, dashboard, ficha del postulante |
| `scripts` | `crear_empresas_demo.py`, `generar_cvs_demo.py`, `prueba_e2e.py` |
| `samples` | Vacante de ejemplo, CV modelo y 10 CVs sintéticos (PDF/TXT) |
| `postman` | Colección con login de Cognito y todos los endpoints |

## Despliegue

```bash
# 1) Dependencias Linux para la capa Lambda
python -m pip install -r backend/requirements.txt --target build/layer/python \
  --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 --only-binary=:all:
# 2) Infraestructura
cd infra && python -m venv .venv && .venv/Scripts/python -m pip install aws-cdk-lib constructs
AWS_PROFILE=eyatech npx aws-cdk@latest deploy TalentFlowAI --outputs-file ../build/outputs.json
# 3) Clave de Groq (no se versiona)
aws secretsmanager put-secret-value --profile eyatech --region us-east-1 \
  --secret-id talentflow/groq --secret-string '{"GROQ_API_KEY":"gsk_..."}'
# 4) Empresas y usuarios de demo (contraseñas en build/credenciales_demo.txt)
python scripts/crear_empresas_demo.py --profile eyatech
# 5) Frontend en Amplify (dominio por defecto amplifyapp.com)
cd frontend && npm install && npm run build   # usa .env.production
#    zip de dist/ → aws amplify create-deployment / start-deployment (app d3fk1eh5p88ntj, rama main)
```

## Prueba

```bash
python -m pytest backend/tests -q
python scripts/prueba_e2e.py --esperar     # crea proceso, propone rúbrica con IA, sube 10 CVs y muestra el ranking
```

## Usuarios de demo

| Empresa | Rol | Correo |
| --- | --- | --- |
| Nova Talent Services | admin | admin@nova.example.com |
| Nova Talent Services | reclutador | analista@nova.example.com |
| Nova Talent Services | líder (área BI) | lider.bi@nova.example.com |
| Andes Retail | reclutador | analista@andes.example.com |

## Límites conocidos

- Solo texto: PDFs escaneados quedan en revisión ("requiere OCR"). Imágenes y validación de certificados están fuera de alcance.
- Groq gratuito tiene límites por minuto; la cola y el despachador limitan a 4 CVs en paralelo y Step Functions reintenta los 429.
- Solo CVs sintéticos en la demo. Los datos expiran a los 180 días (TTL de DynamoDB y ciclo de vida de S3).
