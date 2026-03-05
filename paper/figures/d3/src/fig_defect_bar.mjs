#!/usr/bin/env node
/**
 * Figure: Defect Distribution — grouped bar chart by defect type and framework.
 * Reads data from scripts/defect_results_annotated.json.
 */
import { createSvg, PALETTE, FONT, d3 } from '../lib/d3-paper-utils.mjs';
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const dataPath = resolve(__dirname, '../../../../scripts/defect_results_annotated.json');
const raw = JSON.parse(readFileSync(dataPath, 'utf8'));

// Aggregate defects by type and framework
const frameworkMap = { langgraph: 'LangGraph', crewai: 'CrewAI', autogen: 'AutoGen', adk: 'ADK' };
const frameworks = ['LangGraph', 'CrewAI', 'AutoGen', 'ADK'];
const defectTypes = ['dead_ends', 'exit_reachability', 'router_shape', 'tool_declarations', 'human_presence'];
const defectLabels = ['Dead Ends', 'Unreachable Exit', 'Router Shape', 'Missing Tool', 'Missing Human Gate'];
const categories = ['Structural', 'Structural', 'Structural', 'Structural', 'Policy'];

const counts = {};
for (const dt of defectTypes) {
  counts[dt] = {};
  for (const fw of frameworks) counts[dt][fw] = 0;
}

for (const wf of raw.details) {
  const fw = frameworkMap[wf.framework];
  for (const d of wf.defects) {
    if (counts[d.check] && counts[d.check][fw] !== undefined) {
      counts[d.check][fw]++;
    }
  }
}

const W = 460, H = 260;
const margin = { top: 30, right: 20, bottom: 65, left: 45 };
const iw = W - margin.left - margin.right;
const ih = H - margin.top - margin.bottom;

const { svg, serialize } = createSvg(W, H);
const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

// Scales
const x0 = d3.scaleBand()
  .domain(defectLabels)
  .range([0, iw])
  .padding(0.25);

const x1 = d3.scaleBand()
  .domain(frameworks)
  .range([0, x0.bandwidth()])
  .padding(0.08);

const y = d3.scaleLinear()
  .domain([0, 6])
  .range([ih, 0]);

const fwColors = {
  'LangGraph': PALETTE.primary,
  'CrewAI': PALETTE.tool,
  'AutoGen': PALETTE.router,
  'ADK': PALETTE.llm,
};

// Grid
[1, 2, 3, 4, 5, 6].forEach(v => {
  g.append('line')
    .attr('x1', 0).attr('y1', y(v))
    .attr('x2', iw).attr('y2', y(v))
    .attr('stroke', PALETTE.grid)
    .attr('stroke-width', 0.5);
});

// Category separator
const sepX = x0('Missing Human Gate') - x0.padding() * x0.step() / 2;
g.append('line')
  .attr('x1', sepX).attr('y1', -15)
  .attr('x2', sepX).attr('y2', ih + 5)
  .attr('stroke', PALETTE.neutral)
  .attr('stroke-width', 1)
  .attr('stroke-dasharray', '4,3');

g.append('text')
  .attr('x', sepX / 2).attr('y', -8)
  .attr('text-anchor', 'middle')
  .attr('font-size', FONT.sizeAnnotation)
  .attr('fill', PALETTE.textLight)
  .attr('font-weight', 600)
  .text('Structural');

g.append('text')
  .attr('x', (sepX + iw) / 2).attr('y', -8)
  .attr('text-anchor', 'middle')
  .attr('font-size', FONT.sizeAnnotation)
  .attr('fill', PALETTE.textLight)
  .attr('font-weight', 600)
  .text('Policy');

// Bars
defectLabels.forEach((dl, i) => {
  const dt = defectTypes[i];
  const barGroup = g.append('g').attr('transform', `translate(${x0(dl)},0)`);

  frameworks.forEach(fw => {
    const val = counts[dt][fw];
    if (val > 0) {
      barGroup.append('rect')
        .attr('x', x1(fw))
        .attr('y', y(val))
        .attr('width', x1.bandwidth())
        .attr('height', ih - y(val))
        .attr('fill', fwColors[fw])
        .attr('rx', 2)
        .attr('opacity', 0.85);

      // Value label on bar
      barGroup.append('text')
        .attr('x', x1(fw) + x1.bandwidth() / 2)
        .attr('y', y(val) - 3)
        .attr('text-anchor', 'middle')
        .attr('font-size', FONT.sizeSmall)
        .attr('fill', PALETTE.text)
        .attr('font-weight', 600)
        .text(val);
    }
  });
});

// X axis
g.append('g')
  .attr('transform', `translate(0,${ih})`)
  .call(d3.axisBottom(x0).tickSize(0))
  .call(g => g.select('.domain').attr('stroke', PALETTE.text))
  .call(g => g.selectAll('.tick text')
    .attr('font-size', FONT.sizeSmall)
    .attr('fill', PALETTE.text)
    .attr('transform', 'rotate(-25)')
    .attr('text-anchor', 'end')
    .attr('dx', '-0.3em')
    .attr('dy', '0.5em'));

// Y axis
g.append('g')
  .call(d3.axisLeft(y).ticks(6).tickSize(-3))
  .call(g => g.select('.domain').attr('stroke', PALETTE.text))
  .call(g => g.selectAll('.tick text')
    .attr('font-size', FONT.sizeTick)
    .attr('fill', PALETTE.text));

g.append('text')
  .attr('transform', 'rotate(-90)')
  .attr('x', -ih / 2).attr('y', -32)
  .attr('text-anchor', 'middle')
  .attr('font-size', FONT.sizeLabel)
  .attr('fill', PALETTE.text)
  .text('Count');

// Legend
const leg = g.append('g').attr('transform', `translate(${iw - 170}, ${ih + 42})`);
frameworks.forEach((fw, i) => {
  const lx = i * 72;
  leg.append('rect')
    .attr('x', lx).attr('y', -5)
    .attr('width', 10).attr('height', 10)
    .attr('rx', 2)
    .attr('fill', fwColors[fw])
    .attr('opacity', 0.85);
  leg.append('text')
    .attr('x', lx + 14).attr('y', 4)
    .attr('font-size', FONT.sizeSmall)
    .attr('fill', PALETTE.text)
    .text(fw);
});

console.log(serialize());
