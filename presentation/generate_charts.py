"""Export transparent evidence charts and crop a citation from the source PDF."""
import argparse
from pathlib import Path
import posixpath
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import pypdfium2 as pdfium

from evidence import ASSETS, DEFAULT_DEMO, ROOT, closeout, read_json

FOREST, ORANGE, RUST = "#013230", "#FF6A1F", "#823711"

for font_file in (ASSETS.parent / "fonts").glob("Poppins-*.ttf"):
    font_manager.fontManager.addfont(font_file)
plt.rcParams["font.family"] = "Poppins"


def source_crop(demo, output):
    data = read_json(demo / "results.json")
    case = next(c for c in data if c["case"] == "nvidia_2024_clean")
    source = next(s for s in case["source_values"] if s["metric"] == "revenue"
                  and s["period"]["end_date"].startswith("2024"))
    ev = source["evidence"][0]
    import hashlib
    path = ROOT / "tests/fixtures/nvidia_2024/annual_report.pdf"
    assert "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() == ev["source_id"]
    doc = pdfium.PdfDocument(path)
    page = doc[ev["page"] - 1]
    x0, top, x1, bottom = ev["bbox"]
    media_left, _, _, media_top = page.get_mediabox()
    crop_left, _, _, crop_top = page.get_bbox()
    # The extracted locator is relative to MediaBox; PDFium renders CropBox.
    left, right = media_left + x0, media_left + x1
    upper, lower = media_top - top, media_top - bottom
    text_page = page.get_textpage()
    source_text = text_page.get_text_bounded(left-3, lower-2, right+4, upper+2)
    assert all(token in source_text for token in ("Revenue", "60,922", "26,974", "26,914")), source_text
    text_page.close()
    factor = 4
    bitmap = page.render(scale=factor)
    im = bitmap.to_pil()
    render_box = (left - crop_left - 3, crop_top - upper - 2,
                  right - crop_left + 4, crop_top - lower + 2)
    im.crop(tuple(round(factor * v) for v in render_box)).save(output)
    bitmap.close()
    page.close()
    doc.close()


def report_excerpt(output):
    """Copy the image associated with the NVIDIA income statement caption."""
    ns = {
        "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
        "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    with ZipFile(ROOT / "report things/MAFIS Project Report.docx") as report:
        body = ET.fromstring(report.read("word/document.xml")).find("w:body", ns)
        rels = {rel.attrib["Id"]: rel.attrib["Target"]
                for rel in ET.fromstring(report.read("word/_rels/document.xml.rels"))}
        image = None
        for paragraph in body.findall("w:p", ns):
            drawing = paragraph.find(".//a:blip", ns)
            if drawing is not None:
                image = drawing.get(f"{{{ns['r']}}}embed")
            caption = "".join(text.text or "" for text in paragraph.findall(".//w:t", ns))
            if caption.startswith("Figure ") and "NVIDIA FY2024 income statement excerpt" in caption and image:
                target = rels[image]
                part = target.lstrip("/") if target.startswith("/") else posixpath.normpath("word/" + target)
                output.write_bytes(report.read(part))
                return
    raise ValueError("NVIDIA income statement excerpt not found in the project report")


def hbars(output, labels, values, stamps, xmax, *, xlabel):
    fig, ax = plt.subplots(figsize=(8, 1.75 + .43 * len(labels)), dpi=180)
    pos = list(range(len(labels)))
    ax.barh(pos, values, height=.53, color=[FOREST] + [ORANGE] * (len(labels) - 1),
            edgecolor=[FOREST] + [RUST] * (len(labels) - 1), linewidth=.75, zorder=3)
    for i, (value, stamp) in enumerate(zip(values, stamps)):
        ax.text(value + xmax * .022, i, stamp, va="center", color=FOREST, fontsize=11, weight="bold")
    ax.set_yticks(pos, labels)
    ax.invert_yaxis()
    ax.set(xlim=(0, xmax), xlabel=xlabel)
    ax.tick_params(length=0, colors=FOREST, labelsize=11)
    ax.xaxis.label.set_color(FOREST)
    ax.xaxis.grid(alpha=.16, zorder=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.savefig(output, transparent=True, bbox_inches="tight", pad_inches=.08)
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-dir", type=Path, default=DEFAULT_DEMO)
    parser.add_argument("--out", type=Path, default=ASSETS)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    d = closeout()
    retrieval = [d["pages"], d["anchors"]]
    hbars(args.out / "retrieval_at_5.png", ["Page hit", "Anchor passage"],
          [n for n, _ in retrieval], [f"{n}/{k}" for n, k in retrieval], 34,
          xlabel="Labelled queries")
    arms = d["arms"]
    hbars(args.out / "offline_timing.png", [key.replace("_", " ") for key in arms],
          [a[5] for a in arms.values()], [f"{a[5]:.3f} s" for a in arms.values()], 29,
          xlabel="Mean local inference seconds (mock run)")
    source_crop(args.demo_dir, args.out / "nvidia_revenue_row.png")
    report_excerpt(args.out / "report_figure_2.png")
