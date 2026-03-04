# Discord Bot Setup Guide

This guide walks you through creating and configuring the Discord bot for BeSa AI Assistant.

---

## What You Will Need

Before running `cdk deploy` you must collect **five values** from the Discord Developer Portal and your Discord server:

| Value | Where to find it | Used for |
|---|---|---|
| **Bot Token** | Developer Portal → Bot → Reset Token | Secrets Manager (outbound API auth) |
| **Application ID** | Developer Portal → General Information | Webhook verification, API calls |
| **Public Key** | Developer Portal → General Information | Ed25519 signature verification |
| **Guild (Server) ID** | Discord client (Developer Mode) | Slash command registration |
| **Bot Channel ID** | Discord client (Developer Mode) | Channel message polling |

---

## Step 1: Create a Discord Application

1. Go to [https://discord.com/developers/applications](https://discord.com/developers/applications)
2. Click **New Application** (top-right)
3. Enter the name: **BeSa AI Assistant**
4. Accept the Developer Terms of Service
5. Click **Create**

**Copy from the General Information page:**
- `APPLICATION_ID` (labelled "Application ID")
- `PUBLIC_KEY` (labelled "Public Key")

---

## Step 2: Create the Bot

1. In the left sidebar, click **Bot**
2. Click **Reset Token** → confirm → **Copy the token now** (you cannot view it again)
   - Save this as your `DISCORD_BOT_TOKEN`
3. Under **Privileged Gateway Intents**, enable:
   - **Message Content Intent** (required to read message text)
   - **Server Members Intent** (optional, for future features)
4. Under **Bot Permissions**, ensure the bot has at least:
   - `Read Messages / View Channels`
   - `Send Messages`
   - `Create Public Threads`
   - `Send Messages in Threads`
   - `Read Message History`
   - `Use Slash Commands`

---

## Step 3: Configure OAuth2 and Invite the Bot

1. In the left sidebar, click **OAuth2 → URL Generator**
2. Under **Scopes**, select:
   - `bot`
   - `applications.commands`
3. Under **Bot Permissions**, select the permissions from Step 2
4. Copy the generated URL and open it in your browser
5. Select your Discord server (guild) from the dropdown
6. Click **Authorize**

---

## Step 4: Get Your Guild and Channel IDs

You need Discord's **Developer Mode** enabled to copy IDs.

**Enable Developer Mode:**
1. Open Discord → User Settings (gear icon, bottom-left)
2. Go to **Advanced**
3. Toggle **Developer Mode** ON

**Get Guild (Server) ID:**
1. Right-click your server name in the left sidebar
2. Click **Copy Server ID**
   - Save this as your `DISCORD_GUILD_ID`

**Get Bot Channel ID:**
1. Create a channel named **#ask-besa-ai-assistant** (or use an existing support channel)
2. Right-click the channel name
3. Click **Copy Channel ID**
   - Save this as your `DISCORD_BOT_CHANNEL_ID`

---

## Step 5: Configure infrastructure/app.py

Open `infrastructure/app.py` and fill in the three values you just collected:

```python
DISCORD_APPLICATION_ID = "your_application_id_here"
DISCORD_GUILD_ID       = "your_guild_id_here"
DISCORD_BOT_CHANNEL_ID = "your_channel_id_here"
```

Alternatively, export them as environment variables before deploying:

```bash
export DISCORD_APPLICATION_ID=123456789012345678
export DISCORD_GUILD_ID=987654321098765432
export DISCORD_BOT_CHANNEL_ID=111222333444555666
```

---

## Step 6: Store Secrets in AWS Secrets Manager

After `cdk deploy` completes, store the Bot Token and Public Key in Secrets Manager.
The CDK stack creates the secret ARNs — you just need to set the values.

```bash
# Store the bot token
aws secretsmanager put-secret-value \
  --secret-id besa-ai-assistant/discord-bot-token \
  --secret-string '{"token":"YOUR_BOT_TOKEN_HERE"}' \
  --region us-east-1

# Store the public key
aws secretsmanager put-secret-value \
  --secret-id besa-ai-assistant/discord-public-key \
  --secret-string '{"public_key":"YOUR_PUBLIC_KEY_HERE"}' \
  --region us-east-1
```

---

## Step 7: Configure the Interactions Endpoint URL

After `cdk deploy`, the webhook URL is printed as a CDK Output:

```
besa-ai-assistant-agent.WebhookURL = https://XXXXXXXXXX.execute-api.us-east-1.amazonaws.com/prod/discord/webhook
```

1. Go back to the Discord Developer Portal → your app → **General Information**
2. Paste the webhook URL into the **Interactions Endpoint URL** field
3. Click **Save Changes**

Discord will send a PING to verify the endpoint. The Lambda will respond with a PONG automatically.

---

## Step 8: Register Slash Commands

The bot exposes these slash commands (registered automatically via the CDK deploy through a Custom Resource Lambda, or manually):

| Command | Description |
|---|---|
| `/ask <question>` | Ask the AI assistant a question |
| `/faq` | Browse available FAQ topics |
| `/help` | Show usage instructions |

To register slash commands manually (if the Custom Resource didn't run):

```bash
curl -X POST \
  "https://discord.com/api/v10/applications/${DISCORD_APPLICATION_ID}/guilds/${DISCORD_GUILD_ID}/commands" \
  -H "Authorization: Bot ${DISCORD_BOT_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "ask",
    "description": "Ask the BeSa AI assistant a question",
    "options": [{
      "type": 3,
      "name": "question",
      "description": "Your question about the AWS workshop",
      "required": true
    }]
  }'
```

---

## Troubleshooting

**Interaction failed (Discord shows error after /ask)**
- Check that the Webhook Lambda is running: CloudWatch Logs → `/aws/lambda/besa-ai-assistant-webhook`
- Verify the Public Key is correctly set in Secrets Manager

**Bot doesn't respond to channel messages**
- Check that Message Content Intent is enabled (Step 2)
- Verify `DISCORD_BOT_CHANNEL_ID` matches the actual channel
- Check Poller Lambda logs: CloudWatch Logs → `/aws/lambda/besa-ai-assistant-poller`

**Signature verification fails (403 errors)**
- Ensure the Public Key in Secrets Manager exactly matches the value in Developer Portal (no extra spaces)

**Commands not showing in Discord**
- Slash commands can take up to 1 hour to propagate globally; guild commands are instant
- Verify the bot was invited with `applications.commands` scope (Step 3)
