// The app's state on the public pages (REQ-GHA-018 clause 1): asleep, waking up, awake
// or going to sleep, next to "Open app" in the site's nav and next to "Launch live demo"
// on this page. One file for both. The state comes from the wake controller's status
// address, never from the app, so loading a page never contacts or wakes the app.
// An error, a timeout or an unknown state shows nothing, and so does an empty
// CONTROLLER: nothing is requested until the controller's address is set here.
// The labels are placeholders until Igor writes them.
(function () {
  var CONTROLLER = ''; // the wake controller's base address, without a trailing slash
  var LABELS = {
    asleep: 'App asleep',
    waking: 'App waking up',
    awake: 'App awake',
    'going-to-sleep': 'App going to sleep'
  };
  var els = document.querySelectorAll('[data-app-state]');
  if (!CONTROLLER || !els.length || !window.fetch || !window.AbortController) return;

  function show(state) {
    // A string check first: a key lookup would turn ["awake"] into "awake".
    var known = typeof state === 'string' && Object.prototype.hasOwnProperty.call(LABELS, state);
    for (var i = 0; i < els.length; i++) {
      if (!known) { els[i].hidden = true; continue; }
      els[i].setAttribute('data-state', state);
      els[i].querySelector('.app-state-label').textContent = LABELS[state];
      els[i].hidden = false;
    }
  }

  function read() {
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, 5000);
    fetch(CONTROLLER + '/status', { signal: ctrl.signal })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { show(d && d.state); }, function () { show(null); })
      .then(function () { clearTimeout(timer); });
  }

  read();
  // Re-read while the page is in view, so a visitor who stays sees the change.
  setInterval(function () { if (document.visibilityState === 'visible') read(); }, 30000);
})();
