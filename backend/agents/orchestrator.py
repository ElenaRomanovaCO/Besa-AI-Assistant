"""Orchestrator Agent: confidence-ranked waterfall coordination using Strands."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Optional

from strands import Agent, tool
from strands.models import BedrockModel

from backend.agents.aws_docs_agent import AWSDocsAgent
from backend.agents.discord_agent import DiscordAgent
from backend.agents.faq_agent import FAQAgent
from backend.agents.reasoning_agent import ReasoningAgent
from backend.models.agent_models import (
    BotResponse,
    ConfidenceLevel,
    QuestionContext,
    RankedAnswer,
    SourceResult,
    SourceType,
    WaterfallConfig,
)
from backend.models.config_models import SystemConfig
from backend.services.discord_service import DiscordService

logger = logging.getLogger(__name__)

_NOVA_PRO_MODEL_ID = "amazon.nova-pro-v1:0"

_ORCHESTRATOR_SYSTEM_PROMPT = """You are the orchestrator for BeSa AI, an AWS workshop assistant.

You coordinate specialized sub-agents to answer student questions.

TOOL USAGE RULES:
- invoke_faq_agent: call ALWAYS first
- invoke_discord_agent: call if FAQ confidence is below threshold
- invoke_aws_docs_agent: call for ANY question about specific AWS service APIs, SDK
  parameter names, IAM actions, service quotas, limits, timeouts, port numbers, or
  GenAI/rapidly-evolving services (AgentCore, Bedrock, Strands, Nova, Titan, SageMaker).
  High confidence from invoke_reasoning_agent does NOT exempt you — AI training data
  may be stale for these services.
- invoke_reasoning_agent: call for general questions (Jupyter usage, workshop workflow,
  Python basics) or to synthesize after AWS Docs returns results.

ANSWER QUALITY RULES:
- NEVER copy raw tool output into primary_answer. Write the answer in your own words.
- Synthesize a clear, direct answer using tool results as context.
- primary_answer must be clean prose for Discord — no "Category:", no "Tags:" lines.
- Keep answers concise (3-8 sentences).
- Include source attribution in every response.

Response schema (JSON):
{
  "primary_answer": "your synthesized answer in clean prose",
  "source": "FAQ | Discord History | AI Reasoning | AWS Documentation | Multiple Sources",
  "confidence": 0.0-1.0,
  "source_urls": ["url1", "url2"],
  "requires_verification": false,
  "waterfall_steps": ["faq", "discord", "reasoning"],
  "warnings": []
}"""


class OrchestratorAgent:
    """
    Central coordinator implementing the confidence-ranked waterfall logic.
    Uses AWS Strands Agent framework with Nova Pro as the orchestration model.

    The Strands Agent decides which sub-agents to invoke and when to stop
    the waterfall. Sub-agents are registered as @tool functions.
    """

    def __init__(
        self,
        faq_agent: FAQAgent,
        discord_agent: DiscordAgent,
        reasoning_agent: ReasoningAgent,
        aws_docs_agent: AWSDocsAgent,
        region: str = "us-east-1",
    ):
        self._faq_agent = faq_agent
        self._discord_agent = discord_agent
        self._reasoning_agent = reasoning_agent
        self._aws_docs_agent = aws_docs_agent
        self._region = region
        # Config and collected results are set per-invocation
        self._current_config: Optional[WaterfallConfig] = None
        self._waterfall_results: list[SourceResult] = []
        self._strands_agent: Optional[Agent] = None

    def _build_strands_agent(self, config: WaterfallConfig) -> Agent:
        """
        Build a Strands Agent with tool functions bound to the current config.
        Agent is re-created per invocation to ensure fresh state.
        """
        # Capture self for tool closures
        orchestrator = self

        @tool
        def invoke_faq_agent(question: str) -> str:
            """
            Search the FAQ knowledge base for a semantically similar answer.
            Returns the best match with confidence score.
            Call this FIRST in every waterfall.

            Args:
                question: The student's question to search for
            """
            faq_result = orchestrator._faq_agent.search_faq(
                question, threshold=config.faq_threshold
            )
            source_result = orchestrator._faq_agent.to_source_result(faq_result)
            orchestrator._waterfall_results.append(source_result)

            confidence_pct = int(source_result.confidence_score * 100)
            meets_threshold = source_result.confidence_score >= config.faq_threshold

            return (
                f"FAQ search result: confidence={confidence_pct}%, "
                f"meets_threshold={'YES' if meets_threshold else 'NO'}, "
                f"threshold={int(config.faq_threshold * 100)}%\n\n"
                f"Answer: {source_result.answer[:1000] if source_result.answer else 'No FAQ match found.'}"
            )

        @tool
        def invoke_discord_agent(question: str) -> str:
            """
            Search Discord channel history for relevant past discussions.
            Expands the question into keywords and scores messages by overlap.
            Call this if FAQ confidence is below threshold.

            Args:
                question: The student's question to search for
            """
            if not config.enable_discord_agent:
                return "Discord agent is disabled by configuration."

            discord_result = orchestrator._discord_agent.search_discord_history(
                question=question,
                channels=config.searchable_channel_ids,
                expansion_depth=config.query_expansion_depth,
                overlap_threshold=config.discord_overlap_threshold,
            )
            source_result = orchestrator._discord_agent.to_source_result(discord_result)
            orchestrator._waterfall_results.append(source_result)

            confidence_pct = int(source_result.confidence_score * 100)
            meets_threshold = (
                source_result.confidence_score >= config.discord_overlap_threshold
            )

            return (
                f"Discord search result: confidence={confidence_pct}%, "
                f"meets_threshold={'YES' if meets_threshold else 'NO'}, "
                f"keywords_used={discord_result.keywords_used}\n\n"
                f"Answer: {source_result.answer[:1000] if source_result.answer else 'No Discord matches found.'}"
            )

        @tool
        def invoke_reasoning_agent(question: str) -> str:
            """
            Synthesize an answer using Claude Sonnet's AWS expertise.
            Call this when FAQ and Discord return low-confidence results.
            This is the most expensive operation — only invoke when necessary.

            Args:
                question: The student's question to reason about
            """
            if not config.enable_reasoning_agent:
                return "Reasoning agent is disabled by configuration."

            partial = [r for r in orchestrator._waterfall_results if r.answer]
            reasoning_result = orchestrator._reasoning_agent.synthesize_answer(
                question=question,
                partial_results=partial,
            )
            source_result = orchestrator._reasoning_agent.to_source_result(reasoning_result)
            orchestrator._waterfall_results.append(source_result)

            return (
                f"Reasoning result: confidence_level={reasoning_result.confidence_level}, "
                f"requires_verification={reasoning_result.requires_verification}\n\n"
                f"Answer: {reasoning_result.answer[:1000] if reasoning_result.answer else 'Reasoning failed.'}"
            )

        @tool
        def invoke_aws_docs_agent(question: str) -> str:
            """
            Search real AWS documentation pages for authoritative answers.

            CALL THIS (do NOT skip it) when the question involves ANY of:
            - AWS service APIs, SDK parameters, IAM actions or policies
            - Service quotas, limits, timeouts, or port numbers
            - GenAI/rapidly-evolving services: AgentCore, Bedrock, Strands Agents,
              Nova, Titan, SageMaker, Guardrails, Knowledge Base
            - Specific configuration parameter names or API shapes
            - Container/deployment specifications or required fields

            Do NOT rely on invoke_reasoning_agent alone for these topics — the
            service may have changed since training data.

            Args:
                question: The student's question
            """
            if not config.enable_aws_docs_agent:
                return "AWS Docs agent is disabled by configuration."

            prior_context = " ".join(
                r.answer[:200] for r in orchestrator._waterfall_results if r.answer
            )
            docs_result = orchestrator._aws_docs_agent.get_aws_documentation_context(
                question=question,
                context=prior_context,
            )
            source_result = orchestrator._aws_docs_agent.to_source_result(docs_result)
            orchestrator._waterfall_results.append(source_result)

            return (
                f"AWS Docs result: confidence={int(source_result.confidence_score * 100)}%, "
                f"snippets={len(docs_result.snippets)}\n\n"
                f"Answer: {source_result.answer[:1000] if source_result.answer else 'No documentation found.'}"
            )

        tools = [invoke_faq_agent]
        if config.enable_discord_agent:
            tools.append(invoke_discord_agent)
        if config.enable_reasoning_agent:
            tools.append(invoke_reasoning_agent)
        if config.enable_aws_docs_agent:
            tools.append(invoke_aws_docs_agent)

        return Agent(
            model=BedrockModel(
                model_id=_NOVA_PRO_MODEL_ID,
                region_name=self._region,
            ),
            tools=tools,
            system_prompt=_ORCHESTRATOR_SYSTEM_PROMPT,
        )

    def handle_question(
        self,
        question: str,
        context: QuestionContext,
        config: WaterfallConfig,
    ) -> BotResponse:
        """
        Main entry point for processing a student question through the waterfall.

        Args:
            question: Raw question text from student
            context: Discord metadata (channel, user, thread)
            config: Current system configuration (thresholds, enabled agents)

        Returns:
            BotResponse with ranked answers and source attribution
        """
        start_time = time.time()
        self._current_config = config
        self._waterfall_results = []  # Reset per invocation

        # Build the Strands agent with tools bound to this config
        agent = self._build_strands_agent(config)

        orchestration_prompt = f"""A student in an AWS workshop has asked the following question:

"{question}"

Student info: user={context.user_name}, channel={context.channel_id}

Follow these steps IN ORDER to find the best answer:

STEP 1 — Always call invoke_faq_agent("{question}") first.

STEP 2 — If FAQ confidence < {int(config.faq_threshold * 100)}%, call invoke_discord_agent.

STEP 3 — Classify the question:
  TYPE A (specific AWS technical): question involves an AWS service API, SDK parameter name,
    IAM action, service quota, execution limit, timeout, port number, container spec, or
    a GenAI/rapidly-evolving service (AgentCore, Bedrock, Strands Agents, Nova, Titan,
    SageMaker, Guardrails, Knowledge Base).
  TYPE B (general): workshop workflow, general Jupyter/Python usage, environment setup.

STEP 4 — Based on classification:
  - TYPE A → call invoke_aws_docs_agent. High reasoning confidence does NOT exempt you
    from this step — AI training data may be stale for these fast-moving services.
    Only call invoke_reasoning_agent after if docs are insufficient to synthesize.
  - TYPE B → call invoke_reasoning_agent.

Return your final response as JSON matching the required schema."""

        try:
            agent_response = agent(orchestration_prompt)
            bot_response = self._parse_agent_response(
                str(agent_response),
                context.correlation_id,
                int((time.time() - start_time) * 1000),
            )
        except Exception as e:
            logger.error(
                "Orchestrator agent error for correlation_id=%s: %s",
                context.correlation_id,
                e,
            )
            # Fall back to direct waterfall on Strands error
            bot_response = self._direct_waterfall_fallback(
                question=question,
                config=config,
                correlation_id=context.correlation_id,
                elapsed_ms=int((time.time() - start_time) * 1000),
            )

        return bot_response

    def _parse_agent_response(
        self, raw_response: str, correlation_id: str, elapsed_ms: int
    ) -> BotResponse:
        """Parse the Strands agent JSON response into a BotResponse."""
        import json
        import re

        # Extract JSON from agent response
        json_match = re.search(r"\{[^{}]*\}", raw_response, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                source_type = SourceType(data.get("source", "Unknown"))
                answer = RankedAnswer(
                    rank=1,
                    source_type=source_type,
                    answer=data.get("primary_answer", raw_response),
                    confidence_score=float(data.get("confidence", 0.5)),
                    source_urls=data.get("source_urls", []),
                    requires_verification=data.get("requires_verification", False),
                )
                return BotResponse(
                    answers=[answer],
                    primary_source=source_type,
                    total_processing_time_ms=elapsed_ms,
                    correlation_id=correlation_id,
                    waterfall_steps_executed=data.get("waterfall_steps", []),
                    warnings=data.get("warnings", []),
                )
            except (json.JSONDecodeError, ValueError, KeyError):
                pass

        # If JSON parsing fails, use the raw text with best available source result
        return self._build_response_from_results(
            raw_response, correlation_id, elapsed_ms
        )

    def _build_response_from_results(
        self, fallback_text: str, correlation_id: str, elapsed_ms: int
    ) -> BotResponse:
        """Build BotResponse from accumulated waterfall results."""
        if not self._waterfall_results:
            return self._empty_response(correlation_id, elapsed_ms)

        # Sort by confidence, pick the best
        sorted_results = sorted(
            [r for r in self._waterfall_results if r.answer],
            key=lambda r: r.confidence_score,
            reverse=True,
        )

        if not sorted_results:
            return self._empty_response(correlation_id, elapsed_ms)

        answers = [
            RankedAnswer(
                rank=i + 1,
                source_type=r.source_type,
                answer=r.answer,
                confidence_score=r.confidence_score,
                source_urls=r.source_urls,
            )
            for i, r in enumerate(sorted_results[:3])
        ]

        return BotResponse(
            answers=answers,
            primary_source=answers[0].source_type,
            total_processing_time_ms=elapsed_ms,
            correlation_id=correlation_id,
            waterfall_steps_executed=[r.source_type.value for r in sorted_results],
        )

    def _direct_waterfall_fallback(
        self,
        question: str,
        config: WaterfallConfig,
        correlation_id: str,
        elapsed_ms: int,
    ) -> BotResponse:
        """
        Direct Python waterfall — bypasses Strands Agent on error.
        Ensures the system always returns an answer even if the LLM orchestrator fails.
        """
        logger.warning("Falling back to direct waterfall for correlation_id=%s", correlation_id)
        steps_executed = []

        # Step 1: FAQ
        if config.enable_faq_agent:
            faq_result = self._faq_agent.search_faq(question, threshold=config.faq_threshold)
            source = self._faq_agent.to_source_result(faq_result)
            self._waterfall_results.append(source)
            steps_executed.append("faq")
            if source.confidence_score >= config.faq_threshold:
                return self._make_single_answer_response(
                    source, correlation_id, elapsed_ms, steps_executed
                )

        # Step 2: Discord
        if config.enable_discord_agent:
            discord_result = self._discord_agent.search_discord_history(
                question, config.searchable_channel_ids,
                config.query_expansion_depth, config.discord_overlap_threshold,
            )
            source = self._discord_agent.to_source_result(discord_result)
            self._waterfall_results.append(source)
            steps_executed.append("discord")
            if source.confidence_score >= config.discord_overlap_threshold:
                return self._make_single_answer_response(
                    source, correlation_id, elapsed_ms, steps_executed
                )

        # Step 3: Reasoning
        if config.enable_reasoning_agent:
            partial = [r for r in self._waterfall_results if r.answer]
            reasoning_result = self._reasoning_agent.synthesize_answer(question, partial)
            source = self._reasoning_agent.to_source_result(reasoning_result)
            self._waterfall_results.append(source)
            steps_executed.append("reasoning")
            if reasoning_result.is_valid:
                return self._make_single_answer_response(
                    source, correlation_id, elapsed_ms, steps_executed
                )

        # Step 4: AWS Docs
        if config.enable_aws_docs_agent:
            prior = " ".join(r.answer[:200] for r in self._waterfall_results if r.answer)
            docs_result = self._aws_docs_agent.get_aws_documentation_context(question, prior)
            source = self._aws_docs_agent.to_source_result(docs_result)
            self._waterfall_results.append(source)
            steps_executed.append("aws_docs")
            if source.confidence_score > 0:
                return self._make_single_answer_response(
                    source, correlation_id, elapsed_ms, steps_executed
                )

        return self._empty_response(correlation_id, elapsed_ms)

    def _make_single_answer_response(
        self,
        source: SourceResult,
        correlation_id: str,
        elapsed_ms: int,
        steps: list[str],
    ) -> BotResponse:
        answer = RankedAnswer(
            rank=1,
            source_type=source.source_type,
            answer=source.answer,
            confidence_score=source.confidence_score,
            source_urls=source.source_urls,
        )
        return BotResponse(
            answers=[answer],
            primary_source=source.source_type,
            total_processing_time_ms=elapsed_ms,
            correlation_id=correlation_id,
            waterfall_steps_executed=steps,
        )

    def _empty_response(self, correlation_id: str, elapsed_ms: int) -> BotResponse:
        """Return a helpful response when all sources fail."""
        fallback_answer = RankedAnswer(
            rank=1,
            source_type=SourceType.UNKNOWN,
            answer=(
                "I couldn't find a confident answer to your question. "
                "Please try rephrasing, or ask a workshop volunteer for help. "
                "You can also check the AWS documentation at https://docs.aws.amazon.com/"
            ),
            confidence_score=0.0,
        )
        return BotResponse(
            answers=[fallback_answer],
            primary_source=SourceType.UNKNOWN,
            total_processing_time_ms=elapsed_ms,
            correlation_id=correlation_id,
            warnings=["All knowledge sources returned low-confidence results."],
        )

    def evaluate_confidence(
        self, results: list[SourceResult], source_type: SourceType
    ) -> bool:
        """
        Evaluate if results from a source meet the confidence threshold.

        Args:
            results: Results from a sub-agent
            source_type: Which source (FAQ, Discord, etc.)

        Returns:
            True if confidence threshold met, False to continue waterfall
        """
        if not results or not self._current_config:
            return False
        best_score = max(r.confidence_score for r in results)
        config = self._current_config

        thresholds = {
            SourceType.FAQ: config.faq_threshold,
            SourceType.DISCORD_HISTORY: config.discord_overlap_threshold,
            SourceType.AI_REASONING: 0.50,
            SourceType.AWS_DOCS: 0.60,
        }
        threshold = thresholds.get(source_type, 0.70)
        return best_score >= threshold

    def merge_and_rank(self, all_results: list[SourceResult]) -> list[RankedAnswer]:
        """
        Merge results from multiple sources and rank by relevance.
        Used when no single source exceeds threshold — combines top-3.

        Args:
            all_results: Results from all queried sources

        Returns:
            Ranked list of answers with source attribution
        """
        valid = sorted(
            [r for r in all_results if r.answer and r.confidence_score > 0],
            key=lambda r: r.confidence_score,
            reverse=True,
        )
        return [
            RankedAnswer(
                rank=i + 1,
                source_type=r.source_type,
                answer=r.answer,
                confidence_score=r.confidence_score,
                source_urls=r.source_urls,
            )
            for i, r in enumerate(valid[:3])
        ]
