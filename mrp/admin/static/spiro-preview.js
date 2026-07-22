// Shared spirogram canvas helpers for the admin.
//
// The trochoid math is renderer-faithful, matching mrp/video/geometry.py
// (gcd cycle length, hypotrochoid inside / epitrochoid outside, phase as a
// starting-angle offset). It backs the Actor Designer, the actor library
// headshot grid, and the Scene Casting storyboard so every preview matches
// the render exactly. Field names read by mrpReadComponentShapes bind to the
// component form in templates/video/_actor_macros.html and to
// _trace_payloads() in mrp/admin/video_casting.py.
(function () {
  'use strict';

  const clamp01 = (value) => Math.min(1, Math.max(0, value));

  // `extent` is the max point radius, as the renderer normalizes by before
  // placing.
  window.mrpSpiroPoints = function (shape) {
    const fixed = Number(shape.fixed_radius);
    const moving = Math.max(0.000001, Number(shape.moving_radius));
    const pen = Number(shape.pen_offset);
    const phase = Number(shape.phase) || 0;
    const fInt = Math.max(1, Math.round(Math.abs(fixed)));
    const mInt = Math.max(1, Math.round(Math.abs(moving)));
    let a = fInt, b = mInt;
    while (b) { const t = b; b = a % b; a = t; }
    const end = Math.PI * 2 * (mInt / (a || 1));
    const n = Math.max(2, Math.round(Math.min(Number(shape.samples) || 900, 1200)));
    const outside = shape.rotation === 'outside';
    const pts = [];
    let extent = 0;
    for (let i = 0; i < n; i += 1) {
      const theta = (i / (n - 1)) * end + phase;
      let x, y;
      if (outside) {
        const rs = fixed + moving, ratio = rs / moving;
        x = rs * Math.cos(theta) - pen * Math.cos(ratio * theta);
        y = rs * Math.sin(theta) - pen * Math.sin(ratio * theta);
      } else {
        const rd = fixed - moving, ratio = rd / moving;
        x = rd * Math.cos(theta) + pen * Math.cos(ratio * theta);
        y = rd * Math.sin(theta) - pen * Math.sin(ratio * theta);
      }
      pts.push([x, y]);
      extent = Math.max(extent, Math.hypot(x, y));
    }
    return { pts, extent: extent > 0 ? extent : 1 };
  };

  window.mrpFieldValue = function (card, name, fallback) {
    const field = card.querySelector(`[name="${name}"]`);
    return field ? field.value : fallback;
  };

  const minMaxNormalized = (values) => {
    const low = Math.min(...values);
    const high = Math.max(...values);
    const span = high - low;
    // Relative guard matching hue_flow_values: numerically-constant sources
    // collapse to the center instead of amplifying float noise.
    if (span <= Math.max(Math.abs(low), Math.abs(high), 1) * 1e-9) {
      return values.map(() => 0.5);
    }
    return values.map((value) => (value - low) / span);
  };

  // Per-point color-flow values in [0, 1], matching mrp/video/geometry.py
  // hue_flow_values (and the archived prototype's pointToHue).
  window.mrpHueFlowValues = function (pts, source) {
    const TAU = Math.PI * 2;
    const n = pts.length;
    if (source === 'angle') {
      return pts.map(([x, y]) => (((Math.atan2(y, x) % TAU) + TAU) % TAU) / TAU);
    }
    if (source === 'radius') {
      return minMaxNormalized(pts.map(([x, y]) => Math.hypot(x, y)));
    }
    if (source === 'velocity') {
      return minMaxNormalized(pts.map((_, index) => {
        const a = pts[Math.max(0, index - 1)];
        const b = pts[Math.min(n - 1, index + 1)];
        return Math.hypot(b[0] - a[0], b[1] - a[1]);
      }));
    }
    return pts.map((_, index) => {
      if (index === 0 || index === n - 1) return 0;
      const [px, py] = pts[index - 1];
      const [cx, cy] = pts[index];
      const [nx, ny] = pts[index + 1];
      const incoming = Math.atan2(cy - py, cx - px);
      const outgoing = Math.atan2(ny - cy, nx - cx);
      const turn = ((((outgoing - incoming + Math.PI) % TAU) + TAU) % TAU) - Math.PI;
      return Math.abs(turn) / Math.PI;
    });
  };

  // Rotate a #rrggbb color's hue by `degrees`, returning a CSS color.
  window.mrpShiftHue = function (hex, degrees) {
    const r = parseInt(hex.slice(1, 3), 16) / 255;
    const g = parseInt(hex.slice(3, 5), 16) / 255;
    const b = parseInt(hex.slice(5, 7), 16) / 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    const l = (max + min) / 2;
    let h = 0, s = 0;
    if (max !== min) {
      const d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
      else if (max === g) h = ((b - r) / d + 2) / 6;
      else h = ((r - g) / d + 4) / 6;
    }
    const hue = ((h * 360 + degrees) % 360 + 360) % 360;
    return `hsl(${hue.toFixed(1)} ${(s * 100).toFixed(1)}% ${(l * 100).toFixed(1)}%)`;
  };

  // Read every .actor-component-card in `container` into draw-ready shapes.
  window.mrpReadComponentShapes = function (container) {
    const shapes = [];
    container.querySelectorAll('.actor-component-card').forEach((card) => {
      shapes.push({
        fixed_radius: Number(window.mrpFieldValue(card, 'fixed_radius', 180)),
        moving_radius: Math.max(0.001, Number(window.mrpFieldValue(card, 'moving_radius', 60))),
        pen_offset: Number(window.mrpFieldValue(card, 'pen_offset', 100)),
        phase: Number(window.mrpFieldValue(card, 'phase', 0)) || 0,
        rotation: window.mrpFieldValue(card, 'geometry_rotation', 'inside') === 'outside' ? 'outside' : 'inside',
        samples: Math.min(2400, Math.max(240, Number(window.mrpFieldValue(card, 'samples', 900)))),
        anchor_x: Number(window.mrpFieldValue(card, 'anchor_x', 0.5)),
        anchor_y: Number(window.mrpFieldValue(card, 'anchor_y', 0.5)),
        base_scale: Number(window.mrpFieldValue(card, 'base_scale', 1)),
        color: window.mrpFieldValue(card, 'color', '#ff5fd2'),
        opacity: Number(window.mrpFieldValue(card, 'opacity', 0.8)),
        line_width: Number(window.mrpFieldValue(card, 'line_width', 2)),
        color_flow: (() => {
          const source = window.mrpFieldValue(card, 'color_flow_source', '');
          if (!source) return null;
          return {
            source,
            swing_degrees: Number(window.mrpFieldValue(card, 'color_flow_swing', 90)) || 90,
          };
        })(),
      });
    });
    return shapes;
  };

  // Draw identity shapes onto a square-ish canvas, matching the renderer's
  // placement: normalize by extent, size by min(w,h) * (0.5 - margin) * scale.
  // `revealProgress` < 1 strokes only the leading fraction of each curve and
  // `showHead` marks the trace head, spirophonic-prototype style.
  window.mrpDrawShapes = function (canvas, shapes, options) {
    const opts = options || {};
    const margin = typeof opts.margin === 'number' ? opts.margin : 0.08;
    const progress = clamp01(typeof opts.revealProgress === 'number' ? opts.revealProgress : 1);
    const context = canvas.getContext('2d');
    context.fillStyle = opts.background || '#101014';
    context.fillRect(0, 0, canvas.width, canvas.height);
    shapes.forEach((shape) => {
      const { pts, extent } = window.mrpSpiroPoints(shape);
      const identityScale = Number(shape.base_scale) || 1;
      const fit = Math.min(canvas.width, canvas.height) * (0.5 - margin) * identityScale / extent;
      const anchorX = shape.anchor_x === undefined ? 0.5 : Number(shape.anchor_x);
      const anchorY = shape.anchor_y === undefined ? 0.5 : Number(shape.anchor_y);
      const originX = canvas.width * clamp01(anchorX);
      const originY = canvas.height * clamp01(anchorY);
      const last = Math.max(1, Math.round(progress * (pts.length - 1)));
      const color = shape.color || '#ff5fd2';
      const flow = shape.color_flow && shape.color_flow.source ? shape.color_flow : null;
      context.globalAlpha = clamp01(shape.opacity === undefined ? 0.8 : Number(shape.opacity));
      context.lineWidth = Math.max(0.5, Number(shape.line_width) || 2);
      context.shadowBlur = 8;
      const traceTo = (start, end) => {
        context.beginPath();
        for (let i = start; i <= end; i += 1) {
          const px = originX + pts[i][0] * fit;
          const py = originY + pts[i][1] * fit;
          if (i === start) context.moveTo(px, py); else context.lineTo(px, py);
        }
      };
      if (!flow) {
        traceTo(0, last);
        context.strokeStyle = color;
        context.shadowColor = color;
        context.stroke();
      } else {
        // Level-quantized runs matching the renderer's color-flow strokes:
        // flow values oscillate once per winding, so each point's value is
        // quantized onto fixed hue levels and constant-level runs are batched
        // into one path per level — per-petal detail, few stroke calls.
        const LEVELS = 24;
        const values = window.mrpHueFlowValues(pts, flow.source);
        const swing = Number(flow.swing_degrees) || 90;
        const level = (i) => Math.min(
          LEVELS - 1,
          Math.floor(Math.min(1, Math.max(0, values[i])) * LEVELS)
        );
        const levelPaths = new Map();
        let runStart = 0;
        const flushRun = (endIndex) => {
          const key = level(runStart);
          if (!levelPaths.has(key)) levelPaths.set(key, new Path2D());
          const path = levelPaths.get(key);
          const from = Math.max(0, runStart - 1);
          const to = Math.min(last, endIndex);
          path.moveTo(originX + pts[from][0] * fit, originY + pts[from][1] * fit);
          for (let i = from + 1; i <= to; i += 1) {
            path.lineTo(originX + pts[i][0] * fit, originY + pts[i][1] * fit);
          }
        };
        for (let i = 1; i <= last; i += 1) {
          if (level(i) !== level(runStart)) {
            flushRun(i);
            runStart = i;
          }
        }
        flushRun(last);
        levelPaths.forEach((path, key) => {
          const segmentColor = window.mrpShiftHue(
            color,
            ((key + 0.5) / LEVELS - 0.5) * swing
          );
          context.strokeStyle = segmentColor;
          context.shadowColor = segmentColor;
          context.stroke(path);
        });
      }
      if (opts.showHead && progress < 1) {
        context.beginPath();
        context.arc(originX + pts[last][0] * fit, originY + pts[last][1] * fit, 5, 0, Math.PI * 2);
        context.fillStyle = '#f6f4ef';
        context.fill();
      }
      context.globalAlpha = 1;
      context.shadowBlur = 0;
    });
  };

  // Static full-reveal render for library headshot cards.
  window.mrpDrawHeadshot = function (canvas, shapes) {
    window.mrpDrawShapes(canvas, shapes);
  };

  // requestAnimationFrame transport for the designer preview: the curve is
  // revealed over `durationSeconds`, looping while playing.
  window.mrpSpiroPlayer = function (canvas, getShapes, options) {
    const opts = options || {};
    const duration = Number(opts.durationSeconds) > 0 ? Number(opts.durationSeconds) : 6;
    let progress = 1;
    let playing = false;
    let frameId = 0;
    let lastTime = 0;

    function draw() {
      window.mrpDrawShapes(canvas, getShapes(), {
        revealProgress: progress,
        showHead: playing,
        background: opts.background,
      });
      if (opts.onchange) opts.onchange(progress, playing);
    }
    function tick(timestamp) {
      const elapsed = (timestamp - lastTime) / 1000;
      lastTime = timestamp;
      progress = (progress + elapsed / duration) % 1;
      draw();
      frameId = requestAnimationFrame(tick);
    }
    const player = {
      play() {
        if (playing) return;
        playing = true;
        if (progress >= 1) progress = 0;
        lastTime = performance.now();
        frameId = requestAnimationFrame(tick);
        draw();
      },
      pause() {
        playing = false;
        cancelAnimationFrame(frameId);
        draw();
      },
      reset() {
        playing = false;
        cancelAnimationFrame(frameId);
        progress = 1;
        draw();
      },
      toggle() {
        if (playing) player.pause(); else player.play();
      },
      redraw: draw,
      get playing() { return playing; },
      get progress() { return progress; },
    };
    draw();
    return player;
  };

  // Keep every .slider-pair's range and number inputs in sync. The number
  // input carries the form name; the range is a nameless live control, so
  // form posts never see duplicate values. Delegated so cloned component
  // cards work with no extra wiring.
  document.addEventListener('input', (event) => {
    const el = event.target;
    if (!(el instanceof HTMLInputElement)) return;
    const pair = el.closest('.slider-pair');
    if (!pair) return;
    if (el.type === 'range') {
      const number = pair.querySelector('input[type="number"]');
      if (number && number.value !== el.value) {
        number.value = el.value;
        number.dispatchEvent(new Event('input', { bubbles: true }));
      }
    } else if (el.type === 'number' && el.value !== '') {
      const range = pair.querySelector('input[type="range"]');
      if (range) range.value = el.value;
    }
  });
})();
