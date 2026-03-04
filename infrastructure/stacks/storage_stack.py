"""Storage infrastructure: S3, DynamoDB, Bedrock Knowledge Base, S3 Vectors."""

from __future__ import annotations

from aws_cdk import (
    Duration,
    RemovalPolicy,
    Stack,
    Tags,
)
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3vectors as s3vectors
from constructs import Construct


class StorageStack(Stack):
    """
    Provisions:
    - S3 bucket for FAQ file storage (versioned, encrypted)
    - DynamoDB tables: config, logs, rate-limits, state (on-demand billing)
    - S3 Vectors bucket + index for vector search (replaces OpenSearch Serverless)
    - Bedrock Knowledge Base connected to S3 + S3 Vectors
    - IAM role for Bedrock Knowledge Base
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        project_name: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.project_name = project_name

        # ------------------------------------------------------------------ #
        # S3 — FAQ Storage
        # ------------------------------------------------------------------ #
        self.faq_bucket = s3.Bucket(
            self,
            "FAQBucket",
            bucket_name=f"{project_name}-faq-{self.account}",
            versioned=True,
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    noncurrent_version_expiration=Duration.days(90),
                    enabled=True,
                )
            ],
        )

        # ------------------------------------------------------------------ #
        # DynamoDB — Configuration Table
        # ------------------------------------------------------------------ #
        self.config_table = dynamodb.Table(
            self,
            "ConfigTable",
            table_name=f"{project_name}-config",
            partition_key=dynamodb.Attribute(
                name="config_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.RETAIN,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
        )

        self.config_table.add_global_secondary_index(
            index_name="pk-sk-index",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
        )

        # ------------------------------------------------------------------ #
        # DynamoDB — Query Logs Table (TTL for 90-day retention)
        # ------------------------------------------------------------------ #
        self.logs_table = dynamodb.Table(
            self,
            "LogsTable",
            table_name=f"{project_name}-logs",
            partition_key=dynamodb.Attribute(
                name="log_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="ttl",
        )

        self.logs_table.add_global_secondary_index(
            index_name="log-type-timestamp-index",
            partition_key=dynamodb.Attribute(
                name="log_type", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="timestamp", type=dynamodb.AttributeType.STRING
            ),
        )

        # ------------------------------------------------------------------ #
        # DynamoDB — Rate Limit Table (TTL for auto-reset)
        # ------------------------------------------------------------------ #
        self.rate_limit_table = dynamodb.Table(
            self,
            "RateLimitTable",
            table_name=f"{project_name}-rate-limits",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
            time_to_live_attribute="ttl",
        )

        # ------------------------------------------------------------------ #
        # DynamoDB — Poll State Table
        # ------------------------------------------------------------------ #
        self.state_table = dynamodb.Table(
            self,
            "StateTable",
            table_name=f"{project_name}-state",
            partition_key=dynamodb.Attribute(
                name="pk", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="sk", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ------------------------------------------------------------------ #
        # S3 Vectors — Vector store for Bedrock Knowledge Base
        #
        # Replaces OpenSearch Serverless. No minimum hourly cost — pay only
        # for storage and queries. CloudFormation creates the index directly
        # (no custom resource Lambda required).
        # ------------------------------------------------------------------ #

        # Vector bucket (globally unique name, lowercase only)
        self.vector_bucket = s3vectors.CfnVectorBucket(
            self,
            "FAQVectorBucket",
            vector_bucket_name=f"besa-faq-vec-{self.account}",
        )

        # Vector index — Titan Embeddings v2 produces 1024-dim float32 vectors
        self.vector_index = s3vectors.CfnIndex(
            self,
            "FAQVectorIndex",
            vector_bucket_arn=self.vector_bucket.attr_vector_bucket_arn,
            index_name="besa-faq-index",
            data_type="float32",
            dimension=1024,
            distance_metric="cosine",
        )
        self.vector_index.add_dependency(self.vector_bucket)

        # ------------------------------------------------------------------ #
        # IAM — Bedrock Knowledge Base Execution Role
        # ------------------------------------------------------------------ #
        self.kb_role = iam.Role(
            self,
            "BedrockKBRole",
            role_name=f"{project_name}-bedrock-kb-role",
            assumed_by=iam.ServicePrincipal("bedrock.amazonaws.com"),
            description="Execution role for BeSa AI Bedrock Knowledge Base",
        )

        # Allow Bedrock KB to read FAQ files from S3
        self.faq_bucket.grant_read(self.kb_role)

        # Allow Bedrock KB to invoke Titan Embeddings v2
        self.kb_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["bedrock:InvokeModel"],
                resources=[
                    f"arn:aws:bedrock:{self.region}::foundation-model/"
                    "amazon.titan-embed-text-v2:0"
                ],
            )
        )

        # Allow Bedrock KB to read/write vectors in S3 Vectors
        self.kb_role.add_to_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=[
                    "s3vectors:GetVectorBucket",
                    "s3vectors:ListIndexes",
                    "s3vectors:GetIndex",
                    "s3vectors:QueryVectors",
                    "s3vectors:GetVectors",
                    "s3vectors:PutVectors",
                    "s3vectors:ListVectors",
                ],
                resources=[
                    self.vector_bucket.attr_vector_bucket_arn,
                    f"{self.vector_bucket.attr_vector_bucket_arn}/index/*",
                ],
            )
        )

        # ------------------------------------------------------------------ #
        # Bedrock Knowledge Base
        # ------------------------------------------------------------------ #
        self.knowledge_base = bedrock.CfnKnowledgeBase(
            self,
            "FAQKnowledgeBase",
            name=f"{project_name}-faq-kb",
            description="BeSa AI FAQ knowledge base — semantic search over workshop FAQs",
            role_arn=self.kb_role.role_arn,
            knowledge_base_configuration=bedrock.CfnKnowledgeBase.KnowledgeBaseConfigurationProperty(
                type="VECTOR",
                vector_knowledge_base_configuration=bedrock.CfnKnowledgeBase.VectorKnowledgeBaseConfigurationProperty(
                    embedding_model_arn=(
                        f"arn:aws:bedrock:{self.region}::foundation-model/"
                        "amazon.titan-embed-text-v2:0"
                    ),
                ),
            ),
            storage_configuration=bedrock.CfnKnowledgeBase.StorageConfigurationProperty(
                type="S3_VECTORS",
                s3_vectors_configuration=bedrock.CfnKnowledgeBase.S3VectorsConfigurationProperty(
                    vector_bucket_arn=self.vector_bucket.attr_vector_bucket_arn,
                    index_arn=self.vector_index.attr_index_arn,
                ),
            ),
        )
        self.knowledge_base.add_dependency(self.vector_index)
        self.knowledge_base.node.add_dependency(self.kb_role)

        # Bedrock Data Source — S3 bucket as FAQ source
        self.faq_data_source = bedrock.CfnDataSource(
            self,
            "FAQDataSource",
            knowledge_base_id=self.knowledge_base.attr_knowledge_base_id,
            name=f"{project_name}-faq-s3-source",
            description="FAQ files stored in S3 (markdown format)",
            data_source_configuration=bedrock.CfnDataSource.DataSourceConfigurationProperty(
                type="S3",
                s3_configuration=bedrock.CfnDataSource.S3DataSourceConfigurationProperty(
                    bucket_arn=self.faq_bucket.bucket_arn,
                    inclusion_prefixes=["faq/"],
                ),
            ),
            vector_ingestion_configuration=bedrock.CfnDataSource.VectorIngestionConfigurationProperty(
                chunking_configuration=bedrock.CfnDataSource.ChunkingConfigurationProperty(
                    chunking_strategy="FIXED_SIZE",
                    fixed_size_chunking_configuration=bedrock.CfnDataSource.FixedSizeChunkingConfigurationProperty(
                        max_tokens=300,
                        overlap_percentage=20,
                    ),
                )
            ),
        )

        Tags.of(self).add("Project", project_name)
        Tags.of(self).add("Component", "Storage")
