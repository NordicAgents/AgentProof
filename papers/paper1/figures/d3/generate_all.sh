#!/usr/bin/env bash
# Generate all D3.js figures for the AgentProof paper.
# Produces SVG and PDF in paper/figures/.
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FIG_OUT="$SCRIPT_DIR/.."

cd "$SCRIPT_DIR"

# Ensure dependencies
if [ ! -d node_modules ]; then
    echo "Installing npm dependencies..."
    npm install --silent
fi

# Detect SVG→PDF converter once
svg_to_pdf() {
    local svg="$1" pdf="$2"
    if command -v rsvg-convert &>/dev/null; then
        rsvg-convert -f pdf -o "$pdf" "$svg"
    elif command -v inkscape &>/dev/null; then
        inkscape "$svg" --export-type=pdf --export-filename="$pdf" 2>/dev/null
    else
        echo "WARNING: No SVG-to-PDF converter found (install librsvg: brew install librsvg). Skipping PDF for $svg."
    fi
}

# Figure pairs: "script_basename:output_name"
FIGURES="fig_dfa_monitor:dfa_monitor fig_pipeline:pipeline fig_deployment:deployment fig_scaling:scaling_plot fig_example_graph:example_graph fig_defect_bar:defect_bar fig_precision_bar:precision_bar"

for pair in $FIGURES; do
    script="${pair%%:*}"
    name="${pair##*:}"
    echo "Generating ${name}..."
    node "src/${script}.mjs" > "$FIG_OUT/${name}.svg"
    svg_to_pdf "$FIG_OUT/${name}.svg" "$FIG_OUT/${name}.pdf"
done

echo ""
echo "Done. Generated $(ls "$FIG_OUT"/*.pdf | wc -l | tr -d ' ') PDFs in $FIG_OUT/"
ls -la "$FIG_OUT"/*.pdf
