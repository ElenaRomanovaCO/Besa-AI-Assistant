"""Admin UI infrastructure: Cognito, Admin API Gateway, Amplify Hosting."""

from __future__ import annotations

from aws_cdk import (
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    Tags,
    aws_apigateway as apigw,
    aws_cognito as cognito,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
)
from constructs import Construct

from stacks.network_stack import NetworkStack
from stacks.storage_stack import StorageStack
from stacks.secrets_stack import SecretsStack


class AdminStack(Stack):
    """
    Admin UI backend infrastructure:
    - Cognito User Pool: Admin and User roles, pre-seeded admin account
    - Admin API Gateway: REST API for admin UI → admin Lambda handler
    - Cognito JWT Authorizer on all admin routes
    - Amplify App (frontend hosting) is configured separately via Amplify console
      (Amplify CDK L2 requires GitHub connection which is user-specific)
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        project_name: str,
        network: NetworkStack,
        storage: StorageStack,
        secrets: SecretsStack,
        admin_email: str,
        discord_application_id: str,
        discord_guild_id: str,
        dependencies_layer,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.project_name = project_name

        # ------------------------------------------------------------------ #
        # Cognito User Pool
        # ------------------------------------------------------------------ #
        self.user_pool = cognito.UserPool(
            self,
            "AdminUserPool",
            user_pool_name=f"{project_name}-admin-users",
            self_sign_up_enabled=False,  # Volunteers are pre-provisioned only
            sign_in_aliases=cognito.SignInAliases(email=True, username=False),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_lowercase=True,
                require_uppercase=True,
                require_digits=True,
                require_symbols=True,
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=RemovalPolicy.RETAIN,
            mfa=cognito.Mfa.OPTIONAL,
            mfa_second_factor=cognito.MfaSecondFactor(otp=True, sms=False),
            email=cognito.UserPoolEmail.with_cognito(),
        )

        # User groups for RBAC
        self.admin_group = cognito.CfnUserPoolGroup(
            self,
            "AdminGroup",
            user_pool_id=self.user_pool.user_pool_id,
            group_name="Admin",
            description="Full admin access — manage FAQ, config, rate limits",
            precedence=1,
        )

        self.user_group = cognito.CfnUserPoolGroup(
            self,
            "UserGroup",
            user_pool_id=self.user_pool.user_pool_id,
            group_name="User",
            description="Limited access — adjust configurable values only",
            precedence=10,
        )

        # App client for the Next.js admin UI
        self.user_pool_client = cognito.UserPoolClient(
            self,
            "AdminAppClient",
            user_pool=self.user_pool,
            user_pool_client_name=f"{project_name}-admin-ui-client",
            auth_flows=cognito.AuthFlow(
                user_srp=True,
                user_password=False,  # SRP only, not raw password
            ),
            prevent_user_existence_errors=True,
            id_token_validity=Duration.hours(8),
            access_token_validity=Duration.hours(8),
            refresh_token_validity=Duration.days(30),
            generate_secret=False,  # Public client (SPA), no client secret
        )

        # Pre-seed the admin user
        # CDK creates user → user receives temp password via email → must change on first login
        self.initial_admin = cognito.CfnUserPoolUser(
            self,
            "InitialAdminUser",
            user_pool_id=self.user_pool.user_pool_id,
            username=admin_email,
            user_attributes=[
                cognito.CfnUserPoolUser.AttributeTypeProperty(
                    name="email", value=admin_email
                ),
                cognito.CfnUserPoolUser.AttributeTypeProperty(
                    name="email_verified", value="true"
                ),
            ],
            desired_delivery_mediums=["EMAIL"],
            force_alias_creation=True,
        )

        # Add admin user to Admin group
        cognito.CfnUserPoolUserToGroupAttachment(
            self,
            "AdminUserGroupAttachment",
            user_pool_id=self.user_pool.user_pool_id,
            username=admin_email,
            group_name="Admin",
        ).add_dependency(self.initial_admin)
        self.initial_admin.node.add_dependency(self.admin_group)

        # ------------------------------------------------------------------ #
        # Admin Lambda Function
        # ------------------------------------------------------------------ #
        admin_env = {
            "DISCORD_BOT_TOKEN_SECRET_ARN": secrets.bot_token_secret.secret_arn,
            "DISCORD_PUBLIC_KEY_SECRET_ARN": secrets.public_key_secret.secret_arn,
            "DISCORD_APPLICATION_ID": discord_application_id,
            "DISCORD_GUILD_ID": discord_guild_id,
            "CONFIG_TABLE_NAME": storage.config_table.table_name,
            "LOGS_TABLE_NAME": storage.logs_table.table_name,
            "RATE_LIMIT_TABLE_NAME": storage.rate_limit_table.table_name,
            "FAQ_BUCKET_NAME": storage.faq_bucket.bucket_name,
            "BEDROCK_KNOWLEDGE_BASE_ID": storage.knowledge_base.attr_knowledge_base_id,
            "BEDROCK_DATA_SOURCE_ID": storage.faq_data_source_id,
            "LOG_LEVEL": "INFO",
        }

        self.admin_lambda = lambda_.Function(
            self,
            "AdminLambda",
            function_name=f"{project_name}-admin-api",
            handler="backend.handlers.admin_handler.handler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[dependencies_layer],
            code=lambda_.Code.from_asset(
                "..",
                exclude=[
                    "frontend", "infrastructure", "docs",
                    "*.md", "Makefile", ".env", ".gitignore",
                    ".venv", "venv", "**/.venv", "**/venv",
                    "**/node_modules", "**/__pycache__",
                    "**/*.pyc", "**/*.pyo",
                    "backend/layer", "backend/tests",
                    "cdk.out", ".git",
                ],
            ),
            description="BeSa AI admin REST API handler",
            timeout=Duration.seconds(30),
            memory_size=512,
            environment=admin_env,
            tracing=lambda_.Tracing.ACTIVE,
        )

        # Grant permissions
        storage.config_table.grant_read_write_data(self.admin_lambda)
        storage.logs_table.grant_read_write_data(self.admin_lambda)
        storage.rate_limit_table.grant_write_data(self.admin_lambda)
        storage.faq_bucket.grant_read_write(self.admin_lambda)
        secrets.bot_token_secret.grant_read(self.admin_lambda)
        secrets.public_key_secret.grant_read(self.admin_lambda)

        # Bedrock permissions for FAQ sync
        self.admin_lambda.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:StartIngestionJob",
                    "bedrock:GetIngestionJob",
                    "bedrock:ListIngestionJobs",
                ],
                resources=["*"],
            )
        )

        # ------------------------------------------------------------------ #
        # Cognito JWT Authorizer for Admin API
        # ------------------------------------------------------------------ #
        self.admin_authorizer = apigw.CognitoUserPoolsAuthorizer(
            self,
            "AdminAuthorizer",
            cognito_user_pools=[self.user_pool],
            authorizer_name=f"{project_name}-admin-authorizer",
            identity_source="method.request.header.Authorization",
        )

        # ------------------------------------------------------------------ #
        # Admin REST API
        # ------------------------------------------------------------------ #
        admin_log_group = logs.LogGroup(
            self,
            "AdminAPILogGroup",
            log_group_name=f"/aws/apigateway/{project_name}-admin",
            retention=logs.RetentionDays.ONE_MONTH,
        )

        self.admin_api = apigw.RestApi(
            self,
            "AdminAPI",
            rest_api_name=f"{project_name}-admin-api",
            description="BeSa AI Admin REST API (authenticated by Cognito)",
            deploy_options=apigw.StageOptions(
                stage_name="prod",
                access_log_destination=apigw.LogGroupLogDestination(admin_log_group),
                tracing_enabled=True,
                metrics_enabled=True,
            ),
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=[
                    "https://main.d11zobutovmg96.amplifyapp.com",
                    "http://localhost:3000",
                ],
                allow_methods=apigw.Cors.ALL_METHODS,
                allow_headers=["Content-Type", "Authorization"],
            ),
        )

        # Lambda integration (all routes go to the same admin Lambda)
        admin_integration = apigw.LambdaIntegration(
            self.admin_lambda, proxy=True
        )

        # Build API routes: /api/{resource}/{sub-resource}
        api_root = self.admin_api.root.add_resource("api")
        self._add_route(api_root, "configuration", ["GET", "PUT"], admin_integration)
        faq_resource = api_root.add_resource("faq")
        faq_resource.add_resource("upload").add_method(
            "POST", admin_integration,
            authorizer=self.admin_authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )
        faq_resource.add_resource("sync-status").add_method(
            "GET", admin_integration,
            authorizer=self.admin_authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )
        faq_resource.add_resource("entries").add_method(
            "GET", admin_integration,
            authorizer=self.admin_authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        discord_resource = api_root.add_resource("discord")
        discord_resource.add_resource("channels").add_method(
            "GET", admin_integration,
            authorizer=self.admin_authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        logs_resource = api_root.add_resource("logs")
        logs_resource.add_resource("queries").add_method(
            "GET", admin_integration,
            authorizer=self.admin_authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        analytics_resource = api_root.add_resource("analytics")
        analytics_resource.add_resource("overview").add_method(
            "GET", admin_integration,
            authorizer=self.admin_authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        rate_limits_resource = api_root.add_resource("rate-limits")
        rate_limits_resource.add_resource("reset").add_method(
            "POST", admin_integration,
            authorizer=self.admin_authorizer,
            authorization_type=apigw.AuthorizationType.COGNITO,
        )

        # ------------------------------------------------------------------ #
        # Outputs
        # ------------------------------------------------------------------ #
        CfnOutput(
            self, "UserPoolId",
            value=self.user_pool.user_pool_id,
            description="Cognito User Pool ID — set in Next.js environment variables",
            export_name=f"{project_name}-user-pool-id",
        )
        CfnOutput(
            self, "UserPoolClientId",
            value=self.user_pool_client.user_pool_client_id,
            description="Cognito App Client ID — set in Next.js environment variables",
            export_name=f"{project_name}-user-pool-client-id",
        )
        CfnOutput(
            self, "AdminAPIUrl",
            value=self.admin_api.url,
            description="Admin REST API base URL — set in Next.js environment variables",
            export_name=f"{project_name}-admin-api-url",
        )
        CfnOutput(
            self, "AdminUserEmail",
            value=admin_email,
            description="Pre-seeded admin user email — check inbox for temp password",
        )

        Tags.of(self).add("Project", project_name)
        Tags.of(self).add("Component", "Admin")

    def _add_route(
        self,
        parent: apigw.IResource,
        resource_name: str,
        methods: list[str],
        integration: apigw.Integration,
    ) -> apigw.Resource:
        """Add a resource with multiple methods under the given parent."""
        resource = parent.add_resource(resource_name)
        for method in methods:
            resource.add_method(
                method,
                integration,
                authorizer=self.admin_authorizer,
                authorization_type=apigw.AuthorizationType.COGNITO,
            )
        return resource
