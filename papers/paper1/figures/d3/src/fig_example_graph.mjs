#!/usr/bin/env node
/**
 * Figure: Example Extracted Workflow Graph with typed nodes.
 * Based on the email triage workflow (lg_email_triage) which has a dead-end defect.
 */
import { createSvg, addArrowMarker, addDropShadow, PALETTE, FONT } from '../lib/d3-paper-utils.mjs';

const W = 520, H = 240;
const { svg, serialize } = createSvg(W, H);

const shadow = addDropShadow(svg);
addArrowMarker(svg, 'arrow', PALETTE.text, 5);
addArrowMarker(svg, 'arrowDash', PALETTE.textLight, 5);

const g = svg.append('g').attr('transform', 'translate(0, 10)');

// Node definitions for the example graph
const nw = 82, nh = 32, rx = 5;

const kinds = {
  ENTRY:  { fill: PALETTE.entry + '22',  stroke: PALETTE.entry,  shape: 'rect' },
  ROUTER: { fill: PALETTE.router + '22', stroke: PALETTE.router, shape: 'diamond' },
  LLM:    { fill: PALETTE.llm + '22',    stroke: PALETTE.llm,    shape: 'rect' },
  TOOL:   { fill: PALETTE.tool + '22',   stroke: PALETTE.tool,   shape: 'rect' },
  HUMAN:  { fill: PALETTE.human + '22',  stroke: PALETTE.human,  shape: 'rect' },
  EXIT:   { fill: PALETTE.exit + '22',   stroke: PALETTE.exit,   shape: 'rect' },
};

const nodes = [
  { id: '__start__',      kind: 'ENTRY',  x: 50,  y: 100, label: '__start__' },
  { id: 'classify',       kind: 'LLM',    x: 155, y: 100, label: 'classify' },
  { id: 'router',         kind: 'ROUTER', x: 265, y: 100, label: 'router' },
  { id: 'urgent_handler', kind: 'HUMAN',  x: 375, y: 45,  label: 'urgent_handler' },
  { id: 'normal_handler', kind: 'LLM',    x: 375, y: 155, label: 'normal_handler' },
  { id: 'draft_response', kind: 'TOOL',   x: 475, y: 155, label: 'draft_response', deadEnd: true },
  { id: '__end__',        kind: 'EXIT',   x: 475, y: 45,  label: '__end__' },
];

const edges = [
  { from: '__start__',      to: 'classify',       type: 'direct' },
  { from: 'classify',       to: 'router',         type: 'direct' },
  { from: 'router',         to: 'urgent_handler', type: 'conditional', label: 'urgent' },
  { from: 'router',         to: 'normal_handler', type: 'conditional', label: 'normal' },
  { from: 'urgent_handler', to: '__end__',        type: 'direct' },
  { from: 'normal_handler', to: 'draft_response', type: 'direct' },
  // Note: draft_response has NO outgoing edge → dead end!
];

// Draw edges first (behind nodes)
for (const e of edges) {
  const from = nodes.find(n => n.id === e.from);
  const to = nodes.find(n => n.id === e.to);

  const dx = to.x - from.x, dy = to.y - from.y;
  const dist = Math.sqrt(dx * dx + dy * dy);
  const ux = dx / dist, uy = dy / dist;
  const x1 = from.x + ux * (nw / 2 + 2);
  const y1 = from.y + uy * (nh / 2 + 2);
  const x2 = to.x - ux * (nw / 2 + 4);
  const y2 = to.y - uy * (nh / 2 + 4);

  const isDash = e.type === 'conditional';

  g.append('line')
    .attr('x1', x1).attr('y1', y1)
    .attr('x2', x2).attr('y2', y2)
    .attr('stroke', isDash ? PALETTE.textLight : PALETTE.text)
    .attr('stroke-width', 1.2)
    .attr('stroke-dasharray', isDash ? '5,3' : null)
    .attr('marker-end', isDash ? 'url(#arrowDash)' : 'url(#arrow)');

  if (e.label) {
    const mx = (x1 + x2) / 2 + (uy > 0 ? -4 : 4);
    const my = (y1 + y2) / 2 + (dy < 0 ? -6 : -6);
    g.append('text')
      .attr('x', mx).attr('y', my)
      .attr('text-anchor', 'middle')
      .attr('font-size', FONT.sizeSmall)
      .attr('fill', PALETTE.textLight)
      .attr('font-style', 'italic')
      .text(e.label);
  }
}

// Draw nodes
for (const n of nodes) {
  const k = kinds[n.kind];
  const ng = g.append('g').attr('transform', `translate(${n.x},${n.y})`);

  if (n.kind === 'ROUTER') {
    // Diamond shape
    const dw = nw / 2, dh = nh / 2 + 4;
    ng.append('polygon')
      .attr('points', `0,${-dh} ${dw},0 0,${dh} ${-dw},0`)
      .attr('fill', k.fill)
      .attr('stroke', k.stroke)
      .attr('stroke-width', 1.5)
      .attr('filter', `url(#${shadow})`);
  } else {
    ng.append('rect')
      .attr('x', -nw / 2).attr('y', -nh / 2)
      .attr('width', nw).attr('height', nh)
      .attr('rx', n.kind === 'ENTRY' || n.kind === 'EXIT' ? nh / 2 : rx)
      .attr('fill', k.fill)
      .attr('stroke', n.deadEnd ? PALETTE.danger : k.stroke)
      .attr('stroke-width', n.deadEnd ? 2 : 1.3)
      .attr('stroke-dasharray', n.deadEnd ? '4,2' : null)
      .attr('filter', `url(#${shadow})`);
  }

  // Kind label (small, above)
  ng.append('text')
    .attr('text-anchor', 'middle')
    .attr('dy', '-0.2em')
    .attr('font-size', FONT.sizeSmall)
    .attr('fill', k.stroke)
    .attr('font-weight', 700)
    .attr('letter-spacing', '0.5px')
    .text(n.kind);

  // Node name
  ng.append('text')
    .attr('text-anchor', 'middle')
    .attr('dy', '1em')
    .attr('font-size', FONT.sizeSmall)
    .attr('fill', PALETTE.text)
    .attr('font-family', FONT.mono)
    .text(n.label.length > 12 ? n.label.slice(0, 11) + '…' : n.label);
}

// Dead-end annotation
{
  const de = nodes.find(n => n.deadEnd);
  g.append('text')
    .attr('x', de.x).attr('y', de.y + nh / 2 + 14)
    .attr('text-anchor', 'middle')
    .attr('font-size', FONT.sizeAnnotation)
    .attr('fill', PALETTE.danger)
    .attr('font-weight', 600)
    .text('⚠ dead end');
}

// Legend
const leg = g.append('g').attr('transform', `translate(14, ${H - 42})`);
const legendItems = [
  { kind: 'ENTRY', label: 'Entry' },
  { kind: 'LLM', label: 'LLM' },
  { kind: 'ROUTER', label: 'Router' },
  { kind: 'TOOL', label: 'Tool' },
  { kind: 'HUMAN', label: 'Human' },
  { kind: 'EXIT', label: 'Exit' },
];

legendItems.forEach((item, i) => {
  const lx = i * 78;
  const k = kinds[item.kind];
  leg.append('rect')
    .attr('x', lx).attr('y', -5)
    .attr('width', 10).attr('height', 10)
    .attr('rx', 2)
    .attr('fill', k.fill)
    .attr('stroke', k.stroke)
    .attr('stroke-width', 0.8);
  leg.append('text')
    .attr('x', lx + 14).attr('y', 4)
    .attr('font-size', FONT.sizeSmall)
    .attr('fill', PALETTE.text)
    .text(item.label);
});

console.log(serialize());
