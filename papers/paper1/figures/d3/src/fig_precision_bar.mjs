#!/usr/bin/env node
/**
 * Figure: Precision per Check — stacked horizontal bar chart.
 * Shows TP / FP / Arguable breakdown with precision labels.
 */
import { createSvg, PALETTE, FONT, d3 } from '../lib/d3-paper-utils.mjs';
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const dataPath = resolve(__dirname, '../../../../scripts/defect_results_annotated.json');
const raw = JSON.parse(readFileSync(dataPath, 'utf8'));

const precision = raw.precision_by_check;
const checks = Object.keys(precision);
const checkLabels = {
  dead_ends: 'Dead Ends',
  exit_reachability: 'Unreachable Exit',
  router_shape: 'Router Shape',
  tool_declarations: 'Missing Tool',
  human_presence: 'Missing Human Gate',
};

const W = 400, H = 200;
const margin = { top: 20, right: 80, bottom: 25, left: 130 };
const iw = W - margin.left - margin.right;
const ih = H - margin.top - margin.bottom;

const { svg, serialize } = createSvg(W, H);
const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

const y = d3.scaleBand()
  .domain(checks.map(c => checkLabels[c]))
  .range([0, ih])
  .padding(0.3);

const maxTotal = Math.max(...checks.map(c => {
  const p = precision[c];
  return p.tp + p.fp + p.arguable;
}));

const x = d3.scaleLinear()
  .domain([0, maxTotal + 1])
  .range([0, iw]);

const colors = {
  tp: PALETTE.success,
  fp: PALETTE.danger,
  arguable: PALETTE.warning,
};

// Grid
[2, 4, 6, 8, 10].filter(v => v <= maxTotal + 1).forEach(v => {
  g.append('line')
    .attr('x1', x(v)).attr('y1', 0)
    .attr('x2', x(v)).attr('y2', ih)
    .attr('stroke', PALETTE.grid)
    .attr('stroke-width', 0.5);
});

// Bars
for (const c of checks) {
  const p = precision[c];
  const label = checkLabels[c];
  let cumX = 0;

  for (const [key, color] of [['tp', colors.tp], ['fp', colors.fp], ['arguable', colors.arguable]]) {
    const val = p[key];
    if (val > 0) {
      g.append('rect')
        .attr('x', x(cumX))
        .attr('y', y(label))
        .attr('width', x(val) - x(0))
        .attr('height', y.bandwidth())
        .attr('fill', color)
        .attr('rx', 2)
        .attr('opacity', 0.8);

      // Value inside bar if wide enough
      if (x(val) - x(0) > 16) {
        g.append('text')
          .attr('x', x(cumX) + (x(val) - x(0)) / 2)
          .attr('y', y(label) + y.bandwidth() / 2 + 1)
          .attr('text-anchor', 'middle')
          .attr('dominant-baseline', 'middle')
          .attr('font-size', FONT.sizeSmall)
          .attr('fill', '#fff')
          .attr('font-weight', 700)
          .text(val);
      }
    }
    cumX += val;
  }

  // Precision annotation
  const total = p.tp + p.fp + p.arguable;
  g.append('text')
    .attr('x', x(total) + 8)
    .attr('y', y(label) + y.bandwidth() / 2 + 1)
    .attr('dominant-baseline', 'middle')
    .attr('font-size', FONT.sizeTick)
    .attr('fill', PALETTE.text)
    .attr('font-weight', 600)
    .text(`P = ${p.precision.toFixed(2)}`);
}

// Y axis
g.append('g')
  .call(d3.axisLeft(y).tickSize(0))
  .call(g => g.select('.domain').attr('stroke', PALETTE.text))
  .call(g => g.selectAll('.tick text')
    .attr('font-size', FONT.sizeTick)
    .attr('fill', PALETTE.text));

// X axis
g.append('g')
  .attr('transform', `translate(0,${ih})`)
  .call(d3.axisBottom(x).ticks(5).tickSize(-3))
  .call(g => g.select('.domain').attr('stroke', PALETTE.text))
  .call(g => g.selectAll('.tick text')
    .attr('font-size', FONT.sizeTick)
    .attr('fill', PALETTE.text));

g.append('text')
  .attr('x', iw / 2).attr('y', ih + 22)
  .attr('text-anchor', 'middle')
  .attr('font-size', FONT.sizeTick)
  .attr('fill', PALETTE.text)
  .text('Findings');

// Legend
const leg = g.append('g').attr('transform', `translate(${iw + 10}, 0)`);
const legendItems = [
  { label: 'TP', color: colors.tp },
  { label: 'FP', color: colors.fp },
  { label: 'Arguable', color: colors.arguable },
];
legendItems.forEach((item, i) => {
  leg.append('rect')
    .attr('x', 0).attr('y', i * 16)
    .attr('width', 10).attr('height', 10)
    .attr('rx', 2)
    .attr('fill', item.color)
    .attr('opacity', 0.8);
  leg.append('text')
    .attr('x', 14).attr('y', i * 16 + 9)
    .attr('font-size', FONT.sizeSmall)
    .attr('fill', PALETTE.text)
    .text(item.label);
});

console.log(serialize());
