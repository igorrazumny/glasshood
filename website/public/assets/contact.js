// The contact form (REQ-GHA-018 clause 3). A message goes to the same mail function the
// 9robots.ai and testrobin.ai forms use, tagged as coming from glasshood.ai; the function
// checks the sending site and the reCAPTCHA token. No email address appears on the site.
// reCAPTCHA site keys are public by design.
(function () {
  var FUNCTION_URL = 'https://sendcontactform-llkttegjbq-oa.a.run.app';
  var RECAPTCHA_SITE_KEY = '6LeYXJ8sAAAAAE-goQsoWJpvgQOVtl_v6v0IX2QK';
  var form = document.getElementById('contact-form');
  if (!form) return;
  var name = document.getElementById('contact-name');
  var email = document.getElementById('contact-email');
  var message = document.getElementById('contact-message');
  var button = form.querySelector('button[type="submit"]');
  var status = document.getElementById('contact-status');

  var s = document.createElement('script');
  s.src = 'https://www.google.com/recaptcha/api.js?render=' + RECAPTCHA_SITE_KEY;
  s.async = true;
  document.head.appendChild(s);

  // If reCAPTCHA did not load, or does not answer within 10 s, the message goes out with
  // an empty token and the mail function decides, as on the other two sites' forms.
  function token() {
    if (!window.grecaptcha) return Promise.resolve('');
    var ask = new Promise(function (resolve) { window.grecaptcha.ready(resolve); })
      .then(function () { return window.grecaptcha.execute(RECAPTCHA_SITE_KEY, { action: 'contact' }); });
    var late = new Promise(function (resolve) { setTimeout(function () { resolve(''); }, 10000); });
    return Promise.race([ask, late]);
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    button.disabled = true;
    button.textContent = 'Sending…';
    status.textContent = '';
    var ctrl = new AbortController();
    var timer = setTimeout(function () { ctrl.abort(); }, 30000);
    token()
      .then(function (recaptchaToken) {
        return fetch(FUNCTION_URL, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          signal: ctrl.signal,
          body: JSON.stringify({
            name: name.value,
            email: email.value,
            category: 'GlassHood',
            subject: '[glasshood.ai] Contact form',
            message: 'source: glasshood.ai\n\n' + message.value,
            recaptchaToken: recaptchaToken
          })
        });
      })
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        form.reset();
        status.textContent = 'Thanks — your message is on its way. We’ll get back to you.';
      })
      .catch(function () {
        status.textContent = 'Something went wrong sending your message — please try again.';
      })
      .then(function () {
        clearTimeout(timer);
        button.disabled = false;
        button.textContent = 'Send message';
      });
  });
})();
