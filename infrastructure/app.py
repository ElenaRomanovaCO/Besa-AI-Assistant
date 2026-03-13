#!/usr/bin/env python3
"""
BeSa AI Assistant — CDK Application Entry Point

Deployment:
  cd infrastructure
  pip install -r requirements.txt
  cdk bootstrap aws://<ACCOUNT_ID>/us-east-1
  cdk deploy --all

After deployment:
  1. Set Discord bot token in Secrets Manager (see docs/DISCORD_SETUP.md)
  2. Set Discord public key in Secrets Manager
  3. Configure Discord bot Interactions Endpoint URL (from WebhookURL output)
  4. Upload initial FAQ file via Admin UI or AWS Console
  5. Configure Amplify app for frontend (see docs/DEPLOYMENT.md)
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (one level above infrastructure/).
# Variables already set in the environment (CI/CD, shell exports) are NOT overridden.
load_dotenv(Path(__file__).parent.parent / ".env")

import aws_cdk as cdk

from stacks.network_stack import NetworkStack
from stacks.storage_stack import StorageStack
from stacks.secrets_stack import SecretsStack
from stacks.agent_stack import AgentStack
from stacks.admin_stack import AdminStack
from stacks.waf_stack import WAFStack

# =========================================================================== #
# Configuration — update these values before deploying
# =========================================================================== #

PROJECT_NAME = "besa-ai-assistant"
AWS_ACCOUNT = os.environ.get("CDK_DEFAULT_ACCOUNT") or None  # None → CDK uses ${AWS::AccountId} token
AWS_REGION = os.environ.get("CDK_DEFAULT_REGION") or "us-east-1"

# Discord settings — fill in after creating the Discord bot
# See: docs/DISCORD_SETUP.md
DISCORD_APPLICATION_ID = os.environ.get("DISCORD_APPLICATION_ID", "REPLACE_ME")
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID", "REPLACE_ME")
DISCORD_BOT_CHANNEL_ID = os.environ.get("DISCORD_BOT_CHANNEL_ID", "REPLACE_ME")

# Admin UI settings
ADMIN_EMAIL = "eromanova115@gmail.com"

# Environment (set CDK_STAGE=staging for staging deployment)
STAGE = os.environ.get("CDK_STAGE", "production")

# =========================================================================== #

# Staging uses a separate prefix to avoid resource name collisions
STACK_PREFIX = PROJECT_NAME if STAGE == "production" else f"{PROJECT_NAME}-staging"

env = cdk.Environment(account=AWS_ACCOUNT, region=AWS_REGION)

app = cdk.App()

# Network — VPC with private subnets and VPC endpoints
network = NetworkStack(
    app,
    f"{STACK_PREFIX}-network",
    project_name=STACK_PREFIX,
    env=env,
    description="BeSa AI Assistant — VPC and network infrastructure",
)

# Secrets — Discord credentials (values set manually post-deploy)
secrets = SecretsStack(
    app,
    f"{STACK_PREFIX}-secrets",
    project_name=STACK_PREFIX,
    env=env,
    description="BeSa AI Assistant — Secrets Manager for Discord credentials",
)

# Storage — S3, DynamoDB, Bedrock Knowledge Base, Guardrails
storage = StorageStack(
    app,
    f"{STACK_PREFIX}-storage",
    project_name=STACK_PREFIX,
    env=env,
    description="BeSa AI Assistant — S3, DynamoDB, Bedrock Knowledge Base",
)

# Agent — Lambda functions, SQS, API Gateway (Discord endpoint)
agent = AgentStack(
    app,
    f"{STACK_PREFIX}-agent",
    project_name=STACK_PREFIX,
    network=network,
    storage=storage,
    secrets=secrets,
    discord_application_id=DISCORD_APPLICATION_ID,
    discord_guild_id=DISCORD_GUILD_ID,
    discord_bot_channel_id=DISCORD_BOT_CHANNEL_ID,
    ops_email=ADMIN_EMAIL,
    guardrail_id=storage.guardrail.attr_guardrail_id,
    guardrail_version=storage.guardrail_version.attr_version,
    env=env,
    description="BeSa AI Assistant — Lambda agents, SQS queue, Discord API Gateway",
)

# Admin — Cognito, Admin API, Amplify
admin = AdminStack(
    app,
    f"{STACK_PREFIX}-admin",
    project_name=STACK_PREFIX,
    network=network,
    storage=storage,
    secrets=secrets,
    admin_email=ADMIN_EMAIL,
    discord_application_id=DISCORD_APPLICATION_ID,
    discord_guild_id=DISCORD_GUILD_ID,
    env=env,
    description="BeSa AI Assistant — Cognito auth, Admin API, Amplify hosting",
)

# WAF — protects both API Gateways
waf = WAFStack(
    app,
    f"{STACK_PREFIX}-waf",
    project_name=STACK_PREFIX,
    api_gateway_arns=[
        # API Gateway stage ARNs (required for WAF association)
        f"arn:aws:apigateway:{AWS_REGION}::/restapis/{agent.api.rest_api_id}/stages/prod",
        f"arn:aws:apigateway:{AWS_REGION}::/restapis/{admin.admin_api.rest_api_id}/stages/prod",
    ],
    env=env,
    description="BeSa AI Assistant — WAF protection for API Gateways",
)

# Stack deployment order
agent.add_dependency(network)
agent.add_dependency(storage)
agent.add_dependency(secrets)
admin.add_dependency(network)
admin.add_dependency(storage)
admin.add_dependency(secrets)
# admin no longer depends on agent (has its own layer)
waf.add_dependency(agent)
waf.add_dependency(admin)

app.synth()
