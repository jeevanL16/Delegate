/* ============================================================
   Delegate: Resolve — Custom Client Script
   Injected via .chainlit/config.toml -> [UI] custom_js = "/public/custom.js"
   ============================================================ */

(function () {
  'use strict';

  // Force dark theme in localStorage and on root html element
  try {
    if (localStorage.getItem('theme') !== 'dark') {
      localStorage.setItem('theme', 'dark');
    }
  } catch (e) {}
  document.documentElement.classList.add('dark');
  document.documentElement.setAttribute('data-theme', 'dark');

  function injectHeader() {
    if (document.getElementById('delegate-header-bar')) {
      return;
    }

    const header = document.createElement('header');
    header.id = 'delegate-header-bar';
    header.innerHTML = `
      <div class="delegate-header-inner">
        <div class="delegate-header-brand">
          <img src="/public/logo.svg" alt="Delegate" class="delegate-header-logo" />
          <span class="delegate-header-word">Delegate : Resolve</span>
        </div>
        <div class="delegate-header-trust">
          <img src="/public/icons/shield-check.svg" width="14" height="14" alt="Secured" />
          <span>🔒 Secured by Delegate Policy Engine</span>
        </div>
      </div>
    `;

    document.body.prepend(header);
    document.body.classList.add('has-delegate-header');
  }

  function hideThemeToggle() {
    // Hide theme toggle buttons to lock theme to dark mode
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

  function applyPolicyOutcomeShine() {
    const steps = document.querySelectorAll('.step, [class*="step"], [data-testid="step"]');
    steps.forEach((step) => {
      if (
        step.textContent &&
        step.textContent.includes('Policy Outcome') &&
        !step.classList.contains('delegate-shine')
      ) {
        step.classList.add('delegate-shine');
      }
    });
  }

  function init() {
    injectHeader();
    hideThemeToggle();
    applyPolicyOutcomeShine();

    const observer = new MutationObserver(() => {
      injectHeader();
      hideThemeToggle();
      applyPolicyOutcomeShine();
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
