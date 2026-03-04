"""Agent infrastructure: Lambda functions, SQS queue, and Discord API Gateway endpoint."""

from __future__ import annotations

from aws_cdk import (
    Duration,
    Stack,
    Tags,
    aws_apigateway as apigw,
    aws_cloudwatch as cloudwatch,
    aws_ec2 as ec2,
    aws_events as events,
    aws_events_targets as targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_lambda_event_sources as event_sources,
    aws_logs as logs,
    aws_sqs as sqs,
)
from constructs import Construct

from stacks.network_stack import NetworkStack
from stacks.storage_stack import StorageStack
from stacks.secrets_stack import SecretsStack


class AgentStack(Stack):
    """
    Provisions the agent processing infrastructure:
    - SQS FIFO queue for question processing (guaranteed ordering per user)
    - Webhook Lambda: receives Discord interactions, acks within 3 seconds, enqueues
    - Poller Lambda: polls bot channel every 60s for new channel messages
    - Processor Lambda: dequeues questions, runs waterfall, posts Discord response
    - API Gateway: Discord interactions endpoint (POST /discord/webhook)
    - EventBridge Scheduler: triggers Poller Lambda every 60 seconds
    - CloudWatch: log groups, dashboard, alarms
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        project_name: str,
        network: NetworkStack,
        storage: StorageStack,
        secrets: SecretsStack,
        discord_application_id: str,
        discord_guild_id: str,
        discord_bot_channel_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.project_name = project_name

        # ------------------------------------------------------------------ #
        # Lambda Code Asset — project root, excluding non-backend directories
        # All three Lambda functions share this asset so it is hashed once.
        # ------------------------------------------------------------------ #
        lambda_code = lambda_.Code.from_asset(
            "..",
            exclude=[
                # Frontend — not needed in Lambda
                "frontend",
                # Infrastructure code — not needed in Lambda
                "infrastructure",
                # Docs and config files — not needed in Lambda
                "docs",
                "*.md",
                "Makefile",
                ".env",
                ".gitignore",
                # Virtual environments
                ".venv",
                "venv",
                "**/.venv",
                "**/venv",
                # Node modules (frontend)
                "**/node_modules",
                # Python bytecode
                "**/__pycache__",
                "**/*.pyc",
                "**/*.pyo",
                # Lambda layer build output (deployed as a Layer, not inline)
                "backend/layer",
                # Tests — not needed in Lambda
                "backend/tests",
                # CDK output
                "cdk.out",
                ".git",
            ],
        )

        # ------------------------------------------------------------------ #
        # Lambda Layer — shared Python dependencies
        # ------------------------------------------------------------------ #
        dependencies_layer = lambda_.LayerVersion(
            self,
            "DependenciesLayer",
            layer_version_name=f"{project_name}-dependencies",
            code=lambda_.Code.from_asset("../backend/layer"),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="BeSa AI shared dependencies (strands-agents, discord.py, httpx, etc.)",
        )

        # ------------------------------------------------------------------ #
        # SQS FIFO Queue — async question processing
        # ------------------------------------------------------------------ #
        dead_letter_queue = sqs.Queue(
            self,
            "ProcessingDLQ",
            queue_name=f"{project_name}-processing-dlq.fifo",
            fifo=True,
            retention_period=Duration.days(14),
        )

        self.processing_queue = sqs.Queue(
            self,
            "ProcessingQueue",
            queue_name=f"{project_name}-processing.fifo",
            fifo=True,
            content_based_deduplication=True,
            visibility_timeout=Duration.minutes(16),  # > Lambda timeout (15 min)
            retention_period=Duration.hours(4),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=dead_letter_queue,
            ),
        )

        # ------------------------------------------------------------------ #
        # Common Lambda environment variables
        # ------------------------------------------------------------------ #
        common_env = {
            "DISCORD_BOT_TOKEN_SECRET_ARN": secrets.bot_token_secret.secret_arn,
            "DISCORD_PUBLIC_KEY_SECRET_ARN": secrets.public_key_secret.secret_arn,
            "DISCORD_APPLICATION_ID": discord_application_id,
            "DISCORD_GUILD_ID": discord_guild_id,
            "DISCORD_BOT_CHANNEL_ID": discord_bot_channel_id,
            "PROCESSING_QUEUE_URL": self.processing_queue.queue_url,
            "CONFIG_TABLE_NAME": storage.config_table.table_name,
            "LOGS_TABLE_NAME": storage.logs_table.table_name,
            "RATE_LIMIT_TABLE_NAME": storage.rate_limit_table.table_name,
            "STATE_TABLE_NAME": storage.state_table.table_name,
            "BEDROCK_KNOWLEDGE_BASE_ID": storage.knowledge_base.attr_knowledge_base_id,
            "BEDROCK_DATA_SOURCE_ID": storage.faq_data_source.attr_data_source_id,
            "FAQ_BUCKET_NAME": storage.faq_bucket.bucket_name,
            "LOG_LEVEL": "INFO",
        }

        # Common Lambda configuration
        common_lambda_kwargs = dict(
            runtime=lambda_.Runtime.PYTHON_3_12,
            layers=[dependencies_layer],
            vpc=network.vpc,
            vpc_subnets=ec2.SubnetSelection(
                subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
            ),
            security_groups=[network.lambda_sg],
            environment=common_env,
            tracing=lambda_.Tracing.ACTIVE,  # X-Ray tracing
        )

        # ------------------------------------------------------------------ #
        # Webhook Lambda — Discord interactions endpoint (fast, < 3s)
        # ------------------------------------------------------------------ #
        self.webhook_lambda = lambda_.Function(
            self,
            "WebhookLambda",
            function_name=f"{project_name}-webhook",
            handler="backend.handlers.webhook_handler.handler",
            code=lambda_code,
            description="Receives Discord slash command interactions, acks within 3s, queues to SQS",
            timeout=Duration.seconds(10),  # Short — only ack + SQS publish
            memory_size=256,
            **common_lambda_kwargs,
        )
        self._grant_common_permissions(self.webhook_lambda, storage, secrets)
        self.processing_queue.grant_send_messages(self.webhook_lambda)

        self.webhook_log_group = logs.LogGroup(
            self,
            "WebhookLogGroup",
            log_group_name=f"/aws/lambda/{project_name}-webhook",
            retention=logs.RetentionDays.ONE_MONTH,
        )

        # ------------------------------------------------------------------ #
        # Poller Lambda — periodic channel message polling
        # ------------------------------------------------------------------ #
        self.poller_lambda = lambda_.Function(
            self,
            "PollerLambda",
            function_name=f"{project_name}-poller",
            handler="backend.handlers.poller_handler.handler",
            code=lambda_code,
            description="Polls bot channel for new messages every 60 seconds",
            timeout=Duration.seconds(30),
            memory_size=256,
            **common_lambda_kwargs,
        )
        self._grant_common_permissions(self.poller_lambda, storage, secrets)
        self.processing_queue.grant_send_messages(self.poller_lambda)

        # EventBridge Scheduler — trigger poller every 60 seconds
        poller_rule = events.Rule(
            self,
            "PollerSchedule",
            rule_name=f"{project_name}-poller-schedule",
            description="Trigger Discord channel message poller every 60 seconds",
            schedule=events.Schedule.rate(Duration.minutes(1)),
        )
        poller_rule.add_target(targets.LambdaFunction(self.poller_lambda))

        # ------------------------------------------------------------------ #
        # Processor Lambda — SQS-triggered agent processing (long-running)
        # ------------------------------------------------------------------ #
        self.processor_lambda = lambda_.Function(
            self,
            "ProcessorLambda",
            function_name=f"{project_name}-processor",
            handler="backend.handlers.processor_handler.handler",
            code=lambda_code,
            description="Processes questions through multi-agent waterfall, posts Discord response",
            timeout=Duration.minutes(15),  # Max Lambda timeout
            memory_size=2048,  # Agents need more memory
            **common_lambda_kwargs,
        )
        self._grant_common_permissions(self.processor_lambda, storage, secrets)
        self.processing_queue.grant_consume_messages(self.processor_lambda)

        # SQS event source — batch size 1 for agent workloads
        self.processor_lambda.add_event_source(
            event_sources.SqsEventSource(
                self.processing_queue,
                batch_size=1,
                max_concurrency=5,  # Limit concurrent agent invocations
            )
        )

        # Bedrock permissions for processor
        self.processor_lambda.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock-agent-runtime:Retrieve",
                    "bedrock-agent-runtime:RetrieveAndGenerate",
                ],
                resources=["*"],
            )
        )

        # ------------------------------------------------------------------ #
        # API Gateway — Discord interactions endpoint
        # ------------------------------------------------------------------ #
        api_log_group = logs.LogGroup(
            self,
            "APIGWLogGroup",
            log_group_name=f"/aws/apigateway/{project_name}",
            retention=logs.RetentionDays.ONE_MONTH,
        )

        self.api = apigw.RestApi(
            self,
            "DiscordAPI",
            rest_api_name=f"{project_name}-discord-api",
            description="BeSa AI Discord interactions endpoint",
            deploy_options=apigw.StageOptions(
                stage_name="prod",
                access_log_destination=apigw.LogGroupLogDestination(api_log_group),
                access_log_format=apigw.AccessLogFormat.json_with_standard_fields(
                    caller=True,
                    http_method=True,
                    ip=True,
                    protocol=True,
                    request_time=True,
                    resource_path=True,
                    response_length=True,
                    status=True,
                    user=True,
                ),
                tracing_enabled=True,
                metrics_enabled=True,
                throttling_burst_limit=100,
                throttling_rate_limit=50,
            ),
        )

        # POST /discord/webhook
        discord_resource = self.api.root.add_resource("discord")
        webhook_resource = discord_resource.add_resource("webhook")
        webhook_resource.add_method(
            "POST",
            apigw.LambdaIntegration(
                self.webhook_lambda,
                proxy=True,
                timeout=Duration.seconds(9),  # API GW max is 29s, but we need < 3s
            ),
        )

        # Store webhook URL as output
        from aws_cdk import CfnOutput
        CfnOutput(
            self,
            "WebhookURL",
            value=f"{self.api.url}discord/webhook",
            description=(
                "Discord interactions endpoint URL. "
                "Set this in Discord Developer Portal → General Information → "
                "Interactions Endpoint URL"
            ),
            export_name=f"{project_name}-webhook-url",
        )

        # ------------------------------------------------------------------ #
        # CloudWatch Alarms
        # ------------------------------------------------------------------ #
        self._create_alarms(project_name, dead_letter_queue)

        # ------------------------------------------------------------------ #
        # CloudWatch Dashboard
        # ------------------------------------------------------------------ #
        self._create_dashboard(project_name, dead_letter_queue)

        Tags.of(self).add("Project", project_name)
        Tags.of(self).add("Component", "Agent")

    def _create_alarms(self, project_name: str, dlq: sqs.Queue) -> None:
        """Create CloudWatch alarms for error detection and operational health."""

        # Processor Lambda — error count > 3 in any 5-minute window
        cloudwatch.Alarm(
            self,
            "ProcessorErrorAlarm",
            alarm_name=f"{project_name}-processor-errors",
            alarm_description="Processor Lambda errors > 3 in 5 minutes — agent pipeline failing",
            metric=self.processor_lambda.metric_errors(
                period=Duration.minutes(5),
                statistic="Sum",
            ),
            threshold=3,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        )

        # Processor Lambda — P95 duration > 13 minutes (Lambda timeout is 15)
        cloudwatch.Alarm(
            self,
            "ProcessorDurationAlarm",
            alarm_name=f"{project_name}-processor-duration",
            alarm_description="Processor Lambda P95 duration approaching 15-minute timeout",
            metric=self.processor_lambda.metric_duration(
                period=Duration.minutes(5),
                statistic="p95",
            ),
            threshold=13 * 60 * 1000,  # 13 minutes in milliseconds
            evaluation_periods=2,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        )

        # Webhook Lambda — error count > 1 in any 1-minute window
        cloudwatch.Alarm(
            self,
            "WebhookErrorAlarm",
            alarm_name=f"{project_name}-webhook-errors",
            alarm_description="Webhook Lambda errors — Discord interactions failing to acknowledge",
            metric=self.webhook_lambda.metric_errors(
                period=Duration.minutes(1),
                statistic="Sum",
            ),
            threshold=1,
            evaluation_periods=2,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        )

        # SQS DLQ — any message visible means processing failed after 3 retries
        cloudwatch.Alarm(
            self,
            "DLQAlarm",
            alarm_name=f"{project_name}-dlq-messages",
            alarm_description="Messages in DLQ — questions failed after 3 retries",
            metric=dlq.metric_approximate_number_of_messages_visible(
                period=Duration.minutes(5),
                statistic="Maximum",
            ),
            threshold=1,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        )

        # API Gateway — 5xx error rate > 5% over 5 minutes
        cloudwatch.Alarm(
            self,
            "APIGateway5xxAlarm",
            alarm_name=f"{project_name}-api-5xx",
            alarm_description="Discord API Gateway 5xx errors — webhook endpoint degraded",
            metric=self.api.metric_server_error(
                period=Duration.minutes(5),
                statistic="Sum",
            ),
            threshold=5,
            evaluation_periods=1,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
        )

    def _create_dashboard(self, project_name: str, dlq: sqs.Queue) -> None:
        """Create a CloudWatch dashboard for operational monitoring."""

        dashboard = cloudwatch.Dashboard(
            self,
            "OperationalDashboard",
            dashboard_name=f"{project_name}-operations",
        )

        # Row 1: Lambda invocations and errors
        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="Lambda Invocations",
                width=8,
                left=[
                    self.processor_lambda.metric_invocations(
                        period=Duration.minutes(5), statistic="Sum", label="Processor"
                    ),
                    self.webhook_lambda.metric_invocations(
                        period=Duration.minutes(5), statistic="Sum", label="Webhook"
                    ),
                    self.poller_lambda.metric_invocations(
                        period=Duration.minutes(5), statistic="Sum", label="Poller"
                    ),
                ],
            ),
            cloudwatch.GraphWidget(
                title="Lambda Errors",
                width=8,
                left=[
                    self.processor_lambda.metric_errors(
                        period=Duration.minutes(5), statistic="Sum", label="Processor errors"
                    ),
                    self.webhook_lambda.metric_errors(
                        period=Duration.minutes(5), statistic="Sum", label="Webhook errors"
                    ),
                ],
            ),
            cloudwatch.GraphWidget(
                title="Processor Duration (ms)",
                width=8,
                left=[
                    self.processor_lambda.metric_duration(
                        period=Duration.minutes(5), statistic="p50", label="p50"
                    ),
                    self.processor_lambda.metric_duration(
                        period=Duration.minutes(5), statistic="p95", label="p95"
                    ),
                    self.processor_lambda.metric_duration(
                        period=Duration.minutes(5), statistic="Maximum", label="max"
                    ),
                ],
            ),
        )

        # Row 2: SQS queue depth and API Gateway
        dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title="SQS Processing Queue Depth",
                width=8,
                left=[
                    self.processing_queue.metric_approximate_number_of_messages_visible(
                        period=Duration.minutes(1), statistic="Maximum", label="Queued"
                    ),
                    self.processing_queue.metric_approximate_number_of_messages_not_visible(
                        period=Duration.minutes(1), statistic="Maximum", label="In-flight"
                    ),
                ],
            ),
            cloudwatch.GraphWidget(
                title="SQS DLQ (Failed Messages)",
                width=8,
                left=[
                    dlq.metric_approximate_number_of_messages_visible(
                        period=Duration.minutes(5), statistic="Maximum", label="DLQ depth"
                    ),
                ],
            ),
            cloudwatch.GraphWidget(
                title="API Gateway Requests",
                width=8,
                left=[
                    self.api.metric_count(
                        period=Duration.minutes(5), statistic="Sum", label="Total requests"
                    ),
                    self.api.metric_client_error(
                        period=Duration.minutes(5), statistic="Sum", label="4xx errors"
                    ),
                    self.api.metric_server_error(
                        period=Duration.minutes(5), statistic="Sum", label="5xx errors"
                    ),
                ],
            ),
        )

        # Row 3: Alarm reference summary
        dashboard.add_widgets(
            cloudwatch.TextWidget(
                markdown=(
                    "## Operational Status\n\n"
                    f"**Project:** {project_name}\n\n"
                    "Monitor alarms in the CloudWatch Alarms console.\n\n"
                    f"Alarms: `{project_name}-processor-errors` | "
                    f"`{project_name}-processor-duration` | "
                    f"`{project_name}-webhook-errors` | "
                    f"`{project_name}-dlq-messages` | "
                    f"`{project_name}-api-5xx`"
                ),
                width=24,
                height=3,
            ),
        )

    def _grant_common_permissions(
        self,
        fn: lambda_.Function,
        storage: StorageStack,
        secrets: SecretsStack,
    ) -> None:
        """Grant common permissions needed by all Lambda functions."""
        # DynamoDB access
        storage.config_table.grant_read_write_data(fn)
        storage.logs_table.grant_read_write_data(fn)
        storage.rate_limit_table.grant_read_write_data(fn)
        storage.state_table.grant_read_write_data(fn)

        # S3 access for FAQ bucket
        storage.faq_bucket.grant_read_write(fn)

        # Secrets Manager access
        secrets.bot_token_secret.grant_read(fn)
        secrets.public_key_secret.grant_read(fn)

        # X-Ray tracing
        fn.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["xray:PutTraceSegments", "xray:PutTelemetryRecords"],
                resources=["*"],
            )
        )
