import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import test from 'node:test';

const require = createRequire(import.meta.url);
const {
  attach,
  createGuardState,
  guardedForm,
  isEditorField,
  savedSuccessfully,
} = require('../../../../mrp/admin/static/unsaved-guard.js');

// Minimal stand-ins for the two nodes the guard actually touches.
function fakeElement() {
  const listeners = new Map();
  return {
    listeners,
    contains: () => true,
    addEventListener(type, handler) {
      if (!listeners.has(type)) listeners.set(type, []);
      listeners.get(type).push(handler);
    },
    removeEventListener(type, handler) {
      const handlers = listeners.get(type) || [];
      const index = handlers.indexOf(handler);
      if (index >= 0) handlers.splice(index, 1);
    },
    emit(type, event) {
      (listeners.get(type) || []).slice().forEach((handler) => handler(event));
    },
  };
}

// An element that reports itself as living inside a guarded editor form.
const editorForm = { id: 'editor' };
const inEditor = (extra) => ({
  closest: (selector) => (selector === 'form[data-unsaved-guard]' ? editorForm : null),
  ...extra,
});
// The job panel: real htmx traffic on the same page, from outside any guarded
// form. Its status poller is not even in a form.
const outsideEditor = (extra) => ({ closest: () => null, ...extra });

function harness() {
  const container = fakeElement();
  const view = fakeElement();
  const controller = attach({
    document: { body: container },
    window: view,
    container,
  });
  const field = inEditor({ form: editorForm });
  return {
    container,
    controller,
    field,
    // Returns whether the browser would raise its leave-this-page dialog.
    wouldWarn() {
      let prevented = false;
      view.emit('beforeunload', {
        preventDefault() { prevented = true; },
        set returnValue(_value) {},
        get returnValue() { return ''; },
      });
      return prevented;
    },
    edit() {
      container.emit('input', { target: field });
    },
    submit() {
      container.emit('htmx:beforeRequest', { detail: { elt: inEditor() } });
    },
    respond(status) {
      container.emit('htmx:afterRequest', {
        detail: { elt: inEditor(), xhr: { status } },
      });
    },
    // A render job's one-second status poll, or its submit/cancel forms.
    jobTraffic(status) {
      container.emit('htmx:beforeRequest', { detail: { elt: outsideEditor() } });
      container.emit('htmx:afterRequest', {
        detail: { elt: outsideEditor(), xhr: { status } },
      });
    },
  };
}

test('an untouched editor never challenges a navigation', () => {
  const app = harness();

  assert.equal(app.wouldWarn(), false);
});

test('a typed field arms the guard', () => {
  const app = harness();

  app.edit();

  assert.equal(app.wouldWarn(), true);
});

test('a save in flight does not challenge its own HX-Redirect', () => {
  // The route answers a successful save with HX-Redirect, which unloads the
  // page. Warning there would fire the dialog on every successful save.
  const app = harness();

  app.edit();
  app.submit();

  assert.equal(app.wouldWarn(), false);
});

test('a rejected save re-arms the guard', () => {
  // A 422 is swapped in as content by the base template: nothing was stored
  // and the user still has the work in front of them.
  const app = harness();

  app.edit();
  app.submit();
  app.respond(422);

  assert.equal(app.wouldWarn(), true);
});

test('a stored save leaves nothing to warn about', () => {
  const app = harness();

  app.edit();
  app.submit();
  app.respond(200);

  assert.equal(app.wouldWarn(), false);
});

test('a dropped connection re-arms rather than sticking off', () => {
  const app = harness();

  app.edit();
  app.submit();
  app.container.emit('htmx:sendError', {
    detail: { elt: inEditor(), xhr: { status: 0 } },
  });

  assert.equal(app.wouldWarn(), true);
});

test('adding a card with no field to type in still arms the guard', () => {
  const app = harness();

  app.controller.markDirty();

  assert.equal(app.wouldWarn(), true);
});

test('destroy releases every listener it added', () => {
  const app = harness();

  app.controller.destroy();
  app.edit();

  assert.equal(app.wouldWarn(), false);
});

test('a running job poll never disarms the guard or clears the edit', () => {
  // An active render polls its status once a second from a hidden element
  // outside every form. Treating that 200 as "saved" would silently drop the
  // flag while the user is still typing.
  const app = harness();

  app.edit();
  for (let tick = 0; tick < 3; tick += 1) app.jobTraffic(200);

  assert.equal(app.wouldWarn(), true);
});

test('only fields of a guarded form count as unsaved work', () => {
  const container = { contains: () => true };

  assert.equal(isEditorField(inEditor({ form: editorForm }), container), true);
  // A link or button is not typed work, even inside a guarded form.
  assert.equal(isEditorField(inEditor({}), container), false);
  assert.equal(isEditorField(null, container), false);
  // The job panel's own inputs are one-shot parameters, not editor state.
  assert.equal(isEditorField(outsideEditor({ form: {} }), container), false);
  // A guarded form outside the watched container is somebody else's.
  assert.equal(
    isEditorField(inEditor({ form: editorForm }), { contains: () => false }),
    false
  );
});

test('guardedForm honours an explicit selector', () => {
  const element = { closest: (selector) => (selector === '.mine' ? editorForm : null) };

  assert.equal(guardedForm(element, null, '.mine'), editorForm);
  assert.equal(guardedForm(element, null), null);
  assert.equal(guardedForm(null, null, '.mine'), null);
});

test('only a 2xx counts as stored', () => {
  assert.equal(savedSuccessfully({ status: 200 }), true);
  assert.equal(savedSuccessfully({ status: 204 }), true);
  assert.equal(savedSuccessfully({ status: 422 }), false);
  assert.equal(savedSuccessfully({ status: 409 }), false);
  assert.equal(savedSuccessfully({ status: 500 }), false);
  assert.equal(savedSuccessfully({ status: 0 }), false);
  assert.equal(savedSuccessfully(null), false);
});

test('the state machine reports its own transitions', () => {
  const state = createGuardState();

  assert.equal(state.dirty, false);
  state.edited();
  assert.equal(state.dirty, true);
  state.submitted();
  assert.equal(state.saving, true);
  assert.equal(state.shouldWarn(), false);
  state.settled(false);
  assert.equal(state.saving, false);
  assert.equal(state.dirty, true);
  state.settled(true);
  assert.equal(state.dirty, false);
  state.edited();
  state.reset();
  assert.equal(state.shouldWarn(), false);
});
