# MAFIS course presentation based on the project report

- `MAFIS_AI_Project_Benchmark.pptx` has 16 slides with embedded notes, editable workflow shapes and tables, a retrieval chart and an animated demo.
- `report_slide_blueprint.md` contains the exact copy, visual placement and speaker notes for all 16 slides.
- `build_deck.py`: recreates the deck and blueprint with python-pptx. Its source files and assets are all local.
- `generate_simulation.py`: converts the saved NVIDIA correction trace into a looping GIF. Start Slide Show on slide 13 to see it play; if your viewer displays only a still, open `assets/nvidia_correction.gif`.
- `generate_charts.py` exports transparent retrieval and timing PNGs and copies the NVIDIA income statement excerpt from the report for slide 6. The deck uses an editable retrieval chart and timing tables.
- `diagrams/*.dot`: Graphviz source for preprocessing/retrieval, orchestration and the correction trace. The rendered SVGs are separate, and the PowerPoint workflow remains editable.
- `fonts/` contains Poppins Regular and Bold and their SIL Open Font License. Install the fonts before presenting on a different computer that lacks Poppins.

## Rebuild from the MAFIS root

```powershell
python -m pip install -r presentation/requirements.txt
python presentation/generate_charts.py
python presentation/generate_simulation.py
Push-Location presentation
npm ci
npm run diagrams
Pop-Location
python presentation/build_deck.py
```

Python builds the PowerPoint. Node/npm regenerates the optional SVGs. The Python scripts read the checked-in summary in `evaluation/results.md`, the fixture manifest, the figures in the project report and the saved local offline run under `output/batch2/demo`. The generation commands use previously recorded offline evidence.

If the local demo directory is absent (for example, on a fresh checkout), regenerate the NVIDIA traces using the repository's Python environment and the real local Chroma/MiniLM retriever. Mock generation requires no API key. The embedder can need an initial model download if it is not already cached:

```powershell
.\.venv\Scripts\python.exe -m scripts.batch2_demo --case-ids nvidia_2024 --output output/batch2/demo
```

For a separate demo directory, pass `--demo-dir path/to/demo` to both asset generators. The standalone GIF script validates the gate, retry, verification and net-margin records before making frames.

The deck uses the repository implementation and saved runs for technical claims, and follows the grading instructions in `report things/Final Guidelines.docx.pdf`. The project report supplies literature context and the NVIDIA filing excerpt. Slide 10 presents the offline closeout calculation table. Slide 14 uses the recorded local DeepSeek-R1 pair in `assets/apple_demo_scores.json`. Slide 15 shows the separate mock ablations.
