#!/usr/bin/env node
/**
 * Figure: Trust Boundary Deployment Model.
 * Shows untrusted zone (developer, workflow definition) and trusted CI/CD pipeline.
 */
import { createSvg, addArrowMarker, addDropShadow, PALETTE, FONT } from '../lib/d3-paper-utils.mjs';

const W = 520, H = 200;
const { svg, serialize } = createSvg(W, H);

const shadow = addDropShadow(svg);
addArrowMarker(svg, 'arrow', PALETTE.text, 5);
addArrowMarker(svg, 'arrowGreen', PALETTE.success, 5);
addArrowMarker(svg, 'arrowRed', PALETTE.danger, 5);

const g = svg.append('g');

const nw = 88, nh = 34, rx = 5;

// Trusted boundary box
g.append('rect')
  .attr('x', 210).attr('y', 18)
  .attr('width', 290).attr('height', 130)
  .attr('rx', 8)
  .attr('fill', PALETTE.success + '0A')
  .attr('stroke', PALETTE.success)
  .attr('stroke-width', 1.5)
  .attr('stroke-dasharray', '6,3');

g.append('text')
  .attr('x', 355).attr('y', 35)
  .attr('text-anchor', 'middle')
  .attr('font-size', FONT.sizeAnnotation)
  .attr('fill', PALETTE.success)
  .attr('font-weight', 600)
  .text('Trusted CI/CD Pipeline');

// Untrusted label
g.append('text')
  .attr('x', 85).attr('y', 15)
  .attr('text-anchor', 'middle')
  .attr('font-size', FONT.sizeAnnotation)
  .attr('fill', PALETTE.danger)
  .attr('font-weight', 600)
  .text('Untrusted');

// Nodes
const nodes = [
  { id: 'dev',      label: 'Developer',    sub: '(T1 / T2)',   x: 85,  y: 65,  fill: PALETTE.danger + '14', stroke: PALETTE.danger },
  { id: 'workflow', label: 'Workflow',      sub: 'Definition',  x: 85,  y: 120, fill: PALETTE.danger + '14', stroke: PALETTE.danger },
  { id: 'extract',  label: 'Extractor',    sub: null,          x: 265, y: 85,  fill: PALETTE.success + '14', stroke: PALETTE.success },
  { id: 'verify',   label: 'Agentproof',   sub: 'Verifier',    x: 380, y: 85,  fill: PALETTE.success + '14', stroke: PALETTE.success },
  { id: 'deploy',   label: '✓ Deploy',     sub: null,          x: 445, y: 170, fill: '#E8F5E9', stroke: PALETTE.success },
  { id: 'reject',   label: '✗ Reject',     sub: null,          x: 330, y: 170, fill: '#FFEBEE', stroke: PALETTE.danger },
];

for (const n of nodes) {
  const ng = g.append('g').attr('transform', `translate(${n.x},${n.y})`);

  ng.append('rect')
    .attr('x', -nw / 2).attr('y', -nh / 2)
    .attr('width', nw).attr('height', nh)
    .attr('rx', rx)
    .attr('fill', n.fill)
    .attr('stroke', n.stroke)
    .attr('stroke-width', 1.2)
    .attr('filter', `url(#${shadow})`);

  if (n.sub) {
    ng.append('text').attr('text-anchor', 'middle').attr('dy', '-0.1em')
      .attr('font-size', FONT.sizeLabel).attr('font-weight', 600).attr('fill', PALETTE.text)
      .text(n.label);
    ng.append('text').attr('text-anchor', 'middle').attr('dy', '1.05em')
      .attr('font-size', FONT.sizeSmall).attr('fill', PALETTE.textLight)
      .text(n.sub);
  } else {
    ng.append('text').attr('text-anchor', 'middle').attr('dy', '0.35em')
      .attr('font-size', FONT.sizeLabel).attr('font-weight', 600).attr('fill', PALETTE.text)
      .text(n.label);
  }
}

// Arrows
function line(n1, n2, marker = 'arrow', color = PALETTE.text) {
  const from = nodes.find(n => n.id === n1);
  const to = nodes.find(n => n.id === n2);
  const dx = to.x - from.x, dy = to.y - from.y;
  const dist = Math.sqrt(dx * dx + dy * dy);
  const ux = dx / dist, uy = dy / dist;
  g.append('line')
    .attr('x1', from.x + ux * nw / 2).attr('y1', from.y + uy * nh / 2)
    .attr('x2', to.x - ux * nw / 2).attr('y2', to.y - uy * nh / 2)
    .attr('stroke', color)
    .attr('stroke-width', 1.3)
    .attr('marker-end', `url(#${marker})`);
}

// dev → workflow
line('dev', 'workflow');

// workflow → extract
line('workflow', 'extract');

// extract → verify
line('extract', 'verify');

// verify → deploy (pass)
{
  const vx = 380, vy = 85 + nh / 2;
  const dx = 445, dy = 170 - nh / 2;
  g.append('path')
    .attr('d', `M ${vx + 15},${vy} L ${dx},${dy}`)
    .attr('fill', 'none')
    .attr('stroke', PALETTE.success)
    .attr('stroke-width', 1.3)
    .attr('marker-end', 'url(#arrowGreen)');
  g.append('text')
    .attr('x', (vx + 15 + dx) / 2 + 12).attr('y', (vy + dy) / 2 - 2)
    .attr('text-anchor', 'middle')
    .attr('font-size', FONT.sizeSmall)
    .attr('fill', PALETTE.success)
    .attr('font-weight', 600)
    .text('PASS');
}

// verify → reject (fail)
{
  const vx = 380, vy = 85 + nh / 2;
  const dx = 330, dy = 170 - nh / 2;
  g.append('path')
    .attr('d', `M ${vx - 15},${vy} L ${dx},${dy}`)
    .attr('fill', 'none')
    .attr('stroke', PALETTE.danger)
    .attr('stroke-width', 1.3)
    .attr('marker-end', 'url(#arrowRed)');
  g.append('text')
    .attr('x', (vx - 15 + dx) / 2 - 12).attr('y', (vy + dy) / 2 - 2)
    .attr('text-anchor', 'middle')
    .attr('font-size', FONT.sizeSmall)
    .attr('fill', PALETTE.danger)
    .attr('font-weight', 600)
    .text('FAIL');
}

console.log(serialize());
