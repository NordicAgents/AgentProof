.PHONY: pdf supplement all clean clean-supplement

MAIN_TEX := main.tex
SUPP_TEX := supplement.tex

all: pdf supplement

pdf:
	latexmk -pdf -interaction=nonstopmode -halt-on-error $(MAIN_TEX)

# The supplement is a STANDALONE article-class document: it does not use
# aaai2027.sty (submission-locked) and does not \input anything from sections/.
# It resolves citations against ../references.bib.
supplement:
	latexmk -pdf -interaction=nonstopmode -halt-on-error $(SUPP_TEX)

clean:
	latexmk -C $(MAIN_TEX)

clean-supplement:
	latexmk -C $(SUPP_TEX)
