.PHONY: pdf clean arxiv

MAIN_TEX := main.tex
DIST_DIR := dist
ARXIV_TARBALL := $(DIST_DIR)/agentproof-arxiv.tar.gz

FIGURES := figures/pipeline.pdf figures/example_graph.pdf figures/dfa_monitor.pdf

pdf: $(FIGURES)
	latexmk -pdf -interaction=nonstopmode -halt-on-error $(MAIN_TEX)

clean:
	latexmk -C $(MAIN_TEX)
	rm -rf $(DIST_DIR)

arxiv: pdf
	mkdir -p $(DIST_DIR)
	tar -czf $(ARXIV_TARBALL) \
		main.tex arxiv.sty references.bib \
		sections/*.tex \
		generated/*.tex \
		$(FIGURES)
	@echo "Wrote $(ARXIV_TARBALL)"

figures/pipeline.pdf: figures/pipeline.tex
	cd figures && latexmk -pdf -interaction=nonstopmode -halt-on-error pipeline.tex

figures/example_graph.pdf: figures/example_graph.tex
	cd figures && latexmk -pdf -interaction=nonstopmode -halt-on-error example_graph.tex

figures/dfa_monitor.pdf: figures/dfa_monitor.tex
	cd figures && latexmk -pdf -interaction=nonstopmode -halt-on-error dfa_monitor.tex

