/* 工作台 ↔ 房间过渡 · 中间那颗 Q 头当加载 */
(function () {
  var KEY = 'dk_mode_transit';
  var FACE = '/companion/assets/daimon-face.png?v=20260830q';
  var OUT_MS = 520;
  var HOLD_MS = 380;

  function readFlag() {
    try { return JSON.parse(sessionStorage.getItem(KEY) || ''); }
    catch (e) { return null; }
  }

  function pageDark() {
    var b = document.body;
    if (!b) return false;
    if (b.classList.contains('night')) return true;
    if (b.classList.contains('day')) return false;
    if (b.classList.contains('theme-sepia')) return false;
    return true;
  }

  function ensure() {
    var el = document.getElementById('dkTransit');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'dkTransit';
    el.className = 'dk-transit';
    el.setAttribute('aria-hidden', 'true');
    el.innerHTML =
      '<div class="dk-transit-stage">' +
        '<span class="dk-transit-ring"></span>' +
        '<span class="dk-transit-ring r2"></span>' +
        '<img class="dk-transit-face" src="' + FACE + '" alt="">' +
      '</div>';
    document.body.insertBefore(el, document.body.firstChild);
    return el;
  }

  function play(url) {
    if (!url) return;
    var dark = pageDark();
    try {
      sessionStorage.setItem(KEY, JSON.stringify({ to: url, dark: dark }));
    } catch (e) {}
    var el = ensure();
    el.classList.toggle('dark', dark);
    el.classList.add('on');
    el.classList.remove('out');
    setTimeout(function () { location.href = url; }, OUT_MS);
  }

  function inbound() {
    var st = readFlag();
    if (!st) {
      document.documentElement.classList.remove('dk-transit-hold', 'dk-transit-dark');
      return;
    }
    try { sessionStorage.removeItem(KEY); } catch (e) {}
    var el = ensure();
    el.classList.toggle('dark', !!st.dark);
    el.classList.add('on');
    document.documentElement.classList.remove('dk-transit-hold', 'dk-transit-dark');
    requestAnimationFrame(function () {
      setTimeout(function () {
        el.classList.add('out');
        setTimeout(function () { el.classList.remove('on', 'out'); }, 340);
      }, HOLD_MS);
    });
  }

  window.dkModeTransit = { play: play };

  document.addEventListener('click', function (e) {
    var a = e.target.closest('a[data-mode-transit]');
    if (!a) return;
    if (e.defaultPrevented) return;
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (a.target === '_blank') return;
    var href = a.getAttribute('href');
    if (!href) return;
    e.preventDefault();
    play(href);
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', inbound);
  } else {
    inbound();
  }
})();
