"""Discord Sub-Agent: channel history search using Strands Agent (Nova Pro).

Architecture:
- A Strands Agent backed by Amazon Bedrock Nova Pro receives the student's
  question and a list of channel IDs to search.
- The agent is given one tool: get_channel_messages(channel_id, limit).
  Nova Pro decides which channels to search, in what order, and when to stop.
- The agent returns a JSON object with relevant message IDs and relevance scores.
- We map those IDs back to the cached DiscordMessage objects and build a
  DiscordResult for the orchestrator.
- If the Strands Agent fails for any reason, a keyword-expansion fallback
  (the original pipeline) is used transparently.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from strands import Agent, tool
from strands.models import BedrockModel

from backend.models.agent_models import SourceResult, SourceType
from backend.models.discord_models import DiscordMessage, DiscordResult, RankedMessage
from backend.services.discord_service import DiscordService

logger = logging.getLogger(__name__)

_NOVA_PRO_MODEL_ID = "amazon.nova-pro-v1:0"

_DISCORD_SEARCH_SYSTEM_PROMPT = """You are a Discord history search specialist for an AWS workshop assistant.

Your task: given a student's question and a set of Discord channel IDs, search those channels for past discussions that are relevant to the question.

You have ONE tool available: get_channel_messages(channel_id, limit)
- Use it to fetch messages from a channel
- Search the channels most likely to contain relevant discussions first
- You may search multiple channels if the first yields no useful results
- Stop searching once you have found clearly relevant messages

After searching, identify the most relevant messages and return your findings as a JSON object with EXACTLY this schema — no other text after the JSON:

{
  "relevant_messages": [
    {
      "message_id": "<exact message_id from the fetched data>",
      "relevance_score": <float 0.0 to 1.0>,
      "matched_keywords": ["keyword1", "keyword2"]
    }
  ],
  "confidence_score": <float 0.0 to 1.0, highest relevance_score among results>,
  "keywords_used": ["term1", "term2", ...]
}

Rules:
- Only include messages with relevance_score >= 0.30
- Rank by relevance_score descending, include at most 5 messages
- If no relevant messages found: {"relevant_messages": [], "confidence_score": 0.0, "keywords_used": []}
- keywords_used should list the key terms you searched for"""

_SEARCH_PROMPT_TEMPLATE = """Search Discord channel history to find past discussions relevant to this student question:

Question: "{question}"

Channel IDs to search: {channels}

Use get_channel_messages to fetch messages. Search the channels, identify the most relevant messages, then return your JSON findings."""

# Fallback: Nova Pro query expansion prompt (used when Strands agent fails)
_QUERY_EXPANSION_PROMPT = """You are a search query expansion specialist for an AWS workshop Discord server.

Given a student's question, generate {depth} semantically related search keywords and phrases.
These keywords will be used to search Discord message history for relevant past discussions.

Rules:
- Include technical terms, AWS service names, concepts, and common variations
- Include both formal and informal phrasings
- Include error messages or symptoms if the question describes a problem
- Output ONLY a JSON array of strings, no other text
- Generate exactly {depth} keywords

Student question: {question}

Output format: ["keyword1", "keyword2", ...]"""


class DiscordAgent:
    """
    Searches Discord channel history using a Strands Agent (Nova Pro).

    Nova Pro receives the question and available channel IDs, calls the
    get_channel_messages tool to fetch messages, and returns a structured
    ranking of relevant messages.

    Falls back to the keyword-expansion pipeline if the Strands agent fails.
    """

    def __init__(
        self,
        discord_service: DiscordService,
        region: str = "us-east-1",
        model_id: str = _NOVA_PRO_MODEL_ID,
    ):
        self._discord = discord_service
        self._region = region
        self._model_id = model_id

    # ---------------------------------------------------------------------- #
    # Public interface (unchanged — orchestrator depends on these signatures) #
    # ---------------------------------------------------------------------- #

    def search_discord_history(
        self,
        question: str,
        channels: list[str],
        expansion_depth: int = 10,
        overlap_threshold: float = 0.70,
        max_messages_per_channel: int = 200,
    ) -> DiscordResult:
        """
        Search Discord channels for past discussions relevant to the question.

        Uses a Strands Agent (Nova Pro) with get_channel_messages tool.
        Falls back to keyword-overlap pipeline if the agent fails.

        Args:
            question: Student's question
            channels: List of Discord channel IDs to search
            expansion_depth: Number of keywords for the fallback pipeline (7-15)
            overlap_threshold: Minimum relevance score (used in fallback)
            max_messages_per_channel: Max messages to fetch per channel

        Returns:
            DiscordResult with matched messages and confidence score
        """
        if not channels:
            logger.info("No searchable channels configured — skipping Discord search.")
            return DiscordResult(messages=[], confidence_score=0.0)

        try:
            return self._strands_search(
                question=question,
                channels=channels,
                max_per_channel=min(max_messages_per_channel, 100),
                overlap_threshold=overlap_threshold,
            )
        except Exception as e:
            logger.warning(
                "Strands Discord search failed (%s), falling back to keyword pipeline.", e
            )
            return self._keyword_search_fallback(
                question=question,
                channels=channels,
                expansion_depth=expansion_depth,
                overlap_threshold=overlap_threshold,
                max_per_channel=min(max_messages_per_channel, 100),
            )

    def to_source_result(self, discord_result: DiscordResult) -> SourceResult:
        """Convert DiscordResult into the unified SourceResult format."""
        if not discord_result.has_results:
            return SourceResult(
                source_type=SourceType.DISCORD_HISTORY,
                answer="",
                confidence_score=0.0,
            )

        answer_parts = []
        urls = []

        for ranked_msg in discord_result.messages[:3]:
            author = ranked_msg.message.author_name
            content = ranked_msg.message.content[:800]
            score_pct = int(ranked_msg.overlap_score * 100)
            answer_parts.append(
                f"**@{author}** ({score_pct}% match):\n> {content}"
            )
            urls.append(ranked_msg.message.url)
            if ranked_msg.thread_context:
                for thread_msg in ranked_msg.thread_context[:2]:
                    answer_parts.append(
                        f"  ↳ **@{thread_msg.author_name}**: {thread_msg.content[:400]}"
                    )

        return SourceResult(
            source_type=SourceType.DISCORD_HISTORY,
            answer="\n\n".join(answer_parts),
            confidence_score=discord_result.confidence_score,
            source_urls=urls,
            metadata={
                "keywords_used": discord_result.keywords_used,
                "total_matches": len(discord_result.messages),
            },
        )

    # ---------------------------------------------------------------------- #
    # Strands Agent search (primary path)                                     #
    # ---------------------------------------------------------------------- #

    def _strands_search(
        self,
        question: str,
        channels: list[str],
        max_per_channel: int,
        overlap_threshold: float,
    ) -> DiscordResult:
        """
        Use a Strands Agent (Nova Pro) with get_channel_messages tool to
        intelligently search and rank Discord messages.

        The message cache is populated as the agent calls get_channel_messages,
        letting us reconstruct DiscordMessage objects after parsing the response.
        """
        # Cache: message_id → DiscordMessage (populated by tool calls)
        fetched_messages: dict[str, DiscordMessage] = {}
        discord_svc = self._discord

        @tool
        def get_channel_messages(channel_id: str, limit: int = 100) -> str:
            """
            Fetch recent messages from a Discord channel.

            Args:
                channel_id: The Discord channel ID to search
                limit: Maximum number of messages to retrieve (max 100)

            Returns:
                JSON array of message objects with id, author, content, timestamp
            """
            clamped = max(1, min(limit, 100))
            msgs = discord_svc.get_channel_messages(
                channel_id=channel_id, limit=clamped
            )
            for msg in msgs:
                fetched_messages[msg.message_id] = msg

            return json.dumps([
                {
                    "message_id": msg.message_id,
                    "author": msg.author_name,
                    "content": msg.content[:600],
                    "timestamp": msg.timestamp.isoformat(),
                    "thread_id": msg.thread_id,
                }
                for msg in msgs
            ])

        agent = Agent(
            model=BedrockModel(
                model_id=self._model_id,
                region_name=self._region,
            ),
            tools=[get_channel_messages],
            system_prompt=_DISCORD_SEARCH_SYSTEM_PROMPT,
        )

        prompt = _SEARCH_PROMPT_TEMPLATE.format(
            question=question,
            channels=", ".join(channels),
        )

        response = agent(prompt)
        response_text = str(response).strip()

        return self._parse_agent_response(
            response_text=response_text,
            fetched_messages=fetched_messages,
            overlap_threshold=overlap_threshold,
        )

    def _parse_agent_response(
        self,
        response_text: str,
        fetched_messages: dict[str, DiscordMessage],
        overlap_threshold: float,
    ) -> DiscordResult:
        """
        Parse the Strands Agent's JSON response into a DiscordResult.

        Extracts the JSON block from the agent's response text, maps message IDs
        back to DiscordMessage objects, and enriches top results with thread context.
        """
        # Extract JSON block — agent may include reasoning text before/after
        json_match = re.search(
            r'\{\s*"relevant_messages".*?\}(?=\s*$|\s*\n\s*$)',
            response_text,
            re.DOTALL,
        )
        if not json_match:
            # Broader fallback: grab the last {...} block
            json_match = re.search(r'\{[^{}]*"relevant_messages"[^{}]*\}', response_text, re.DOTALL)

        if not json_match:
            logger.warning("Discord Strands agent returned no parseable JSON.")
            return DiscordResult(messages=[], confidence_score=0.0)

        try:
            data = json.loads(json_match.group(0))
        except json.JSONDecodeError as e:
            logger.warning("Discord agent JSON parse error: %s", e)
            return DiscordResult(messages=[], confidence_score=0.0)

        raw_messages = data.get("relevant_messages", [])
        keywords_used = data.get("keywords_used", [])
        confidence = float(data.get("confidence_score", 0.0))

        # Map agent-ranked message IDs back to DiscordMessage objects
        ranked: list[RankedMessage] = []
        for item in raw_messages:
            msg_id = str(item.get("message_id", ""))
            relevance = float(item.get("relevance_score", 0.0))
            keywords = item.get("matched_keywords", [])

            if relevance < overlap_threshold:
                continue

            discord_msg = fetched_messages.get(msg_id)
            if discord_msg is None:
                logger.debug("Agent referenced unknown message_id: %s", msg_id)
                continue

            ranked.append(
                RankedMessage(
                    message=discord_msg,
                    overlap_score=relevance,
                    matched_keywords=keywords,
                )
            )

        # Sort descending by relevance (agent may not guarantee ordering)
        ranked.sort(key=lambda m: m.overlap_score, reverse=True)

        # Enrich top 2 results with thread context
        for ranked_msg in ranked[:2]:
            if ranked_msg.message.thread_id:
                try:
                    ranked_msg.thread_context = self._discord.get_thread_messages(
                        ranked_msg.message.thread_id
                    )
                except Exception as e:
                    logger.debug("Thread context fetch failed: %s", e)

        return DiscordResult(
            messages=ranked[:5],
            confidence_score=ranked[0].overlap_score if ranked else 0.0,
            keywords_used=keywords_used,
        )

    # ---------------------------------------------------------------------- #
    # Keyword-pipeline fallback (used when Strands agent fails)               #
    # ---------------------------------------------------------------------- #

    def _keyword_search_fallback(
        self,
        question: str,
        channels: list[str],
        expansion_depth: int,
        overlap_threshold: float,
        max_per_channel: int,
    ) -> DiscordResult:
        """
        Original keyword-expansion pipeline — used when the Strands Agent fails.

        1. Expand question to keywords via Nova Pro invoke_model
        2. Fetch messages from all channels
        3. Score by keyword overlap
        4. Return top results above threshold
        """
        import boto3
        from botocore.exceptions import ClientError

        bedrock = boto3.client("bedrock-runtime", region_name=self._region)

        keywords = self._expand_query(bedrock, question, expansion_depth)
        if not keywords:
            keywords = self._fallback_keywords(question)

        all_messages: list[DiscordMessage] = []
        for channel_id in channels:
            msgs = self._discord.get_channel_messages(
                channel_id=channel_id,
                limit=max_per_channel,
            )
            all_messages.extend(msgs)

        if not all_messages:
            return DiscordResult(
                messages=[], confidence_score=0.0, keywords_used=keywords
            )

        ranked = self._rank_by_overlap(all_messages, keywords)
        above_threshold = [m for m in ranked if m.overlap_score >= overlap_threshold]
        top_results = (above_threshold or ranked)[:5]

        for ranked_msg in top_results[:2]:
            if ranked_msg.message.thread_id:
                try:
                    ranked_msg.thread_context = self._discord.get_thread_messages(
                        ranked_msg.message.thread_id
                    )
                except Exception:
                    pass

        return DiscordResult(
            messages=top_results,
            confidence_score=top_results[0].overlap_score if top_results else 0.0,
            keywords_used=keywords,
        )

    def _expand_query(self, bedrock_client, question: str, depth: int) -> list[str]:
        """Expand question into keywords using Nova Pro (fallback pipeline only)."""
        from botocore.exceptions import ClientError

        depth = max(7, min(15, depth))
        prompt = _QUERY_EXPANSION_PROMPT.format(depth=depth, question=question.strip())
        try:
            response = bedrock_client.invoke_model(
                modelId=self._model_id,
                body=json.dumps({
                    "messages": [{"role": "user", "content": prompt}],
                    "inferenceConfig": {"maxTokens": 512, "temperature": 0.3},
                }),
                contentType="application/json",
                accept="application/json",
            )
            body = json.loads(response["body"].read())
            text = (
                body.get("output", {})
                .get("message", {})
                .get("content", [{}])[0]
                .get("text", "")
            )
            return self._extract_keywords_from_json(text, depth)
        except Exception as e:
            logger.error("Fallback query expansion failed: %s", e)
            return self._fallback_keywords(question)

    @staticmethod
    def _extract_keywords_from_json(text: str, expected_depth: int) -> list[str]:
        """Extract keyword list from model output, handling partial JSON."""
        try:
            keywords = json.loads(text.strip())
            if isinstance(keywords, list):
                return [str(k).strip() for k in keywords if k][:15]
        except json.JSONDecodeError:
            pass
        match = re.search(r"\[([^\]]+)\]", text, re.DOTALL)
        if match:
            try:
                keywords = json.loads(f"[{match.group(1)}]")
                return [str(k).strip() for k in keywords if k][:15]
            except json.JSONDecodeError:
                pass
        words = re.findall(r'"([^"]+)"', text)
        return words[:expected_depth] if words else []

    @staticmethod
    def _rank_by_overlap(
        messages: list[DiscordMessage],
        keywords: list[str],
    ) -> list[RankedMessage]:
        """Rank messages by keyword overlap percentage (fallback pipeline only)."""
        if not keywords:
            return []
        keyword_set = {kw.lower() for kw in keywords}
        ranked: list[RankedMessage] = []
        for msg in messages:
            searchable = msg.to_searchable_text()
            matched = [kw for kw in keyword_set if kw in searchable]
            overlap = len(matched) / len(keyword_set) if keyword_set else 0.0
            if overlap > 0:
                ranked.append(
                    RankedMessage(
                        message=msg,
                        overlap_score=round(overlap, 4),
                        matched_keywords=matched,
                    )
                )
        return sorted(ranked, key=lambda m: m.overlap_score, reverse=True)

    @staticmethod
    def _fallback_keywords(question: str) -> list[str]:
        """Generate basic keywords from question words when Nova Pro fails."""
        stop_words = {
            "how", "what", "why", "when", "where", "who", "which", "is", "are",
            "do", "does", "did", "can", "could", "should", "would", "the", "a",
            "an", "in", "on", "at", "to", "for", "of", "and", "or", "but",
        }
        words = re.findall(r"\b\w{3,}\b", question.lower())
        return list(dict.fromkeys(w for w in words if w not in stop_words))[:10]
