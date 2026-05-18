/* ============================================================
   Área 30 — Scroll reveal observer
   Pareja de animations.css. Carga AL FINAL del <body>.
   ============================================================ */

(function () {
  'use strict';

  var SELECTOR = '.reveal-up, .reveal-fade, .reveal-scale, .reveal-stagger, .text-reveal-line';
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function showAll(els) {
    for (var i = 0; i < els.length; i++) els[i].classList.add('is-visible');
  }

  function init() {
    var els = document.querySelectorAll(SELECTOR);
    if (!els.length) return;

    if (reduced || !('IntersectionObserver' in window)) {
      showAll(els);
      return;
    }

    var io = new IntersectionObserver(function (entries, observer) {
      for (var i = 0; i < entries.length; i++) {
        if (entries[i].isIntersecting) {
          entries[i].target.classList.add('is-visible');
          observer.unobserve(entries[i].target);
        }
      }
    }, {
      threshold: 0.15,
      rootMargin: '0px 0px -40px 0px'
    });

    for (var j = 0; j < els.length; j++) io.observe(els[j]);
  }

  // Permite ejecutar también sobre nodos añadidos dinámicamente (e.g. cards fetched por JS).
  window.A30Reveal = {
    refresh: init
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

/* ============================================================
   Área 30 — Interacciones de botones (energético premium)
   Ripple, spring press feedback, magnetic CTA.
   Compañero del bloque 12–14 de animations.css.
   ============================================================ */

(function () {
  'use strict';

  var reduced = window.matchMedia &&
                window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduced) return;

  var PRESS_SELECTOR  = '.gold-btn, .ripple-btn, .filter-btn';
  var RIPPLE_SELECTOR = '.gold-btn, .ripple-btn, .filter-btn';

  /* ---- Press feedback (down → 0.96, up → spring overshoot) ---- */
  document.addEventListener('pointerdown', function (e) {
    var btn = e.target.closest(PRESS_SELECTOR);
    if (!btn || btn.disabled) return;
    btn.classList.remove('a30-spring-release');
    btn.classList.add('is-pressed');
    spawnRipple(btn, e);
  }, { passive: true });

  function releaseAll() {
    var pressed = document.querySelectorAll('.is-pressed');
    for (var i = 0; i < pressed.length; i++) {
      var el = pressed[i];
      el.classList.remove('is-pressed');
      el.classList.add('a30-spring-release');
      (function (node) {
        setTimeout(function () {
          node.classList.remove('a30-spring-release');
        }, 430);
      })(el);
    }
  }

  document.addEventListener('pointerup', releaseAll, { passive: true });
  document.addEventListener('pointercancel', releaseAll, { passive: true });
  window.addEventListener('blur', releaseAll);

  /* ---- Ripple ink ---- */
  function spawnRipple(btn, evt) {
    if (!btn.matches(RIPPLE_SELECTOR)) return;

    var rect = btn.getBoundingClientRect();
    if (rect.width < 16 || rect.height < 16) return;

    // Garantiza contención del span
    var cs = window.getComputedStyle(btn);
    if (cs.position === 'static') btn.style.position = 'relative';
    if (cs.overflow !== 'hidden') btn.style.overflow = 'hidden';

    var size = Math.max(rect.width, rect.height) * 2.2;
    var x = (evt.clientX || (rect.left + rect.width / 2)) - rect.left - size / 2;
    var y = (evt.clientY || (rect.top  + rect.height / 2)) - rect.top  - size / 2;

    var ink = document.createElement('span');
    ink.className = 'a30-ripple-ink';
    ink.style.width  = size + 'px';
    ink.style.height = size + 'px';
    ink.style.left   = x + 'px';
    ink.style.top    = y + 'px';
    btn.appendChild(ink);

    setTimeout(function () {
      if (ink.parentNode) ink.parentNode.removeChild(ink);
    }, 640);
  }

  /* ---- Magnetic CTA (opt-in con .magnetic-btn) ---- */
  function bindMagnetic(btn) {
    if (btn.__a30Magnetic) return;
    btn.__a30Magnetic = true;

    var raf = 0;
    var pendingX = 0;
    var pendingY = 0;

    function apply() {
      raf = 0;
      btn.style.setProperty('--magx', pendingX.toFixed(2) + 'px');
      btn.style.setProperty('--magy', pendingY.toFixed(2) + 'px');
    }

    btn.addEventListener('pointermove', function (e) {
      var r = btn.getBoundingClientRect();
      var nx = (e.clientX - r.left - r.width  / 2) / r.width;
      var ny = (e.clientY - r.top  - r.height / 2) / r.height;
      pendingX = Math.max(-1, Math.min(1, nx)) * 8;
      pendingY = Math.max(-1, Math.min(1, ny)) * 8;
      if (!raf) raf = requestAnimationFrame(apply);
    });

    btn.addEventListener('pointerleave', function () {
      if (raf) { cancelAnimationFrame(raf); raf = 0; }
      btn.style.setProperty('--magx', '0px');
      btn.style.setProperty('--magy', '0px');
    });
  }

  function initMagnetic() {
    var els = document.querySelectorAll('.magnetic-btn');
    for (var i = 0; i < els.length; i++) bindMagnetic(els[i]);
  }

  window.A30Buttons = {
    refreshMagnetic: initMagnetic
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initMagnetic);
  } else {
    initMagnetic();
  }
})();
