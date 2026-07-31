import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  STATE_SCHEMA,
  backgroundColor,
  createEngine,
  decodePreviewState,
  drawLyricCue,
  layerColor,
  lyricCueAt,
  mapLayerState,
  mappedLayerShape,
  normalizeRange,
  previewRevisionChanged,
  previewSectionsAt,
  savedPreviewShapes,
  samplePreviewState,
  sectionIndexAtTime,
  stateSampleWindow,
  validatePreviewDocument,
} = require('../../../../mrp/admin/static/video-live-preview.js');

const mappingFixture = JSON.parse(readFileSync(
  new URL('../fixtures/live-preview-mapping-v1.json', import.meta.url),
  'utf8'
));

function engineHarness(options = {}) {
  let nextFrameId = 1;
  let now = options.now ?? 1000;
  const frames = new Map();
  const cancelled = [];
  const draws = [];
  const changes = [];
  const canvas = {};

  const engine = createEngine({
    canvas,
    range: options.range || { start: 10, end: 15 },
    initialTime: options.initialTime ?? 10,
    loop: options.loop ?? true,
    reducedMotion: options.reducedMotion ?? false,
    now: () => now,
    requestFrame(callback) {
      const id = nextFrameId;
      nextFrameId += 1;
      frames.set(id, callback);
      return id;
    },
    cancelFrame(id) {
      cancelled.push(id);
      frames.delete(id);
    },
    getShapes(masterTime) {
      return [{ masterTime }];
    },
    drawShapes(_canvas, shapes, drawOptions) {
      draws.push({ shapes, options: drawOptions });
      now += options.drawCost ?? 0;
    },
    onchange(progress, playing, masterTime) {
      changes.push({ masterTime, playing, progress });
    },
  });

  return {
    cancelled,
    changes,
    draws,
    engine,
    frames,
    setNow(value) {
      now = value;
    },
    step(timestamp) {
      const entry = frames.entries().next().value;
      assert.ok(entry, 'an animation frame should be scheduled');
      const [id, callback] = entry;
      frames.delete(id);
      callback(timestamp);
    },
  };
}

function fakeAudio() {
  const listeners = new Map();
  return {
    currentTime: 0,
    pauseCalls: 0,
    paused: true,
    playCalls: 0,
    addEventListener(type, callback) {
      listeners.set(type, callback);
    },
    removeEventListener(type, callback) {
      if (listeners.get(type) === callback) listeners.delete(type);
    },
    pause() {
      this.pauseCalls += 1;
      this.paused = true;
    },
    play() {
      this.playCalls += 1;
      this.paused = false;
      return Promise.resolve();
    },
    listeners,
  };
}

test('renderAt and paused seek draw absolute master time', () => {
  const harness = engineHarness();

  harness.engine.renderAt(12.75);
  assert.equal(harness.engine.currentTime, 12.75);
  assert.equal(harness.draws.at(-1).options.clockSeconds, 12.75);
  assert.equal(harness.draws.at(-1).options.showHead, true);
  assert.equal(harness.changes.at(-1).progress, 0.55);

  harness.engine.seek(14.25);
  assert.equal(harness.engine.currentTime, 14.25);
  assert.equal(harness.draws.at(-1).options.clockSeconds, 14.25);
  assert.equal(harness.engine.playing, false);
});

test('silent playback advances absolute time and loops inside its range', () => {
  const harness = engineHarness();

  assert.equal(harness.engine.play(), true);
  harness.step(2500);
  assert.equal(harness.engine.currentTime, 11.5);
  assert.equal(harness.draws.at(-1).options.clockSeconds, 11.5);

  harness.step(7000);
  assert.equal(harness.engine.currentTime, 11);
  assert.equal(harness.draws.at(-1).options.clockSeconds, 11);
  assert.equal(harness.engine.playing, true);
});

test('audio currentTime is authoritative and remains absolute', () => {
  const harness = engineHarness();
  const audio = fakeAudio();

  harness.engine.setAudio(audio, { time: 12, captureTime: false });
  harness.engine.play();
  assert.equal(audio.currentTime, 12);
  assert.equal(audio.playCalls, 1);

  audio.currentTime = 13.875;
  harness.step(2000);
  assert.equal(harness.engine.currentTime, 13.875);
  assert.equal(harness.draws.at(-1).options.clockSeconds, 13.875);

  harness.engine.pause();
  assert.equal(audio.pauseCalls, 1);
  assert.equal(harness.engine.currentTime, 13.875);
});

test('a non-looping range stops exactly at its end', () => {
  const harness = engineHarness({ loop: false });

  harness.engine.play();
  harness.step(7000);

  assert.equal(harness.engine.currentTime, 15);
  assert.equal(harness.engine.playing, false);
  assert.equal(harness.draws.at(-1).options.clockSeconds, 15);
  assert.equal(harness.frames.size, 0);
});

test('scheduled redraw targets 30 fps without slowing the master clock', () => {
  const harness = engineHarness({ initialTime: 10 });
  harness.engine.play();
  const initialDraws = harness.draws.length;

  harness.step(1010);
  assert.equal(harness.engine.currentTime, 10.01);
  assert.equal(harness.draws.length, initialDraws);
  harness.step(1040);
  assert.equal(harness.engine.currentTime, 10.04);
  assert.equal(harness.draws.length, initialDraws + 1);
  assert.equal(harness.engine.redrawFps, 30);
});

test('expensive drawing adapts from 30 to 20 fps with a 15 fps floor', () => {
  const harness = engineHarness({
    drawCost: 40,
    initialTime: 10,
  });
  harness.engine.play();
  for (let index = 1; index <= 9; index += 1) {
    harness.step(1000 + index * 40);
  }

  assert.equal(harness.engine.redrawFps, 20);
  assert.ok(harness.engine.drawCostMs >= 0);
  assert.ok(harness.engine.currentTime > 10.3);
});

test('slow observed frame cadence can adapt all the way to 15 fps', () => {
  const harness = engineHarness({ initialTime: 10 });
  harness.engine.play();
  for (let index = 1; index <= 18; index += 1) {
    harness.step(1000 + index * 70);
  }

  assert.equal(harness.engine.redrawFps, 15);
  assert.ok(harness.engine.drawIntervalMs >= 0);
  assert.ok(harness.engine.currentTime > 11);
});

test('reduced motion uses the 15 fps redraw floor without changing time', () => {
  const harness = engineHarness({
    initialTime: 10,
    reducedMotion: true,
  });
  harness.engine.play();
  const initialDraws = harness.draws.length;

  harness.step(1040);
  assert.equal(harness.engine.currentTime, 10.04);
  assert.equal(harness.draws.length, initialDraws);
  harness.step(1080);
  assert.ok(Math.abs(harness.engine.currentTime - 10.08) < 1e-10);
  assert.equal(harness.draws.length, initialDraws + 1);
  assert.equal(harness.engine.redrawFps, 15);
  assert.equal(harness.engine.reducedMotion, true);
});

test('destroy cancels transport and removes audio lifecycle listeners', () => {
  const harness = engineHarness();
  const audio = fakeAudio();
  harness.engine.setAudio(audio, { time: 11, captureTime: false });
  harness.engine.play();
  const drawCount = harness.draws.length;

  harness.engine.destroy();

  assert.equal(harness.engine.playing, false);
  assert.equal(harness.frames.size, 0);
  assert.equal(audio.listeners.size, 0);
  assert.equal(audio.paused, true);
  harness.engine.seek(14);
  assert.equal(harness.draws.length, drawCount);
});

test('stateSampleWindow returns adjacent fixed-rate samples', () => {
  const documentModel = {
    duration_seconds: 5,
    state_rate_hz: 20,
    state_sample_count: 101,
  };

  assert.deepEqual(stateSampleWindow(documentModel, 1.225), {
    lowerIndex: 24,
    upperIndex: 25,
    fraction: 0.5,
  });
  assert.deepEqual(stateSampleWindow(documentModel, 99), {
    lowerIndex: 100,
    upperIndex: 100,
    fraction: 0,
  });
  assert.equal(stateSampleWindow({ mode: 'geometry-only' }, 2), null);
});

test('normalizeRange rejects missing or empty playback ranges', () => {
  assert.deepEqual(normalizeRange(null, 20), { start: 0, end: 20 });
  assert.throws(
    () => normalizeRange({ start: 5, end: 5 }, null),
    /end is after its start/
  );
});

test('version-1 Float32 state decodes once and interpolates numeric columns', () => {
  const first = STATE_SCHEMA.map((_name, index) => index);
  const second = STATE_SCHEMA.map((_name, index) => index + 10);
  first[0] = 2;
  first[1] = 1;
  second[0] = 3;
  second[1] = 2;
  const values = new Float32Array([...first, ...second]);
  const documentModel = {
    format: 'mrp-music-video-live-preview',
    version: 2,
    mode: 'audio-reactive',
    duration_seconds: 0.05,
    state_rate_hz: 20,
    state_encoding: 'base64-float32-le',
    state_width: STATE_SCHEMA.length,
    state_sample_count: 2,
    state_schema: STATE_SCHEMA,
    state_samples_base64: Buffer.from(values.buffer).toString('base64'),
    video: {},
    text: {},
    sections: [
      {
        id: 'only',
        start: 0,
        end: 0.05,
        composition_key: 'only',
      },
    ],
    compositions: { only: { traces: [] } },
    lyrics: [],
  };

  const decoded = decodePreviewState(documentModel);
  const halfway = samplePreviewState(decoded, 0.025);

  assert.equal(halfway.section_index, 2);
  assert.equal(halfway.previous_section_index, 1);
  assert.equal(halfway.master_energy, 7);
  assert.equal(halfway.rotation_time, STATE_SCHEMA.indexOf('rotation_time') + 5);
  assert.equal(samplePreviewState(decoded, 5).section_index, 3);
  assert.throws(
    () => decodePreviewState({
      ...documentModel,
      state_width: STATE_SCHEMA.length - 1,
    }),
    /contract does not match/
  );
});

test('JavaScript layer mapping matches canonical Python parity fixtures', () => {
  mappingFixture.cases.forEach((fixtureCase) => {
    const actual = mapLayerState(
      fixtureCase.layer,
      mappingFixture.audio_state,
      mappingFixture.time_seconds,
      fixtureCase.preset,
      fixtureCase.visibility_override
    );
    Object.entries(fixtureCase.expected).forEach(([name, expected]) => {
      assert.ok(
        Math.abs(actual[name] - expected) < 1e-10,
        `${fixtureCase.name}: ${name} ${actual[name]} != ${expected}`
      );
    });
  });
});

test('mapped color and reactive background match renderer color math', () => {
  assert.equal(layerColor('#4c78ff', 64.2, 0.9512, 1), '#f6cffe');
  assert.equal(
    backgroundColor(
      {
        video: { background: '#101014', background_response: 0.16 },
        mapping_preset: { background_response: 1.25 },
      },
      { master_energy: 0.6 }
    ),
    '#2d2d30'
  );
});

test('wobble defaults off and combines independently with continuous rotation', () => {
  const documentModel = fullTrackFixture();
  const preset = documentModel.mapping_preset;
  const layer = {
    ...documentModel.compositions.verse.traces[0],
    rotation_degrees_per_second: 0,
  };
  const state = reactiveState({
    master_energy: 0.5,
    rotation_time: 0,
  });

  const still = mapLayerState(layer, state, 0, preset);
  const wobbleOnly = mapLayerState(
    { ...layer, rotation_wobble_degrees: 12 },
    state,
    0,
    preset
  );
  const rotateAndWobble = mapLayerState(
    {
      ...layer,
      rotation_degrees_per_second: 3,
      rotation_wobble_degrees: 12,
    },
    { ...state, rotation_time: 2 },
    0,
    preset
  );

  assert.equal(still.rotation_radians, 0);
  assert.ok(Math.abs(wobbleOnly.rotation_radians - 12 * Math.PI / 180) < 1e-12);
  assert.ok(rotateAndWobble.rotation_radians > wobbleOnly.rotation_radians);
});

function fullTrackFixture() {
  const trace = (id, depth = 'foreground') => ({
    id,
    role: 'master',
    geometry: {
      family: 'spirogram',
      fixed_radius: 96,
      moving_radius: 32,
      pen_offset: 48,
      samples: 240,
    },
    trace: {
      cycles_per_second: 0.08,
      trail_fraction: 0.3,
      ghost_count: 1,
      ghost_spacing: 0.08,
      head_radius: 3,
    },
    color: '#4c78ff',
    color_locked: true,
    depth,
    anchor_x: 0.5,
    anchor_y: 0.5,
    base_scale: 1,
    opacity: 0.8,
    line_width: 2,
    rotation_degrees_per_second: 3,
    hue_shift_degrees: 0,
    blend_mode: 'normal',
    drivers: {},
    phase_fraction: 0.25,
  });
  return {
    format: 'mrp-music-video-live-preview',
    version: 2,
    mode: 'geometry-only',
    duration_seconds: 12,
    video: {
      background: '#101014',
      background_response: 0,
      lyric_fade_seconds: 1,
    },
    text: {
      size: 60,
      maximum_width_fraction: 0.82,
      position: 'bottom',
      active_color: '#ffffff',
    },
    mapping_preset: {
      background_response: 1,
      hue_response: 1,
      motion_response: 1,
      onset_response: 1,
      opacity_response: 1,
      role_gains: {},
      scale_response: 1,
      visibility_bias: 0,
    },
    palette_preset: { colors: { master: '#4c78ff' } },
    custom_palette: [],
    sections: [
      {
        id: 'verse_1',
        label: 'Verse',
        start: 0,
        end: 5,
        composition_key: 'verse',
      },
      {
        id: 'chorus_1',
        label: 'Chorus',
        start: 7,
        end: 12,
        composition_key: 'chorus',
      },
    ],
    compositions: {
      verse: { traces: [trace('verse-front')] },
      chorus: { traces: [trace('chorus-back', 'background')] },
    },
    lyrics: [
      { text: 'First line', start: 1, end: 3 },
      { text: 'Chorus line', start: 8, end: 10 },
    ],
  };
}

function reactiveState(overrides = {}) {
  return {
    section_index: 1,
    previous_section_index: 0,
    transition_progress: 0.25,
    layer_fraction: 1,
    scale: 1,
    motion: 1,
    color_intensity: 1,
    onset_response: 1,
    palette_shift: 0,
    lyrics_opacity: 0.8,
    spatial_spread: 1,
    anchor_drift: 0,
    trail_length: 1,
    beat_gain: 1,
    intensity_gain: 1,
    trace_time: 6.5,
    rotation_time: 6.5,
    master_energy: 0.5,
    master_accent: 0.2,
    drums_energy: 0,
    drums_accent: 0,
    vocals_energy: 0,
    vocals_accent: 0,
    ...overrides,
  };
}

test('full-track scene lookup follows sampled state and geometry fallback', () => {
  const documentModel = fullTrackFixture();

  assert.equal(sectionIndexAtTime(documentModel, 2), 0);
  assert.equal(sectionIndexAtTime(documentModel, 6), 0);
  assert.equal(sectionIndexAtTime(documentModel, 9), 1);
  assert.equal(previewSectionsAt(documentModel, reactiveState(), 6).current.id, 'chorus_1');
  assert.equal(previewSectionsAt(documentModel, reactiveState(), 6).previous.id, 'verse_1');
  assert.equal(previewSectionsAt(documentModel, null, 6).current.id, 'verse_1');
});

test('saved full-track shapes blend canonical previous and current compositions', () => {
  const documentModel = fullTrackFixture();
  documentModel.compositions.chorus.traces[0].presentation = 'full_outline';
  documentModel.compositions.chorus.traces[0].spatial = {
    mode: 'tilted',
    orientation_mode: 'circuit_step',
    pitch_step_degrees: 5,
    yaw_step_degrees: 15,
    retained_circuits: 12,
    retention_fade: 0.9,
  };
  const state = reactiveState();
  const shapes = savedPreviewShapes(documentModel, state, 6.5);

  assert.deepEqual(shapes.map((shape) => shape.id), ['chorus-back', 'verse-front']);
  assert.equal(shapes[0].presentation, 'full_outline');
  assert.equal(shapes[1].presentation ?? 'animated_trace', 'animated_trace');
  assert.ok(shapes[0].opacity < shapes[1].opacity);
  assert.equal(shapes[0].trace_time, 6.5);
  assert.equal(shapes[1].trace_time, 6.5);
  assert.equal(shapes[0].spatial.orientation_mode, 'circuit_step');
  assert.equal(shapes[0].spatial.retained_circuits, 12);

  const expectedCurrent = mappedLayerShape(
    documentModel.compositions.chorus.traces[0],
    state,
    documentModel,
    6.5,
    0,
    0.25
  );
  assert.deepEqual(shapes[0], expectedCurrent);
  assert.deepEqual(
    savedPreviewShapes(
      documentModel,
      reactiveState({ transition_progress: 1 }),
      7
    ).map((shape) => shape.id),
    ['chorus-back']
  );
});

test('lyric cue selection and fades remain tied to absolute seek time', () => {
  const documentModel = fullTrackFixture();
  const state = reactiveState({ lyrics_opacity: 0.8 });

  assert.equal(lyricCueAt(documentModel, state, 0.5), null);
  assert.deepEqual(lyricCueAt(documentModel, state, 1.5), {
    alpha: 0.4,
    end: 3,
    start: 1,
    text: 'First line',
  });
  assert.equal(lyricCueAt(documentModel, state, 3), null);
  assert.equal(lyricCueAt(documentModel, null, 8.5).alpha, 0.5);
});

test('the shared lyric painter scales project text onto either preview canvas', () => {
  const calls = [];
  const context = new Proxy(
    {
      fillText(...args) {
        calls.push(['fillText', ...args]);
      },
      restore() {
        calls.push(['restore']);
      },
      save() {
        calls.push(['save']);
      },
      strokeText(...args) {
        calls.push(['strokeText', ...args]);
      },
    },
    {
      set(target, name, value) {
        calls.push(['set', name, value]);
        target[name] = value;
        return true;
      },
    }
  );
  const canvas = {
    height: 540,
    width: 960,
    getContext() {
      return context;
    },
  };
  const documentModel = {
    text: {
      active_color: '#ffe066',
      maximum_width_fraction: 0.75,
      position: 'center',
      size: 60,
    },
    video: { height: 1080 },
  };

  assert.equal(
    drawLyricCue(
      canvas,
      documentModel,
      { alpha: 0.4, text: 'Design with the lyric' }
    ),
    true
  );
  assert.ok(calls.some((entry) => (
    entry[0] === 'set' && entry[1] === 'font' && entry[2] === '600 30px system-ui, sans-serif'
  )));
  assert.ok(calls.some((entry) => (
    entry[0] === 'set' && entry[1] === 'globalCompositeOperation' && entry[2] === 'source-over'
  )));
  assert.ok(calls.some((entry) => (
    entry[0] === 'set' && entry[1] === 'globalAlpha' && entry[2] === 0.4
  )));
  assert.ok(calls.some((entry) => (
    entry[0] === 'set' && entry[1] === 'fillStyle' && entry[2] === '#ffe066'
  )));
  assert.deepEqual(
    calls.filter((entry) => ['strokeText', 'fillText'].includes(entry[0])),
    [
      ['strokeText', 'Design with the lyric', 480, 270, 720],
      ['fillText', 'Design with the lyric', 480, 270, 720],
    ]
  );
  assert.equal(drawLyricCue(canvas, documentModel, null), false);
});

test('source-revision checks detect staleness without replacing loaded state', () => {
  const loaded = {
    source_revision: {
      project_sha256: 'project-a',
      lyrics_sha256: 'lyrics-a',
      analysis_key: 'analysis-a',
      renderer_contract: 1,
    },
  };
  const same = JSON.parse(JSON.stringify(loaded));
  const changed = {
    source_revision: {
      ...loaded.source_revision,
      lyrics_sha256: 'lyrics-b',
    },
  };

  assert.equal(previewRevisionChanged(loaded, same), false);
  assert.equal(previewRevisionChanged(loaded, changed), true);
  assert.equal(loaded.source_revision.lyrics_sha256, 'lyrics-a');
});

test('malformed preview documents fail closed before drawing', () => {
  const valid = fullTrackFixture();
  assert.equal(validatePreviewDocument(valid), valid);
  assert.equal(decodePreviewState(valid), null);
  assert.throws(
    () => validatePreviewDocument({ ...valid, version: 1 }),
    /does not match version 2/
  );
  assert.throws(
    () => validatePreviewDocument({
      ...valid,
      sections: [{ ...valid.sections[0], composition_key: 'missing' }],
    }),
    /invalid timed scene/
  );
  assert.throws(
    () => validatePreviewDocument({
      ...valid,
      lyrics: [{ text: 'bad', start: 2, end: 1 }],
    }),
    /invalid lyric cue/
  );
});
