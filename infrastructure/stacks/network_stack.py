"""VPC and network infrastructure for the BeSa AI Assistant."""

from __future__ import annotations

from aws_cdk import Stack, Tags
from aws_cdk import aws_ec2 as ec2
from constructs import Construct


class NetworkStack(Stack):
    """
    Creates VPC with public and private subnets.
    Lambda functions run in private subnets and access AWS services
    via VPC endpoints (no NAT gateway cost for AWS API calls).
    NAT Gateway is included for outbound internet access (Discord API calls).
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

        # VPC with 2 AZs, private subnets with NAT, public subnets
        self.vpc = ec2.Vpc(
            self,
            "VPC",
            vpc_name=f"{project_name}-vpc",
            max_azs=2,
            nat_gateways=1,  # Single NAT GW for cost optimization (dev/staging)
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
            enable_dns_hostnames=True,
            enable_dns_support=True,
        )

        # VPC Endpoints for AWS service access without NAT (cost saving)
        # S3 Gateway endpoint (free)
        self.vpc.add_gateway_endpoint(
            "S3Endpoint",
            service=ec2.GatewayVpcEndpointAwsService.S3,
        )

        # DynamoDB Gateway endpoint (free)
        self.vpc.add_gateway_endpoint(
            "DynamoDBEndpoint",
            service=ec2.GatewayVpcEndpointAwsService.DYNAMODB,
        )

        # Security group for Lambda functions
        self.lambda_sg = ec2.SecurityGroup(
            self,
            "LambdaSG",
            vpc=self.vpc,
            security_group_name=f"{project_name}-lambda-sg",
            description="Security group for BeSa AI Lambda functions",
            allow_all_outbound=True,  # Needed for Discord API calls via NAT
        )

        # Interface VPC endpoints for Bedrock, Secrets Manager, SQS, Bedrock Runtime
        # Bedrock Runtime (for model invocations)
        self.vpc.add_interface_endpoint(
            "BedrockRuntimeEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[self.lambda_sg],
        )

        # Bedrock Agent Runtime (for Knowledge Base)
        self.vpc.add_interface_endpoint(
            "BedrockAgentRuntimeEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.BEDROCK_AGENT_RUNTIME,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[self.lambda_sg],
        )

        # Secrets Manager
        self.vpc.add_interface_endpoint(
            "SecretsManagerEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[self.lambda_sg],
        )

        # SQS
        self.vpc.add_interface_endpoint(
            "SQSEndpoint",
            service=ec2.InterfaceVpcEndpointAwsService.SQS,
            subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[self.lambda_sg],
        )

        Tags.of(self).add("Project", project_name)
        Tags.of(self).add("Component", "Network")
