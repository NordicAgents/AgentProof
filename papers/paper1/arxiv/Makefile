.PHONY: pdf clean arxiv

MAIN_TEX := main.tex
DIST_DIR := dist
STAGE_DIR := $(DIST_DIR)/arxiv-stage
ARXIV_TARBALL := $(DIST_DIR)/agentproof-arxiv.tar.gz

FIG_NAMES := pipeline example_graph dfa_monitor deployment defect_bar precision_bar scaling_plot
FIGURES := $(addprefix ../figures/,$(addsuffix .pdf,$(FIG_NAMES)))

pdf: $(FIGURES)
	latexmk -pdf -interaction=nonstopmode -halt-on-error $(MAIN_TEX)

clean:
	latexmk -C $(MAIN_TEX)
	rm -rf $(DIST_DIR)

# Self-contained arXiv bundle: shared assets are copied in so the tarball
# layout matches the figures/... paths used by the sources. arXiv does not
# run bibtex, so main.bbl must be included.
arxiv: pdf
	rm -rf $(STAGE_DIR)
	mkdir -p $(STAGE_DIR)/sections $(STAGE_DIR)/figures $(STAGE_DIR)/generated
	cp main.tex arxiv.sty appendix_proofs.tex appendix_grammar.tex main.bbl $(STAGE_DIR)/
	cp ../references.bib $(STAGE_DIR)/
	cp sections/*.tex $(STAGE_DIR)/sections/
	cp ../generated/*.tex $(STAGE_DIR)/generated/
	cp $(FIGURES) $(STAGE_DIR)/figures/
	tar -czf $(ARXIV_TARBALL) -C $(STAGE_DIR) .
	@echo "Wrote $(ARXIV_TARBALL)"

../figures/pipeline.pdf: ../figures/pipeline.tex
	cd ../figures && latexmk -pdf -interaction=nonstopmode -halt-on-error pipeline.tex

../figures/example_graph.pdf: ../figures/example_graph.tex
	cd ../figures && latexmk -pdf -interaction=nonstopmode -halt-on-error example_graph.tex

../figures/dfa_monitor.pdf: ../figures/dfa_monitor.tex
	cd ../figures && latexmk -pdf -interaction=nonstopmode -halt-on-error dfa_monitor.tex
