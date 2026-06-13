// Progressive disclosure: the overview is shown on load; clicking a card
// reveals the detail sections and scrolls to the chosen one.
(function () {
  var page = document.querySelector('.pd-page');
  if (!page) return;

  function reveal(targetId) {
    page.classList.add('revealed');
    var el = targetId && document.getElementById(targetId);
    if (el) {
      // Let the sections paint before scrolling to the target.
      requestAnimationFrame(function () {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    }
  }

  document.querySelectorAll('.pd-card').forEach(function (card) {
    card.addEventListener('click', function (e) {
      e.preventDefault();
      reveal(card.getAttribute('data-target'));
    });
  });
})();
