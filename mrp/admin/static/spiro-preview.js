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

  const TAU = Math.PI * 2;

  const intGcd = (x, y) => {
    let a = Math.max(1, Math.round(Math.abs(x)));
    let b = Math.max(1, Math.round(Math.abs(y)));
    while (b) { const t = b; b = a % b; a = t; }
    return a || 1;
  };

  const numberOr = (value, fallback) => {
    if (value === undefined || value === null || value === '') return fallback;
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };

  // SVG path sampling, mirroring mrp/video/geometry.py _path_points: sample
  // uniform arc-length stations (getPointAtLength is arc-length exact, so no
  // oversampling pass is needed), close or ping-pong, center on the sampled
  // bbox center, no y-flip (SVG y-down == canvas == cv2). The pre-phase cycle
  // is cached per `samples|d`; phase rotates the start point per call.
  const pathPointCache = new Map();
  let pathProbe = null;

  const ensurePathProbe = () => {
    if (pathProbe) return pathProbe;
    const svgNS = 'http://www.w3.org/2000/svg';
    const svg = document.createElementNS(svgNS, 'svg');
    svg.setAttribute('aria-hidden', 'true');
    svg.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden;visibility:hidden';
    pathProbe = document.createElementNS(svgNS, 'path');
    svg.appendChild(pathProbe);
    document.body.appendChild(svg);
    return pathProbe;
  };

  window.mrpPathPoints = function (d, samples) {
    const count = Math.max(2, Math.round(samples));
    const key = `${count}|${d}`;
    if (!pathPointCache.has(key)) {
      const probe = ensurePathProbe();
      probe.setAttribute('d', d);
      let total = 0;
      try { total = probe.getTotalLength(); } catch (err) { total = 0; }
      if (!(total > 0)) return null;
      const at = (length) => {
        const point = probe.getPointAtLength(length);
        return [point.x, point.y];
      };
      // Coarse pass for the bbox diagonal backing the closed-endpoint rule.
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      for (let i = 0; i < 64; i += 1) {
        const [x, y] = at((i / 63) * total);
        minX = Math.min(minX, x); maxX = Math.max(maxX, x);
        minY = Math.min(minY, y); maxY = Math.max(maxY, y);
      }
      const diagonal = Math.hypot(maxX - minX, maxY - minY);
      if (!(diagonal > 0)) return null;
      const [sx, sy] = at(0);
      const [ex, ey] = at(total);
      const closed = Math.hypot(ex - sx, ey - sy) < 1e-6 * diagonal;
      let pts;
      if (closed) {
        pts = [];
        for (let i = 0; i < count; i += 1) pts.push(at((i / (count - 1)) * total));
        pts[count - 1] = [pts[0][0], pts[0][1]];
      } else {
        const forward = Math.floor(count / 2) + 1;
        pts = [];
        for (let i = 0; i < forward; i += 1) pts.push(at((i / (forward - 1)) * total));
        for (let i = forward - 2; i >= 0; i -= 1) pts.push([pts[i][0], pts[i][1]]);
      }
      let loX = Infinity, hiX = -Infinity, loY = Infinity, hiY = -Infinity;
      pts.forEach(([x, y]) => {
        loX = Math.min(loX, x); hiX = Math.max(hiX, x);
        loY = Math.min(loY, y); hiY = Math.max(hiY, y);
      });
      const centerX = (loX + hiX) / 2;
      const centerY = (loY + hiY) / 2;
      let extent = 0;
      const centered = pts.map(([x, y]) => {
        const px = x - centerX, py = y - centerY;
        extent = Math.max(extent, Math.hypot(px, py));
        return [px, py];
      });
      pathPointCache.set(key, { pts: centered, extent: extent > 0 ? extent : 1 });
    }
    return pathPointCache.get(key);
  };

  // `extent` is the max point radius, as the renderer normalizes by before
  // placing. Family dispatch and closure formulas mirror
  // mrp/video/geometry.py generate_spiro_points — keep them in sync.
  window.mrpSpiroPoints = function (shape) {
    const family = shape.family || 'spirogram';
    const phase = numberOr(shape.phase, 0);
    const n = Math.max(2, Math.round(Math.min(numberOr(shape.samples, 900), 1200)));
    if (family === 'path') {
      const d = String(shape.path_data || '').trim();
      const base = d ? window.mrpPathPoints(d, n) : null;
      // Empty or unparsable path data degrades to a dot so live previews
      // never throw while the textarea is mid-edit.
      if (!base) return { pts: [[0, 0], [0, 0]], extent: 1 };
      const cycle = base.pts.length - 1;
      const fraction = (((phase % TAU) + TAU) % TAU) / TAU;
      const shift = Math.round(fraction * cycle) % cycle;
      const pts = [];
      for (let i = 0; i < cycle; i += 1) pts.push(base.pts[(shift + i) % cycle]);
      pts.push(base.pts[shift % cycle]);
      return { pts, extent: base.extent };
    }
    if (family === 'harmonograph') {
      // Damped lissajous ping-ponged closed, mirroring _harmonograph_points.
      const fx = numberOr(shape.harm_freq_x, 3.01);
      const fy = numberOr(shape.harm_freq_y, 2);
      const delta = numberOr(shape.harm_delta, Math.PI / 2);
      const damping = numberOr(shape.harm_damping, 0.02);
      const turns = Math.max(1, Math.round(numberOr(shape.harm_turns, 12)));
      const span = turns * TAU;
      const forward = Math.floor(n / 2) + 1;
      const pts = [];
      let extent = 0;
      for (let i = 0; i < forward; i += 1) {
        const theta = (i / (forward - 1)) * span + phase;
        const envelope = Math.exp(-damping * theta);
        const x = Math.sin(fx * theta + delta) * envelope;
        const y = Math.sin(fy * theta) * envelope;
        pts.push([x, y]);
        extent = Math.max(extent, Math.hypot(x, y));
      }
      for (let i = forward - 2; i >= 0; i -= 1) pts.push([pts[i][0], pts[i][1]]);
      return { pts, extent: extent > 0 ? extent : 1 };
    }
    let end, pointAt;
    if (family === 'lissajous') {
      const a = Math.max(1, Math.round(numberOr(shape.liss_freq_x, 3)));
      const b = Math.max(1, Math.round(numberOr(shape.liss_freq_y, 2)));
      const delta = numberOr(shape.liss_delta, Math.PI / 2);
      end = TAU / intGcd(a, b);
      pointAt = (theta) => [Math.sin(a * theta + delta), Math.sin(b * theta)];
    } else if (family === 'rose') {
      let rn = Math.max(1, Math.round(numberOr(shape.rose_n, 5)));
      let rd = Math.max(1, Math.round(numberOr(shape.rose_d, 1)));
      const divisor = intGcd(rn, rd);
      rn /= divisor;
      rd /= divisor;
      end = (rn * rd) % 2 === 1 ? Math.PI * rd : TAU * rd;
      const k = rn / rd;
      pointAt = (theta) => {
        const r = Math.cos(k * theta);
        return [r * Math.cos(theta), r * Math.sin(theta)];
      };
    } else if (family === 'superformula') {
      const m = Math.max(0, Math.round(numberOr(shape.sf_m, 6)));
      const n1 = numberOr(shape.sf_n1, 0.3);
      const n2 = numberOr(shape.sf_n2, 0.3);
      const n3 = numberOr(shape.sf_n3, 0.3);
      end = m % 2 === 0 ? TAU : 2 * TAU;
      pointAt = (theta) => {
        const u = (m * theta) / 4;
        const base = Math.abs(Math.cos(u)) ** n2 + Math.abs(Math.sin(u)) ** n3;
        let r = base ** (-1 / n1);
        if (!Number.isFinite(r)) r = 0;
        r = Math.min(r, 1e9);
        return [r * Math.cos(theta), r * Math.sin(theta)];
      };
    } else {
      const fixed = Number(shape.fixed_radius);
      const moving = Math.max(0.000001, Number(shape.moving_radius));
      const pen = Number(shape.pen_offset);
      end = TAU * (Math.max(1, Math.round(Math.abs(moving))) / intGcd(fixed, moving));
      const outside = shape.rotation === 'outside';
      pointAt = (theta) => {
        if (outside) {
          const rs = fixed + moving, ratio = rs / moving;
          return [
            rs * Math.cos(theta) - pen * Math.cos(ratio * theta),
            rs * Math.sin(theta) - pen * Math.sin(ratio * theta),
          ];
        }
        const rd = fixed - moving, ratio = rd / moving;
        return [
          rd * Math.cos(theta) + pen * Math.cos(ratio * theta),
          rd * Math.sin(theta) - pen * Math.sin(ratio * theta),
        ];
      };
    }
    const pts = [];
    let extent = 0;
    for (let i = 0; i < n; i += 1) {
      const theta = (i / (n - 1)) * end + phase;
      const [x, y] = pointAt(theta);
      pts.push([x, y]);
      extent = Math.max(extent, Math.hypot(x, y));
    }
    if (family !== 'spirogram' && pts.length > 1) {
      // Snap the wrap point exactly closed, matching generate_spiro_points.
      pts[pts.length - 1] = [pts[0][0], pts[0][1]];
    }
    return { pts, extent: extent > 0 ? extent : 1 };
  };

  // Clone a component card out of `template` into `container`, capped at 9
  // components per actor (mirrors ActorConfig's max_length). Component 1 owns
  // the center of a 3x3 anchor grid; each added component lands in its own
  // cell (reading order, skipping the center) so it is visible immediately
  // instead of stacking pixel-perfectly on the defaults of component 1.
  // Returns the new fieldset, or null when the actor is full.
  window.mrpAddActorComponent = function (container, template) {
    const MAX_COMPONENTS = 9;
    // Ordinal -> anchor slot. Index 0 is component 1's center cell (r2c2).
    const SLOTS = [
      [0.5, 0.5],
      [0.25, 0.25], [0.5, 0.25], [0.75, 0.25],
      [0.25, 0.5], [0.75, 0.5],
      [0.25, 0.75], [0.5, 0.75], [0.75, 0.75],
    ];
    const count = container.querySelectorAll('fieldset').length + 1;
    if (count > MAX_COMPONENTS) return null;
    const clone = template.content.cloneNode(true);
    clone.querySelector('input[name="trace_id"]').value = `shape-${count}`;
    const slot = SLOTS[count - 1];
    [['anchor_x', slot[0]], ['anchor_y', slot[1]]].forEach(([name, value]) => {
      const number = clone.querySelector(`input[name="${name}"]`);
      if (!number) return;
      number.value = value;
      const pair = number.closest('.slider-pair');
      const range = pair && pair.querySelector('input[type="range"]');
      if (range) range.value = value;
    });
    container.appendChild(clone);
    window.mrpSyncFamilyFields(container);
    return container.querySelector('fieldset:last-of-type');
  };

  // Show only the selected curve family's controls in a component card.
  window.mrpSyncFamilyFields = function (root) {
    (root || document).querySelectorAll('.actor-component-card').forEach((card) => {
      const select = card.querySelector('select[name="geometry_family"]');
      if (!select) return;
      card.querySelectorAll('.family-field').forEach((field) => {
        field.classList.toggle('family-hidden', field.dataset.family !== select.value);
      });
    });
  };

  document.addEventListener('change', (event) => {
    if (event.target instanceof HTMLSelectElement
        && event.target.name === 'geometry_family') {
      const card = event.target.closest('.actor-component-card');
      if (card) window.mrpSyncFamilyFields(card.parentElement || document);
    }
  });

  window.mrpFieldValue = function (card, name, fallback) {
    const field = card.querySelector(`[name="${name}"]`);
    return field ? field.value : fallback;
  };

  // Drag a component around an identity preview canvas to write its
  // anchor_x/anchor_y sliders. Pointer conventions mirror the Scene Casting
  // storyboard (anchor-center hit-test with max(28px, fitted-radius) reach,
  // pointer capture, -0.5..1.5 clamp, one bubbling `input` on release), but
  // this writes the actor-local identity anchors rather than scene direction.
  // `onpick` (optional) is called with the hit card — or null on an empty
  // canvas press — before any drag starts, so pages can drive selection.
  window.mrpEnableComponentDrag = function (canvas, container, redraw, onpick) {
    if (!canvas || !container) return;
    const MARGIN = 0.08;
    const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
    let drag = null;

    const canvasPoint = (event) => {
      const rect = canvas.getBoundingClientRect();
      return {
        x: (event.clientX - rect.left) * (canvas.width / rect.width),
        y: (event.clientY - rect.top) * (canvas.height / rect.height),
      };
    };
    const pickCard = (pt) => {
      let best = null;
      let bestDist = Infinity;
      container.querySelectorAll('.actor-component-card').forEach((card) => {
        const ax = clamp(Number(window.mrpFieldValue(card, 'anchor_x', 0.5)) || 0.5, 0, 1);
        const ay = clamp(Number(window.mrpFieldValue(card, 'anchor_y', 0.5)) || 0.5, 0, 1);
        const scale = Number(window.mrpFieldValue(card, 'base_scale', 1)) || 1;
        const cx = canvas.width * ax;
        const cy = canvas.height * ay;
        const reach = Math.max(
          28,
          Math.min(canvas.width, canvas.height) * (0.5 - MARGIN) * scale
        );
        const dist = Math.hypot(pt.x - cx, pt.y - cy);
        if (dist < reach && dist < bestDist) { best = card; bestDist = dist; }
      });
      return best;
    };
    const setPair = (el, value) => {
      // Snap to the input's declared step (anchors use 0.001, the admin's
      // three-decimal convention): form validation rejects values finer
      // than the step granularity, silently blocking saves.
      const step = Number(el.step) || 0.001;
      el.value = String(Number((Math.round(value / step) * step).toFixed(4)));
      const pair = el.closest('.slider-pair');
      const range = pair && pair.querySelector('input[type="range"]');
      if (range) range.value = el.value;
    };

    canvas.addEventListener('pointerdown', (event) => {
      const pt = canvasPoint(event);
      const card = pickCard(pt);
      if (onpick) onpick(card || null);
      if (!card) return;
      const xEl = card.querySelector('input[name="anchor_x"]');
      const yEl = card.querySelector('input[name="anchor_y"]');
      if (!xEl || !yEl) return;
      drag = {
        xEl, yEl,
        startX: pt.x, startY: pt.y,
        baseX: Number(xEl.value) || 0.5,
        baseY: Number(yEl.value) || 0.5,
      };
      canvas.setPointerCapture(event.pointerId);
      canvas.classList.add('dragging');
      event.preventDefault();
    });
    canvas.addEventListener('pointermove', (event) => {
      if (!drag) return;
      const pt = canvasPoint(event);
      setPair(drag.xEl, clamp(drag.baseX + (pt.x - drag.startX) / canvas.width, -0.5, 1.5));
      setPair(drag.yEl, clamp(drag.baseY + (pt.y - drag.startY) / canvas.height, -0.5, 1.5));
      redraw();
    });
    const endDrag = (event) => {
      if (!drag) return;
      drag.xEl.dispatchEvent(new Event('input', { bubbles: true }));
      drag = null;
      canvas.classList.remove('dragging');
      if (event) canvas.releasePointerCapture(event.pointerId);
    };
    canvas.addEventListener('pointerup', endDrag);
    canvas.addEventListener('pointercancel', endDrag);
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
        family: window.mrpFieldValue(card, 'geometry_family', 'spirogram') || 'spirogram',
        fixed_radius: Number(window.mrpFieldValue(card, 'fixed_radius', 180)),
        moving_radius: Math.max(0.001, Number(window.mrpFieldValue(card, 'moving_radius', 60))),
        pen_offset: Number(window.mrpFieldValue(card, 'pen_offset', 100)),
        phase: Number(window.mrpFieldValue(card, 'phase', 0)) || 0,
        rotation: window.mrpFieldValue(card, 'geometry_rotation', 'inside') === 'outside' ? 'outside' : 'inside',
        liss_freq_x: window.mrpFieldValue(card, 'liss_freq_x', 3),
        liss_freq_y: window.mrpFieldValue(card, 'liss_freq_y', 2),
        liss_delta: window.mrpFieldValue(card, 'liss_delta', 1.5708),
        rose_n: window.mrpFieldValue(card, 'rose_n', 5),
        rose_d: window.mrpFieldValue(card, 'rose_d', 1),
        sf_m: window.mrpFieldValue(card, 'sf_m', 6),
        sf_n1: window.mrpFieldValue(card, 'sf_n1', 0.3),
        sf_n2: window.mrpFieldValue(card, 'sf_n2', 0.3),
        sf_n3: window.mrpFieldValue(card, 'sf_n3', 0.3),
        path_data: window.mrpFieldValue(card, 'path_data', ''),
        harm_freq_x: window.mrpFieldValue(card, 'harm_freq_x', 3.01),
        harm_freq_y: window.mrpFieldValue(card, 'harm_freq_y', 2),
        harm_delta: window.mrpFieldValue(card, 'harm_delta', 1.5708),
        harm_damping: window.mrpFieldValue(card, 'harm_damping', 0.02),
        harm_turns: window.mrpFieldValue(card, 'harm_turns', 12),
        cycles_per_second: Math.max(0.001, Number(window.mrpFieldValue(card, 'cycles_per_second', 0.08)) || 0.08),
        trail_fraction: Number(window.mrpFieldValue(card, 'trail_fraction', 0.24)),
        ghost_count: Number(window.mrpFieldValue(card, 'ghost_count', 1)),
        ghost_spacing: Number(window.mrpFieldValue(card, 'ghost_spacing', 0.08)),
        samples: Math.min(2400, Math.max(240, Number(window.mrpFieldValue(card, 'samples', 900)))),
        anchor_x: Number(window.mrpFieldValue(card, 'anchor_x', 0.5)),
        anchor_y: Number(window.mrpFieldValue(card, 'anchor_y', 0.5)),
        base_scale: Number(window.mrpFieldValue(card, 'base_scale', 1)),
        selected: card.classList.contains('is-selected'),
        color: window.mrpFieldValue(card, 'color', '#ff5fd2'),
        opacity: Number(window.mrpFieldValue(card, 'opacity', 0.8)),
        line_width: Number(window.mrpFieldValue(card, 'line_width', 2)),
        head_radius: Number(window.mrpFieldValue(card, 'head_radius', 3)),
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
  // `showHead` marks the trace head, spirophonic-prototype style. When
  // `clockSeconds` is given, each shape reveals at its own
  // cycles_per_second (fraction of a loop = clockSeconds * cycles_per_second),
  // mirroring the renderer's per-trace speed so the field is honored here.
  window.mrpDrawShapes = function (canvas, shapes, options) {
    const opts = options || {};
    const margin = typeof opts.margin === 'number' ? opts.margin : 0.08;
    const baseProgress = clamp01(typeof opts.revealProgress === 'number' ? opts.revealProgress : 1);
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
      const cycle = Math.max(1, pts.length - 1);
      const playing = typeof opts.clockSeconds === 'number';
      // Playing: the trace head travels at cycles_per_second (progress is the
      // head's cycle position). Static: a growing reveal 0..baseProgress, the
      // identity/headshot look.
      const progress = playing
        ? ((opts.clockSeconds * numberOr(shape.cycles_per_second, 0.08)) % 1 + 1) % 1
        : baseProgress;
      const color = shape.color || '#ff5fd2';
      const flow = shape.color_flow && shape.color_flow.source ? shape.color_flow : null;
      const baseAlpha = clamp01(shape.opacity === undefined ? 0.8 : Number(shape.opacity));
      context.lineWidth = Math.max(0.5, Number(shape.line_width) || 2);
      context.shadowBlur = 8;

      const flowValues = flow ? window.mrpHueFlowValues(pts, flow.source) : null;
      const flowSwing = flow ? (Number(flow.swing_degrees) || 90) : 0;

      // Stroke an ordered list of curve indices at a given alpha. Solid color,
      // or level-quantized color-flow batching (mirrors the renderer's runs).
      const strokeIndices = (indices, alpha) => {
        if (indices.length < 2) return;
        context.globalAlpha = clamp01(baseAlpha * alpha);
        if (!flow) {
          context.beginPath();
          indices.forEach((idx, k) => {
            const px = originX + pts[idx][0] * fit;
            const py = originY + pts[idx][1] * fit;
            if (k === 0) context.moveTo(px, py); else context.lineTo(px, py);
          });
          context.strokeStyle = color;
          context.shadowColor = color;
          context.stroke();
          return;
        }
        const LEVELS = 24;
        const level = (idx) => Math.min(
          LEVELS - 1,
          Math.floor(Math.min(1, Math.max(0, flowValues[idx])) * LEVELS)
        );
        const levelPaths = new Map();
        for (let k = 1; k < indices.length; k += 1) {
          const key = level(indices[k]);
          if (!levelPaths.has(key)) levelPaths.set(key, new Path2D());
          const path = levelPaths.get(key);
          const a = indices[k - 1];
          const b = indices[k];
          path.moveTo(originX + pts[a][0] * fit, originY + pts[a][1] * fit);
          path.lineTo(originX + pts[b][0] * fit, originY + pts[b][1] * fit);
        }
        levelPaths.forEach((path, key) => {
          const segmentColor = window.mrpShiftHue(
            color, ((key + 0.5) / LEVELS - 0.5) * flowSwing
          );
          context.strokeStyle = segmentColor;
          context.shadowColor = segmentColor;
          context.stroke(path);
        });
      };

      // Integer indices for a cyclic window ending at `endFrac` (cycle
      // position) with length `lenFrac`, mirroring cyclic_trace_window.
      const windowIndices = (endFrac, lenFrac) => {
        const len = clamp01(lenFrac);
        const endI = (((endFrac % 1) + 1) % 1) * cycle;
        const startI = endI - len * cycle;
        const list = [];
        for (let i = Math.floor(startI); i <= Math.ceil(endI); i += 1) {
          list.push(((i % cycle) + cycle) % cycle);
        }
        return list;
      };

      let headIndex = Math.round(progress * cycle) % cycle;
      if (playing) {
        // Rolling trail window at cycles_per_second, with fading ghosts
        // trailing behind it — the renderer's exact trace composition.
        const trail = clamp01(numberOr(shape.trail_fraction, 0.24)) || 0.001;
        const ghostCount = Math.max(0, Math.round(numberOr(shape.ghost_count, 1)));
        const ghostSpacing = numberOr(shape.ghost_spacing, 0.08);
        for (let g = ghostCount; g >= 1; g -= 1) {
          strokeIndices(
            windowIndices(progress - g * (trail + ghostSpacing), trail),
            0.3 / g
          );
        }
        strokeIndices(windowIndices(progress, trail), 1);
      } else {
        const last = Math.max(1, Math.round(progress * cycle));
        const list = [];
        for (let i = 0; i <= last; i += 1) list.push(i);
        strokeIndices(list, 1);
        headIndex = last;
      }

      // Mirror the renderer's head semantics: hidden at 0, else at least 1px.
      const headRadius = numberOr(shape.head_radius, 3);
      if (opts.showHead && headRadius > 0 && (playing || progress < 1)) {
        context.globalAlpha = baseAlpha;
        context.beginPath();
        context.arc(
          originX + pts[headIndex][0] * fit,
          originY + pts[headIndex][1] * fit,
          Math.max(1, Math.round(headRadius)),
          0,
          Math.PI * 2
        );
        context.fillStyle = '#f6f4ef';
        context.fill();
      }
      // Selection halo: a dashed ring at the component's drag reach, so the
      // designer shows which shape a settings card (or canvas pick) owns.
      if (shape.selected) {
        context.save();
        context.globalAlpha = 0.85;
        context.setLineDash([6, 6]);
        context.lineWidth = 1.5;
        context.shadowBlur = 0;
        context.strokeStyle = '#f6f4ef';
        context.beginPath();
        context.arc(
          originX,
          originY,
          Math.max(28, Math.min(canvas.width, canvas.height) * (0.5 - margin) * identityScale),
          0,
          Math.PI * 2
        );
        context.stroke();
        context.restore();
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
    // Real-time clock in seconds: each shape reveals at its own
    // cycles_per_second, so Play traces at the same speed the renderer will.
    let clock = 0;
    let playing = false;
    let frameId = 0;
    let lastTime = 0;

    // Headline progress for the % readout: the cycle position of the fastest
    // shape (the one that laps first), so the indicator still animates when
    // shapes run at different speeds.
    function headlineProgress(shapes) {
      if (playing) {
        let maxCps = 0;
        shapes.forEach((shape) => {
          maxCps = Math.max(maxCps, numberOr(shape.cycles_per_second, 0.08));
        });
        return (clock * maxCps) % 1;
      }
      return 1;
    }

    function draw() {
      const shapes = getShapes();
      window.mrpDrawShapes(canvas, shapes, {
        clockSeconds: playing ? clock : undefined,
        revealProgress: playing ? undefined : 1,
        showHead: playing,
        background: opts.background,
      });
      if (opts.onchange) opts.onchange(headlineProgress(shapes), playing);
    }
    function tick(timestamp) {
      clock += (timestamp - lastTime) / 1000;
      lastTime = timestamp;
      draw();
      frameId = requestAnimationFrame(tick);
    }
    const player = {
      play() {
        if (playing) return;
        playing = true;
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
        clock = 0;
        draw();
      },
      toggle() {
        if (playing) player.pause(); else player.play();
      },
      redraw: draw,
      get playing() { return playing; },
      get progress() { return headlineProgress(getShapes()); },
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
