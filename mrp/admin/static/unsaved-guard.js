// Warn before leaving an editor that has typed-but-unsaved changes.
//
// The casting editor navigates constantly -- the scene list, the scope tabs and
// the actor cards are all plain links -- and every one of them is a full page
// load that silently discards whatever is in the form. The scene form is long
// (cast, direction, energy, transition, background), so losing it is expensive.
//
// The state machine is kept apart from the DOM so it can be tested directly.
// It has to survive one awkward detail: a *successful* save also unloads the
// page, because the route answers with HX-Redirect. So a save in flight
// disarms the guard, and only a failed request re-arms it.
(function (root, factory) {
  'use strict';

  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.mrpUnsavedGuard = api;
})(typeof window === 'undefined' ? null : window, function () {
  'use strict';

  function createGuardState() {
    let dirty = false;
    let saving = false;

    return {
      get dirty() { return dirty; },
      get saving() { return saving; },
      // A field was touched, or a card was added/removed.
      edited() { dirty = true; },
      // A save request left the page. Whatever happens next -- an HX-Redirect
      // navigation or an error partial -- must not raise the browser dialog.
      submitted() { saving = true; },
      // `successful` is the HTTP outcome, not htmx's idea of one: a 422
      // validation partial is swapped in as content by the base template, and
      // the user still has unsaved work in front of them.
      settled(successful) {
        saving = false;
        if (successful) dirty = false;
      },
      reset() { dirty = false; saving = false; },
      shouldWarn() { return dirty && !saving; },
    };
  }

  // True for a response that actually stored the edit. htmx reports a swapped
  // 422 as a completed request, so read the status rather than trusting it.
  function savedSuccessfully(xhr) {
    if (!xhr) return false;
    const status = Number(xhr.status);
    return Number.isFinite(status) && status >= 200 && status < 300;
  }

  // Editor forms opt in, because the page carries forms that are not editors.
  // A running render job polls its status once a second from a hidden element,
  // and the job panel has its own submit and cancel forms. Treating any of
  // those as "the edit was saved" would quietly wipe the flag mid-typing.
  const GUARDED = 'form[data-unsaved-guard]';

  function guardedForm(element, container, selector) {
    if (!element || typeof element.closest !== 'function') return null;
    const form = element.closest(selector || GUARDED);
    if (!form) return null;
    if (container && typeof container.contains === 'function'
        && !container.contains(form)) {
      return null;
    }
    return form;
  }

  // Only fields of a guarded form arm it. A click on a link, a control outside
  // every form, or the job panel's own inputs are not unsaved editor work.
  function isEditorField(target, container, selector) {
    if (!target || !target.form) return false;
    return Boolean(guardedForm(target, container, selector));
  }

  function attach(options) {
    const settings = options || {};
    const doc = settings.document || (typeof document === 'undefined' ? null : document);
    const view = settings.window || (typeof window === 'undefined' ? null : window);
    if (!doc || !view) return null;
    const container = settings.container || doc.body;
    if (!container) return null;

    const state = settings.state || createGuardState();
    const selector = settings.selector || GUARDED;
    const cleanups = [];
    const listen = (element, type, handler) => {
      if (!element || typeof element.addEventListener !== 'function') return;
      element.addEventListener(type, handler);
      cleanups.push(() => element.removeEventListener(type, handler));
    };

    const onEdit = (event) => {
      if (isEditorField(event.target, container, selector)) state.edited();
    };
    listen(container, 'input', onEdit);
    listen(container, 'change', onEdit);

    // htmx submits every editor form, so the transport is the same everywhere.
    // Both ends check the source: a request that is not a guarded form's save
    // must neither disarm the guard nor report the edit as stored.
    const requestForm = (event) => {
      const detail = event.detail || {};
      return guardedForm(detail.elt || event.target, container, selector);
    };
    listen(container, 'htmx:beforeRequest', (event) => {
      if (requestForm(event)) state.submitted();
    });
    const onSettled = (event) => {
      if (!requestForm(event)) return;
      const detail = event.detail || {};
      state.settled(savedSuccessfully(detail.xhr));
    };
    listen(container, 'htmx:afterRequest', onSettled);
    // A dropped connection never reaches afterRequest in older htmx builds;
    // re-arming on the error keeps the guard from being stuck off.
    listen(container, 'htmx:sendError', onSettled);

    const onBeforeUnload = (event) => {
      if (!state.shouldWarn()) return undefined;
      // Browsers show their own wording; both forms are needed for coverage.
      event.preventDefault();
      event.returnValue = '';
      return '';
    };
    listen(view, 'beforeunload', onBeforeUnload);

    return {
      state,
      markDirty: () => state.edited(),
      markSaved: () => state.reset(),
      destroy() {
        cleanups.splice(0).forEach((undo) => undo());
      },
    };
  }

  return {
    GUARDED,
    attach,
    createGuardState,
    guardedForm,
    isEditorField,
    savedSuccessfully,
  };
});
