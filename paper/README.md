# Agentproof arXiv preprint

This folder contains an arXiv-compatible LaTeX source tree for an Agentproof
preprint, plus helper scripts to regenerate evaluation tables.

## Prerequisites

- TeX Live (or equivalent) with `pdflatex`, `bibtex`, and `latexmk`
- Python 3 (for optional table regeneration)

## Build the PDF

```bash
cd paper
make pdf
```

Output: `paper/main.pdf`

## Build an arXiv submission bundle

```bash
cd paper
make arxiv
```

Output: `paper/dist/agentproof-arxiv.tar.gz`

Upload the tarball to arXiv as a **TeX/LaTeX** submission (pdflatex + bibtex).

## Regenerate evaluation tables (optional)

```bash
cd paper
python3 scripts/collect_case_study_stats.py
python3 scripts/render_tables.py
make pdf
```

