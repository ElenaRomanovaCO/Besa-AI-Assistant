"""AWS Docs Sub-Agent: Real-time AWS documentation search via AWS Docs MCP server.

Uses awslabs.aws-documentation-mcp-server (stdio transport) to perform live
searches against the official AWS documentation site. A Strands Agent backed by
Amazon Bedrock Nova Pro decides which pages to read and synthesises the answer.

MCP tools exposed by the server:
  - search_documentation(search_phrase, limit) → list of matching doc entries
  - read_documentation(url) → markdown content of a documentation page
  - recommend(url) → related documentation entries
"""

from __future__ import annotations

import logging
import re
import shutil
import sys
from dataclasses import dataclass, field
from typing import Optional

from mcp import StdioServerParameters, stdio_client
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp import MCPClient

from backend.models.agent_models import SourceResult, SourceType

logger = logging.getLogger(__name__)

_NOVA_PRO_MODEL_ID = "amazon.nova-pro-v1:0"

_AWS_DOCS_SYSTEM_PROMPT = """You are an AWS documentation specialist with real-time access to official AWS documentation.

You have these tools available:
- search_documentation: search AWS docs for a topic
- read_documentation: fetch and read a specific AWS documentation page
- recommend: find related documentation pages

When answering a question:
1. Call search_documentation with the key topic (limit=5)
2. Review the search results and call read_documentation on the 2 most relevant pages
3. Synthesise a complete, accurate answer grounded in what the documentation says
4. Include direct documentation URLs in your answer
5. Include AWS console navigation paths (e.g., AWS Console → Lambda → Configuration → Timeout)
6. Include relevant AWS CLI commands when applicable
7. Note any service limits, quotas, or regional variations

Format your answer in clear plain text suitable for Discord (no markdown tables).
Always cite the documentation URL for every factual claim."""

_SEARCH_PROMPT_TEMPLATE = """Search AWS documentation to answer this question:

Question: {question}
AWS Services involved: {services}
{context_section}

Steps:
1. Use search_documentation to find the most relevant documentation pages (limit=5)
2. Use read_documentation to read the content of the top 2 most relevant results
3. Return a comprehensive, accurate answer with documentation URLs

Be concise but complete. Include the exact documentation URLs you read."""


def _get_mcp_server_params() -> StdioServerParameters:
    """
    Return stdio parameters for the AWS docs MCP server.

    Preference order:
    1. Console script installed by pip (works in Lambda layer at /opt/bin/)
    2. Python module invocation (fallback for dev environments)
    """
    script = shutil.which("awslabs.aws-documentation-mcp-server")
    if script:
        return StdioServerParameters(command=script, args=[])

    # Fallback: run as Python module (package must be installed)
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "awslabs.aws_documentation_mcp_server"],
    )


class AWSDocsAgent:
    """
    AWS documentation sub-agent using the AWS Docs MCP server.

    Spawns awslabs.aws-documentation-mcp-server as a stdio subprocess,
    then creates a Strands Agent (Nova Pro) with the MCP search and read
    tools to find and synthesise answers from real AWS documentation pages.

    Public interface is unchanged from the previous Claude-knowledge version:
      - get_aws_documentation_context(question, context) → DocsResult
      - extract_service_names(question) → list[str]
      - to_source_result(docs_result) → SourceResult
    """

    def __init__(self, region: str = "us-east-1"):
        self._region = region
        self._mcp_server_params = _get_mcp_server_params()

    def get_aws_documentation_context(
        self,
        question: str,
        context: str = "",
    ) -> "DocsResult":
        """
        Search real AWS documentation for an answer using the MCP server.

        Opens the MCP server subprocess, connects a Strands Agent (Nova Pro),
        instructs it to search and read AWS documentation pages, then parses
        the response into a DocsResult.

        Args:
            question: Student's question
            context: Optional low-confidence context from earlier waterfall steps

        Returns:
            DocsResult with documentation snippets and confidence score
        """
        services = self.extract_service_names(question)
        services_str = ", ".join(services) if services else "general AWS services"

        context_section = ""
        if context:
            context_section = (
                f"\n\nPrior search context (low confidence):\n{context[:400]}"
            )

        search_prompt = _SEARCH_PROMPT_TEMPLATE.format(
            question=question,
            services=services_str,
            context_section=context_section,
        )

        try:
            mcp_client = MCPClient(
                lambda: stdio_client(self._mcp_server_params)
            )
            with mcp_client:
                tools = mcp_client.list_tools_sync()
                if not tools:
                    logger.warning("AWS Docs MCP server returned no tools")
                    return DocsResult(snippets=[], confidence_score=0.0)

                agent = Agent(
                    model=BedrockModel(
                        model_id=_NOVA_PRO_MODEL_ID,
                        region_name=self._region,
                    ),
                    tools=tools,
                    system_prompt=_AWS_DOCS_SYSTEM_PROMPT,
                )
                response = agent(search_prompt)
                answer_text = str(response).strip()

            if not answer_text:
                return DocsResult(snippets=[], confidence_score=0.0)

            snippets = self._extract_snippets(answer_text, services)
            # Confidence: 0.85 if we got substantive content with doc URLs,
            # 0.70 if we got an answer but no verifiable URLs
            urls_found = bool(
                re.search(r"https://docs\.aws\.amazon\.com/", answer_text)
            )
            confidence = 0.85 if (snippets and urls_found) else 0.70

            return DocsResult(
                snippets=snippets,
                confidence_score=confidence,
                source="AWS Documentation (MCP)",
                full_answer=answer_text,
            )

        except FileNotFoundError:
            logger.error(
                "AWS Docs MCP server not found. "
                "Ensure awslabs.aws-documentation-mcp-server is installed."
            )
            return DocsResult(snippets=[], confidence_score=0.0)
        except Exception as e:
            logger.error("AWS Docs MCP agent error: %s", e, exc_info=True)
            return DocsResult(snippets=[], confidence_score=0.0)

    def extract_service_names(self, question: str) -> list[str]:
        """
        Extract AWS service names mentioned in the question.

        Returns:
            List of AWS service names (e.g., ["Lambda", "DynamoDB"])
        """
        aws_services = [
            "Lambda", "DynamoDB", "S3", "EC2", "RDS", "ECS", "EKS", "Fargate",
            "API Gateway", "CloudFormation", "CDK", "CloudWatch", "IAM", "Cognito",
            "SQS", "SNS", "EventBridge", "Step Functions", "Glue", "Athena",
            "Kinesis", "Bedrock", "SageMaker", "CodePipeline", "CodeBuild",
            "Route 53", "CloudFront", "VPC", "ALB", "NLB", "ELB",
            "Secrets Manager", "Parameter Store", "KMS", "ACM", "WAF",
            "OpenSearch", "ElastiCache", "Aurora", "Redshift", "Timestream",
            "Amplify", "AppSync", "Pinpoint", "Translate", "Textract", "Rekognition",
        ]

        found = []
        for service in aws_services:
            if service.lower() in question.lower():
                found.append(service)

        return found[:5]  # Cap at 5 services

    def _extract_snippets(
        self, answer_text: str, services: list[str]
    ) -> list["DocSnippet"]:
        """
        Parse the agent response into structured DocSnippet objects.
        Splits on numbered sections or markdown headings.
        """
        snippets = []
        sections = re.split(r"\n(?=#{1,3} |\d+\. )", answer_text)

        for i, section in enumerate(sections[:5]):
            section = section.strip()
            if not section:
                continue

            lines = section.split("\n", 1)
            title = lines[0].strip("#").strip().strip(".")
            content = lines[1].strip() if len(lines) > 1 else section

            # Determine primary service for this snippet
            service = "AWS"
            for svc in services:
                if svc.lower() in section.lower():
                    service = svc
                    break

            # Extract the first documentation URL found in this section
            url_match = re.search(
                r"https://docs\.aws\.amazon\.com/[\w\-/\.#?=]+", section
            )
            doc_url = url_match.group(0) if url_match else ""

            snippets.append(
                DocSnippet(
                    title=title[:200],
                    content=content[:1000],
                    service=service,
                    relevance_score=0.90 - (i * 0.05),  # Decay by position
                    doc_url=doc_url,
                )
            )

        return snippets

    def to_source_result(self, docs_result: "DocsResult") -> SourceResult:
        """Convert DocsResult into the unified SourceResult format used by the orchestrator."""
        if not docs_result.has_results:
            return SourceResult(
                source_type=SourceType.AWS_DOCS,
                answer="",
                confidence_score=0.0,
            )

        urls = [s.doc_url for s in docs_result.snippets if s.doc_url]
        answer = docs_result.full_answer or "\n\n".join(
            f"**{s.title}**\n{s.content}" for s in docs_result.snippets[:3]
        )

        return SourceResult(
            source_type=SourceType.AWS_DOCS,
            answer=answer,
            confidence_score=docs_result.confidence_score,
            source_urls=urls,
            metadata={
                "services": [s.service for s in docs_result.snippets],
                "source": docs_result.source,
            },
        )


@dataclass
class DocSnippet:
    """A relevant AWS documentation snippet extracted from MCP search results."""

    title: str
    content: str
    service: str
    relevance_score: float
    doc_url: str = ""


@dataclass
class DocsResult:
    """Result from the AWS documentation MCP search."""

    snippets: list[DocSnippet]
    confidence_score: float
    source: str = "AWS Documentation (MCP)"
    full_answer: str = ""

    @property
    def has_results(self) -> bool:
        return bool(self.snippets) or bool(self.full_answer)
