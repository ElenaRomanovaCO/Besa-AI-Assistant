"""FAQ knowledge base data models."""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class FAQEntry:
    """A single FAQ entry in the knowledge base."""

    id: str
    question: str
    answer: str
    category: str = "General"
    tags: list[str] = field(default_factory=list)
    last_updated: datetime = field(default_factory=datetime.utcnow)

    def to_markdown(self) -> str:
        """Render as markdown for Bedrock Knowledge Base ingestion."""
        tags_str = ", ".join(self.tags) if self.tags else "general"
        return (
            f"# {self.question}\n\n"
            f"**Category**: {self.category}\n"
            f"**Tags**: {tags_str}\n\n"
            f"## Answer\n\n{self.answer}\n"
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question": self.question,
            "answer": self.answer,
            "category": self.category,
            "tags": self.tags,
            "last_updated": self.last_updated.isoformat(),
        }


@dataclass
class FAQResult:
    """Result from FAQ knowledge base search."""

    entries: list["FAQEntry"]
    confidence_score: float  # Highest similarity score (0.0 to 1.0)
    source: str = "FAQ"
    raw_bedrock_results: list[dict] = field(default_factory=list)

    @property
    def top_entry(self) -> Optional["FAQEntry"]:
        return self.entries[0] if self.entries else None

    @property
    def has_results(self) -> bool:
        return bool(self.entries)


@dataclass
class FAQSearchParams:
    """Parameters for FAQ knowledge base search."""

    question: str
    threshold: float = 0.75
    top_k: int = 3
    knowledge_base_id: str = ""


class FAQFileParser:
    """Parses FAQ files from CSV, JSON, and Markdown formats."""

    @staticmethod
    def parse_csv(content: str) -> list[FAQEntry]:
        """
        Parse CSV with columns: id, question, answer, category, tags.
        Tags column should be semicolon-separated.
        """
        entries = []
        reader = csv.DictReader(io.StringIO(content))
        for i, row in enumerate(reader):
            entry_id = row.get("id") or f"faq-{i+1}"
            tags_raw = row.get("tags", "")
            tags = [t.strip() for t in tags_raw.split(";") if t.strip()]
            entries.append(
                FAQEntry(
                    id=entry_id,
                    question=row["question"].strip(),
                    answer=row["answer"].strip(),
                    category=row.get("category", "General").strip(),
                    tags=tags,
                )
            )
        return entries

    @staticmethod
    def parse_json(content: str) -> list[FAQEntry]:
        """
        Parse JSON array: [{id, question, answer, category, tags}].
        """
        data = json.loads(content)
        if not isinstance(data, list):
            data = data.get("faqs", data.get("entries", [data]))
        entries = []
        for i, item in enumerate(data):
            entry_id = item.get("id") or f"faq-{i+1}"
            tags = item.get("tags", [])
            if isinstance(tags, str):
                tags = [t.strip() for t in tags.split(",") if t.strip()]
            entries.append(
                FAQEntry(
                    id=entry_id,
                    question=item["question"].strip(),
                    answer=item["answer"].strip(),
                    category=item.get("category", "General").strip(),
                    tags=tags,
                )
            )
        return entries

    @staticmethod
    def parse_markdown(content: str) -> list[FAQEntry]:
        """
        Parse Markdown FAQ files. Auto-detects one of three formats:

        Format 1 — Structured (original):
          ## Q: Question text
          A: Answer text
          Category: category_name
          Tags: tag1, tag2

        Format 2 — Bold Q/A (BeSA FAQ style):
          **Q: Question text**
          A: Answer text (multi-paragraph)

        Format 3 — Heading-based (workshop issue resolutions):
          # Issue Title
          Prose answer...
        """
        has_structured_q = bool(re.search(r'^#{1,2}\s*Q:\s', content, re.MULTILINE))
        has_bold_q = bool(re.search(r'^\*\*Q[:.]\s', content, re.MULTILINE))

        if has_structured_q:
            return FAQFileParser._parse_structured_md(content)
        elif has_bold_q:
            return FAQFileParser._parse_bold_md(content)
        else:
            return FAQFileParser._parse_heading_md(content)

    @staticmethod
    def _parse_structured_md(content: str) -> list[FAQEntry]:
        """Original format: ## Q: / A: / Category: / Tags:"""
        entries = []
        lines = content.split("\n")
        current: dict = {}
        entry_id = 0

        for line in lines:
            line = line.strip()
            if line.startswith("## Q:") or line.startswith("# Q:"):
                if current.get("question") and current.get("answer"):
                    entries.append(FAQEntry(
                        id=f"faq-{entry_id}",
                        question=current["question"],
                        answer=current["answer"].strip(),
                        category=current.get("category", "General"),
                        tags=current.get("tags", []),
                    ))
                entry_id += 1
                current = {"question": line.split("Q:", 1)[1].strip()}
            elif line.startswith("A:"):
                current["answer"] = line[2:].strip()
            elif line.startswith("Category:"):
                current["category"] = line.split(":", 1)[1].strip()
            elif line.startswith("Tags:"):
                tags_raw = line.split(":", 1)[1].strip()
                current["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]
            elif line and current.get("answer") is not None:
                current["answer"] = current["answer"] + "\n" + line

        if current.get("question") and current.get("answer"):
            entries.append(FAQEntry(
                id=f"faq-{entry_id}",
                question=current["question"],
                answer=current["answer"].strip(),
                category=current.get("category", "General"),
                tags=current.get("tags", []),
            ))
        return entries

    @staticmethod
    def _parse_bold_md(content: str) -> list[FAQEntry]:
        """Bold format: **Q: text** or **Q. text** / A: text (BeSA FAQ style)."""
        entries = []
        lines = content.split("\n")
        current: dict = {}
        entry_id = 0
        in_answer = False

        for line in lines:
            stripped = line.strip()

            # Skip section headers, image refs, horizontal rules
            if stripped.startswith("#") or stripped == "---" or stripped.startswith("!["):
                in_answer = False
                continue

            # Detect **Q: text** or **Q. text**
            q_match = re.match(r'^\*\*Q[:.]\s*(.+?)[\*]*$', stripped, re.IGNORECASE)
            if q_match:
                if current.get("question") and current.get("answer"):
                    entries.append(FAQEntry(
                        id=f"faq-{entry_id}",
                        question=current["question"],
                        answer=current["answer"].strip(),
                        category=current.get("category", "General"),
                        tags=current.get("tags", []),
                    ))
                entry_id += 1
                current = {"question": q_match.group(1).strip().rstrip("*")}
                in_answer = False
                continue

            # Detect A: or A. answer line
            a_match = re.match(r'^A[:.]\s+(.*)', stripped, re.IGNORECASE)
            if a_match and current.get("question"):
                current["answer"] = a_match.group(1).strip()
                in_answer = True
                continue

            # Multi-line answer continuation (non-empty lines only)
            if in_answer and stripped:
                current["answer"] = current["answer"] + "\n" + stripped

        if current.get("question") and current.get("answer"):
            entries.append(FAQEntry(
                id=f"faq-{entry_id}",
                question=current["question"],
                answer=current["answer"].strip(),
                category=current.get("category", "General"),
                tags=current.get("tags", []),
            ))
        return entries

    @staticmethod
    def _parse_heading_md(content: str) -> list[FAQEntry]:
        """Heading-based format: # Issue Title / prose answer (workshop issues style)."""
        entries = []
        lines = content.split("\n")
        current: dict = {}
        entry_id = 0

        for line in lines:
            stripped = line.strip()

            # # or ## heading starts a new entry
            h_match = re.match(r'^#{1,2}\s+(.+)$', stripped)
            if h_match:
                if current.get("question") and current.get("answer", "").strip():
                    entries.append(FAQEntry(
                        id=f"faq-{entry_id}",
                        question=current["question"],
                        answer=current["answer"].strip(),
                        category="Workshop Issues",
                        tags=[],
                    ))
                entry_id += 1
                title = h_match.group(1).strip().strip("*").strip()
                current = {"question": title, "answer": ""}
                continue

            if current.get("question") is None:
                continue

            # Skip image lines
            if stripped.startswith("!["):
                continue

            if stripped:
                current["answer"] = current.get("answer", "") + stripped + "\n"

        if current.get("question") and current.get("answer", "").strip():
            entries.append(FAQEntry(
                id=f"faq-{entry_id}",
                question=current["question"],
                answer=current["answer"].strip(),
                category="Workshop Issues",
                tags=[],
            ))
        return entries

    @classmethod
    def parse(cls, content: str, file_format: str) -> list[FAQEntry]:
        """Auto-parse based on file format."""
        fmt = file_format.lower().lstrip(".")
        if fmt == "csv":
            return cls.parse_csv(content)
        elif fmt == "json":
            return cls.parse_json(content)
        elif fmt in ("md", "markdown"):
            return cls.parse_markdown(content)
        raise ValueError(f"Unsupported FAQ file format: {file_format}. Use csv, json, or md.")

    @staticmethod
    def validate(entries: list[FAQEntry]) -> list[str]:
        """Validate FAQ entries, return list of error messages."""
        errors = []
        seen_ids = set()
        for i, entry in enumerate(entries):
            prefix = f"Entry {i+1} (id={entry.id})"
            if not entry.question:
                errors.append(f"{prefix}: question is empty")
            if not entry.answer:
                errors.append(f"{prefix}: answer is empty")
            if len(entry.question) > 500:
                errors.append(f"{prefix}: question exceeds 500 characters")
            if len(entry.answer) > 10000:
                errors.append(f"{prefix}: answer exceeds 10000 characters")
            if entry.id in seen_ids:
                errors.append(f"{prefix}: duplicate id '{entry.id}'")
            seen_ids.add(entry.id)
        return errors
