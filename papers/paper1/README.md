# Agentproof paper 1

LaTeX sources for the Agentproof paper in two versions, sharing figures,
generated tables, and the bibliography:

```
paper1/
├── arxiv/           # full-length arXiv preprint (main.tex, arxiv.sty, sections/, appendices)
├── aaai/            # condensed AAAI-27 submission (main.tex, sections/, reproducibility checklist)
├── figures/         # shared figures (d3 sources + rendered PDFs/SVGs, TikZ sources)
├── generated/       # shared auto-generated tables and stats (see scripts/)
├── scripts/         # regenerate generated/ from evaluation outputs
└── references.bib   # shared bibliography
```

Both versions resolve shared assets from the parent directory: `aaai/` uses
explicit `../` paths, `arxiv/` uses `TEXINPUTS`/`BIBINPUTS` (set in its
`latexmkrc`) so its sources match the self-contained arXiv tarball layout.

## Prerequisites

- TeX Live (or equivalent) with `pdflatex`, `bibtex`, and `latexmk`
- Python 3 (for optional table regeneration)

## Build the PDFs

```bash
cd arxiv && make pdf   # -> arxiv/main.pdf
cd aaai  && make pdf   # -> aaai/main.pdf
```

## Build an arXiv submission bundle

```bash
cd arxiv
make arxiv
```

Output: `arxiv/dist/agentproof-arxiv.tar.gz` — a self-contained bundle
(sources, `main.bbl`, figures, generated tables). Upload to arXiv as a
**TeX/LaTeX** submission (pdflatex).

## Regenerate evaluation tables (optional)

```bash
python3 scripts/collect_case_study_stats.py
python3 scripts/render_tables.py
```

Then rebuild the PDFs.
