/* 主题切换 + 返回顶部 + 小交互（与 app.js 无耦合，可独立加载） */
(function () {
  'use strict';
  var KEY = 'wxbot-theme';

  function applyTheme(mode) {
    document.documentElement.setAttribute('data-theme', mode);
    try { localStorage.setItem(KEY, mode); } catch (e) {}
    var btn = document.getElementById('themeToggle');
    if (btn) btn.textContent = mode === 'dark' ? '☀️ 浅色' : '🌙 深色';
  }

  function initTheme() {
    var saved = null;
    try { saved = localStorage.getItem(KEY); } catch (e) {}
    // 支持 ?theme=dark / ?theme=light 直接指定（方便分享深色链接、截图）
    var q = (location.search.match(/[?&]theme=(dark|light)\b/) || [])[1];
    if (q) saved = q;
    if (!saved && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      saved = 'dark';
    }
    applyTheme(saved === 'dark' ? 'dark' : 'light');
    var btn = document.getElementById('themeToggle');
    if (btn) {
      btn.addEventListener('click', function () {
        var cur = document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
        applyTheme(cur === 'dark' ? 'light' : 'dark');
      });
    }
  }

  function initBackTop() {
    var btn = document.getElementById('backTop');
    if (!btn) return;
    function onScroll() {
      if (window.scrollY > 500) btn.classList.add('show');
      else btn.classList.remove('show');
    }
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
    btn.addEventListener('click', function () {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { initTheme(); initBackTop(); });
  } else {
    initTheme(); initBackTop();
  }
})();
