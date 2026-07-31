// Shared absolute-time browser engine for music-video Live Preview.
//
// The engine owns only transport and canvas timing. Scene Casting supplies
// live unsaved shapes; later Full-track Preview will supply saved compositions
// and sampled canonical state. All drawing times are absolute master seconds.
(function (root, factory) {
  'use strict';

  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) {
    root.mrpLivePreview = api;
    if (root.document) {
      const initialize = () => {
        api.initScenePreview(root.document);
        api.initFullTrackPreview(root.document);
      };
      if (root.document.readyState === 'loading') {
        root.document.addEventListener('DOMContentLoaded', initialize, { once: true });
      } else {
        initialize();
      }
    }
  }
})(typeof window === 'undefined' ? null : window, function (root) {
  'use strict';

  const finite = (value) => {
    if (value === undefined || value === null || value === '') return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  };

  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const clamp01 = (value) => clamp(value, 0, 1);
  const TAU = Math.PI * 2;
  // Keep identical to STATE_SCHEMA in mrp/admin/video_live_preview.py; the
  // decoder compares the two exactly and refuses a mismatched document.
  const STATE_SCHEMA = [
    'section_index',
    'previous_section_index',
    'master_energy',
    'master_accent',
    'drums_energy',
    'drums_accent',
    'bass_energy',
    'bass_accent',
    'vocals_energy',
    'vocals_accent',
    'instruments_energy',
    'instruments_accent',
    'spectral_centroid',
    'transition_progress',
    'layer_fraction',
    'scale',
    'motion',
    'color_intensity',
    'onset_response',
    'palette_shift',
    'lyrics_opacity',
    'spatial_spread',
    'anchor_drift',
    'trail_length',
    'beat_gain',
    'intensity_gain',
    'trace_time',
    'rotation_time',
  ];

  function normalizeRange(range, durationSeconds) {
    const duration = finite(durationSeconds);
    const startValue = range ? finite(range.start) : null;
    const endValue = range ? finite(range.end) : null;
    const start = Math.max(0, startValue === null ? 0 : startValue);
    const end = endValue === null ? duration : endValue;
    // Guard both ends explicitly: a NaN slips straight through `end <= start`,
    // and a silently NaN range corrupts every later clamp and seek.
    if (
      end === null
      || !Number.isFinite(start)
      || !Number.isFinite(end)
      || end <= start
    ) {
      throw new Error('Live Preview needs a range whose end is after its start.');
    }
    return { start, end };
  }

  function stateSampleWindow(documentModel, masterTimeSeconds) {
    const rate = finite(documentModel && documentModel.state_rate_hz);
    const count = Math.max(
      0,
      Math.round(finite(documentModel && documentModel.state_sample_count) || 0)
    );
    if (rate === null || rate <= 0 || count <= 0) return null;
    const duration = finite(documentModel && documentModel.duration_seconds);
    const requested = Math.max(0, finite(masterTimeSeconds) || 0);
    const time = duration === null ? requested : Math.min(requested, duration);
    const position = Math.min(count - 1, time * rate);
    const lowerIndex = Math.floor(position);
    const upperIndex = Math.min(count - 1, lowerIndex + 1);
    return {
      lowerIndex,
      upperIndex,
      fraction: upperIndex === lowerIndex ? 0 : position - lowerIndex,
    };
  }

  function decodeBase64(value) {
    if (root && typeof root.atob === 'function') {
      const binary = root.atob(value);
      const bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1) {
        bytes[index] = binary.charCodeAt(index);
      }
      return bytes;
    }
    if (typeof Buffer !== 'undefined') {
      return new Uint8Array(Buffer.from(value, 'base64'));
    }
    throw new Error('Live Preview cannot decode base64 state in this browser.');
  }

  function validatePreviewDocument(documentModel) {
    if (
      !documentModel
      || documentModel.format !== 'mrp-music-video-live-preview'
      || documentModel.version !== 1
    ) {
      throw new Error('Live Preview document does not match version 1.');
    }
    if (!['audio-reactive', 'geometry-only'].includes(documentModel.mode)) {
      throw new Error('Live Preview mode is invalid.');
    }
    const duration = finite(documentModel.duration_seconds);
    if (duration === null || duration <= 0) {
      throw new Error('Live Preview duration is unavailable.');
    }
    if (
      !documentModel.video
      || !documentModel.text
      || !Array.isArray(documentModel.sections)
      || !documentModel.sections.length
      || !documentModel.compositions
      || typeof documentModel.compositions !== 'object'
      || !Array.isArray(documentModel.lyrics)
    ) {
      throw new Error('Live Preview timeline data is incomplete.');
    }
    documentModel.sections.forEach((section) => {
      const start = finite(section.start);
      const end = finite(section.end);
      if (
        !section.id
        || start === null
        || end === null
        || end <= start
        || !section.composition_key
        || !documentModel.compositions[section.composition_key]
      ) {
        throw new Error('Live Preview contains an invalid timed scene.');
      }
    });
    documentModel.lyrics.forEach((line) => {
      const start = finite(line.start);
      const end = finite(line.end);
      if (
        typeof line.text !== 'string'
        || start === null
        || end === null
        || end <= start
      ) {
        throw new Error('Live Preview contains an invalid lyric cue.');
      }
    });
    return documentModel;
  }

  function decodePreviewState(documentModel) {
    validatePreviewDocument(documentModel);
    if (!documentModel || documentModel.mode !== 'audio-reactive') return null;
    if (
      documentModel.format !== 'mrp-music-video-live-preview'
      || documentModel.version !== 1
      || documentModel.state_encoding !== 'base64-float32-le'
      || documentModel.state_width !== STATE_SCHEMA.length
      || !Array.isArray(documentModel.state_schema)
      || documentModel.state_schema.join('\n') !== STATE_SCHEMA.join('\n')
    ) {
      throw new Error('Live Preview state contract does not match version 1.');
    }
    const count = Math.round(finite(documentModel.state_sample_count) || 0);
    if (count <= 0 || typeof documentModel.state_samples_base64 !== 'string') {
      throw new Error('Live Preview state samples are missing.');
    }
    const bytes = decodeBase64(documentModel.state_samples_base64);
    const expectedBytes = count * STATE_SCHEMA.length * 4;
    if (bytes.byteLength !== expectedBytes) {
      throw new Error('Live Preview state byte length does not match its dimensions.');
    }
    const probe = new Uint16Array([0x0102]);
    const littleEndian = new Uint8Array(probe.buffer)[0] === 0x02;
    let values;
    if (littleEndian && bytes.byteOffset % 4 === 0) {
      values = new Float32Array(bytes.buffer, bytes.byteOffset, expectedBytes / 4);
    } else {
      values = new Float32Array(expectedBytes / 4);
      const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
      for (let index = 0; index < values.length; index += 1) {
        values[index] = view.getFloat32(index * 4, true);
      }
    }
    return {
      count,
      duration: finite(documentModel.duration_seconds) || 0,
      rate: finite(documentModel.state_rate_hz) || 0,
      schema: STATE_SCHEMA,
      values,
      width: STATE_SCHEMA.length,
    };
  }

  function samplePreviewState(decoded, masterTimeSeconds) {
    if (!decoded || decoded.rate <= 0 || decoded.count <= 0) return null;
    const requested = Math.max(0, finite(masterTimeSeconds) || 0);
    const time = Math.min(requested, decoded.duration);
    const position = Math.min(decoded.count - 1, time * decoded.rate);
    const lowerIndex = Math.floor(position);
    const upperIndex = Math.min(decoded.count - 1, lowerIndex + 1);
    const fraction = upperIndex === lowerIndex ? 0 : position - lowerIndex;
    const lowerOffset = lowerIndex * decoded.width;
    const upperOffset = upperIndex * decoded.width;
    const state = {};
    decoded.schema.forEach((name, column) => {
      const lower = decoded.values[lowerOffset + column];
      state[name] = column < 2
        ? lower
        : lower + (decoded.values[upperOffset + column] - lower) * fraction;
    });
    return state;
  }

  function flattenLayer(layer) {
    if (!layer) return {};
    return {
      ...(layer.geometry || {}),
      ...(layer.trace || {}),
      ...layer,
      geometry: undefined,
      trace: undefined,
    };
  }

  function semanticSample(state, role) {
    return {
      energy: finite(state && state[`${role}_energy`]) || 0,
      accent: finite(state && state[`${role}_accent`]) || 0,
    };
  }

  function driverValue(layer, state, driverName, fallbackRole, fallbackFeature) {
    const configured = layer.drivers && layer.drivers[driverName];
    const parts = configured ? String(configured).split('.', 2) : [];
    const role = parts.length === 2 ? parts[0] : fallbackRole;
    const feature = parts.length === 2 ? parts[1] : fallbackFeature;
    return {
      role,
      value: semanticSample(state, role)[feature] || 0,
    };
  }

  const ROLE_SCALE_RESPONSE = {
    master: 0.1,
    drums: 0.06,
    bass: 0.2,
    vocals: 0.1,
    instruments: 0.13,
  };
  const ROLE_VISIBILITY_THRESHOLD = {
    vocals: 0.2,
    instruments: 0.38,
    master: 0.48,
    bass: 0.62,
    drums: 0.82,
  };

  function mapLayerState(layerValue, state, timeSeconds, presetValue, visibilityOverride) {
    const layer = flattenLayer(layerValue);
    const preset = presetValue || {};
    const roleGains = preset.role_gains || {};
    const gain = (role) => finite(roleGains[role]) || 1;
    const role = semanticSample(state, layer.role);
    const scaleDriver = driverValue(layer, state, 'scale', layer.role, 'energy');
    const scaleGain = gain(scaleDriver.role);
    const scale = (
      (finite(layer.base_scale) || 1)
      * (finite(state.scale) || 0)
      * (
        1
        + ROLE_SCALE_RESPONSE[scaleDriver.role]
        * (finite(preset.scale_response) || 0)
        * scaleDriver.value
        * scaleGain
      )
    );

    let visibility;
    if (visibilityOverride !== undefined && visibilityOverride !== null) {
      visibility = clamp01(visibilityOverride);
    } else {
      const threshold = (
        ROLE_VISIBILITY_THRESHOLD[layer.role]
        - (finite(preset.visibility_bias) || 0)
      );
      const layerVisibility = clamp01(
        ((finite(state.layer_fraction) || 0) - threshold) / 0.18
      );
      // Parity fallback for map_layer_state's role_visibility branch. Sampled
      // documents omit these columns, so this resolves to the plain
      // layer_fraction path; every Live Preview caller passes an override.
      const roleVisibility = finite(state[`visibility_${layer.role}`]);
      visibility = roleVisibility === null
        ? layerVisibility
        : roleVisibility * layerVisibility;
    }

    const opacityDriver = driverValue(layer, state, 'opacity', layer.role, 'energy');
    const opacityGain = gain(opacityDriver.role);
    const pulseDriver = driverValue(layer, state, 'pulse', layer.role, 'accent');
    const pulseGain = gain(pulseDriver.role);
    const energyOpacity = 0.58 + 0.42 * Math.max(
      opacityDriver.value * (layer.drivers && layer.drivers.opacity ? opacityGain : 1),
      pulseDriver.value * (
        layer.drivers && layer.drivers.pulse ? pulseGain : 1
      ) * 0.75
    );
    let opacity = (
      (finite(layer.opacity) || 0)
      * visibility
      * energyOpacity
      * (finite(preset.opacity_response) || 0)
    );
    if (!(layer.drivers && layer.drivers.opacity) && layer.depth === 'background') {
      opacity *= 0.35 + 1.1 * clamp01(
        semanticSample(state, 'master').energy * (finite(state.intensity_gain) || 0)
      );
    }

    const accent = layer.drivers && layer.drivers.pulse
      ? pulseDriver.value
      : Math.max(role.accent, semanticSample(state, 'drums').accent * 0.35);
    const lineWidth = (finite(layer.line_width) || 0) * (
      1
      + (finite(state.onset_response) || 0)
      * (finite(preset.onset_response) || 0)
      * accent
      * pulseGain
      * 1.4
    );
    let rotation = (
      (finite(layer.rotation_degrees_per_second) || 0)
      * Math.PI
      / 180
      * (finite(state.rotation_time) || 0)
      * (finite(preset.motion_response) || 0)
      * scaleGain
    );
    rotation += (
      Math.sin(timeSeconds * 0.37 + scaleDriver.value * Math.PI)
      * (finite(layer.rotation_wobble_degrees) || 0)
      * Math.PI
      / 180
    );

    const trailFraction = (
      (finite(layer.trail_fraction) || 0)
      * (0.82 + 0.18 * (finite(state.motion) || 0))
      * (0.9 + 0.1 * scaleDriver.value * scaleGain)
      * (finite(state.trail_length) || 0)
    );

    let colorEnergy;
    let intensityEnergy;
    let colorGain;
    if (!(layer.drivers && layer.drivers.color)) {
      colorEnergy = semanticSample(state, 'vocals').energy;
      intensityEnergy = layer.depth === 'background'
        ? semanticSample(state, 'master').energy
        : role.energy;
      colorGain = gain(layer.role);
    } else {
      const colorDriver = driverValue(layer, state, 'color', 'vocals', 'energy');
      colorEnergy = colorDriver.value;
      intensityEnergy = colorEnergy;
      colorGain = gain(colorDriver.role);
    }
    const hueShift = (
      (finite(layer.hue_shift_degrees) || 0)
      + (finite(state.palette_shift) || 0) * 360
      + colorEnergy * 18 * (finite(preset.hue_response) || 0)
      + (finite(state.spectral_centroid) || 0)
      * 12
      * (finite(preset.hue_response) || 0)
    );
    let beatPulse = 0;
    if ((layer.drivers && layer.drivers.pulse) || layer.role === 'drums') {
      beatPulse = clamp01(
        pulseDriver.value ** 1.35
        * (finite(state.onset_response) || 0)
        * (finite(preset.onset_response) || 0)
        * (finite(state.beat_gain) || 0)
      );
      opacity *= 1 + beatPulse * 0.35;
    }
    const energyColorResponse = (
      0.55
      + 0.75
      * clamp01(intensityEnergy * (finite(state.intensity_gain) || 0))
      * colorGain
    );
    return {
      beat_pulse: beatPulse,
      color_intensity: clamp(
        (finite(state.color_intensity) || 0) * energyColorResponse,
        0.2,
        1.4
      ),
      hue_shift_degrees: hueShift,
      line_width: Math.max(0.25, lineWidth),
      opacity: clamp01(opacity),
      rotation_radians: rotation,
      scale,
      trail_fraction: clamp(trailFraction, 0.02, 1),
    };
  }

  function parseHex(value) {
    const text = String(value || '#000000');
    return [1, 3, 5].map((index) => parseInt(text.slice(index, index + 2), 16) / 255);
  }

  function rgbToHsv([red, green, blue]) {
    const maximum = Math.max(red, green, blue);
    const minimum = Math.min(red, green, blue);
    const span = maximum - minimum;
    let hue = 0;
    if (span > 0) {
      if (maximum === red) hue = ((green - blue) / span) % 6;
      else if (maximum === green) hue = (blue - red) / span + 2;
      else hue = (red - green) / span + 4;
      hue /= 6;
      if (hue < 0) hue += 1;
    }
    return [hue, maximum === 0 ? 0 : span / maximum, maximum];
  }

  function hsvToRgb([hue, saturation, value]) {
    const sector = ((hue % 1) + 1) % 1 * 6;
    const index = Math.floor(sector);
    const fraction = sector - index;
    const p = value * (1 - saturation);
    const q = value * (1 - fraction * saturation);
    const t = value * (1 - (1 - fraction) * saturation);
    return [
      [value, t, p],
      [q, value, p],
      [p, value, t],
      [p, q, value],
      [t, p, value],
      [value, p, q],
    ][index % 6];
  }

  function layerColor(baseColor, hueShiftDegrees, intensity, flash) {
    const hsv = rgbToHsv(parseHex(baseColor));
    hsv[0] = (hsv[0] + hueShiftDegrees / 360) % 1;
    hsv[1] = Math.min(1, hsv[1] * intensity);
    hsv[2] = Math.min(1, hsv[2] * (0.78 + 0.22 * intensity));
    const flashMix = Math.min(0.72, Math.max(0, flash) ** 1.4 * 0.72);
    const rgb = hsvToRgb(hsv).map(
      (component) => component * (1 - flashMix) + flashMix
    );
    return `#${rgb.map(
      (component) => Math.round(component * 255).toString(16).padStart(2, '0')
    ).join('')}`;
  }

  function baseLayerColor(documentModel, layer, layerIndex) {
    if (layer.color_locked) return layer.color;
    if (documentModel.custom_palette && documentModel.custom_palette.length) {
      return documentModel.custom_palette[layerIndex % documentModel.custom_palette.length];
    }
    const colors = documentModel.palette_preset && documentModel.palette_preset.colors;
    return (colors && colors[layer.role]) || layer.color;
  }

  function mappedLayerShape(
    layerValue,
    state,
    documentModel,
    timeSeconds,
    layerIndex,
    visibilityOverride
  ) {
    const layer = flattenLayer(layerValue);
    const mapped = mapLayerState(
      layer,
      state,
      timeSeconds,
      documentModel.mapping_preset,
      visibilityOverride
    );
    const phase = (finite(layer.phase_fraction) || 0) * TAU;
    const depthResponse = layer.depth === 'background' ? 0.45 : 1;
    const anchorX = (
      0.5
      + ((finite(layer.anchor_x) || 0) - 0.5) * (finite(state.spatial_spread) || 0)
      + Math.sin(timeSeconds * 0.11 + phase)
      * (finite(state.anchor_drift) || 0)
      * depthResponse
    );
    const anchorY = (
      (finite(layer.anchor_y) || 0)
      + Math.cos(timeSeconds * 0.09 + phase)
      * (finite(state.anchor_drift) || 0)
      * 0.7
      * depthResponse
    );
    return {
      ...layer,
      anchor_x: anchorX,
      anchor_y: anchorY,
      base_scale: mapped.scale,
      beat_pulse: mapped.beat_pulse,
      color: layerColor(
        baseLayerColor(documentModel, layer, layerIndex),
        mapped.hue_shift_degrees,
        mapped.color_intensity,
        mapped.beat_pulse
      ),
      line_width: mapped.line_width,
      opacity: mapped.opacity,
      rotation_radians: mapped.rotation_radians,
      trace_time: finite(state.trace_time) || 0,
      trail_fraction: mapped.trail_fraction,
    };
  }

  function backgroundColor(documentModel, state) {
    const background = (
      documentModel.video && documentModel.video.background
    ) || '#101014';
    if (!state) return background;
    const response = (
      (finite(documentModel.video && documentModel.video.background_response) || 0)
      * (finite(
        documentModel.mapping_preset
        && documentModel.mapping_preset.background_response
      ) || 0)
      * semanticSample(state, 'master').energy
    );
    const values = parseHex(background).map(
      (component) => Math.round((component * 255) + (255 - component * 255) * response)
    );
    return `#${values.map(
      (component) => clamp(component, 0, 255).toString(16).padStart(2, '0')
    ).join('')}`;
  }

  function sectionIndexAtTime(documentModel, masterTimeSeconds) {
    const sections = (
      documentModel && Array.isArray(documentModel.sections)
        ? documentModel.sections
        : []
    );
    if (!sections.length) return -1;
    const time = Math.max(0, finite(masterTimeSeconds) || 0);
    let index = 0;
    for (let candidate = 0; candidate < sections.length; candidate += 1) {
      const section = sections[candidate];
      if (time >= (finite(section.start) || 0)) index = candidate;
      if (
        time >= (finite(section.start) || 0)
        && time < (finite(section.end) || 0)
      ) {
        return candidate;
      }
      if (time < (finite(section.start) || 0)) break;
    }
    return index;
  }

  function previewSectionsAt(
    documentModel,
    state,
    masterTimeSeconds
  ) {
    const sections = (
      documentModel && Array.isArray(documentModel.sections)
        ? documentModel.sections
        : []
    );
    if (!sections.length) {
      return {
        current: null,
        currentIndex: -1,
        previous: null,
        previousIndex: -1,
        transitionProgress: 1,
      };
    }
    const sampledIndex = finite(state && state.section_index);
    const currentIndex = clamp(
      sampledIndex === null
        ? sectionIndexAtTime(documentModel, masterTimeSeconds)
        : Math.round(sampledIndex),
      0,
      sections.length - 1
    );
    const sampledPrevious = finite(state && state.previous_section_index);
    const previousIndex = sampledPrevious === null
      ? -1
      : Math.round(sampledPrevious);
    return {
      current: sections[currentIndex] || null,
      currentIndex,
      previous: previousIndex >= 0 ? sections[previousIndex] || null : null,
      previousIndex,
      transitionProgress: state
        ? clamp01(finite(state.transition_progress) || 0)
        : 1,
    };
  }

  function geometryLayerShape(documentModel, layerValue, masterTimeSeconds, layerIndex) {
    const layer = flattenLayer(layerValue);
    return {
      ...layer,
      color: baseLayerColor(documentModel, layer, layerIndex),
      rotation_radians: (
        (finite(layer.rotation_degrees_per_second) || 0)
        * Math.PI
        / 180
        * masterTimeSeconds
      ),
      trace_time: masterTimeSeconds,
    };
  }

  function savedPreviewShapes(documentModel, state, masterTimeSeconds) {
    if (!documentModel) return [];
    const sections = previewSectionsAt(documentModel, state, masterTimeSeconds);
    if (!sections.current) return [];
    const compositions = documentModel.compositions || {};
    let weighted = [[sections.current, 1]];
    if (
      state
      && sections.previous
      && sections.previous.composition_key !== sections.current.composition_key
      && sections.transitionProgress < 1
    ) {
      weighted = [
        [sections.previous, 1 - sections.transitionProgress],
        [sections.current, sections.transitionProgress],
      ];
    }
    const depthOrder = { background: 0, foreground: 1 };
    const indexed = [];
    weighted.forEach(([section, weight], compositionIndex) => {
      const composition = compositions[section.composition_key] || {};
      (composition.traces || []).forEach((layer, layerIndex) => {
        if (weight <= 0) return;
        const flattened = flattenLayer(layer);
        const shape = state
          ? mappedLayerShape(
            flattened,
            state,
            documentModel,
            masterTimeSeconds,
            layerIndex,
            weight
          )
          : geometryLayerShape(
            documentModel,
            flattened,
            masterTimeSeconds,
            layerIndex
          );
        indexed.push({
          compositionIndex,
          depth: depthOrder[shape.depth] || 0,
          layerIndex,
          shape,
        });
      });
    });
    indexed.sort((left, right) => (
      left.depth - right.depth
      || left.compositionIndex - right.compositionIndex
      || left.layerIndex - right.layerIndex
    ));
    return indexed.map((item) => item.shape);
  }

  function smoothstep(value) {
    const bounded = clamp01(value);
    return bounded * bounded * (3 - 2 * bounded);
  }

  function lyricCueAt(documentModel, state, masterTimeSeconds) {
    const lyrics = (
      documentModel && Array.isArray(documentModel.lyrics)
        ? documentModel.lyrics
        : []
    );
    const time = Math.max(0, finite(masterTimeSeconds) || 0);
    const line = lyrics.find((candidate) => (
      time >= (finite(candidate.start) || 0)
      && time < (finite(candidate.end) || 0)
    ));
    if (!line) return null;
    const start = finite(line.start) || 0;
    const end = finite(line.end) || start;
    const fade = Math.max(
      0,
      finite(
        documentModel
        && documentModel.video
        && documentModel.video.lyric_fade_seconds
      ) || 0
    );
    let alpha = state
      ? clamp01(finite(state.lyrics_opacity) || 0)
      : 1;
    if (fade > 0) {
      alpha *= smoothstep((time - start) / fade);
      alpha *= smoothstep((end - time) / fade);
    }
    return {
      alpha: clamp01(alpha),
      end,
      start,
      text: String(line.text || ''),
    };
  }

  function drawLyricCue(targetCanvas, documentModel, cue) {
    if (!targetCanvas || !documentModel || !cue || cue.alpha <= 0) return false;
    const context = targetCanvas.getContext('2d');
    const text = documentModel.text || {};
    const video = documentModel.video || {};
    const referenceHeight = Math.max(1, finite(video.height) || targetCanvas.height);
    const fontSize = Math.max(
      1,
      Math.round((finite(text.size) || 60) * targetCanvas.height / referenceHeight)
    );
    const maximumWidth = (
      targetCanvas.width
      * clamp(finite(text.maximum_width_fraction) || 0.82, 0.2, 0.95)
    );
    let y = targetCanvas.height * 0.82;
    if (text.position === 'top') y = targetCanvas.height * 0.11;
    if (text.position === 'center') y = targetCanvas.height * 0.5;
    context.save();
    context.globalCompositeOperation = 'source-over';
    context.globalAlpha = cue.alpha;
    context.font = `600 ${fontSize}px system-ui, sans-serif`;
    context.textAlign = 'center';
    context.textBaseline = 'middle';
    context.lineJoin = 'round';
    context.lineWidth = Math.max(2, Math.round(fontSize / 15));
    context.strokeStyle = 'rgba(0, 0, 0, .82)';
    context.fillStyle = text.active_color || '#ffffff';
    context.strokeText(cue.text, targetCanvas.width / 2, y, maximumWidth);
    context.fillText(cue.text, targetCanvas.width / 2, y, maximumWidth);
    context.restore();
    return true;
  }

  function previewFrameAt(documentModel, decodedState, masterTimeSeconds) {
    const state = samplePreviewState(decodedState, masterTimeSeconds);
    const sections = previewSectionsAt(documentModel, state, masterTimeSeconds);
    return {
      lyric: lyricCueAt(documentModel, state, masterTimeSeconds),
      section: sections.current,
      sections,
      shapes: savedPreviewShapes(documentModel, state, masterTimeSeconds),
      state,
    };
  }

  function previewRevisionKey(documentModel) {
    return JSON.stringify(
      documentModel && documentModel.source_revision
        ? documentModel.source_revision
        : {}
    );
  }

  function previewRevisionChanged(loadedDocument, candidateDocument) {
    return previewRevisionKey(loadedDocument) !== previewRevisionKey(candidateDocument);
  }

  function createEngine(options) {
    const opts = options || {};
    const canvas = opts.canvas;
    const drawShapes = opts.drawShapes || (root && root.mrpDrawShapes);
    const getShapes = opts.getShapes;
    if (!canvas) throw new Error('Live Preview needs a canvas.');
    if (typeof drawShapes !== 'function') {
      throw new Error('Live Preview needs a drawShapes function.');
    }
    if (typeof getShapes !== 'function') {
      throw new Error('Live Preview needs a getShapes function.');
    }

    const requestFrame = opts.requestFrame
      || (root && root.requestAnimationFrame && root.requestAnimationFrame.bind(root));
    const cancelFrame = opts.cancelFrame
      || (root && root.cancelAnimationFrame && root.cancelAnimationFrame.bind(root));
    const now = opts.now
      || (() => (
        root && root.performance && typeof root.performance.now === 'function'
          ? root.performance.now()
          : Date.now()
      ));
    if (typeof requestFrame !== 'function' || typeof cancelFrame !== 'function') {
      throw new Error('Live Preview needs animation-frame scheduling.');
    }

    let documentModel = opts.previewDocument || null;
    let duration = finite(documentModel && documentModel.duration_seconds);
    let range = normalizeRange(opts.range, duration);
    let loop = opts.loop === true;
    let masterTime = clamp(
      finite(opts.initialTime) === null ? range.start : finite(opts.initialTime),
      range.start,
      range.end
    );
    let liveOverrides = null;
    let playing = false;
    let destroyed = false;
    let frameId = 0;
    let lastTick = 0;
    let lastDrawTick = null;
    let audio = null;
    const redrawRates = [30, 20, 15];
    const baseRateIndex = opts.reducedMotion === true ? 2 : 0;
    let redrawRateIndex = baseRateIndex;
    let drawCostAverage = 0;
    let drawCostSamples = 0;
    let drawIntervalAverage = 0;
    let scheduledDrawCount = 0;

    const progress = () => (
      range.end > range.start
        ? clamp((masterTime - range.start) / (range.end - range.start), 0, 1)
        : 0
    );

    function notify(shapes) {
      if (typeof opts.onchange === 'function') {
        opts.onchange(progress(), playing, masterTime, shapes, {
          drawCostMs: drawCostAverage,
          drawIntervalMs: drawIntervalAverage,
          reducedMotion: opts.reducedMotion === true,
          targetFps: redrawRates[redrawRateIndex],
        });
      }
    }

    function renderAt(masterTimeSeconds, overrides) {
      if (destroyed) return masterTime;
      const requested = finite(masterTimeSeconds);
      if (requested !== null) {
        masterTime = clamp(requested, range.start, range.end);
      }
      if (overrides !== undefined) liveOverrides = overrides;
      const shapes = getShapes(masterTime, liveOverrides, documentModel) || [];
      const background = typeof opts.background === 'function'
        ? opts.background(masterTime, liveOverrides, documentModel, shapes)
        : opts.background;
      const canvasMargin = typeof opts.margin === 'function'
        ? opts.margin(masterTime, liveOverrides, documentModel, shapes)
        : opts.margin;
      drawShapes(canvas, shapes, {
        clockSeconds: masterTime,
        showHead: opts.showHead !== false,
        background,
        margin: canvasMargin,
      });
      if (typeof opts.afterDraw === 'function') {
        opts.afterDraw({
          canvas,
          document: documentModel,
          liveOverrides,
          masterTime,
          playing,
          progress: progress(),
          shapes,
        });
      }
      notify(shapes);
      return masterTime;
    }

    function setRedrawRateIndex(nextIndex) {
      const bounded = clamp(
        Math.round(nextIndex),
        baseRateIndex,
        redrawRates.length - 1
      );
      if (bounded === redrawRateIndex) return;
      redrawRateIndex = bounded;
      drawCostAverage = 0;
      drawCostSamples = 0;
      drawIntervalAverage = 0;
      if (typeof opts.onperformance === 'function') {
        opts.onperformance({
          drawCostMs: drawCostAverage,
          drawIntervalMs: drawIntervalAverage,
          reducedMotion: opts.reducedMotion === true,
          targetFps: redrawRates[redrawRateIndex],
        });
      }
    }

    function recordDrawCost(costMilliseconds, intervalMilliseconds) {
      const cost = Math.max(0, finite(costMilliseconds) || 0);
      const observedInterval = Math.max(
        0,
        finite(intervalMilliseconds) || 0
      );
      drawCostAverage = drawCostSamples === 0
        ? cost
        : drawCostAverage * 0.8 + cost * 0.2;
      drawIntervalAverage = drawCostSamples === 0
        ? observedInterval
        : drawIntervalAverage * 0.8 + observedInterval * 0.2;
      drawCostSamples += 1;
      const interval = 1000 / redrawRates[redrawRateIndex];
      if (
        drawCostSamples >= 8
        && (
          drawCostAverage > interval * 0.95
          || drawIntervalAverage > interval * 1.2
        )
        && redrawRateIndex < redrawRates.length - 1
      ) {
        setRedrawRateIndex(redrawRateIndex + 1);
        return;
      }
      if (
        drawCostSamples >= 90
        && redrawRateIndex > baseRateIndex
        && drawCostAverage < (1000 / redrawRates[redrawRateIndex - 1]) * 0.65
      ) {
        setRedrawRateIndex(redrawRateIndex - 1);
      }
    }

    function scheduledRender(tickTime) {
      const interval = 1000 / redrawRates[redrawRateIndex];
      if (
        lastDrawTick !== null
        && tickTime - lastDrawTick < interval - 1
      ) {
        return false;
      }
      const observedInterval = lastDrawTick === null
        ? interval
        : tickTime - lastDrawTick;
      lastDrawTick = tickTime;
      const started = now();
      renderAt(masterTime);
      scheduledDrawCount += 1;
      recordDrawCost(now() - started, observedInterval);
      return true;
    }

    function cancelScheduledFrame() {
      if (!frameId) return;
      cancelFrame(frameId);
      frameId = 0;
    }

    function removeAudioListeners(element) {
      if (!element || typeof element.removeEventListener !== 'function') return;
      element.removeEventListener('seeked', audioSeeked);
      element.removeEventListener('ended', audioEnded);
    }

    function addAudioListeners(element) {
      if (!element || typeof element.addEventListener !== 'function') return;
      element.addEventListener('seeked', audioSeeked);
      element.addEventListener('ended', audioEnded);
    }

    function startAudio() {
      if (!audio || typeof audio.play !== 'function') return;
      let result;
      try {
        result = audio.play();
      } catch (error) {
        if (typeof opts.onaudioerror === 'function') opts.onaudioerror(error);
        return;
      }
      if (result && typeof result.catch === 'function') {
        const activeAudio = audio;
        result.catch((error) => {
          if (destroyed || !playing || audio !== activeAudio) return;
          removeAudioListeners(activeAudio);
          audio = null;
          lastTick = now();
          if (typeof opts.onaudioerror === 'function') opts.onaudioerror(error);
        });
      }
    }

    function syncAudioTime() {
      if (!audio) return;
      try {
        audio.currentTime = masterTime;
      } catch (error) {
        if (typeof opts.onaudioerror === 'function') opts.onaudioerror(error);
      }
    }

    function setAudio(nextAudio, audioOptions) {
      if (destroyed) return null;
      const settings = audioOptions || {};
      if (audio) {
        const current = finite(audio.currentTime);
        if (settings.captureTime !== false && current !== null) {
          masterTime = clamp(current, range.start, range.end);
        }
        removeAudioListeners(audio);
        if (audio !== nextAudio && typeof audio.pause === 'function') audio.pause();
      }
      audio = nextAudio || null;
      const requested = finite(settings.time);
      if (requested !== null) {
        masterTime = clamp(requested, range.start, range.end);
      }
      if (audio) {
        addAudioListeners(audio);
        syncAudioTime();
        if (playing) startAudio();
      }
      lastTick = now();
      renderAt(masterTime);
      return audio;
    }

    function finishAtEnd() {
      playing = false;
      cancelScheduledFrame();
      masterTime = range.end;
      if (audio && typeof audio.pause === 'function') audio.pause();
      renderAt(masterTime);
    }

    function wrapTime(value) {
      const span = range.end - range.start;
      return range.start + ((((value - range.start) % span) + span) % span);
    }

    function tick(timestamp) {
      if (!playing || destroyed) return;
      const tickTime = finite(timestamp) === null ? now() : finite(timestamp);
      let nextTime;
      if (audio) {
        nextTime = finite(audio.currentTime);
        if (nextTime === null) nextTime = masterTime;
      } else {
        nextTime = masterTime + Math.max(0, tickTime - lastTick) / 1000;
      }
      lastTick = tickTime;

      if (nextTime >= range.end) {
        if (!loop) {
          finishAtEnd();
          return;
        }
        masterTime = wrapTime(nextTime);
        syncAudioTime();
        if (audio && audio.paused) startAudio();
      } else {
        masterTime = clamp(nextTime, range.start, range.end);
      }
      scheduledRender(tickTime);
      if (playing) frameId = requestFrame(tick);
    }

    function audioSeeked() {
      if (!audio || destroyed) return;
      const value = finite(audio.currentTime);
      if (value === null) return;
      masterTime = value >= range.end && loop
        ? wrapTime(value)
        : clamp(value, range.start, range.end);
      renderAt(masterTime);
    }

    function audioEnded() {
      if (!playing || destroyed) return;
      if (!loop) {
        finishAtEnd();
        return;
      }
      masterTime = range.start;
      syncAudioTime();
      startAudio();
      renderAt(masterTime);
    }

    function loadPreview(nextDocument, nextRange) {
      if (destroyed) return null;
      documentModel = nextDocument || null;
      duration = finite(documentModel && documentModel.duration_seconds);
      range = normalizeRange(nextRange, duration);
      masterTime = clamp(masterTime, range.start, range.end);
      syncAudioTime();
      renderAt(masterTime);
      return documentModel;
    }

    function setRange(nextRange, shouldLoop) {
      if (destroyed) return { ...range };
      range = normalizeRange(nextRange, duration);
      if (typeof shouldLoop === 'boolean') loop = shouldLoop;
      masterTime = clamp(masterTime, range.start, range.end);
      syncAudioTime();
      renderAt(masterTime);
      return { ...range };
    }

    function play(nextAudio, nextRange) {
      if (destroyed || playing) return false;
      if (nextRange) setRange(nextRange, nextRange.loop);
      if (arguments.length > 0) {
        setAudio(nextAudio, { captureTime: false });
      }
      if (masterTime >= range.end) masterTime = range.start;
      playing = true;
      lastTick = now();
      lastDrawTick = lastTick;
      syncAudioTime();
      startAudio();
      renderAt(masterTime);
      frameId = requestFrame(tick);
      return true;
    }

    function pause() {
      if (destroyed) return masterTime;
      if (audio) {
        const value = finite(audio.currentTime);
        if (value !== null) masterTime = clamp(value, range.start, range.end);
        if (typeof audio.pause === 'function') audio.pause();
      }
      playing = false;
      cancelScheduledFrame();
      renderAt(masterTime);
      return masterTime;
    }

    function seek(masterTimeSeconds) {
      if (destroyed) return masterTime;
      const requested = finite(masterTimeSeconds);
      if (requested !== null) {
        masterTime = clamp(requested, range.start, range.end);
      }
      syncAudioTime();
      renderAt(masterTime);
      return masterTime;
    }

    function reset() {
      if (destroyed) return masterTime;
      playing = false;
      cancelScheduledFrame();
      if (audio && typeof audio.pause === 'function') audio.pause();
      masterTime = range.start;
      syncAudioTime();
      renderAt(masterTime);
      return masterTime;
    }

    function toggle(nextAudio) {
      if (playing) {
        pause();
        return false;
      }
      if (arguments.length > 0) play(nextAudio);
      else play();
      return true;
    }

    function destroy() {
      if (destroyed) return;
      playing = false;
      cancelScheduledFrame();
      if (audio) {
        removeAudioListeners(audio);
        if (typeof audio.pause === 'function') audio.pause();
      }
      audio = null;
      destroyed = true;
      if (typeof opts.ondestroy === 'function') opts.ondestroy();
    }

    return {
      destroy,
      loadPreview,
      pause,
      play,
      redraw: (overrides) => renderAt(masterTime, overrides),
      renderAt,
      reset,
      seek,
      setAudio,
      setRange,
      toggle,
      get audio() { return audio; },
      get currentTime() { return masterTime; },
      get document() { return documentModel; },
      get drawCostMs() { return drawCostAverage; },
      get drawIntervalMs() { return drawIntervalAverage; },
      get playing() { return playing; },
      get progress() { return progress(); },
      get range() { return { ...range }; },
      get redrawFps() { return redrawRates[redrawRateIndex]; },
      get reducedMotion() { return opts.reducedMotion === true; },
      get scheduledDrawCount() { return scheduledDrawCount; },
    };
  }

  function initScenePreview(documentRoot) {
    if (!root || !root.document) return null;
    const doc = documentRoot || root.document;
    const canvas = doc.getElementById('scene-storyboard-canvas');
    const dataEl = doc.getElementById('scene-storyboard-data');
    const emptyEl = doc.getElementById('storyboard-empty');
    if (!canvas || !dataEl || typeof root.mrpDrawShapes !== 'function') return null;
    if (canvas.__mrpLivePreviewController) {
      canvas.__mrpLivePreviewController.destroy();
    }

    let model;
    try {
      model = JSON.parse(dataEl.textContent);
    } catch (error) {
      return null;
    }

    const context = canvas.getContext('2d');
    const width = canvas.width;
    const height = canvas.height;
    const margin = typeof model.margin === 'number' ? model.margin : 0.08;
    const tau = Math.PI * 2;
    const cleanups = [];
    let destroyed = false;
    let previewDocument = null;
    let decodedState = null;
    let currentState = null;
    let hasUnsavedEdits = false;
    // Failure is tracked beside the document rather than as a stub document,
    // so a failed load still draws the scene's own saved background.
    let previewFailure = null;
    const stateElement = doc.getElementById('storyboard-state');
    const previewUrl = canvas.dataset.previewUrl || '';

    function setPreviewStatus(kind, message) {
      if (!stateElement) return;
      stateElement.textContent = message;
      stateElement.className = `badge badge-${kind}`;
      stateElement.dataset.state = kind;
    }

    function refreshPreviewStatus() {
      if (hasUnsavedEdits) {
        setPreviewStatus('draft', 'Unsaved scene edits');
        return;
      }
      if (previewFailure) {
        setPreviewStatus(previewFailure.kind, previewFailure.message);
        return;
      }
      if (!previewDocument) {
        setPreviewStatus('draft', 'Loading audio response…');
        return;
      }
      if (previewDocument.mode === 'audio-reactive' && decodedState) {
        setPreviewStatus('live', 'Current · audio reactive');
        return;
      }
      const reason = previewDocument.mode_reason || {};
      if (reason.code === 'analysis_stale') {
        setPreviewStatus('failed', 'Stale · Run Analyze');
      } else {
        setPreviewStatus('draft', 'Geometry only · Run Analyze');
      }
    }

    const listen = (target, type, listener) => {
      if (!target || typeof target.addEventListener !== 'function') return;
      target.addEventListener(type, listener);
      cleanups.push(() => target.removeEventListener(type, listener));
    };

    const fieldValue = (card, name) => {
      const element = card.querySelector(`[name="${name}"]`);
      return element ? element.value : '';
    };

    const numberOrNull = (value) => {
      const text = String(value).trim();
      if (text === '') return null;
      const parsed = Number(text);
      return Number.isFinite(parsed) ? parsed : null;
    };

    const fallbackPhase = (value) => {
      let hash = 2166136261;
      String(value).split('').forEach((character) => {
        hash ^= character.charCodeAt(0);
        hash = Math.imul(hash, 16777619);
      });
      return (hash >>> 0) / 0xffffffff;
    };

    function selectedSection(documentModel) {
      if (!documentModel || !Array.isArray(documentModel.sections)) return null;
      return documentModel.sections.find((section) => section.id === model.section_id)
        || documentModel.sections.find(
          (section) => section.start <= model.range.start && section.end >= model.range.end
        )
        || null;
    }

    function savedPhaseByTrace() {
      const selected = selectedSection(previewDocument);
      const composition = (
        selected
        && previewDocument
        && previewDocument.compositions
        && previewDocument.compositions[selected.composition_key]
      );
      return new Map(
        ((composition && composition.traces) || []).map(
          (trace) => [
            trace.id,
            {
              phase_fraction: finite(trace.phase_fraction) || 0,
              phase_fractions: trace.phase_fractions || null,
            },
          ]
        )
      );
    }

    function computeShapes() {
      const cards = Array.from(
        doc.querySelectorAll('#actor-assignments fieldset[data-assignment-id]')
      );
      const actors = (
        previewDocument && previewDocument.actors
          ? previewDocument.actors
          : model.actors
      ) || {};
      if (!cards.length || !Object.keys(actors).length) {
        const selected = selectedSection(previewDocument);
        const savedComposition = (
          selected
          && previewDocument
          && previewDocument.compositions
          && previewDocument.compositions[selected.composition_key]
        );
        const traceValues = (
          savedComposition && savedComposition.traces
            ? savedComposition.traces
            : model.traces
        ) || [];
        return traceValues.map((traceValue) => {
          const trace = flattenLayer(traceValue);
          return {
            ...trace,
            assignment: trace.assignment || (
              String(trace.id || '').includes('--')
                ? String(trace.id).split('--', 1)[0]
                : null
            ),
            label: '',
          };
        });
      }

      const shapes = [];
      const phases = savedPhaseByTrace();
      cards.forEach((card) => {
        const actorId = fieldValue(card, 'assigned_actor');
        const actor = actors[actorId];
        if (!actor) return;
        const select = card.querySelector('[name="assigned_actor"]');
        const label = select && select.selectedOptions.length
          ? select.selectedOptions[0].textContent.split('—')[0].trim()
          : actorId;
        const directionX = numberOrNull(fieldValue(card, 'direction_anchor_x'));
        const directionY = numberOrNull(fieldValue(card, 'direction_anchor_y'));
        const scale = numberOrNull(fieldValue(card, 'direction_scale'));
        const opacity = numberOrNull(fieldValue(card, 'direction_opacity'));
        const depth = fieldValue(card, 'direction_depth');
        const visible = fieldValue(card, 'direction_visible') !== 'false';
        const wardrobe = fieldValue(card, 'direction_color');
        const lineWidth = numberOrNull(fieldValue(card, 'direction_line_width'));
        const presentation = fieldValue(card, 'direction_presentation') || 'animated_trace';
        const rotation = numberOrNull(fieldValue(card, 'direction_rotation'));
        const wobble = numberOrNull(fieldValue(card, 'direction_wobble'));
        const hueShift = numberOrNull(fieldValue(card, 'direction_hue'));
        const blendMode = fieldValue(card, 'direction_blend');
        const energy = {};
        [
          ['direction_cycles', 'cycles_per_second'],
          ['direction_trail', 'trail_fraction'],
          ['direction_ghosts', 'ghost_count'],
          ['direction_ghost_spacing', 'ghost_spacing'],
          ['direction_head', 'head_radius'],
        ].forEach(([field, key]) => {
          const value = numberOrNull(fieldValue(card, field));
          if (value !== null) energy[key] = value;
        });

        actor.components.forEach((componentValue) => {
          const component = flattenLayer(componentValue);
          const anchorX = component.anchor_x + (directionX !== null ? directionX - 0.5 : 0);
          const anchorY = component.anchor_y + (directionY !== null ? directionY - 0.5 : 0);
          const traceId = `${card.dataset.assignmentId}--${component.id}`;
          const role = actor.character || component.role;
          const drivers = actor.character
            ? {
              scale: `${role}.energy`,
              opacity: `${role}.energy`,
              color: `${role}.energy`,
              pulse: `${role}.accent`,
            }
            : component.drivers;
          const savedPhase = phases.get(traceId);
          shapes.push({
            ...component,
            ...energy,
            id: traceId,
            assignment: card.dataset.assignmentId,
            label,
            role,
            drivers,
            phase_fraction: savedPhase
              ? savedPhase.phase_fraction
              : fallbackPhase(traceId),
            phase_fractions: savedPhase ? savedPhase.phase_fractions : null,
            anchor_x: clamp(anchorX, -0.5, 1.5),
            anchor_y: clamp(anchorY, -0.5, 1.5),
            base_scale: clamp(
              component.base_scale * (scale !== null ? scale : 1),
              0.000001,
              2
            ),
            opacity: visible ? component.opacity * (opacity !== null ? opacity : 1) : 0,
            color: wardrobe || component.color,
            color_locked: component.color_locked || Boolean(wardrobe),
            line_width: lineWidth !== null ? lineWidth : component.line_width,
            presentation,
            depth: depth || component.depth,
            rotation_degrees_per_second: clamp(
              (finite(component.rotation_degrees_per_second) || 0)
              + (rotation !== null ? rotation : 0),
              -180,
              180
            ),
            rotation_wobble_degrees: clamp(wobble === null ? 0 : wobble, 0, 180),
            hue_shift_degrees: clamp(
              (finite(component.hue_shift_degrees) || 0)
              + (hueShift !== null ? hueShift : 0),
              -360,
              360
            ),
            blend_mode: blendMode || component.blend_mode,
          });
        });
      });
      return shapes;
    }

    let handles = new Map();
    let lastShapes = [];
    const depthOrder = { background: 0, foreground: 1 };

    function getStoryboardShapes(masterTime) {
      const liveShapes = computeShapes();
      let shapes = liveShapes;
      currentState = decodedState
        ? samplePreviewState(decodedState, masterTime)
        : null;
      if (currentState && previewDocument) {
        const selected = selectedSection(previewDocument);
        const transition = clamp01(finite(currentState.transition_progress) || 0);
        let currentWeight = 1;
        let previousShapes = [];
        const previousIndex = Math.round(
          finite(currentState.previous_section_index) === null
            ? -1
            : finite(currentState.previous_section_index)
        );
        const previous = previousIndex >= 0
          ? previewDocument.sections[previousIndex]
          : null;
        if (
          selected
          && previous
          && previous.composition_key !== selected.composition_key
          && transition < 1
        ) {
          currentWeight = transition;
          const previousComposition = previewDocument.compositions[
            previous.composition_key
          ];
          previousShapes = ((previousComposition && previousComposition.traces) || [])
            .map((layer, layerIndex) => ({
              ...mappedLayerShape(
                layer,
                currentState,
                previewDocument,
                masterTime,
                layerIndex,
                1 - transition
              ),
              assignment: null,
              label: '',
            }));
        }
        shapes = [
          ...previousShapes,
          ...liveShapes.map((layer, layerIndex) => mappedLayerShape(
            layer,
            currentState,
            previewDocument,
            masterTime,
            layerIndex,
            currentWeight
          )),
        ];
      }
      lastShapes = shapes
        .filter((shape) => shape.opacity > 0.001)
        .sort((a, b) => (depthOrder[a.depth] || 0) - (depthOrder[b.depth] || 0));
      return lastShapes;
    }

    function drawOverlay() {
      context.save();
      context.strokeStyle = 'rgba(255,255,255,0.10)';
      context.lineWidth = 1;
      context.beginPath();
      context.moveTo(width / 2, 0);
      context.lineTo(width / 2, height);
      context.moveTo(0, height / 2);
      context.lineTo(width, height / 2);
      context.stroke();

      handles = new Map();
      lastShapes.forEach((item) => {
        if (!item.assignment) return;
        const originX = width * item.anchor_x;
        const originY = height * item.anchor_y;
        const radius = Math.min(width, height) * (0.5 - margin) * item.base_scale;
        const existing = handles.get(item.assignment);
        const merged = existing || {
          assignment: item.assignment,
          label: item.label,
          cx: originX,
          cy: originY,
          radius: 0,
        };
        merged.cx = originX;
        merged.cy = originY;
        merged.radius = Math.max(merged.radius, radius);
        handles.set(item.assignment, merged);
      });

      handles.forEach((handle) => {
        context.fillStyle = 'rgba(255,255,255,0.9)';
        context.beginPath();
        context.arc(handle.cx, handle.cy, 4, 0, tau);
        context.fill();
        if (handle.label) {
          context.font = '600 13px system-ui, sans-serif';
          const labelWidth = context.measureText(handle.label).width + 12;
          context.fillStyle = 'rgba(0,0,0,0.55)';
          context.fillRect(handle.cx + 8, handle.cy - 10, labelWidth, 20);
          context.fillStyle = '#fff';
          context.textBaseline = 'middle';
          context.fillText(handle.label, handle.cx + 14, handle.cy + 1);
        }
      });
      context.restore();
      if (emptyEl) emptyEl.hidden = lastShapes.length > 0;
    }

    function drawSceneOverlays(drawContext) {
      const cue = previewDocument
        ? lyricCueAt(previewDocument, currentState, drawContext.masterTime)
        : null;
      drawLyricCue(drawContext.canvas, previewDocument, cue);
      // Placement guides and drag handles stay above the audience-facing lyric
      // so the scene remains practical to edit while showing its composition.
      drawOverlay();
    }

    const audioElement = doc.getElementById('storyboard-audio-el');
    const audioToggle = doc.getElementById('storyboard-audio');
    const modelStart = finite(model.range && model.range.start);
    const modelEnd = finite(model.range && model.range.end);
    const audioStart = audioElement ? finite(audioElement.dataset.start) : null;
    const audioEnd = audioElement ? finite(audioElement.dataset.end) : null;
    const sceneStart = modelStart !== null ? modelStart : audioStart || 0;
    const sceneEnd = modelEnd !== null ? modelEnd : audioEnd;
    const rangeEnd = sceneEnd !== null && sceneEnd > sceneStart
      ? sceneEnd
      : sceneStart + 1;
    const playButton = doc.getElementById('storyboard-play');
    const resetButton = doc.getElementById('storyboard-reset');
    const progressElement = doc.getElementById('storyboard-progress');
    const withAudio = () => Boolean(audioElement && audioToggle && audioToggle.checked);
    const reducedMotion = Boolean(
      root.matchMedia
      && root.matchMedia('(prefers-reduced-motion: reduce)').matches
    );

    const engine = createEngine({
      canvas,
      previewDocument: model,
      range: { start: sceneStart, end: rangeEnd },
      initialTime: sceneStart,
      loop: true,
      reducedMotion,
      background: () => (
        previewDocument
          ? backgroundColor(previewDocument, currentState)
          : model.background || '#101014'
      ),
      margin: () => {
        const documentMargin = previewDocument
          ? finite(previewDocument.video && previewDocument.video.canvas_margin)
          : null;
        return documentMargin === null ? margin : documentMargin;
      },
      getShapes: getStoryboardShapes,
      drawShapes: root.mrpDrawShapes,
      afterDraw: drawSceneOverlays,
      onchange(progress, playing) {
        if (playButton) {
          playButton.textContent = playing ? '❚❚ Pause' : '▶ Play';
        }
        if (progressElement) {
          progressElement.textContent = `${Math.round(progress * 100)}%`;
        }
      },
    });

    const redrawStoryboard = () => engine.redraw();
    root.redrawStoryboard = redrawStoryboard;
    refreshPreviewStatus();

    const loadController = typeof root.AbortController === 'function'
      ? new root.AbortController()
      : null;
    if (loadController) cleanups.push(() => loadController.abort());

    async function loadPreviewData() {
      if (!previewUrl || typeof root.fetch !== 'function') {
        previewFailure = {
          kind: 'draft',
          message: 'Geometry only · Run Analyze',
        };
        refreshPreviewStatus();
        return;
      }
      try {
        const response = await root.fetch(previewUrl, {
          headers: { Accept: 'application/json' },
          signal: loadController ? loadController.signal : undefined,
        });
        const payload = await response.json();
        if (!response.ok) {
          const message = payload && payload.error && payload.error.message;
          throw new Error(message || 'Live Preview data is unavailable.');
        }
        validatePreviewDocument(payload);
        const nextDecoded = decodePreviewState(payload);
        if (destroyed) return;
        previewDocument = payload;
        decodedState = nextDecoded;
        previewFailure = null;
        engine.loadPreview(payload, { start: sceneStart, end: rangeEnd });
        refreshPreviewStatus();
      } catch (error) {
        if (destroyed || (error && error.name === 'AbortError')) return;
        previewDocument = null;
        decodedState = null;
        previewFailure = {
          kind: 'failed',
          message: 'Stale · preview data unavailable',
        };
        refreshPreviewStatus();
        engine.redraw();
      }
    }
    loadPreviewData();

    listen(playButton, 'click', () => {
      if (engine.playing) {
        engine.pause();
        return;
      }
      if (withAudio()) {
        engine.setAudio(audioElement, {
          time: engine.currentTime,
          captureTime: false,
        });
      } else {
        engine.setAudio(null);
      }
      engine.play();
    });

    listen(resetButton, 'click', () => engine.reset());

    listen(audioToggle, 'change', () => {
      if (!engine.playing) return;
      if (withAudio()) {
        engine.setAudio(audioElement, {
          time: engine.currentTime,
          captureTime: false,
        });
      } else {
        engine.setAudio(null);
      }
    });

    let drag = null;
    const canvasPoint = (event) => {
      const rectangle = canvas.getBoundingClientRect();
      return {
        x: (event.clientX - rectangle.left) * (width / rectangle.width),
        y: (event.clientY - rectangle.top) * (height / rectangle.height),
      };
    };
    const pickHandle = (point) => {
      let best = null;
      let bestDistance = Infinity;
      handles.forEach((handle) => {
        const distance = Math.hypot(point.x - handle.cx, point.y - handle.cy);
        const reach = Math.max(28, handle.radius);
        if (distance < reach && distance < bestDistance) {
          best = handle;
          bestDistance = distance;
        }
      });
      return best;
    };

    listen(canvas, 'pointerdown', (event) => {
      const point = canvasPoint(event);
      const handle = pickHandle(point);
      if (!handle) return;
      const card = doc.querySelector(
        `#actor-assignments fieldset[data-assignment-id="${handle.assignment}"]`
      );
      if (!card) return;
      const xElement = card.querySelector('[name="direction_anchor_x"]');
      const yElement = card.querySelector('[name="direction_anchor_y"]');
      drag = {
        xElement,
        yElement,
        startX: point.x,
        startY: point.y,
        baseX: numberOrNull(xElement && xElement.value),
        baseY: numberOrNull(yElement && yElement.value),
      };
      canvas.setPointerCapture(event.pointerId);
      canvas.classList.add('dragging');
      event.preventDefault();
    });

    listen(canvas, 'pointermove', (event) => {
      if (!drag) return;
      const point = canvasPoint(event);
      const deltaX = (point.x - drag.startX) / width;
      const deltaY = (point.y - drag.startY) / height;
      const nextX = clamp((drag.baseX !== null ? drag.baseX : 0.5) + deltaX, -0.5, 1.5);
      const nextY = clamp((drag.baseY !== null ? drag.baseY : 0.5) + deltaY, -0.5, 1.5);
      if (drag.xElement) drag.xElement.value = nextX.toFixed(3);
      if (drag.yElement) drag.yElement.value = nextY.toFixed(3);
      redrawStoryboard();
    });

    const endDrag = (event) => {
      if (!drag) return;
      if (drag.xElement) {
        drag.xElement.dispatchEvent(new root.Event('input', { bubbles: true }));
      }
      drag = null;
      canvas.classList.remove('dragging');
      if (event) canvas.releasePointerCapture(event.pointerId);
    };
    listen(canvas, 'pointerup', endDrag);
    listen(canvas, 'pointercancel', endDrag);

    const assignments = doc.getElementById('actor-assignments');
    const redrawUnsaved = () => {
      hasUnsavedEdits = true;
      refreshPreviewStatus();
      redrawStoryboard();
    };
    root.markStoryboardUnsaved = redrawUnsaved;
    listen(assignments, 'input', redrawUnsaved);
    listen(assignments, 'change', redrawUnsaved);

    const controller = {
      engine,
      redraw: redrawStoryboard,
      destroy() {
        if (destroyed) return;
        destroyed = true;
        while (cleanups.length) cleanups.pop()();
        engine.destroy();
        if (root.redrawStoryboard === redrawStoryboard) {
          delete root.redrawStoryboard;
        }
        if (root.markStoryboardUnsaved === redrawUnsaved) {
          delete root.markStoryboardUnsaved;
        }
        if (canvas.__mrpLivePreviewController === controller) {
          delete canvas.__mrpLivePreviewController;
        }
        delete canvas.dataset.livePreviewReady;
      },
      get previewDocument() { return previewDocument; },
      get shapes() { return lastShapes; },
      get state() { return currentState; },
    };
    canvas.__mrpLivePreviewController = controller;
    canvas.dataset.livePreviewReady = 'true';

    const cleanupOnSwap = (event) => {
      const target = event && event.target;
      if (target === canvas || (target && target.contains && target.contains(canvas))) {
        controller.destroy();
      }
    };
    listen(root.document, 'htmx:beforeCleanupElement', cleanupOnSwap);
    listen(root, 'pagehide', () => controller.destroy());

    engine.renderAt(sceneStart);
    return controller;
  }

  function initFullTrackPreview(documentRoot) {
    if (!root || !root.document) return null;
    const doc = documentRoot || root.document;
    const canvas = doc.getElementById('track-live-preview-canvas');
    if (!canvas || typeof root.mrpDrawShapes !== 'function') return null;
    if (canvas.__mrpFullTrackPreviewController) {
      canvas.__mrpFullTrackPreviewController.destroy();
    }

    const previewUrl = canvas.dataset.previewUrl || '';
    const playButton = doc.getElementById('track-preview-play');
    const resetButton = doc.getElementById('track-preview-reset');
    const reloadButton = doc.getElementById('track-preview-reload');
    const scrubber = doc.getElementById('track-preview-scrubber');
    const timeElement = doc.getElementById('track-preview-time');
    const sceneElement = doc.getElementById('track-preview-scene');
    const lyricElement = doc.getElementById('track-preview-lyric');
    const statusElement = doc.getElementById('track-preview-state');
    const performanceElement = doc.getElementById('track-preview-performance');
    const sceneJumps = doc.getElementById('track-preview-scenes');
    const audioElement = doc.getElementById('track-preview-audio');
    const cleanups = [];
    const loadController = typeof root.AbortController === 'function'
      ? new root.AbortController()
      : null;
    let destroyed = false;
    let engine = null;
    let previewDocument = null;
    let decodedState = null;
    let currentFrame = null;
    let stale = false;
    let checkingStale = false;
    let lastStaleCheck = 0;
    let loadedEtag = '';
    let scrubbing = false;
    const reducedMotion = Boolean(
      root.matchMedia
      && root.matchMedia('(prefers-reduced-motion: reduce)').matches
    );

    const listen = (target, type, listener) => {
      if (!target || typeof target.addEventListener !== 'function') return;
      target.addEventListener(type, listener);
      cleanups.push(() => target.removeEventListener(type, listener));
    };

    function setStatus(kind, message) {
      if (!statusElement) return;
      statusElement.textContent = message;
      statusElement.className = `badge badge-${kind}`;
      statusElement.dataset.state = kind;
    }

    function refreshStatus() {
      if (stale) {
        setStatus('failed', 'Stale loaded state · Reload');
        return;
      }
      if (!previewDocument) {
        setStatus('draft', 'Loading saved preview…');
        return;
      }
      if (previewDocument.mode === 'audio-reactive' && decodedState) {
        setStatus('live', 'Current saved state · Audio reactive');
        return;
      }
      const reason = previewDocument.mode_reason || {};
      if (reason.code === 'analysis_stale') {
        setStatus('failed', 'Geometry only · Analysis stale');
      } else {
        setStatus('draft', 'Geometry only · Run Analyze');
      }
    }

    function updatePerformanceLabel(metrics) {
      if (!metrics) return;
      canvas.dataset.redrawFps = String(metrics.targetFps);
      if (!performanceElement) return;
      performanceElement.textContent = metrics.reducedMotion
        ? `Reduced motion · ${metrics.targetFps} fps redraw target`
        : `${metrics.targetFps} fps redraw target`;
    }

    // One clock for the whole admin, resolved lazily so script order on the
    // page cannot freeze in a stale reference. `root` is null under node, where
    // the tests require the module directly.
    function formatTime(value) {
      if (root && root.mrpTimecode) return root.mrpTimecode.seconds(value);
      if (typeof require === 'function') return require('./video-timecode.js').seconds(value);
      throw new Error('Live Preview needs /static/video-timecode.js loaded first.');
    }

    function drawLoading(message) {
      const context = canvas.getContext('2d');
      context.fillStyle = '#101014';
      context.fillRect(0, 0, canvas.width, canvas.height);
      context.fillStyle = '#a7a7b2';
      context.font = '16px system-ui, sans-serif';
      context.textAlign = 'center';
      context.textBaseline = 'middle';
      context.fillText(message, canvas.width / 2, canvas.height / 2);
    }

    function drawLyric({ canvas: targetCanvas }) {
      const cue = currentFrame && currentFrame.lyric;
      drawLyricCue(targetCanvas, previewDocument, cue);
    }

    function updateSceneJumps() {
      if (!sceneJumps) return;
      sceneJumps.replaceChildren();
      (previewDocument.sections || []).forEach((section) => {
        const start = finite(section.start) || 0;
        const end = finite(section.end) || start;
        const stateRate = finite(previewDocument.state_rate_hz);
        const interiorOffset = stateRate !== null && stateRate > 0
          ? 1 / stateRate
          : 0.001;
        const jumpTime = Math.min(
          Math.max(start, end - 0.001),
          start + interiorOffset
        );
        const button = doc.createElement('button');
        button.type = 'button';
        button.className = 'track-preview-scene-jump';
        button.dataset.sectionId = section.id;
        button.dataset.time = String(jumpTime);
        button.textContent = section.label || section.id;
        // The seek lands just inside the scene so the sampled state resolves
        // to it rather than to the scene before it; say the scene, not a time.
        button.title = `Jump to ${section.label || section.id}, starting ${formatTime(start)}`;
        sceneJumps.appendChild(button);
      });
    }

    function updateIndicators(masterTime, playing) {
      const duration = finite(previewDocument && previewDocument.duration_seconds) || 0;
      if (playButton) {
        playButton.textContent = playing ? '❚❚ Pause' : '▶ Play';
        playButton.setAttribute('aria-pressed', playing ? 'true' : 'false');
      }
      if (scrubber) {
        // Never move the thumb out from under a drag; the pointer owns the
        // position until it is released, and seek keeps the engine in step.
        if (!scrubbing) scrubber.value = String(masterTime);
        scrubber.setAttribute(
          'aria-valuetext',
          `${formatTime(masterTime)} of ${formatTime(duration)}`
        );
      }
      if (timeElement) {
        timeElement.textContent = `${formatTime(masterTime)} / ${formatTime(duration)}`;
      }
      const section = currentFrame && currentFrame.section;
      if (sceneElement) {
        sceneElement.textContent = section
          ? `${section.label || section.id} · ${section.id}`
          : 'No timed scene';
      }
      const lyric = currentFrame && currentFrame.lyric;
      if (lyricElement) {
        lyricElement.textContent = lyric ? lyric.text : '—';
      }
      if (sceneJumps) {
        sceneJumps.querySelectorAll('[data-section-id]').forEach((button) => {
          const active = Boolean(section && button.dataset.sectionId === section.id);
          button.classList.toggle('active', active);
          if (active) button.setAttribute('aria-current', 'true');
          else button.removeAttribute('aria-current');
        });
      }
      const frameTime = doc.querySelector(
        '#video-job-frame input[name="time_seconds"]'
      );
      if (frameTime) frameTime.value = Number(masterTime).toFixed(3);
    }

    async function checkForStale() {
      if (
        destroyed
        || !previewDocument
        || checkingStale
        || !previewUrl
        || typeof root.fetch !== 'function'
      ) {
        return;
      }
      const nowMilliseconds = Date.now();
      if (nowMilliseconds - lastStaleCheck < 3000) return;
      lastStaleCheck = nowMilliseconds;
      checkingStale = true;
      try {
        const headers = { Accept: 'application/json' };
        // A matching validator answers 304 with no body, so the common
        // "nothing changed" case never transfers the document again.
        if (loadedEtag) headers['If-None-Match'] = loadedEtag;
        const response = await root.fetch(previewUrl, {
          headers,
          signal: loadController ? loadController.signal : undefined,
        });
        if (response.status === 304) return;
        const payload = await response.json();
        if (
          !destroyed
          && response.ok
          && previewRevisionChanged(previewDocument, payload)
        ) {
          stale = true;
          refreshStatus();
        }
      } catch (error) {
        if (!destroyed && (!error || error.name !== 'AbortError')) {
          setStatus('failed', 'Cannot verify loaded state · Reload');
        }
      } finally {
        checkingStale = false;
      }
    }

    async function loadPreviewData() {
      if (!previewUrl || typeof root.fetch !== 'function') {
        setStatus('failed', 'Live Preview data is unavailable');
        drawLoading('Live Preview data is unavailable.');
        return;
      }
      try {
        const response = await root.fetch(previewUrl, {
          headers: { Accept: 'application/json' },
          signal: loadController ? loadController.signal : undefined,
        });
        const payload = await response.json();
        if (!response.ok) {
          const message = payload && payload.error && payload.error.message;
          throw new Error(message || 'Live Preview data is unavailable.');
        }
        validatePreviewDocument(payload);
        const nextDecoded = decodePreviewState(payload);
        if (destroyed) return;
        previewDocument = payload;
        decodedState = nextDecoded;
        loadedEtag = (
          response.headers && typeof response.headers.get === 'function'
            ? response.headers.get('ETag') || ''
            : ''
        );
        const duration = finite(payload.duration_seconds);
        if (duration === null || duration <= 0) {
          throw new Error('Live Preview duration is unavailable.');
        }
        if (scrubber) {
          scrubber.max = String(duration);
          scrubber.disabled = false;
        }
        [playButton, resetButton].forEach((button) => {
          if (button) button.disabled = false;
        });
        updateSceneJumps();
        engine = createEngine({
          canvas,
          previewDocument,
          range: { start: 0, end: duration },
          initialTime: 0,
          loop: false,
          reducedMotion,
          background: () => backgroundColor(
            previewDocument,
            currentFrame && currentFrame.state
          ),
          margin: () => (
            finite(previewDocument.video && previewDocument.video.canvas_margin)
            || 0.08
          ),
          getShapes(masterTime) {
            currentFrame = previewFrameAt(
              previewDocument,
              decodedState,
              masterTime
            );
            return currentFrame.shapes;
          },
          drawShapes: root.mrpDrawShapes,
          afterDraw: drawLyric,
          onchange(_progress, playing, masterTime, _shapes, metrics) {
            updateIndicators(masterTime, playing);
            updatePerformanceLabel(metrics);
          },
          onperformance(metrics) {
            updatePerformanceLabel(metrics);
          },
          onaudioerror() {
            setStatus('failed', 'Audio playback unavailable · Visual clock active');
          },
        });
        if (audioElement) {
          engine.setAudio(audioElement, { time: 0, captureTime: false });
        }
        updatePerformanceLabel({
          reducedMotion: engine.reducedMotion,
          targetFps: engine.redrawFps,
        });
        refreshStatus();
        engine.renderAt(0);
        const readyAt = (
          root.performance && typeof root.performance.now === 'function'
            ? root.performance.now()
            : Date.now()
        );
        const resource = (
          root.performance
          && typeof root.performance.getEntriesByType === 'function'
          && root.performance.getEntriesByType('resource').find(
            (entry) => entry.name.endsWith(previewUrl)
          )
        );
        canvas.dataset.firstFrameAfterDataMs = resource
          ? Math.max(0, readyAt - resource.responseEnd).toFixed(2)
          : '';
        canvas.dataset.firstFrameNavigationMs = readyAt.toFixed(2);
        canvas.dataset.livePreviewReady = 'true';
      } catch (error) {
        if (destroyed || (error && error.name === 'AbortError')) return;
        setStatus('failed', error.message || 'Live Preview data is unavailable');
        drawLoading('Live Preview could not be loaded.');
      }
    }

    listen(playButton, 'click', () => {
      if (!engine) return;
      if (engine.playing) engine.pause();
      else engine.play();
    });
    listen(resetButton, 'click', () => {
      if (engine) engine.reset();
    });
    listen(reloadButton, 'click', () => root.location.reload());
    listen(scrubber, 'pointerdown', () => { scrubbing = true; });
    listen(scrubber, 'keydown', () => { scrubbing = true; });
    ['pointerup', 'pointercancel', 'keyup', 'blur', 'change'].forEach((type) => {
      listen(scrubber, type, () => { scrubbing = false; });
    });
    // Releasing outside the control must still hand the thumb back.
    listen(doc, 'pointerup', () => { scrubbing = false; });
    listen(doc, 'pointercancel', () => { scrubbing = false; });
    listen(scrubber, 'input', () => {
      if (engine) engine.seek(scrubber.value);
    });
    listen(sceneJumps, 'click', (event) => {
      const button = event.target.closest('[data-time]');
      if (button && engine) engine.seek(button.dataset.time);
    });
    listen(audioElement, 'loadedmetadata', () => {
      if (engine) engine.seek(engine.currentTime);
    });
    listen(root, 'focus', checkForStale);
    listen(doc, 'visibilitychange', () => {
      if (doc.visibilityState === 'visible') checkForStale();
    });
    listen(doc, 'htmx:afterSwap', (event) => {
      if (
        engine
        && event.detail
        && event.detail.target
        && event.detail.target.id === 'video-job-frame'
      ) {
        updateIndicators(engine.currentTime, engine.playing);
      }
    });

    const controller = {
      checkForStale,
      destroy() {
        if (destroyed) return;
        destroyed = true;
        if (loadController) loadController.abort();
        while (cleanups.length) cleanups.pop()();
        if (engine) engine.destroy();
        if (canvas.__mrpFullTrackPreviewController === controller) {
          delete canvas.__mrpFullTrackPreviewController;
        }
        delete canvas.dataset.livePreviewReady;
      },
      get engine() { return engine; },
      get frame() { return currentFrame; },
      get previewDocument() { return previewDocument; },
    };
    canvas.__mrpFullTrackPreviewController = controller;

    const cleanupOnSwap = (event) => {
      const target = event && event.target;
      if (target === canvas || (target && target.contains && target.contains(canvas))) {
        controller.destroy();
      }
    };
    listen(root.document, 'htmx:beforeCleanupElement', cleanupOnSwap);
    listen(root, 'pagehide', () => controller.destroy());

    refreshStatus();
    drawLoading('Loading saved Live Preview…');
    loadPreviewData();
    return controller;
  }

  return {
    STATE_SCHEMA,
    backgroundColor,
    createEngine,
    decodePreviewState,
    drawLyricCue,
    flattenLayer,
    initFullTrackPreview,
    initScenePreview,
    layerColor,
    lyricCueAt,
    mapLayerState,
    mappedLayerShape,
    normalizeRange,
    previewFrameAt,
    previewRevisionChanged,
    previewSectionsAt,
    savedPreviewShapes,
    samplePreviewState,
    sectionIndexAtTime,
    stateSampleWindow,
    validatePreviewDocument,
  };
});
