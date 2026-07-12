.PHONY: pdf clean

MAIN_TEX := main.tex

pdf:
	latexmk -pdf -interaction=nonstopmode -halt-on-error $(MAIN_TEX)

clean:
	latexmk -C $(MAIN_TEX)
