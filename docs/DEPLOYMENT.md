# Deployment Guide

Step-by-step instructions for deploying BeSa AI Assistant to AWS.

---

## Prerequisites

Make sure you have the following installed and configured before proceeding.

### Required Tools

| Tool | Version | Install |
|---|---|---|
| Python | 3.11+ | [python.org](https://www.python.org/downloads/) |
| Node.js | 18+ | [nodejs.org](https://nodejs.org/) |
| AWS CLI | 2.x | [aws.amazon.com/cli](https://aws.amazon.com/cli/) |
| AWS CDK | 2.x | `npm install -g aws-cdk` |
| Git | any | [git-scm.com](https://git-scm.com/) |

### AWS Account Requirements

- An AWS account with permissions to create: Lambda, DynamoDB, S3, SQS, API Gateway, Cognito, Bedrock, OpenSearch Serverless, Secrets Manager, Amplify, VPC, IAM roles
- AWS CLI configured with credentials: `aws configure`
- Bedrock model access enabled in us-east-1:
  - `amazon.nova-pro-v1:0`
  - `us.anthropic.claude-sonnet-4-6-20251101:0`
  - `amazon.titan-embed-text-v2:0`

**Enable Bedrock model access:**
1. AWS Console → Amazon Bedrock → Model access (us-east-1)
2. Click **Modify model access**
3. Enable the three models listed above
4. Submit and wait for approval (usually instant for Nova/Titan, may take minutes for Claude)

---

## Step 1: Clone the Repository

```bash
git clone <your-repo-url> besa-ai-assistant
cd besa-ai-assistant
```

---

## Step 2: Set Up Discord Bot

Follow [docs/DISCORD_SETUP.md](./DISCORD_SETUP.md) completely before continuing.

You need to have ready:
- Discord Application ID
- Discord Guild (Server) ID
- Discord Bot Channel ID
- Discord Bot Token (will be stored in Secrets Manager after deploy)
- Discord Public Key (will be stored in Secrets Manager after deploy)

---

## Step 3: Configure the CDK Application

Edit the root `.env` file and fill in your Discord values:

```bash
DISCORD_APPLICATION_ID=123456789012345678   # from Discord Developer Portal
DISCORD_GUILD_ID=987654321098765432         # your server ID
DISCORD_BOT_CHANNEL_ID=111222333444555666   # #ask-besa-ai-assistant channel ID
```

CDK automatically loads `.env` from the project root at synth/deploy time.
The `.env` file is gitignored — your values are never committed to source control.

The admin email is already set to `eromanova115@gmail.com`. To change it, update `ADMIN_EMAIL` in `infrastructure/app.py`.

---

## Step 4: Install CDK Dependencies

```bash
cd infrastructure
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cd ..
```

---

## Step 4b: Build the Lambda Dependency Layer

The Lambda functions load shared Python packages from a Lambda Layer.
You must build this layer before deploying.

**Option A — Docker (recommended, cross-compiles for Amazon Linux 2023):**
```bash
make layer
```

**Option B — Local pip (only if you are already on Linux x86_64):**
```bash
make layer-local
```

Or run the script directly:
```bash
bash backend/scripts/build_layer.sh
```

This installs all packages from `backend/requirements.txt` into `backend/layer/python/`.
The CDK stack packages this directory as a Lambda Layer at deploy time.

> **Note:** The `backend/layer/python/` directory is in `.gitignore` — rebuild it on each
> fresh clone before deploying.

---

## Step 5: Bootstrap CDK (First Time Only)

CDK bootstrap creates the S3 bucket and IAM roles used by CDK internally.

```bash
# Get your AWS account ID
export AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

cd infrastructure
cdk bootstrap aws://${AWS_ACCOUNT_ID}/us-east-1
```

---

## Step 6: Deploy All Stacks

```bash
cd infrastructure
cdk deploy --all --require-approval never
```

This deploys five stacks in dependency order:

| Stack | Resources | Approx. Time |
|---|---|---|
| `besa-ai-assistant-network` | VPC, subnets, NAT gateway, VPC endpoints | 5-10 min |
| `besa-ai-assistant-storage` | S3, DynamoDB (4 tables), OpenSearch Serverless, Bedrock KB | 15-25 min |
| `besa-ai-assistant-secrets` | Secrets Manager (bot token, public key placeholders) | 1-2 min |
| `besa-ai-assistant-agent` | Lambda (webhook, poller, processor), SQS, API Gateway, EventBridge | 5-10 min |
| `besa-ai-assistant-admin` | Cognito, Admin API Gateway, Amplify app | 5-10 min |

**Total: 30-60 minutes** (OpenSearch Serverless collection takes the longest).

### Save the CDK Outputs

After deployment, CDK prints outputs like:

```
Outputs:
besa-ai-assistant-agent.WebhookURL         = https://xxxx.execute-api.us-east-1.amazonaws.com/prod/discord/webhook
besa-ai-assistant-storage.KnowledgeBaseId  = ABCDEF1234
besa-ai-assistant-storage.DataSourceId     = GHIJKL5678
besa-ai-assistant-storage.FAQBucketName    = besa-ai-assistant-faq-123456789012
besa-ai-assistant-admin.UserPoolId         = us-east-1_XXXXXXXXX
besa-ai-assistant-admin.UserPoolClientId   = XXXXXXXXXXXXXXXXXXXXXXXXXX
besa-ai-assistant-admin.AdminAPIUrl        = https://yyyy.execute-api.us-east-1.amazonaws.com/prod
besa-ai-assistant-admin.AdminUserEmail     = eromanova115@gmail.com
besa-ai-assistant-admin.AmplifyAppId       = dXXXXXXXXX
```

**Copy these values** — you will need them in the following steps.

---

## Step 7: Store Discord Secrets

```bash
# Replace with your actual values
aws secretsmanager put-secret-value \
  --secret-id besa-ai-assistant/discord-bot-token \
  --secret-string '{"token":"YOUR_BOT_TOKEN_HERE"}' \
  --region us-east-1

aws secretsmanager put-secret-value \
  --secret-id besa-ai-assistant/discord-public-key \
  --secret-string '{"public_key":"YOUR_PUBLIC_KEY_HERE"}' \
  --region us-east-1
```

---

## Step 8: Configure Discord Interactions Endpoint

1. Go to [Discord Developer Portal](https://discord.com/developers/applications) → your app
2. General Information → **Interactions Endpoint URL**
3. Paste the `WebhookURL` from CDK outputs
4. Click **Save Changes**

Discord will verify the endpoint automatically. Check CloudWatch Logs for the webhook Lambda if this fails.

---

## Step 9: Set Up the Admin Frontend

### Option A: Amplify Hosting (Recommended)

The CDK stack creates an Amplify app. Connect it to your repository:

1. AWS Console → AWS Amplify → **besa-ai-assistant-admin**
2. Click **Connect branch**
3. Select your Git provider and repository
4. Select the branch to deploy (e.g., `main`)
5. Build settings — Amplify should auto-detect Next.js. If not, use:
   ```yaml
   version: 1
   frontend:
     phases:
       preBuild:
         commands:
           - cd frontend
           - npm ci
       build:
         commands:
           - npm run build
     artifacts:
       baseDirectory: frontend/.next
       files:
         - '**/*'
     cache:
       paths:
         - frontend/node_modules/**/*
   ```
6. Under **Environment variables**, add:
   ```
   NEXT_PUBLIC_COGNITO_USER_POOL_ID  = <UserPoolId from CDK output>
   NEXT_PUBLIC_COGNITO_CLIENT_ID     = <UserPoolClientId from CDK output>
   NEXT_PUBLIC_API_URL               = <AdminAPIUrl from CDK output>
   ```
7. Click **Save and deploy**

### Option B: Local Development

```bash
cd frontend
npm install
cp ../.env.example .env.local
# Edit .env.local with CDK output values

npm run dev
# Open http://localhost:3000
```

---

## Step 10: First Login to Admin UI

The CDK stack creates an admin user at `eromanova115@gmail.com` with a temporary password.

1. Open the Amplify app URL (or `http://localhost:3000`)
2. Log in with `eromanova115@gmail.com`
3. Check email for the temporary password sent by Cognito
4. You will be prompted to set a new permanent password on first login

---

## Step 11: Upload Initial FAQ File

1. Log in to the Admin UI
2. Navigate to **FAQ Management**
3. Drag and drop a CSV or JSON FAQ file (see format below)
4. Click **Upload & Sync**
5. Wait for sync status to change from `SYNCING` to `COMPLETED` (typically 2-5 minutes)

**CSV format:**
```csv
id,question,answer,category,tags
faq-1,How do I increase Lambda timeout?,Go to Lambda console → Configuration → General configuration → Timeout.,Lambda,lambda;timeout
faq-2,What is the maximum Lambda memory?,Lambda supports 128MB to 10240MB.,Lambda,lambda;memory
```

**JSON format:**
```json
[
  {
    "id": "faq-1",
    "question": "How do I increase Lambda timeout?",
    "answer": "Go to Lambda console → Configuration → General configuration → Timeout.",
    "category": "Lambda",
    "tags": ["lambda", "timeout"]
  }
]
```

---

## Step 12: Test the Discord Bot

1. Go to your Discord server
2. In the #ask-besa-ai-assistant channel, type:
   ```
   /ask How do I increase the Lambda timeout?
   ```
3. The bot should acknowledge within 3 seconds and reply with an answer within 30-60 seconds

---

## Updating the Deployment

To deploy code changes:

```bash
cd infrastructure
cdk deploy --all
```

To deploy only specific stacks:

```bash
cdk deploy besa-ai-assistant-agent    # Lambda code changes
cdk deploy besa-ai-assistant-admin    # Cognito / Admin API changes
```

---

## Running Tests

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

# Unit tests (fast, no AWS required)
pytest tests/unit/ -v

# Integration tests (uses moto, no real AWS required)
pytest tests/integration/ -v

# All tests with coverage
pytest --cov=backend --cov-report=html
```

---

## Tearing Down

To remove all resources and avoid ongoing charges:

```bash
cd infrastructure
cdk destroy --all
```

**Note:** S3 buckets with objects and DynamoDB tables with data are retained by default (deletion protection). To fully delete:

1. Empty the FAQ S3 bucket manually:
   ```bash
   aws s3 rm s3://besa-ai-assistant-faq-<account-id> --recursive
   ```
2. Then run `cdk destroy --all` again

---

## Cost Estimate

Rough monthly cost for moderate usage (1 active workshop per month, ~100 students):

| Service | Estimated Cost |
|---|---|
| Lambda (webhook + processor) | ~$1-5 |
| API Gateway | ~$1-3 |
| SQS | < $1 |
| DynamoDB (on-demand) | ~$1-5 |
| OpenSearch Serverless | ~$25-50 (min 2 OCUs) |
| Bedrock (Nova Pro + Claude) | ~$5-20 per workshop |
| S3 | < $1 |
| NAT Gateway | ~$32 (fixed) |
| Amplify | ~$1-5 |
| **Total** | **~$70-120/month** |

To reduce cost between workshops, consider reducing NAT Gateway usage by switching Lambda to public subnets with VPC endpoints only.
