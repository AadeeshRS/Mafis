"""Offline test doubles are explicit; none are production embedding fallbacks."""

from hashlib import sha256
from pathlib import Path
import re
from uuid import uuid4

import pytest

from rag.ingest import prepare_document


class HashTestEmbedder:
    def __call__(self, texts):
        output = []
        for text in texts:
            vector = [0.0] * 64
            for word in re.findall(r"\w+", text.casefold()):
                vector[int(sha256(word.encode()).hexdigest()[:8], 16) % 64] += 1.0
            output.append(vector)
        return output


@pytest.fixture
def offline_retriever():
    import chromadb
    from chromadb.config import Settings
    from rag.retriever import SharedRetriever
    return SharedRetriever(client=chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False)),
        collection_name="test_" + uuid4().hex, embedder=HashTestEmbedder(), embedding_model="test-hash-v1")


@pytest.fixture(scope="session")
def prepared_document():
    return prepare_document(Path(__file__).parent / "fixtures/nvidia_2024/annual_report.pdf",
        source_url="https://s201.q4cdn.com/141608511/files/doc_financials/2024/ar/NVIDIA-2024-Annual-Report.pdf",
        title="NVIDIA FY2024 Annual Report (including Form 10-K)", entity="NVIDIA Corporation")
