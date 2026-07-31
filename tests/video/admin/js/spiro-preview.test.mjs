import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import test from 'node:test';

const source = readFileSync(
  new URL('../../../../mrp/admin/static/spiro-preview.js', import.meta.url),
  'utf8'
);

function loadPreviewHelpers() {
  const window = {};
  const context = {
    window,
    document: { addEventListener() {} },
    HTMLInputElement: class {},
    Event: class {},
    Path2D: class {},
    cancelAnimationFrame() {},
    requestAnimationFrame() { return 1; },
  };
  runInNewContext(source, context);
  return window;
}

function drawingHarness() {
  const strokes = [];
  const arcs = [];
  const fills = [];
  let path = [];
  const context = {
    beginPath() { path = []; },
    moveTo(x, y) { path.push([x, y]); },
    lineTo(x, y) { path.push([x, y]); },
    closePath() { path.push(['close']); },
    stroke() { strokes.push(path); },
    fill(rule) { fills.push({ path: [...path], rule }); },
    arc(...args) { arcs.push(args); },
    fillRect() {},
    save() {},
    restore() {},
    setLineDash() {},
  };
  return {
    arcs,
    canvas: {
      width: 320,
      height: 180,
      getContext() { return context; },
    },
    fills,
    strokes,
  };
}

function outlineShape(presentation) {
  return {
    family: 'lissajous',
    liss_freq_x: 3,
    liss_freq_y: 2,
    liss_delta: Math.PI / 2,
    samples: 64,
    presentation,
    cycles_per_second: 0.8,
    trail_fraction: 0.2,
    ghost_count: 0,
    head_radius: 4,
    anchor_x: 0.5,
    anchor_y: 0.5,
    base_scale: 1,
    color: '#ffffff',
    opacity: 1,
    line_width: 2,
  };
}

test('Full outline draws the complete curve without trace movement or a head', () => {
  const preview = loadPreviewHelpers();
  const first = drawingHarness();
  const later = drawingHarness();

  preview.mrpDrawShapes(
    first.canvas,
    [outlineShape('full_outline')],
    { clockSeconds: 0, showHead: true }
  );
  preview.mrpDrawShapes(
    later.canvas,
    [outlineShape('full_outline')],
    { clockSeconds: 9, showHead: true }
  );

  assert.equal(first.strokes.length, 1);
  assert.equal(first.strokes[0].length, 64);
  assert.deepEqual(first.strokes, later.strokes);
  assert.deepEqual(first.arcs, []);
  assert.deepEqual(later.arcs, []);

  const animated = drawingHarness();
  preview.mrpDrawShapes(
    animated.canvas,
    [outlineShape('animated_trace')],
    { clockSeconds: 0, showHead: true }
  );
  assert.ok(animated.strokes[0].length < first.strokes[0].length);
  assert.equal(animated.arcs.length, 1);
});

test('Filled shape paints the complete contour without a stroke or trace head', () => {
  const preview = loadPreviewHelpers();
  const first = drawingHarness();
  const later = drawingHarness();

  preview.mrpDrawShapes(
    first.canvas,
    [outlineShape('filled_shape')],
    { clockSeconds: 0, showHead: true }
  );
  preview.mrpDrawShapes(
    later.canvas,
    [outlineShape('filled_shape')],
    { clockSeconds: 9, showHead: true }
  );

  assert.deepEqual(first.strokes, []);
  assert.deepEqual(first.arcs, []);
  assert.equal(first.fills.length, 1);
  assert.equal(first.fills[0].rule, 'evenodd');
  assert.equal(first.fills[0].path.length, 65);
  assert.deepEqual(first.fills, later.fills);
});

test('Filled text submits all SVG contours in one even-odd fill', () => {
  const preview = loadPreviewHelpers();
  const drawing = drawingHarness();
  preview.mrpTextContours = () => [
    [[0, 0], [100, 0], [100, 100], [0, 100], [0, 0]],
    [[30, 30], [70, 30], [70, 70], [30, 70], [30, 30]],
  ];
  const shape = {
    ...outlineShape('filled_shape'),
    family: 'text',
    path_data: 'mock text contours',
  };

  preview.mrpDrawShapes(
    drawing.canvas,
    [shape],
    { clockSeconds: 4, showHead: true }
  );

  assert.equal(drawing.fills.length, 1);
  assert.equal(drawing.fills[0].rule, 'evenodd');
  assert.equal(
    drawing.fills[0].path.filter((point) => point[0] === 'close').length,
    2
  );
  assert.deepEqual(drawing.strokes, []);
});
