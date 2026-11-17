"""The local wire schema must preserve exact evidence for agent validation."""

import json

import httpx
import pytest

from agents.argument_contracts import ArgumentProposal
from agents.critic_agent import CriticExplanation
from agents.document_agent import DocumentExtraction
from agents.financial_agent import FinancialInterpretation
from gemini import ModelOutputError, ModelUnavailable
from ollama_adapter import MAX_REQUEST_BYTES, OllamaAdapter, local_request, probe_ollama


@pytest.fixture
def extraction():
    return {"task": "document_extraction", "question": "Assess annual revenue", "requested_metrics": ["revenue"],
            "chunks": [{"chunk_id": "original-chunk", "kind": "table", "text": "unneeded table text " * 2000,
                        "cells": [{"cell_id": "original-cell", "metric": "revenue", "value": "123.4500", "unit": "currency",
                                   "currency": "USD", "scale": 1000, "period": {"end_date": "2024-12-31"}}]}]}


def respond(monkeypatch, data, inspect=lambda body: None):
    def chat(method, path, *, content, **kwargs):
        assert (method, path) == ("POST", "/api/chat")
        assert len(content) <= MAX_REQUEST_BYTES
        body = json.loads(content)
        assert body["stream"] is False and body["think"] is False
        inspect(body)
        return {"message": {"content": json.dumps(data)}, "done": True, "prompt_eval_count": 99, "eval_count": 12}

    monkeypatch.setattr("ollama_adapter.local_request", chat)


def test_document_sends_compact_rows_and_restores_exact_cell(monkeypatch, extraction):
    def inspect(body):
        context = json.loads(body["messages"][1]["content"])
        assert context["cells"] == [[1, "revenue", "2024-12-31", "123.4500", "USD", 1000]]
        assert context["required_cell_ids"] == [1]
        assert body["format"]["properties"]["cell_ids"]["minItems"] == 1
        assert "original-cell" not in json.dumps(body)
        assert "unneeded table text" not in json.dumps(body)

    respond(monkeypatch, {"cell_ids": [1]}, inspect)
    adapter = OllamaAdapter()
    result = adapter.generate(DocumentExtraction, system="Original instruction", payload=extraction)
    cell, = result.primitives
    assert (cell.chunk_id, cell.cell_id, cell.value, cell.unit) == ("original-chunk", "original-cell", "123.4500", "currency")
    call, = adapter.telemetry
    assert call.status == "success" and call.prompt_tokens == 99
    assert call.compact_context_bytes < call.original_context_bytes / 10


def test_unknown_ids_and_oversized_requests_fail_visibly(monkeypatch, extraction):
    respond(monkeypatch, {"cell_ids": [999]})
    adapter = OllamaAdapter()
    with pytest.raises(ModelOutputError, match="unknown evidence ID"):
        adapter.generate(DocumentExtraction, system="", payload=extraction)
    assert adapter.telemetry[0].status == "invalid_output"
    with pytest.raises(ModelOutputError, match="exceeds"):
        adapter.generate(DocumentExtraction, system="", payload={**extraction, "question": "x" * MAX_REQUEST_BYTES})
    assert len(adapter.telemetry) == 1


def test_financial_and_critic_restore_references(monkeypatch):
    adapter = OllamaAdapter()
    respond(monkeypatch, {"label": "decrease"})
    artifact = {"operation": "revenue_growth", "output_value": "-2.0", "calculation_ref": "calc:original", "inputs": ["heavy metadata"]}
    interpretation = adapter.generate(FinancialInterpretation, system="", payload={"task": "financial_interpretation", "artifact": artifact})
    assert interpretation.calculation_ref == "calc:original"

    respond(monkeypatch, {"explanations": [{"id": 1, "significance": "dimension_consistency"}]})
    finding = {"finding_id": "original-finding", "category": "numerical", "rule": "normalized_same_fact", "description": "Values disagree"}
    result = adapter.generate(CriticExplanation, system="", payload={"task": "critic_explanation", "findings": [finding]})
    assert result.explanations[0].finding_id == "original-finding"


def test_arguments_restore_snapshot_exactly(monkeypatch):
    adapter = OllamaAdapter()
    respond(monkeypatch, {"interpretation": "strength", "premise_ids": [1]})
    premise = {"claim_ref": {"run_id": "run", "claim_id": "original-claim", "version": 2}, "entity": "Example",
               "metric": "operating_margin", "value": "3.250", "period": None, "unit": "percent", "currency": None,
               "scale": 1, "accounting_scope": "consolidated", "calculation_ref": "calc:original",
               "source_ids": ["source"], "quotations": ["Exact full quote retained outside the prompt"]}
    snapshot = {"fingerprint": "a" * 64, "premises": [premise]}
    proposal = adapter.generate(ArgumentProposal, system="", payload={"task": "bull_case", "snapshot": snapshot})
    argument, = proposal.arguments
    assert argument.snapshot_hash == snapshot["fingerprint"]
    restored, = argument.premises
    assert restored.model_dump(mode="json")["value"] == "3.250"
    assert restored.claim_ref.version == 2 and restored.quotations == tuple(premise["quotations"])


def test_loopback_transport_and_unreachable_service(monkeypatch, extraction):
    def client(**kwargs):
        assert kwargs["base_url"] == "http://127.0.0.1:11434"
        assert kwargs["trust_env"] is False
        raise httpx.ConnectError("service unavailable")

    monkeypatch.setattr("ollama_adapter.httpx.Client", client)
    with pytest.raises(httpx.ConnectError):
        local_request("GET", "/api/tags", timeout=3)
    assert probe_ollama()["status"] == "server_unreachable"
    with pytest.raises(ModelUnavailable, match="Could not connect"):
        OllamaAdapter().generate(DocumentExtraction, system="", payload=extraction)
