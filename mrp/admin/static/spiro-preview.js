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
      context.beginPath();
      for (let i = 0; i <= last; i += 1) {
        const px = originX + pts[i][0] * fit;
        const py = originY + pts[i][1] * fit;
        if (i === 0) context.moveTo(px, py); else context.lineTo(px, py);
      }
      const color = shape.color || '#ff5fd2';
      context.globalAlpha = clamp01(shape.opacity === undefined ? 0.8 : Number(shape.opacity));
      context.strokeStyle = color;
      context.lineWidth = Math.max(0.5, Number(shape.line_width) || 2);
      context.shadowColor = color;
      context.shadowBlur = 8;
      context.stroke();
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
