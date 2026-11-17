#!/usr/bin/env python3
"""Infraestructura de TalentFlow AI (AWS CDK, Python)."""
import os

import aws_cdk as cdk
from aws_cdk import (
    Duration, RemovalPolicy, Stack, CfnOutput,
    aws_apigatewayv2 as apigw,
    aws_apigatewayv2_authorizers as authz,
    aws_apigatewayv2_integrations as integ,
    aws_cognito as cognito,
    aws_dynamodb as ddb,
    aws_lambda as lambda_,
    aws_lambda_event_sources as les,
    aws_logs as logs,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_secretsmanager as sm,
    aws_sqs as sqs,
    aws_stepfunctions as sfn,
    aws_stepfunctions_tasks as tasks,
)
from constructs import Construct

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


class TalentFlowStack(Stack):
    def __init__(self, scope: Construct, cid: str, *, origins: list, **kw):
        super().__init__(scope, cid, **kw)

        # ---------- Datos ----------
        table = ddb.Table(
            self, "Tabla", table_name="talentflow",
            partition_key=ddb.Attribute(name="PK", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="SK", type=ddb.AttributeType.STRING),
            billing_mode=ddb.BillingMode.PAY_PER_REQUEST, time_to_live_attribute="expira_en",
            removal_policy=RemovalPolicy.DESTROY,
        )
        table.add_global_secondary_index(
            index_name="GSI1",
            partition_key=ddb.Attribute(name="GSI1PK", type=ddb.AttributeType.STRING),
            sort_key=ddb.Attribute(name="GSI1SK", type=ddb.AttributeType.STRING),
            projection_type=ddb.ProjectionType.ALL,
        )

        bucket = s3.Bucket(
            self, "CVs", block_public_access=s3.BlockPublicAccess.BLOCK_ALL, encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True, removal_policy=RemovalPolicy.DESTROY, auto_delete_objects=True,
            cors=[s3.CorsRule(allowed_methods=[s3.HttpMethods.PUT], allowed_origins=origins,
                              allowed_headers=["*"], max_age=3000)],
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(180))],
        )

        dlq = sqs.Queue(self, "ColaCVsDLQ", queue_name="talentflow-cvs-dlq", retention_period=Duration.days(14))
        cola = sqs.Queue(self, "ColaCVs", queue_name="talentflow-cvs", visibility_timeout=Duration.seconds(45),
                         dead_letter_queue=sqs.DeadLetterQueue(queue=dlq, max_receive_count=200))
        bucket.add_event_notification(s3.EventType.OBJECT_CREATED, s3n.SqsDestination(cola),
                                      s3.NotificationKeyFilter(prefix="cvs/"))

        groq = sm.Secret(self, "GroqSecret", secret_name="talentflow/groq",
                         description="GROQ_API_KEY de TalentFlow AI",
                         secret_string_value=cdk.SecretValue.unsafe_plain_text('{"GROQ_API_KEY":"REEMPLAZAR"}'))

        # ---------- Código ----------
        layer = lambda_.LayerVersion(self, "Deps", code=lambda_.Code.from_asset(os.path.join(ROOT, "build", "layer")),
                                     compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
                                     description="langchain-groq, pydantic, pypdf")
        code = lambda_.Code.from_asset(os.path.join(ROOT, "backend", "src"))
        env = {"TABLE_NAME": table.table_name, "BUCKET_NAME": bucket.bucket_name,
               "GROQ_SECRET_ARN": groq.secret_arn, "GROQ_MODEL": self.node.try_get_context("groq_model") or "openai/gpt-oss-20b",
               "RETENCION_DIAS": "180"}

        def fn(name, handler, timeout=30, memory=512, ia=False):
            f = lambda_.Function(self, name, function_name=f"talentflow-{name.lower()}", runtime=lambda_.Runtime.PYTHON_3_12,
                                 handler=handler, code=code, layers=[layer], timeout=Duration.seconds(timeout),
                                 memory_size=memory, environment=env, log_retention=logs.RetentionDays.ONE_MONTH)
            table.grant_read_write_data(f)
            bucket.grant_read_write(f)
            if ia:
                groq.grant_read(f)
            return f

        f_extraer = fn("Extraer", "steps.extraer", 60)
        f_perfilar = fn("Perfilar", "steps.perfilar", 120, ia=True)
        f_evaluar = fn("Evaluar", "steps.evaluar", 120, ia=True)
        f_calcular = fn("Calcular", "steps.calcular_nota", 30)
        f_entrevistar = fn("Entrevistar", "steps.entrevistar", 90, ia=True)
        f_guardar = fn("Guardar", "steps.guardar", 30)
        f_revision = fn("Revision", "steps.revision", 30)
        f_error = fn("RegistrarError", "steps.registrar_error", 30)

        # ---------- Workflow por CV ----------
        def task(name, f):
            return tasks.LambdaInvoke(self, name, lambda_function=f, payload_response_only=True,
                                      retry_on_service_exceptions=True)

        registrar_error = task("RegistrarError_", f_error)
        revision = task("GuardarRevision", f_revision)
        guardar = task("GuardarExpediente", f_guardar)

        def con_reintentos_ia(t):
            t.add_retry(errors=["GroqRateLimit"], interval=Duration.seconds(15), max_attempts=6, backoff_rate=2,
                        max_delay=Duration.seconds(120), jitter_strategy=sfn.JitterType.FULL)
            t.add_retry(errors=["RespuestaIAInvalida", "ValidationError", "OutputParserException"],
                        interval=Duration.seconds(10), max_attempts=5, backoff_rate=2)
            t.add_retry(errors=["States.TaskFailed"], interval=Duration.seconds(5), max_attempts=1)
            return t

        extraer = task("ExtraerTexto", f_extraer).add_catch(registrar_error, result_path="$.error")
        perfilar = con_reintentos_ia(task("AgentePerfilador", f_perfilar)).add_catch(registrar_error, result_path="$.error")
        evaluar = con_reintentos_ia(task("AgenteEvaluador", f_evaluar)).add_catch(registrar_error, result_path="$.error")
        calcular = task("VerificarYCalcular", f_calcular).add_catch(registrar_error, result_path="$.error")
        entrevistar = con_reintentos_ia(task("AgenteEntrevistador", f_entrevistar)).add_catch(guardar, result_path="$.error_preguntas")
        guardar.add_catch(registrar_error, result_path="$.error")

        definicion = (
            extraer.next(
                sfn.Choice(self, "TextoUtilizable?")
                .when(sfn.Condition.boolean_equals("$.texto_ok", True),
                      perfilar.next(
                          sfn.Choice(self, "PerfilValido?")
                          .when(sfn.Condition.boolean_equals("$.perfil_ok", True),
                                evaluar.next(calcular).next(entrevistar).next(guardar))
                          .otherwise(revision)))
                .otherwise(revision))
        )
        sm_logs = logs.LogGroup(self, "WorkflowLogs", retention=logs.RetentionDays.ONE_MONTH,
                                removal_policy=RemovalPolicy.DESTROY)
        machine = sfn.StateMachine(
            self, "Workflow", state_machine_name="talentflow-evaluacion-cv",
            definition_body=sfn.DefinitionBody.from_chainable(definicion), timeout=Duration.minutes(30),
            logs=sfn.LogOptions(destination=sm_logs, level=sfn.LogLevel.ERROR),
            comment="TalentFlow AI: un CV por ejecución; la IA extrae y razona, el código calcula; sin decisiones de contratación",
        )

        dispatcher = fn("Despachador", "dispatcher.handler", 30, 256)
        dispatcher.add_environment("STATE_MACHINE_ARN", machine.state_machine_arn)
        dispatcher.add_environment("MAX_PARALELO", str(self.node.try_get_context("max_paralelo") or 4))
        machine.grant_start_execution(dispatcher)
        machine.grant_read(dispatcher)
        dispatcher.add_event_source(les.SqsEventSource(cola, batch_size=1, max_concurrency=2,
                                                       report_batch_item_failures=True))

        # ---------- Identidad multiempresa ----------
        pool = cognito.UserPool(
            self, "Usuarios", user_pool_name="talentflow-usuarios", self_sign_up_enabled=False,
            sign_in_aliases=cognito.SignInAliases(email=True), removal_policy=RemovalPolicy.DESTROY,
            custom_attributes={"tenant_id": cognito.StringAttribute(min_len=2, max_len=40, mutable=True),
                               "area": cognito.StringAttribute(max_len=80, mutable=True)},
            password_policy=cognito.PasswordPolicy(min_length=10, require_symbols=False),
        )
        for g in ("admin", "reclutador", "lider"):
            cognito.CfnUserPoolGroup(self, f"Grupo{g}", user_pool_id=pool.user_pool_id, group_name=g)
        client = pool.add_client(
            "Web", user_pool_client_name="talentflow-web", generate_secret=False,
            auth_flows=cognito.AuthFlow(user_password=True, user_srp=True),
            id_token_validity=Duration.hours(8), access_token_validity=Duration.hours(8),
            read_attributes=cognito.ClientAttributes().with_standard_attributes(email=True).with_custom_attributes("tenant_id", "area"),
            write_attributes=cognito.ClientAttributes().with_standard_attributes(email=True),
        )

        # ---------- API ----------
        f_api = fn("Api", "api.handler", 29, 1024, ia=True)
        api = apigw.HttpApi(
            self, "HttpApi", api_name="talentflow-api",
            cors_preflight=apigw.CorsPreflightOptions(
                allow_origins=origins, allow_headers=["authorization", "content-type"],
                allow_methods=[apigw.CorsHttpMethod.GET, apigw.CorsHttpMethod.POST, apigw.CorsHttpMethod.PUT,
                               apigw.CorsHttpMethod.OPTIONS],
                expose_headers=["content-disposition"], max_age=Duration.hours(1)),
        )
        jwt = authz.HttpJwtAuthorizer("Cognito", f"https://cognito-idp.{self.region}.amazonaws.com/{pool.user_pool_id}",
                                      jwt_audience=[client.user_pool_client_id])
        integracion = integ.HttpLambdaIntegration("ApiInt", f_api)
        api.add_routes(path="/health", methods=[apigw.HttpMethod.GET], integration=integracion)
        api.add_routes(path="/v1/{proxy+}", methods=[apigw.HttpMethod.GET, apigw.HttpMethod.POST, apigw.HttpMethod.PUT],
                       integration=integracion, authorizer=jwt)

        for k, v in {"ApiUrl": api.api_endpoint, "UserPoolId": pool.user_pool_id, "ClientId": client.user_pool_client_id,
                     "BucketName": bucket.bucket_name, "StateMachineArn": machine.state_machine_arn,
                     "GroqSecretArn": groq.secret_arn, "QueueUrl": cola.queue_url}.items():
            CfnOutput(self, k, value=v)


app = cdk.App()
amplify = app.node.try_get_context("amplify_url") or ""
origins = [o for o in [amplify, "http://localhost:5173"] if o]
TalentFlowStack(app, "TalentFlowAI", origins=origins,
                env=cdk.Environment(account=os.getenv("CDK_DEFAULT_ACCOUNT"), region="us-east-1"))
app.synth()
