import { JSDOM } from 'jsdom';
import * as d3 from 'd3';

// Tableau 10 muted palette — colorblind-safe, grayscale-distinguishable
export const PALETTE = {
  entry:    '#4E79A7',
  exit:     '#9C9C9C',
  router:   '#E15759',
  llm:      '#59A14F',
  tool:     '#B07AA1',
  human:    '#F28E2B',
  subgraph: '#76B7B2',
  // Semantic aliases
  primary:   '#4E79A7',
  secondary: '#E15759',
  success:   '#59A14F',
  warning:   '#F28E2B',
  danger:    '#E15759',
  neutral:   '#9C9C9C',
  // Chart
  grid:      '#E0E0E0',
  text:      '#333333',
  textLight: '#666666',
  bg:        '#FFFFFF',
};

export const FONT = {
  family: "'Helvetica Neue', Helvetica, Arial, sans-serif",
  mono: "'SF Mono', 'Menlo', 'Monaco', 'Consolas', monospace",
  sizeTitle: 13,
  sizeLabel: 11,
  sizeTick: 9,
  sizeAnnotation: 8.5,
  sizeSmall: 7.5,
};

/**
 * Create an SVG document in jsdom and return helpers.
 * @param {number} width
 * @param {number} height
 * @returns {{ svg: d3.Selection, document: Document, serialize: () => string }}
 */
export function createSvg(width, height) {
  const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>');
  const document = dom.window.document;
  const body = d3.select(document.body);

  const svg = body.append('svg')
    .attr('xmlns', 'http://www.w3.org/2000/svg')
    .attr('width', width)
    .attr('height', height)
    .attr('viewBox', `0 0 ${width} ${height}`)
    .style('font-family', FONT.family);

  // White background
  svg.append('rect')
    .attr('width', width)
    .attr('height', height)
    .attr('fill', PALETTE.bg);

  function serialize() {
    return body.select('svg').node().outerHTML;
  }

  return { svg, document, serialize, d3 };
}

/**
 * Add a drop-shadow filter to the SVG defs.
 */
export function addDropShadow(svg, id = 'dropShadow') {
  const defs = svg.append('defs');
  const filter = defs.append('filter')
    .attr('id', id)
    .attr('x', '-10%').attr('y', '-10%')
    .attr('width', '130%').attr('height', '130%');
  filter.append('feDropShadow')
    .attr('dx', 0.8).attr('dy', 0.8)
    .attr('stdDeviation', 1.2)
    .attr('flood-color', '#000')
    .attr('flood-opacity', 0.1);
  return id;
}

/**
 * Add arrowhead marker definition.
 */
export function addArrowMarker(svg, id = 'arrow', color = PALETTE.text, size = 6) {
  const defs = svg.select('defs').empty() ? svg.append('defs') : svg.select('defs');
  defs.append('marker')
    .attr('id', id)
    .attr('viewBox', '0 0 10 10')
    .attr('refX', 9)
    .attr('refY', 5)
    .attr('markerWidth', size)
    .attr('markerHeight', size)
    .attr('orient', 'auto-start-reverse')
    .append('path')
    .attr('d', 'M 0 0 L 10 5 L 0 10 z')
    .attr('fill', color);
  return id;
}

/**
 * Draw a rounded rectangle node with label.
 */
export function drawNode(parent, { x, y, w, h, label, sublabel, fill, stroke, rx = 5, filter }) {
  const g = parent.append('g').attr('transform', `translate(${x},${y})`);

  g.append('rect')
    .attr('x', -w / 2).attr('y', -h / 2)
    .attr('width', w).attr('height', h)
    .attr('rx', rx)
    .attr('fill', fill || '#fff')
    .attr('stroke', stroke || PALETTE.text)
    .attr('stroke-width', 1.2)
    .attr('filter', filter ? `url(#${filter})` : null);

  if (label) {
    g.append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', sublabel ? '-0.15em' : '0.35em')
      .attr('font-size', FONT.sizeLabel)
      .attr('fill', PALETTE.text)
      .attr('font-weight', 500)
      .text(label);
  }

  if (sublabel) {
    g.append('text')
      .attr('text-anchor', 'middle')
      .attr('dy', '1.1em')
      .attr('font-size', FONT.sizeTick)
      .attr('fill', PALETTE.textLight)
      .attr('font-family', FONT.mono)
      .text(sublabel);
  }

  return g;
}

/**
 * Draw an arrow path between two points.
 */
export function drawArrow(parent, x1, y1, x2, y2, { markerId = 'arrow', dash, color, label, labelOffset } = {}) {
  parent.append('line')
    .attr('x1', x1).attr('y1', y1)
    .attr('x2', x2).attr('y2', y2)
    .attr('stroke', color || PALETTE.text)
    .attr('stroke-width', 1.3)
    .attr('stroke-dasharray', dash || null)
    .attr('marker-end', `url(#${markerId})`);

  if (label) {
    const mx = (x1 + x2) / 2;
    const my = (y1 + y2) / 2;
    const ox = labelOffset?.x || 0;
    const oy = labelOffset?.y || -6;
    parent.append('text')
      .attr('x', mx + ox).attr('y', my + oy)
      .attr('text-anchor', 'middle')
      .attr('font-size', FONT.sizeAnnotation)
      .attr('fill', PALETTE.textLight)
      .text(label);
  }
}

/**
 * Draw a curved arrow (quadratic bezier) between two points.
 */
export function drawCurvedArrow(parent, x1, y1, x2, y2, cx, cy, { markerId = 'arrow', dash, color, label } = {}) {
  parent.append('path')
    .attr('d', `M ${x1},${y1} Q ${cx},${cy} ${x2},${y2}`)
    .attr('fill', 'none')
    .attr('stroke', color || PALETTE.text)
    .attr('stroke-width', 1.3)
    .attr('stroke-dasharray', dash || null)
    .attr('marker-end', `url(#${markerId})`);

  if (label) {
    // Place label near the control point
    const tx = (x1 + 2 * cx + x2) / 4;
    const ty = (y1 + 2 * cy + y2) / 4;
    parent.append('text')
      .attr('x', tx).attr('y', ty)
      .attr('text-anchor', 'middle')
      .attr('font-size', FONT.sizeAnnotation)
      .attr('fill', PALETTE.textLight)
      .text(label);
  }
}

export { d3 };
