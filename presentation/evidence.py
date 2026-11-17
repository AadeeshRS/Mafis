"""Read the versioned closeout summary and the local demo exports."""
from pathlib import Path
import json
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ASSETS = HERE / "assets"
DEFAULT_DEMO = ROOT / "output/batch2/demo"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def closeout():
    text = (ROOT / "evaluation/results.md").read_text(encoding="utf-8")
    arms = {}
    for name, completed, failed, right, total, calls, seconds in re.findall(
        r"^\| (\w+) \| (\d+) \| (\d+) \| (\d+)/(\d+) \| (\d+) \| ([\d.]+) \|$",
        text, re.M,
    ):
        arms[name] = (int(completed), int(failed), int(right), int(total), int(calls), float(seconds))
    page_hit, page_n = map(int, re.search(r"page recall: (\d+)/(\d+)", text).groups())
    anchor_hit, anchor_n = map(int, re.search(r"passage coverage: (\d+)/(\d+)", text).groups())
    manifest = read_json(ROOT / "tests/fixtures/batch2_cases.json")["cases"]
    local = [c for c in manifest if c.get("document") and (ROOT / c["document"]["path"]).is_file()]
    supported = sum(c.get("annotation_ready_for_primary", True) for c in local)
    cells, ops = map(int, re.search(r"(\d+) source-matching values and (\d+) correct", text).groups())
    injected = {}
    for key, pattern in (
        ("Verifier", r"Injected verification: (\{[^}]+\})"),
        ("Critic", r"contradictions:\s*(\{[^}]+\})"),
    ):
        injected[key] = json.loads(re.search(pattern, text).group(1).replace("'", '"'))
    assert len(arms) == 8 and arms["full"][:2] == (supported, len(manifest) - supported)
    return dict(arms=arms, pages=(page_hit, page_n), anchors=(anchor_hit, anchor_n),
                slots=len(manifest), local=len(local), supported=supported, cells=cells,
                engine_ops=ops, injected=injected)


def filing_results():
    """Return the four displayed calculations per admitted filing in report order."""
    issuers = {
        "nvidia_2024": "NVIDIA", "apple_2024": "Apple", "coca_cola_2024": "Coca-Cola",
        "amazon_2024": "Amazon", "pepsico_2024": "PepsiCo", "meta_2024": "Meta", "amd_2024": "AMD",
    }
    text = (ROOT / "evaluation/results.md").read_text(encoding="utf-8")
    rows = {}
    for row in re.findall(r"^\| (\w+) \| (-?\d+\.\d+) \| (-?\d+\.\d+) \| (-?\d+\.\d+) \| (-?\d+\.\d+) \|$", text, re.M):
        rows[row[0]] = row[1:]
    return [[issuer, *rows[key]] for key, issuer in issuers.items()]
