.PHONY: pdf supplement checklist all clean clean-supplement clean-checklist

MAIN_TEX := main.tex
SUPP_TEX := supplement.tex
CHECKLIST_TEX := ReproducibilityChecklist.tex

all: pdf supplement checklist

pdf:
	latexmk -pdf -interaction=nonstopmode -halt-on-error $(MAIN_TEX)

# The supplement is a STANDALONE article-class document: it does not use
# aaai2027.sty (submission-locked) and does not \input anything from sections/.
# It resolves citations against ../references.bib.
supplement:
	latexmk -pdf -interaction=nonstopmode -halt-on-error $(SUPP_TEX)

checklist:
	latexmk -pdf -interaction=nonstopmode -halt-on-error $(CHECKLIST_TEX)

clean:
	latexmk -C $(MAIN_TEX)

clean-supplement:
	latexmk -C $(SUPP_TEX)

clean-checklist:
	latexmk -C $(CHECKLIST_TEX)
