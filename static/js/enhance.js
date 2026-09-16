/* ============================================================
   PREMIUM CUSTOM SELECT DROPDOWNS
   ============================================================ */
(function initCustomSelects() {
  function buildFace(select) {
    if (select.closest('.select-wrap')) return;

    const wrap = document.createElement('div');
    wrap.className = 'select-wrap';

    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);

    const face = document.createElement('div');
    face.className = 'select-face';

    const textEl = document.createElement('span');
    textEl.className = 'select-face-text';
    textEl.textContent = select.options[select.selectedIndex]?.text || '';

    const arrow = document.createElement('span');
    arrow.className = 'select-face-arrow';
    arrow.innerHTML = '<span class="material-symbols-outlined">expand_more</span>';

    face.appendChild(textEl);
    face.appendChild(arrow);
    wrap.appendChild(face);

    select.addEventListener('change', () => {
      textEl.textContent = select.options[select.selectedIndex]?.text || '';
    });
  }

  function initAll() {
    document.querySelectorAll('select').forEach(buildFace);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
  } else {
    initAll();
  }
})();
