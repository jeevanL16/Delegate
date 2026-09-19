/* ============================================================
   Delegate: Resolve — Custom Client Script (Light Mode Enhancements)
   ============================================================ */

(function () {
  'use strict';

  // Force light theme in localStorage and on root html element
  try {
    localStorage.setItem('theme', 'light');
  } catch (e) {}
  document.documentElement.classList.remove('dark');
  document.documentElement.classList.add('light');
  document.documentElement.setAttribute('data-theme', 'light');

  function injectHeader() {
    if (document.getElementById('delegate-header-bar')) {
      return;
    }

    const header = document.createElement('header');
    header.id = 'delegate-header-bar';
    header.innerHTML = `
      <div class="delegate-header-inner">
        <div class="delegate-header-brand">
          <img src="/public/logo.svg" alt="Delegate" width="26" height="26" class="delegate-header-logo" />
          <span class="delegate-header-word">Delegate : Resolve</span>
        </div>
        <div class="delegate-header-trust">
          <span class="pulse-dot"></span>
          <span>Secured by Policy Engine</span>
        </div>
      </div>
    `;

    document.body.prepend(header);
    document.body.classList.add('has-delegate-header');
  }

  function hideThemeToggle() {
    const selectors = [
      '#theme-toggle',
      'button[aria-label*="theme" i]',
      'button[aria-label*="mode" i]',
      'button[aria-label*="light" i]',
      'button[aria-label*="dark" i]',
      'button[id*="theme" i]',
      '.cl-theme-toggle',
      'button:has(svg.lucide-sun)',
      'button:has(svg.lucide-moon)',
    ];
    selectors.forEach((sel) => {
      try {
        document.querySelectorAll(sel).forEach((el) => {
          el.style.setProperty('display', 'none', 'important');
        });
      } catch (e) {}
    });

    // Also hide "Readme" link if present in header
    document.querySelectorAll('a, button, span, p').forEach((el) => {
      if (el.textContent && el.textContent.trim().toLowerCase() === 'readme') {
        const parent = el.closest('a') || el;
        parent.style.setProperty('display', 'none', 'important');
      }
    });
  }

  function init() {
    injectHeader();
    hideThemeToggle();

    const observer = new MutationObserver(() => {
      injectHeader();
      hideThemeToggle();
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true,
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
