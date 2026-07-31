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
    Path2D: class {
      constructor() { this.commands = []; }
      moveTo(x, y) { this.commands.push(['moveTo', x, y]); }
      lineTo(x, y) { this.commands.push(['lineTo', x, y]); }
    },
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
    stroke(value) {
      strokes.push(value && Array.isArray(value.commands) ? value.commands : path);
    },
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

test('3D camera projection matches the canonical Python golden point', () => {
  const preview = loadPreviewHelpers();
  const actual = preview.mrpProjectSpatialPoint(
    [0.3, -0.4, 0.5],
    0.2,
    -0.3,
    0.4,
    0.18
  );
  const expected = [
    0.3761265277862549,
    -0.42500215768814087,
    0.6700183153152466,
  ];

  actual.forEach((value, index) => {
    assert.ok(Math.abs(value - expected[index]) < 1e-7);
  });
});

test('circuit-step orientation holds, advances, and retains prior circuits', () => {
  const preview = loadPreviewHelpers();
  const shape = {
    cycles_per_second: 0.5,
    spatial: {
      mode: 'tilted',
      orientation_mode: 'circuit_step',
      pitch_step_degrees: 0,
      yaw_step_degrees: 15,
      retained_circuits: 2,
      retention_fade: 0.5,
    },
  };

  const before = preview.mrpSpatialOrientationState(shape, 0, 0, 1.999);
  const boundary = preview.mrpSpatialOrientationState(shape, 0, 0, 2);
  const third = preview.mrpSpatialOrientationState(shape, 0, 0, 6.1);

  assert.equal(before.yaw_radians, 0);
  assert.equal(before.retained.length, 0);
  assert.ok(Math.abs(boundary.yaw_radians - 15 * Math.PI / 180) < 1e-12);
  assert.equal(boundary.retained.length, 1);
  assert.equal(third.retained[0].opacity, 0.25);
  assert.equal(third.retained[1].opacity, 0.5);
  assert.ok(Math.abs(third.yaw_radians - 45 * Math.PI / 180) < 1e-12);
  assert.ok(
    Math.abs(third.retained[0].yaw_radians - 15 * Math.PI / 180) < 1e-12
  );
  assert.ok(
    Math.abs(third.retained[1].yaw_radians - 30 * Math.PI / 180) < 1e-12
  );
});

test('standalone preview paints retained circuit outlines behind the live trace', () => {
  const preview = loadPreviewHelpers();
  const currentOnly = drawingHarness();
  const withHistory = drawingHarness();
  const shape = {
    ...outlineShape('full_outline'),
    cycles_per_second: 1,
    spatial: {
      mode: 'tilted',
      orientation_mode: 'circuit_step',
      pitch_degrees: 0,
      yaw_degrees: 0,
      pitch_step_degrees: 0,
      yaw_step_degrees: 30,
      retained_circuits: 2,
      retention_fade: 1,
    },
  };

  preview.mrpDrawShapes(
    currentOnly.canvas,
    [{ ...shape, spatial: { ...shape.spatial, retained_circuits: 0 } }],
    { clockSeconds: 3 }
  );
  preview.mrpDrawShapes(
    withHistory.canvas,
    [shape],
    { clockSeconds: 3 }
  );

  assert.ok(withHistory.strokes.length > currentOnly.strokes.length);
});

test('component form data carries the base roll rate into the preview shape', () => {
  const preview = loadPreviewHelpers();
  const card = {
    classList: { contains() { return false; } },
    querySelector(selector) {
      return selector === '[name="rotation_speed"]' ? { value: '-22.5' } : null;
    },
  };
  const container = { querySelectorAll() { return [card]; } };

  const [shape] = preview.mrpReadComponentShapes(container);

  assert.equal(shape.rotation_degrees_per_second, -22.5);
});

test('component form data carries circuit-step spatial controls', () => {
  const preview = loadPreviewHelpers();
  const values = {
    spatial_mode: 'tilted',
    spatial_orientation_mode: 'circuit_step',
    spatial_pitch_step: '5',
    spatial_yaw_step: '15',
    spatial_retain_circuits: '12',
    spatial_retention_fade: '0.9',
  };
  const card = {
    classList: { contains() { return false; } },
    querySelector(selector) {
      const match = selector.match(/^\[name="([^"]+)"\]$/);
      return match && Object.hasOwn(values, match[1])
        ? { value: values[match[1]] }
        : null;
    },
  };
  const container = { querySelectorAll() { return [card]; } };

  const [shape] = preview.mrpReadComponentShapes(container);

  assert.equal(shape.spatial.orientation_mode, 'circuit_step');
  assert.equal(shape.spatial.pitch_step_degrees, 5);
  assert.equal(shape.spatial.yaw_step_degrees, 15);
  assert.equal(shape.spatial.retained_circuits, 12);
  assert.equal(shape.spatial.retention_fade, 0.9);
});

test('Base roll turns the standalone preview around the viewing axis', () => {
  const preview = loadPreviewHelpers();
  const first = drawingHarness();
  const later = drawingHarness();
  const shape = {
    ...outlineShape('full_outline'),
    rotation_degrees_per_second: 90,
  };

  preview.mrpDrawShapes(first.canvas, [shape], { clockSeconds: 0 });
  preview.mrpDrawShapes(later.canvas, [shape], { clockSeconds: 1 });

  assert.notDeepEqual(first.strokes, later.strokes);
  const [firstX, firstY] = first.strokes[0][0];
  const [laterX, laterY] = later.strokes[0][0];
  assert.ok(Math.abs((laterX - 160) + (firstY - 90)) < 1e-7);
  assert.ok(Math.abs((laterY - 90) - (firstX - 160)) < 1e-7);

  const exactFirst = drawingHarness();
  const exactLater = drawingHarness();
  const exactShape = { ...shape, rotation_radians: 0 };
  preview.mrpDrawShapes(exactFirst.canvas, [exactShape], { clockSeconds: 0 });
  preview.mrpDrawShapes(exactLater.canvas, [exactShape], { clockSeconds: 1 });
  assert.deepEqual(exactFirst.strokes, exactLater.strokes);
});

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
