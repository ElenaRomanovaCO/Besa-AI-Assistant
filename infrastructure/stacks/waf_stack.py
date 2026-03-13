"""AWS WAF WebACL for API Gateway protection."""

from __future__ import annotations

from aws_cdk import Stack, Tags, aws_wafv2 as wafv2
from constructs import Construct


class WAFStack(Stack):
    """
    AWS WAF v2 WebACL with managed rule groups:
    - AWS Common Rule Set (OWASP top 10)
    - Rate-based rule (100 requests per 5 min per IP)
    - Request body size limit (8KB — Discord payloads are small)

    Associates with both API Gateways (Discord webhook + Admin API).
    WAF must be in the same region as the API Gateway (us-east-1).

    Estimated cost: ~$5-6/mo (WebACL $5 + rules $1/rule/mo, first 10M requests included).
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        project_name: str,
        api_gateway_arns: list[str],
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.project_name = project_name

        # ------------------------------------------------------------------ #
        # WAF WebACL
        # ------------------------------------------------------------------ #
        self.web_acl = wafv2.CfnWebACL(
            self,
            "APIWebACL",
            name=f"{project_name}-api-waf",
            scope="REGIONAL",  # API Gateway (not CloudFront)
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                cloud_watch_metrics_enabled=True,
                metric_name=f"{project_name}-waf",
                sampled_requests_enabled=True,
            ),
            rules=[
                # Rule 1: AWS Common Rule Set (OWASP protections)
                wafv2.CfnWebACL.RuleProperty(
                    name="AWSCommonRules",
                    priority=1,
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS",
                            name="AWSManagedRulesCommonRuleSet",
                            excluded_rules=[
                                # Exclude body size check — we handle it in Rule 3
                                wafv2.CfnWebACL.ExcludedRuleProperty(name="SizeRestrictions_BODY"),
                            ],
                        ),
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name=f"{project_name}-common-rules",
                        sampled_requests_enabled=True,
                    ),
                ),
                # Rule 2: Rate-based — 100 requests per 5 min per IP
                wafv2.CfnWebACL.RuleProperty(
                    name="RateLimit",
                    priority=2,
                    action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                            limit=100,  # Per 5-minute window per IP
                            aggregate_key_type="IP",
                        ),
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name=f"{project_name}-rate-limit",
                        sampled_requests_enabled=True,
                    ),
                ),
                # Rule 3: Block oversized request bodies (>8KB)
                wafv2.CfnWebACL.RuleProperty(
                    name="BodySizeLimit",
                    priority=3,
                    action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        size_constraint_statement=wafv2.CfnWebACL.SizeConstraintStatementProperty(
                            field_to_match=wafv2.CfnWebACL.FieldToMatchProperty(body={}),
                            comparison_operator="GT",
                            size=8192,  # 8KB
                            text_transformations=[
                                wafv2.CfnWebACL.TextTransformationProperty(
                                    priority=0, type="NONE"
                                ),
                            ],
                        ),
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name=f"{project_name}-body-size",
                        sampled_requests_enabled=True,
                    ),
                ),
                # Rule 4: SQL injection protection
                wafv2.CfnWebACL.RuleProperty(
                    name="AWSSQLInjection",
                    priority=4,
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS",
                            name="AWSManagedRulesSQLiRuleSet",
                        ),
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name=f"{project_name}-sqli",
                        sampled_requests_enabled=True,
                    ),
                ),
            ],
        )

        # ------------------------------------------------------------------ #
        # Associate WAF with API Gateways
        # ------------------------------------------------------------------ #
        for i, arn in enumerate(api_gateway_arns):
            wafv2.CfnWebACLAssociation(
                self,
                f"WAFAssociation{i}",
                resource_arn=arn,
                web_acl_arn=self.web_acl.attr_arn,
            )

        Tags.of(self).add("Project", project_name)
        Tags.of(self).add("Component", "WAF")
