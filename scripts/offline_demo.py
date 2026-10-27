"""Real PDF + real MiniLM/Chroma + LangGraph, explicitly mocked Gemini SDK.

Development demonstration only; this is not live-model validation or a baseline.
"""

import json
from pathlib import Path

from config import DOCUMENT_MODEL, FINANCIAL_MODEL
from gemini import GeminiAdapter, GeminiSettings
from graph import DocumentInput, run_pipeline, save_outputs
from tests.fakes import ReplaySDKClient


def main():
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/nvidia_2024/annual_report.pdf"
    client = ReplaySDKClient()
    document = GeminiAdapter(GeminiSettings(model_id=DOCUMENT_MODEL), client=client)
    financial = GeminiAdapter(GeminiSettings(model_id=FINANCIAL_MODEL), client=client)
    state = run_pipeline("Assess FY2024 financial health, revenue growth, profitability and liquidity",
        DocumentInput(path=str(fixture),
            source_url="https://s201.q4cdn.com/141608511/files/doc_financials/2024/ar/NVIDIA-2024-Annual-Report.pdf",
            title="NVIDIA FY2024 Annual Report (including Form 10-K)", entity="NVIDIA Corporation"),
        document_llm=document, financial_llm=financial)
    output = Path(__file__).resolve().parents[1] / "output/batch1"
    save_outputs(state, output, adapters=(document, financial))
    print(json.dumps({"status": state["report"].status, "model_execution": "MOCKED, no live Gemini calls",
                      "output": str(output), "issues": [i.model_dump() for i in state["analysis_map"].issues]}))


if __name__ == "__main__":
    main()
