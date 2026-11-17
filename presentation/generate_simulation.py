"""Replay the saved NVIDIA offline correction. This script never calls a model."""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib import font_manager

from evidence import ASSETS, DEFAULT_DEMO, read_json

for font_file in (ASSETS.parent / "fonts").glob("Poppins-*.ttf"):
    font_manager.fontManager.addfont(font_file)
plt.rcParams["font.family"] = "Poppins"


def generate(demo_dir, output):
    folder = demo_dir / "nvidia_2024_corrected"
    evidence = read_json(folder / "evidence.json")
    summary = read_json(folder / "run_summary.json")
    first, *_, last = [entry["result"] for entry in evidence["gate_history"]]
    decision = evidence["retry_decisions"][0]
    claim = next(c for c in evidence["claims"] if c.get("metric") == "net_income"
                 and c["verification_status"] == "verified")
    net_margin = next(c for c in evidence["calculations"] if c["operation"] == "net_margin")
    assert first["decision"] == "blocked" and "missing_primitives" in first["failure_types"]
    assert decision["outcome"] == "executed" and decision["metrics"] == ["net_income"]
    assert decision["operations"] == ["net_margin"] and last["decision"] == "passed"
    assert summary["report_status"] == "success"
    assert any(r["outcome"] == "verified" and
               (r.get("resulting_ref") or {}).get("claim_id") == claim["claim_id"]
               for r in evidence["verification_records"])

    milestones = ("Omission", "Gate", "Planner", "Recheck", "Report")
    states = (
        ("Net income omitted", "First model response"),
        ("Health Gate blocks", "Required evidence missing"),
        ("Planner allocates retry", f"Budget: {decision['budget_before']} to {decision['budget_after']}"),
        ("Net income verified", "Financial Engine recomputes"),
        (f"{net_margin['display_value']}% net margin", "Gate passes · report succeeds"),
    )
    background, ink, muted, orange, apricot = "#013230", "#F3EBDD", "#EADCC6", "#FF6A1F", "#FFD1AC"
    fig, ax = plt.subplots(figsize=(9.10, 4.12), dpi=128, facecolor=background)
    fig.subplots_adjust(0, 0, 1, 1)
    xs = [0.13, 0.315, 0.5, 0.685, 0.87]

    def frame(i):
        ax.clear()
        ax.set(xlim=(0, 1), ylim=(0, 1), facecolor=background)
        ax.axis("off")
        ax.text(.08, .79, f"STEP {i+1:02d} / {len(states):02d}", color=apricot, fontsize=13, weight="bold")
        ax.text(.08, .60, states[i][0], color=ink, fontsize=31, weight="bold")
        ax.text(.08, .48, states[i][1], color=muted, fontsize=17)
        ax.plot([xs[0], xs[-1]], [.26, .26], color="#506B60", lw=2, zorder=1)
        if i:
            ax.plot([xs[0], xs[i]], [.26, .26], color=orange, lw=2.6, zorder=2)
        for j, (x, label) in enumerate(zip(xs, milestones)):
            active = j <= i
            ax.scatter([x], [.26], s=174 if i == j else 90, color=orange if active else "#506B60",
                       edgecolor=background, linewidth=1.6, zorder=3)
            ax.text(x, .14, label, color=ink if active else muted, fontsize=14,
                    ha="center", weight="bold" if j == i else "normal")

    output.parent.mkdir(parents=True, exist_ok=True)
    anim = FuncAnimation(fig, frame, frames=[0, 1, 2, 3, 4, 4], interval=1750, repeat=True)
    anim.save(output, writer=PillowWriter(fps=1 / 1.75), dpi=128)
    plt.close(fig)
    return milestones, states


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-dir", type=Path, default=DEFAULT_DEMO)
    parser.add_argument("--output", type=Path, default=ASSETS / "nvidia_correction.gif")
    args = parser.parse_args()
    generate(args.demo_dir, args.output)
