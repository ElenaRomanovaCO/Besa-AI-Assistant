"""Unit tests for FAQ data models and file parser."""

import pytest
from backend.models.faq_models import FAQEntry, FAQFileParser, FAQResult


class TestFAQFileParser:
    def test_parse_csv_basic(self, sample_faq_csv):
        entries = FAQFileParser.parse_csv(sample_faq_csv)
        assert len(entries) == 3
        assert entries[0].id == "faq-1"
        assert "Lambda timeout" in entries[0].question
        assert "Lambda" in entries[0].category
        assert "timeout" in entries[0].tags

    def test_parse_json_basic(self, sample_faq_json):
        entries = FAQFileParser.parse_json(sample_faq_json)
        assert len(entries) == 2
        assert entries[0].id == "faq-1"
        assert isinstance(entries[0].tags, list)

    def test_parse_csv_missing_tags(self):
        csv = "id,question,answer,category,tags\nfaq-1,Q?,A.,General,\n"
        entries = FAQFileParser.parse_csv(csv)
        assert entries[0].tags == []

    def test_parse_auto_detect_csv(self, sample_faq_csv):
        entries = FAQFileParser.parse(sample_faq_csv, "csv")
        assert len(entries) == 3

    def test_parse_auto_detect_json(self, sample_faq_json):
        entries = FAQFileParser.parse(sample_faq_json, "json")
        assert len(entries) == 2

    def test_parse_unknown_format_raises(self, sample_faq_csv):
        with pytest.raises(ValueError, match="Unsupported"):
            FAQFileParser.parse(sample_faq_csv, "xml")

    def test_validate_empty_question_errors(self):
        entries = [FAQEntry(id="x", question="", answer="a", category="C")]
        errors = FAQFileParser.validate(entries)
        assert any("question is empty" in e for e in errors)

    def test_validate_empty_answer_errors(self):
        entries = [FAQEntry(id="x", question="q?", answer="", category="C")]
        errors = FAQFileParser.validate(entries)
        assert any("answer is empty" in e for e in errors)

    def test_validate_duplicate_ids(self):
        entries = [
            FAQEntry(id="dup", question="q1?", answer="a1", category="C"),
            FAQEntry(id="dup", question="q2?", answer="a2", category="C"),
        ]
        errors = FAQFileParser.validate(entries)
        assert any("duplicate id" in e for e in errors)

    def test_validate_passes_valid_entries(self):
        entries = [
            FAQEntry(id="faq-1", question="How?", answer="Like this.", category="General"),
            FAQEntry(id="faq-2", question="Why?", answer="Because.", category="General"),
        ]
        errors = FAQFileParser.validate(entries)
        assert len(errors) == 0


class TestFAQEntry:
    def test_to_markdown_format(self):
        entry = FAQEntry(
            id="faq-1",
            question="How do I set Lambda timeout?",
            answer="Go to console.",
            category="Lambda",
            tags=["lambda", "timeout"],
        )
        md = entry.to_markdown()
        assert "How do I set Lambda timeout?" in md
        assert "Go to console." in md
        assert "Lambda" in md
        assert "lambda, timeout" in md

    def test_to_dict_roundtrip(self):
        entry = FAQEntry(
            id="faq-1",
            question="Q?",
            answer="A.",
            category="General",
            tags=["x", "y"],
        )
        d = entry.to_dict()
        assert d["id"] == "faq-1"
        assert d["question"] == "Q?"
        assert isinstance(d["tags"], list)


class TestFAQResult:
    def test_top_entry_returns_first(self):
        e1 = FAQEntry(id="1", question="Q1?", answer="A1", category="C")
        e2 = FAQEntry(id="2", question="Q2?", answer="A2", category="C")
        result = FAQResult(entries=[e1, e2], confidence_score=0.85)
        assert result.top_entry.id == "1"  # type: ignore

    def test_top_entry_empty_returns_none(self):
        result = FAQResult(entries=[], confidence_score=0.0)
        assert result.top_entry is None

    def test_has_results(self):
        e1 = FAQEntry(id="1", question="Q?", answer="A.", category="C")
        assert FAQResult(entries=[e1], confidence_score=0.9).has_results
        assert not FAQResult(entries=[], confidence_score=0.0).has_results
