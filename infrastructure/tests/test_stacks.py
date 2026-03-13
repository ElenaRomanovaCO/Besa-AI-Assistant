"""CDK stack assertion tests.

Validates that stacks produce expected CloudFormation resources,
IAM policies, and security configurations.
"""

import pytest
import aws_cdk as cdk
from aws_cdk import assertions

import sys
from pathlib import Path

# Add infrastructure dir to path for stack imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from stacks.network_stack import NetworkStack
from stacks.storage_stack import StorageStack
from stacks.secrets_stack import SecretsStack


@pytest.fixture
def app():
    return cdk.App()


@pytest.fixture
def env():
    return cdk.Environment(account="123456789012", region="us-east-1")


# --------------------------------------------------------------------------- #
# NetworkStack
# --------------------------------------------------------------------------- #

class TestNetworkStack:
    def test_creates_vpc(self, app, env):
        stack = NetworkStack(app, "TestNetwork", project_name="test", env=env)
        template = assertions.Template.from_stack(stack)
        template.resource_count_is("AWS::EC2::VPC", 1)

    def test_creates_nat_gateway(self, app, env):
        stack = NetworkStack(app, "TestNetwork", project_name="test", env=env)
        template = assertions.Template.from_stack(stack)
        template.resource_count_is("AWS::EC2::NatGateway", 1)

    def test_creates_security_group(self, app, env):
        stack = NetworkStack(app, "TestNetwork", project_name="test", env=env)
        template = assertions.Template.from_stack(stack)
        template.resource_count_is("AWS::EC2::SecurityGroup", 1)

    def test_creates_vpc_endpoints(self, app, env):
        stack = NetworkStack(app, "TestNetwork", project_name="test", env=env)
        template = assertions.Template.from_stack(stack)
        # 4 interface endpoints (Bedrock, Bedrock Agent, Secrets Manager, SQS)
        template.resource_count_is("AWS::EC2::VPCEndpoint", 6)  # 4 interface + 2 gateway


# --------------------------------------------------------------------------- #
# StorageStack
# --------------------------------------------------------------------------- #

class TestStorageStack:
    def test_creates_faq_bucket(self, app, env):
        stack = StorageStack(app, "TestStorage", project_name="test", env=env)
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::S3::Bucket", {
            "VersioningConfiguration": {"Status": "Enabled"},
        })

    def test_faq_bucket_blocks_public_access(self, app, env):
        stack = StorageStack(app, "TestStorage", project_name="test", env=env)
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::S3::Bucket", {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
        })

    def test_creates_dynamodb_tables(self, app, env):
        stack = StorageStack(app, "TestStorage", project_name="test", env=env)
        template = assertions.Template.from_stack(stack)
        # 4 tables: config, logs, rate-limits, state
        template.resource_count_is("AWS::DynamoDB::Table", 4)

    def test_config_table_has_pitr(self, app, env):
        stack = StorageStack(app, "TestStorage", project_name="test", env=env)
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::DynamoDB::Table", {
            "TableName": "test-config",
            "PointInTimeRecoverySpecification": {
                "PointInTimeRecoveryEnabled": True,
            },
        })

    def test_tables_use_pay_per_request(self, app, env):
        stack = StorageStack(app, "TestStorage", project_name="test", env=env)
        template = assertions.Template.from_stack(stack)
        # All 4 tables should use PAY_PER_REQUEST
        resources = template.find_resources("AWS::DynamoDB::Table")
        for name, resource in resources.items():
            assert resource["Properties"]["BillingMode"] == "PAY_PER_REQUEST", (
                f"Table {name} should use PAY_PER_REQUEST billing"
            )

    def test_logs_table_has_ttl(self, app, env):
        stack = StorageStack(app, "TestStorage", project_name="test", env=env)
        template = assertions.Template.from_stack(stack)
        template.has_resource_properties("AWS::DynamoDB::Table", {
            "TableName": "test-logs",
            "TimeToLiveSpecification": {
                "AttributeName": "ttl",
                "Enabled": True,
            },
        })

    def test_creates_knowledge_base(self, app, env):
        stack = StorageStack(app, "TestStorage", project_name="test", env=env)
        template = assertions.Template.from_stack(stack)
        template.resource_count_is("AWS::Bedrock::KnowledgeBase", 1)


# --------------------------------------------------------------------------- #
# SecretsStack
# --------------------------------------------------------------------------- #

class TestSecretsStack:
    def test_creates_secrets(self, app, env):
        stack = SecretsStack(app, "TestSecrets", project_name="test", env=env)
        template = assertions.Template.from_stack(stack)
        template.resource_count_is("AWS::SecretsManager::Secret", 2)
