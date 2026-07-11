#!/usr/bin/env node
/**
 * Figure: DFA State Machine for temporal monitoring.
 * Three states: s₀(ready) → s₁(waiting) → s₂(violate)
 * Illustrates the "a → F b" interleaving constraint.
 */
import { createSvg, addArrowMarker, PALETTE, FONT } from '../lib/d3-paper-utils.mjs';

const W = 420, H = 190;
const { svg, serialize } = createSvg(W, H);

// Defs: arrow markers
addArrowMarker(svg, 'arrow', PALETTE.text, 5);
addArrowMarker(svg, 'arrowRed', PALETTE.danger, 5);

const R = 30; // state radius
const states = [
  { id: 's₀', label: 'ready',   x: 90,  y: 85, fill: PALETTE.success + '26', stroke: PALETTE.success },
  { id: 's₁', label: 'waiting', x: 210, y: 85, fill: PALETTE.warning + '26', stroke: PALETTE.warning },
  { id: 's₂', label: 'violate', x: 330, y: 85, fill: PALETTE.danger + '26',  stroke: PALETTE.danger },
];

const g = svg.append('g');

// Draw states
for (const s of states) {
  // Outer circle
  g.append('circle')
    .attr('cx', s.x).attr('cy', s.y).attr('r', R)
    .attr('fill', s.fill)
    .attr('stroke', s.stroke)
    .attr('stroke-width', 1.8);

  // Double circle for accept state s₀
  if (s.id === 's₀') {
    g.append('circle')
      .attr('cx', s.x).attr('cy', s.y).attr('r', R - 4)
      .attr('fill', 'none')
      .attr('stroke', s.stroke)
      .attr('stroke-width', 0.8);
  }

  // State name
  g.append('text')
    .attr('x', s.x).attr('y', s.y - 5)
    .attr('text-anchor', 'middle')
    .attr('font-size', FONT.sizeLabel + 1)
    .attr('font-weight', 600)
    .attr('fill', PALETTE.text)
    .text(s.id);

  // State description
  g.append('text')
    .attr('x', s.x).attr('y', s.y + 11)
    .attr('text-anchor', 'middle')
    .attr('font-size', FONT.sizeTick)
    .attr('fill', PALETTE.textLight)
    .text(s.label);
}

// --- Transitions ---

// Self-loop s₀ → s₀ (no a or b)
{
  const cx = states[0].x, cy = states[0].y;
  const arcR = 22;
  g.append('path')
    .attr('d', `M ${cx - 14},${cy - R} A ${arcR},${arcR} 0 1,1 ${cx + 14},${cy - R}`)
    .attr('fill', 'none')
    .attr('stroke', PALETTE.text)
    .attr('stroke-width', 1.2)
    .attr('marker-end', 'url(#arrow)');
  g.append('text')
    .attr('x', cx).attr('y', cy - R - arcR - 4)
    .attr('text-anchor', 'middle')
    .attr('font-size', FONT.sizeAnnotation)
    .attr('fill', PALETTE.textLight)
    .text('¬a ∧ ¬b');
}

// s₀ → s₁ (a ∧ ¬b)
{
  const x1 = states[0].x + R, y1 = states[0].y;
  const x2 = states[1].x - R, y2 = states[1].y;
  g.append('line')
    .attr('x1', x1).attr('y1', y1)
    .attr('x2', x2).attr('y2', y2)
    .attr('stroke', PALETTE.text)
    .attr('stroke-width', 1.2)
    .attr('marker-end', 'url(#arrow)');
  g.append('text')
    .attr('x', (x1 + x2) / 2).attr('y', y1 - 8)
    .attr('text-anchor', 'middle')
    .attr('font-size', FONT.sizeAnnotation)
    .attr('fill', PALETTE.text)
    .attr('font-weight', 500)
    .text('a ∧ ¬b');
}

// s₁ → s₀ (b) — curved arrow going below
{
  const x1 = states[1].x - 20, y1 = states[1].y + R;
  const x2 = states[0].x + 20, y2 = states[0].y + R;
  const cx = (x1 + x2) / 2, cy = y1 + 28;
  g.append('path')
    .attr('d', `M ${x1},${y1} Q ${cx},${cy} ${x2},${y2}`)
    .attr('fill', 'none')
    .attr('stroke', PALETTE.success)
    .attr('stroke-width', 1.2)
    .attr('marker-end', 'url(#arrow)');
  g.append('text')
    .attr('x', cx).attr('y', cy + 13)
    .attr('text-anchor', 'middle')
    .attr('font-size', FONT.sizeAnnotation)
    .attr('fill', PALETTE.success)
    .attr('font-weight', 500)
    .text('b');
}

// s₁ → s₂ (a before b)
{
  const x1 = states[1].x + R, y1 = states[1].y;
  const x2 = states[2].x - R, y2 = states[2].y;
  g.append('line')
    .attr('x1', x1).attr('y1', y1)
    .attr('x2', x2).attr('y2', y2)
    .attr('stroke', PALETTE.danger)
    .attr('stroke-width', 1.2)
    .attr('marker-end', 'url(#arrowRed)');
  g.append('text')
    .attr('x', (x1 + x2) / 2).attr('y', y1 - 8)
    .attr('text-anchor', 'middle')
    .attr('font-size', FONT.sizeAnnotation)
    .attr('fill', PALETTE.danger)
    .attr('font-weight', 500)
    .text('a (before b)');
}

// Self-loop s₂ → s₂ (any)
{
  const cx = states[2].x, cy = states[2].y;
  const arcR = 22;
  g.append('path')
    .attr('d', `M ${cx - 14},${cy - R} A ${arcR},${arcR} 0 1,1 ${cx + 14},${cy - R}`)
    .attr('fill', 'none')
    .attr('stroke', PALETTE.danger)
    .attr('stroke-width', 1.2)
    .attr('marker-end', 'url(#arrowRed)');
  g.append('text')
    .attr('x', cx).attr('y', cy - R - arcR - 4)
    .attr('text-anchor', 'middle')
    .attr('font-size', FONT.sizeAnnotation)
    .attr('fill', PALETTE.danger)
    .text('any');
}

// Initial arrow into s₀
{
  const x2 = states[0].x - R;
  g.append('line')
    .attr('x1', 30).attr('y1', states[0].y)
    .attr('x2', x2).attr('y2', states[0].y)
    .attr('stroke', PALETTE.text)
    .attr('stroke-width', 1.2)
    .attr('marker-end', 'url(#arrow)');
}

// Caption below
g.append('text')
  .attr('x', W / 2).attr('y', H - 14)
  .attr('text-anchor', 'middle')
  .attr('font-size', FONT.sizeLabel)
  .attr('fill', PALETTE.text)
  .html('DSL pattern:  ');

g.append('text')
  .attr('x', W / 2).attr('y', H - 14)
  .attr('text-anchor', 'middle')
  .attr('font-size', FONT.sizeLabel)
  .attr('fill', PALETTE.text)
  .attr('font-family', FONT.mono)
  .text('a → F b  (interleaving constraint)');

console.log(serialize());
