#!/usr/bin/env node
/**
 * Figure: AgentProof Pipeline Diagram.
 * Framework Workflow → Extractor → AgentGraph → {Structural, Temporal} → Report
 */
import { createSvg, addArrowMarker, addDropShadow, PALETTE, FONT } from '../lib/d3-paper-utils.mjs';

const W = 540, H = 190;
const { svg, serialize } = createSvg(W, H);

const shadow = addDropShadow(svg);
addArrowMarker(svg, 'arrow', PALETTE.text, 5);
addArrowMarker(svg, 'arrowBlue', PALETTE.primary, 5);

const nodeW = 90, nodeH = 36, rx = 6;

const nodes = [
  { id: 'fw',       label: 'Framework',     sub: 'Workflow',         x: 60,  y: 55, fill: '#EEF2F7' },
  { id: 'extract',  label: 'Extractor',     sub: null,               x: 175, y: 55, fill: '#E8F5E9' },
  { id: 'graph',    label: 'AgentGraph',    sub: null,               x: 290, y: 55, fill: '#FFF8E1', mono: true },
  { id: 'struct',   label: 'Structural',    sub: 'Checks',          x: 240, y: 145, fill: PALETTE.primary + '18' },
  { id: 'temporal', label: 'Temporal',      sub: 'Monitors',        x: 340, y: 145, fill: PALETTE.secondary + '18' },
  { id: 'report',   label: 'Report /',      sub: 'Decision',        x: 470, y: 55, fill: '#F3E5F5' },
];

const g = svg.append('g');

// Draw nodes
for (const n of nodes) {
  const ng = g.append('g').attr('transform', `translate(${n.x},${n.y})`);

  ng.append('rect')
    .attr('x', -nodeW / 2).attr('y', -nodeH / 2)
    .attr('width', nodeW).attr('height', nodeH)
    .attr('rx', rx)
    .attr('fill', n.fill)
    .attr('stroke', PALETTE.text)
    .attr('stroke-width', 1)
    .attr('filter', `url(#${shadow})`);

  if (n.sub) {
    ng.append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', '-0.15em')
      .attr('font-size', FONT.sizeLabel)
      .attr('font-weight', 600)
      .attr('fill', PALETTE.text)
      .text(n.label);
    ng.append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', '1.05em')
      .attr('font-size', FONT.sizeTick)
      .attr('fill', PALETTE.textLight)
      .attr('font-family', n.mono ? FONT.mono : FONT.family)
      .text(n.sub);
  } else {
    ng.append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', '0.35em')
      .attr('font-size', FONT.sizeLabel)
      .attr('font-weight', 600)
      .attr('fill', PALETTE.text)
      .attr('font-family', n.mono ? FONT.mono : FONT.family)
      .text(n.label);
  }
}

// Arrows: fw → extract → graph → report (main flow)
function arrowH(x1, x2, y) {
  g.append('line')
    .attr('x1', x1 + nodeW / 2).attr('y1', y)
    .attr('x2', x2 - nodeW / 2).attr('y2', y)
    .attr('stroke', PALETTE.text)
    .attr('stroke-width', 1.3)
    .attr('marker-end', 'url(#arrow)');
}

arrowH(60, 175, 55);
arrowH(175, 290, 55);

// graph → split down to struct and temporal
const gx = 290, gy = 55 + nodeH / 2;
const sy = 145 - nodeH / 2;

// graph → struct
g.append('path')
  .attr('d', `M ${gx},${gy} L ${gx},${gy + 14} L ${240},${sy - 6}`)
  .attr('fill', 'none')
  .attr('stroke', PALETTE.primary)
  .attr('stroke-width', 1.3)
  .attr('marker-end', 'url(#arrowBlue)');

// graph → temporal
g.append('path')
  .attr('d', `M ${gx},${gy} L ${gx},${gy + 14} L ${340},${sy - 6}`)
  .attr('fill', 'none')
  .attr('stroke', PALETTE.secondary)
  .attr('stroke-width', 1.3)
  .attr('marker-end', 'url(#arrowBlue)');

// struct → report
{
  const sx1 = 240 + nodeW / 2, sy1 = 145;
  const rx1 = 470 - nodeW / 2, ry1 = 55;
  g.append('path')
    .attr('d', `M ${sx1},${sy1} L ${sx1 + 20},${sy1} L ${rx1 - 6},${ry1 + nodeH / 2 + 2}`)
    .attr('fill', 'none')
    .attr('stroke', PALETTE.primary)
    .attr('stroke-width', 1.3)
    .attr('marker-end', 'url(#arrowBlue)');
}

// temporal → report
{
  const tx1 = 340 + nodeW / 2, ty1 = 145;
  const rx1 = 470, ry1 = 55 + nodeH / 2;
  g.append('path')
    .attr('d', `M ${tx1},${ty1} L ${tx1 + 10},${ty1} L ${470 - nodeW / 2 - 3},${ry1 + 2}`)
    .attr('fill', 'none')
    .attr('stroke', PALETTE.secondary)
    .attr('stroke-width', 1.3)
    .attr('marker-end', 'url(#arrowBlue)');
}

// graph → report (direct arrow on top)
arrowH(290, 470, 55);

// Labels on the split paths
g.append('text')
  .attr('x', 225).attr('y', 102)
  .attr('text-anchor', 'middle')
  .attr('font-size', FONT.sizeSmall)
  .attr('fill', PALETTE.primary)
  .text('structural');

g.append('text')
  .attr('x', 352).attr('y', 102)
  .attr('text-anchor', 'middle')
  .attr('font-size', FONT.sizeSmall)
  .attr('fill', PALETTE.secondary)
  .text('temporal');

// Stage labels above
const stages = ['①', '②', '③', '', '', '④'];
for (let i = 0; i < nodes.length; i++) {
  if (!stages[i]) continue;
  g.append('text')
    .attr('x', nodes[i].x).attr('y', nodes[i].y - nodeH / 2 - 8)
    .attr('text-anchor', 'middle')
    .attr('font-size', FONT.sizeAnnotation)
    .attr('fill', PALETTE.textLight)
    .text(stages[i]);
}

console.log(serialize());
