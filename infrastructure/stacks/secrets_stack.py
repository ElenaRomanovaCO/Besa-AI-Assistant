"""Secrets Manager resources for Discord credentials."""

from __future__ import annotations

from aws_cdk import Stack, Tags
from aws_cdk import aws_secretsmanager as sm
from constructs import Construct


class SecretsStack(Stack):
    """
    Creates Secrets Manager entries for Discord credentials.
    Secrets are created as placeholders — values must be set manually
    after creating the Discord bot in the Developer Portal.
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

        # Discord Bot Token
        # Value: set via AWS Console or CLI after creating Discord bot
        # Command: aws secretsmanager put-secret-value --secret-id <ARN> --secret-string "YOUR_BOT_TOKEN"
        self.bot_token_secret = sm.Secret(
            self,
            "DiscordBotToken",
            secret_name=f"{project_name}/discord/bot-token",
            description=(
                "Discord Bot Token. Set value via AWS Console or CLI. "
                "Get from: Discord Developer Portal → Your App → Bot → Reset Token"
            ),
        )

        # Discord Public Key (for webhook signature verification)
        # Value: Discord Developer Portal → General Information → Public Key
        self.public_key_secret = sm.Secret(
            self,
            "DiscordPublicKey",
            secret_name=f"{project_name}/discord/public-key",
            description=(
                "Discord Application Public Key for webhook signature verification. "
                "Get from: Discord Developer Portal → General Information → Public Key"
            ),
        )

        Tags.of(self).add("Project", project_name)
        Tags.of(self).add("Component", "Secrets")
