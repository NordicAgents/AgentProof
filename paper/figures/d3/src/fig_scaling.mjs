#!/usr/bin/env node
/**
 * Figure: Scaling Plot — log-log chart of verification time vs. graph size.
 * Reads data from scripts/scaling_results.json.
 */
import { createSvg, PALETTE, FONT, d3 } from '../lib/d3-paper-utils.mjs';
import { readFileSync } from 'fs';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const dataPath = resolve(__dirname, '../../../../scripts/scaling_results.json');
const data = JSON.parse(readFileSync(dataPath, 'utf8'));

const W = 420, H = 300;
const margin = { top: 20, right: 30, bottom: 50, left: 65 };
const iw = W - margin.left - margin.right;
const ih = H - margin.top - margin.bottom;

const { svg, serialize } = createSvg(W, H);
const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

// Scales
const x = d3.scaleLog()
  .domain([40, 6000])
  .range([0, iw]);

const y = d3.scaleLog()
  .domain([0.02, 200])
  .range([ih, 0]);

// Grid lines
const xTicks = [50, 100, 200, 500, 1000, 2000, 5000];
const yTicks = [0.01, 0.1, 1, 10, 100];

g.selectAll('.grid-x')
  .data(xTicks)
  .enter().append('line')
  .attr('x1', d => x(d)).attr('y1', 0)
  .attr('x2', d => x(d)).attr('y2', ih)
  .attr('stroke', PALETTE.grid)
  .attr('stroke-width', 0.5);

g.selectAll('.grid-y')
  .data(yTicks)
  .enter().append('line')
  .attr('x1', 0).attr('y1', d => y(d))
  .attr('x2', iw).attr('y2', d => y(d))
  .attr('stroke', PALETTE.grid)
  .attr('stroke-width', 0.5);

// Axes
// X axis
g.append('g')
  .attr('transform', `translate(0,${ih})`)
  .call(d3.axisBottom(x)
    .tickValues(xTicks)
    .tickFormat(d => d >= 1000 ? `${d / 1000}k` : d))
  .call(g => g.select('.domain').attr('stroke', PALETTE.text))
  .call(g => g.selectAll('.tick line').attr('stroke', PALETTE.text))
  .call(g => g.selectAll('.tick text')
    .attr('font-size', FONT.sizeTick)
    .attr('fill', PALETTE.text));

g.append('text')
  .attr('x', iw / 2).attr('y', ih + 38)
  .attr('text-anchor', 'middle')
  .attr('font-size', FONT.sizeLabel)
  .attr('fill', PALETTE.text)
  .text('Number of nodes');

// Y axis
g.append('g')
  .call(d3.axisLeft(y)
    .tickValues(yTicks)
    .tickFormat(d => d < 1 ? d.toString() : d))
  .call(g => g.select('.domain').attr('stroke', PALETTE.text))
  .call(g => g.selectAll('.tick line').attr('stroke', PALETTE.text))
  .call(g => g.selectAll('.tick text')
    .attr('font-size', FONT.sizeTick)
    .attr('fill', PALETTE.text));

g.append('text')
  .attr('transform', 'rotate(-90)')
  .attr('x', -ih / 2).attr('y', -48)
  .attr('text-anchor', 'middle')
  .attr('font-size', FONT.sizeLabel)
  .attr('fill', PALETTE.text)
  .text('Time (ms)');

// Data: structural check line
const lineGen = d3.line()
  .x(d => x(d.n_nodes))
  .y(d => y(d.structural_check_ms));

g.append('path')
  .datum(data)
  .attr('d', lineGen)
  .attr('fill', 'none')
  .attr('stroke', PALETTE.primary)
  .attr('stroke-width', 2);

g.selectAll('.dot-struct')
  .data(data)
  .enter().append('circle')
  .attr('cx', d => x(d.n_nodes))
  .attr('cy', d => y(d.structural_check_ms))
  .attr('r', 3.5)
  .attr('fill', PALETTE.primary)
  .attr('stroke', '#fff')
  .attr('stroke-width', 1);

// Data: monitor eval horizontal dashed line
const monitorMs = data[0].monitor_eval_ms;
g.append('line')
  .attr('x1', 0).attr('y1', y(monitorMs))
  .attr('x2', iw).attr('y2', y(monitorMs))
  .attr('stroke', PALETTE.secondary)
  .attr('stroke-width', 1.5)
  .attr('stroke-dasharray', '6,3');

// Legend
const leg = g.append('g').attr('transform', `translate(12, 8)`);

leg.append('line')
  .attr('x1', 0).attr('y1', 0).attr('x2', 18).attr('y2', 0)
  .attr('stroke', PALETTE.primary).attr('stroke-width', 2);
leg.append('circle').attr('cx', 9).attr('cy', 0).attr('r', 3).attr('fill', PALETTE.primary);
leg.append('text').attr('x', 24).attr('y', 4)
  .attr('font-size', FONT.sizeTick).attr('fill', PALETTE.text)
  .text('Structural checks');

leg.append('line')
  .attr('x1', 0).attr('y1', 18).attr('x2', 18).attr('y2', 18)
  .attr('stroke', PALETTE.secondary).attr('stroke-width', 1.5)
  .attr('stroke-dasharray', '6,3');
leg.append('text').attr('x', 24).attr('y', 22)
  .attr('font-size', FONT.sizeTick).attr('fill', PALETTE.text)
  .text(`Monitor eval (${monitorMs.toFixed(1)} ms)`);

// Annotation: sub-second threshold
g.append('line')
  .attr('x1', 0).attr('y1', y(1000))
  .attr('x2', iw).attr('y2', y(1000))
  .attr('stroke', PALETTE.neutral)
  .attr('stroke-width', 0.8)
  .attr('stroke-dasharray', '2,2');

console.log(serialize());
