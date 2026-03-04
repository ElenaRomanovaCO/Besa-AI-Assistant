"""FAQ Sub-Agent: semantic similarity search against Bedrock Knowledge Base."""

from __future__ import annotations

import logging
import re
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from backend.models.agent_models import SourceResult, SourceType
from backend.models.faq_models import FAQEntry, FAQResult, FAQSearchParams

logger = logging.getLogger(__name__)


class FAQAgent:
    """
    Queries Amazon Bedrock Knowledge Base for semantically similar FAQ entries.
    Uses Nova Pro via Bedrock KB RetrieveAndGenerate for synthesis, or plain
    Retrieve for raw similarity scores.

    Does NOT use Strands Agent wrapper here — the Bedrock KB retrieve API is
    already a semantic search tool; wrapping it in another LLM loop would
    add latency. The OrchestratorAgent invokes this via @tool.
    """

    def __init__(
        self,
        knowledge_base_id: str,
        region: str = "us-east-1",
        model_id: str = "amazon.nova-pro-v1:0",
    ):
        self._knowledge_base_id = knowledge_base_id
        self._model_id = model_id
        self._bedrock_agent_runtime = boto3.client(
            "bedrock-agent-runtime", region_name=region
        )

    def search_faq(self, question: str, threshold: float = 0.75) -> FAQResult:
        """
        Search FAQ knowledge base using semantic similarity (Bedrock Retrieve API).

        Args:
            question: Student's question
            threshold: Minimum similarity score (0.0 to 1.0)

        Returns:
            FAQResult with matched entries and confidence score
        """
        params = FAQSearchParams(
            question=question,
            threshold=threshold,
            top_k=5,
            knowledge_base_id=self._knowledge_base_id,
        )
        return self._retrieve(params)

    def get_top_matches(self, question: str, top_k: int = 3) -> list[FAQEntry]:
        """
        Retrieve top K FAQ entries by similarity regardless of threshold.

        Args:
            question: Student's question
            top_k: Number of results to return

        Returns:
            List of FAQ entries sorted by similarity score
        """
        params = FAQSearchParams(
            question=question,
            threshold=0.0,  # No threshold filter, return all
            top_k=top_k,
            knowledge_base_id=self._knowledge_base_id,
        )
        result = self._retrieve(params)
        return result.entries

    def _retrieve(self, params: FAQSearchParams) -> FAQResult:
        """
        Call Bedrock Knowledge Base Retrieve API and parse results.
        Falls back to empty result on any error (waterfall continues).
        """
        try:
            response = self._bedrock_agent_runtime.retrieve(
                knowledgeBaseId=params.knowledge_base_id,
                retrievalQuery={"text": params.question},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {
                        "numberOfResults": params.top_k,
                        "overrideSearchType": "SEMANTIC",
                    }
                },
            )

            raw_results = response.get("retrievalResults", [])
            entries: list[FAQEntry] = []
            highest_score = 0.0

            for result in raw_results:
                score = float(result.get("score", 0.0))
                if score < params.threshold:
                    continue
                highest_score = max(highest_score, score)

                content = result.get("content", {}).get("text", "")
                metadata = result.get("location", {}).get("s3Location", {})
                uri = metadata.get("uri", "")

                entry = self._parse_kb_result(content, uri, score)
                if entry:
                    entries.append(entry)

            return FAQResult(
                entries=entries,
                confidence_score=highest_score,
                raw_bedrock_results=raw_results,
            )

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            logger.error("Bedrock KB retrieve error [%s]: %s", error_code, e)
            return FAQResult(entries=[], confidence_score=0.0)
        except Exception as e:
            logger.error("Unexpected FAQ search error: %s", e)
            return FAQResult(entries=[], confidence_score=0.0)

    def _parse_kb_result(
        self, content: str, uri: str, score: float
    ) -> Optional[FAQEntry]:
        """
        Parse raw Bedrock KB result text into an FAQEntry.
        The content is the markdown text stored in S3.
        """
        if not content:
            return None

        # Extract question from markdown (# Question or ## Q: Question)
        question_match = re.search(r"^#+ (?:Q:\s*)?(.+)$", content, re.MULTILINE)
        question_text = question_match.group(1).strip() if question_match else "FAQ Entry"

        # Extract answer section
        answer_match = re.search(r"## Answer\s*\n\n(.+?)(?:\n#|$)", content, re.DOTALL)
        if not answer_match:
            answer_match = re.search(r"A:\s*(.+?)(?:\n#|\Z)", content, re.DOTALL)
        answer_text = answer_match.group(1).strip() if answer_match else content

        # Extract category if present
        category_match = re.search(r"\*\*Category\*\*: (.+)$", content, re.MULTILINE)
        category = category_match.group(1).strip() if category_match else "General"

        # Derive ID from S3 URI
        entry_id = uri.split("/")[-1].replace(".md", "") if uri else "faq-unknown"

        return FAQEntry(
            id=entry_id,
            question=question_text,
            answer=answer_text,
            category=category,
        )

    def to_source_result(self, faq_result: FAQResult) -> SourceResult:
        """Convert FAQResult into the unified SourceResult format."""
        if not faq_result.has_results:
            return SourceResult(
                source_type=SourceType.FAQ,
                answer="",
                confidence_score=0.0,
            )

        top = faq_result.top_entry
        return SourceResult(
            source_type=SourceType.FAQ,
            answer=top.answer,  # type: ignore[union-attr]
            confidence_score=faq_result.confidence_score,
            metadata={
                "category": top.category,  # type: ignore[union-attr]
                "matched_question": top.question,  # type: ignore[union-attr]
                "total_matches": len(faq_result.entries),
            },
        )
