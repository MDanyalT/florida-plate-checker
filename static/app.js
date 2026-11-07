/* Florida Plate Finder — progressive enhancement for the server-rendered pages. */
(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const fmt = (n) => Number(n).toLocaleString();
  const ACTIVE = ['queued', 'running', 'captcha', 'stopping'];
  const PLATE_RE = /^[A-Z0-9 -]+$/;
  const body = document.body;
  const maxLen = Number(document.querySelector('[data-plate-input]')?.maxLength) || 7;

  function debounce(fn, wait = 250) {
    let timer;
    return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), wait); };
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  /* ------------------------------------------------------------ Toasts */
  function toast(message, { kind = 'info', html = false, timeout = 6000 } = {}) {
    const region = $('#toasts');
    if (!region) return;
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
    el.innerHTML = `<p>${html ? message : escapeHtml(message)}</p><button type="button" aria-label="Dismiss">×</button>`;
    el.querySelector('button').addEventListener('click', () => el.remove());
    region.appendChild(el);
    if (timeout) setTimeout(() => el.remove(), timeout);
  }

  /* ------------------------------------------------------------ Dialog */
  function confirmDialog({ title = 'Are you sure?', message = '', confirmLabel = 'Continue', danger = false } = {}) {
    const dialog = $('#confirm-dialog');
    if (!dialog || typeof dialog.showModal !== 'function') {
      return Promise.resolve(window.confirm(`${title}\n\n${message}`));
    }
    $('#confirm-title', dialog).textContent = title;
    const bodyEl = $('#confirm-body', dialog);
    bodyEl.innerHTML = '';
    String(message).split('\n\n').forEach((para) => {
      const p = document.createElement('p');
      p.textContent = para;
      bodyEl.appendChild(p);
    });
    const ok = $('#confirm-ok', dialog);
    ok.textContent = confirmLabel;
    ok.classList.toggle('is-danger', danger);
    dialog.returnValue = '';
    dialog.showModal();
    ok.focus();
    return new Promise((resolve) => {
      dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), { once: true });
    });
  }

  function checkMessage(count) {
    return `${count} plate${count === 1 ? '' : 's'} will be checked on the official FLHSMV site. A browser window will open on this computer, and checks run five at a time with short pauses.\n\nIf the site asks you to prove you're human, complete it in that window, then press Enter in the app's terminal.`;
  }

  /* ------------------------------------------------------------ Basics */
  $$('[data-dismiss]').forEach((button) => button.addEventListener('click', () => button.closest('.flash')?.remove()));

  const menu = $('[data-menu]');
  if (menu) {
    document.addEventListener('click', (event) => { if (!menu.contains(event.target)) menu.open = false; });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && menu.open) { menu.open = false; $('summary', menu).focus(); }
    });
  }

  $$('.help-tip-button').forEach((button) => {
    button.addEventListener('click', () => button.parentElement.classList.toggle('is-open'));
    button.addEventListener('blur', () => button.parentElement.classList.remove('is-open'));
  });

  $$('[data-autosubmit]').forEach((el) => el.addEventListener('change', () => el.form?.requestSubmit()));

  // Forms that need a confirmation (destructive or significant actions).
  $$('form[data-confirm]').forEach((form) => {
    form.addEventListener('submit', async (event) => {
      if (form.dataset.confirmed === 'yes') return;
      event.preventDefault();
      const ok = await confirmDialog({
        title: form.dataset.confirmTitle || 'Are you sure?',
        message: form.dataset.confirm,
        confirmLabel: form.dataset.confirmAction || 'Continue',
        danger: 'confirmDanger' in form.dataset,
      });
      if (ok) { form.dataset.confirmed = 'yes'; form.submit(); }
    });
  });

  // Single-plate "Check" buttons outside the bulk form: show a busy state.
  $$('form[action="/runs/start"]').forEach((form) => {
    form.addEventListener('submit', () => {
      const button = $('button[type="submit"]', form);
      if (button) { button.disabled = true; button.innerHTML = '<span class="spinner small" aria-hidden="true"></span>Starting…'; }
    });
  });

  /* ---------------------------------------------------- Plate previews */
  function setPlate(plateEl, text) {
    if (!plateEl) return;
    const textEl = $('[data-plate-text]', plateEl) || $('.plate-text', plateEl);
    const placeholder = textEl.dataset.placeholder || '';
    const shown = text || placeholder;
    textEl.textContent = shown;
    textEl.classList.toggle('is-placeholder', !text);
    plateEl.style.setProperty('--len', Math.max(shown.length, 3));
    plateEl.setAttribute('aria-label', `License plate preview: ${shown}`);
  }

  function miniPlate(text) {
    return `<div class="plate plate-xs" style="--len:${Math.max(text.length, 3)}" aria-hidden="true"><span class="plate-text">${escapeHtml(text)}</span></div>`;
  }

  const STATUS = {
    Available: { key: 'available', icon: '✓', short: 'Available' },
    'Not available': { key: 'unavailable', icon: '✕', short: 'Unavailable' },
    Invalid: { key: 'review', icon: '!', short: 'Needs verification' },
    Unknown: { key: 'review', icon: '!', short: 'Needs verification' },
    Error: { key: 'review', icon: '!', short: 'Needs verification' },
  };
  function badge(status) {
    const s = STATUS[status] || { key: 'unchecked', icon: '○', short: 'Not checked' };
    return `<span class="badge badge-${s.key}"><span class="badge-icon" aria-hidden="true">${s.icon}</span><span>${s.short}</span></span>`;
  }

  /* ----------------------------------------------------- Home: quick check */
  const quickForm = $('[data-quick-check-form]');
  if (quickForm) {
    const input = $('[data-plate-input]', quickForm);
    const preview = $('[data-plate-preview]', quickForm);
    const errorEl = $('#plate-error');
    const counter = $('[data-char-count]', quickForm);
    const known = $('#plate-known');
    const ideasLink = $('[data-ideas-link]', quickForm);

    const validate = (value) => {
      if (!value) return 'Type a plate first.';
      if (!PLATE_RE.test(value)) return 'Plates can only use letters, numbers, spaces, and hyphens.';
      if (value.length > maxLen) return `That's ${value.length} characters; Florida plates fit up to ${maxLen}.`;
      return '';
    };
    const showError = (message) => {
      errorEl.textContent = message;
      errorEl.hidden = !message;
      input.setAttribute('aria-invalid', message ? 'true' : 'false');
    };

    const lookup = debounce(async (value) => {
      if (!value || validate(value)) { known.hidden = true; return; }
      try {
        const response = await fetch(`/api/plates/lookup?plate=${encodeURIComponent(value)}`);
        const data = await response.json();
        if (input.value.trim().toUpperCase() !== value) return;
        if (!data.saved) { known.hidden = true; return; }
        const when = data.last_checked ? `Checked ${escapeHtml(data.last_checked)}.` : 'Saved, not checked yet.';
        known.innerHTML = `<span class="badge badge-${data.status.key}"><span class="badge-icon" aria-hidden="true">${data.status.icon}</span><span>${escapeHtml(data.status.label)}</span></span>
          <span class="muted">${when}</span><a href="/plates/${data.id}">See details</a>`;
        known.hidden = false;
      } catch (_) { known.hidden = true; }
    }, 300);

    const update = () => {
      const value = input.value.trim().toUpperCase();
      setPlate(preview, value);
      counter.textContent = value ? `${value.length}/${maxLen}` : '';
      if (errorEl.textContent && !validate(value)) showError('');
      if (value && !PLATE_RE.test(value)) showError(validate(value));
      ideasLink.href = value ? `/explore?mode=ideas&text=${encodeURIComponent(input.value.trim())}` : '/explore?mode=ideas';
      lookup(value);
    };
    input.addEventListener('input', update);
    if (input.value) update();

    quickForm.addEventListener('submit', (event) => {
      const message = validate(input.value.trim().toUpperCase());
      if (message) {
        event.preventDefault();
        showError(message);
        input.focus();
        return;
      }
      const submitter = event.submitter;
      if (submitter && submitter.value === 'check') {
        submitter.disabled = true;
        submitter.innerHTML = '<span class="spinner small" aria-hidden="true"></span>Opening official site…';
        // Keep the action value even though the button is now disabled.
        const hidden = document.createElement('input');
        hidden.type = 'hidden'; hidden.name = 'action'; hidden.value = 'check';
        quickForm.appendChild(hidden);
      }
    });

    $$('[data-focus-input]').forEach((link) => link.addEventListener('click', (event) => {
      event.preventDefault();
      input.focus();
      input.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }));
  }

  /* ---------------------------------------------- Simple selection forms */
  $$('[data-selection-form]').forEach((form) => {
    const toggle = $('[data-select-all]', form);
    const checks = $$('input[name="plates"]', form);
    const count = $('[data-selection-count]', form);
    const refresh = () => {
      const selected = checks.filter((item) => item.checked).length;
      if (count) count.textContent = `${selected} selected`;
      if (toggle) {
        toggle.checked = selected === checks.length && checks.length > 0;
        toggle.indeterminate = selected > 0 && selected < checks.length;
      }
    };
    toggle?.addEventListener('change', () => { checks.forEach((item) => { item.checked = toggle.checked; }); refresh(); });
    checks.forEach((item) => item.addEventListener('change', refresh));
    refresh();
  });

  /* ------------------------------------------------- Saved plates bulk */
  const bulkForm = $('[data-bulk-form]');
  if (bulkForm) {
    const rows = $$('[data-row-check]');
    const pageToggle = $('[data-select-page]');
    const bar = $('[data-action-bar]');
    const countEl = bar && $('[data-selected-count]', bar);
    const refresh = () => {
      const selected = rows.filter((row) => row.checked).length;
      if (countEl) countEl.textContent = selected;
      bar?.classList.toggle('is-empty', selected === 0);
      $$('[data-needs-selection]').forEach((button) => { button.disabled = selected === 0; });
      if (pageToggle) {
        pageToggle.checked = selected > 0 && selected === rows.length;
        pageToggle.indeterminate = selected > 0 && selected < rows.length;
      }
      rows.forEach((row) => row.closest('.plate-card')?.classList.toggle('is-selected', row.checked));
    };
    pageToggle?.addEventListener('change', () => { rows.forEach((row) => { row.checked = pageToggle.checked; }); refresh(); });
    rows.forEach((row) => row.addEventListener('change', refresh));
    refresh();

    bulkForm.addEventListener('submit', async (event) => {
      if (bulkForm.dataset.confirmed === 'yes') return;
      const submitter = event.submitter;
      const selected = rows.filter((row) => row.checked).length;
      event.preventDefault();
      if (!selected) { toast('Select at least one plate first.'); return; }
      let ok = true;
      if (submitter?.hasAttribute('data-bulk-check')) {
        const max = Number(bulkForm.dataset.max || 500);
        if (selected > max) { toast(`You can check up to ${max} plates at a time.`, { kind: 'error' }); return; }
        ok = await confirmDialog({ title: `Check ${selected} plate${selected === 1 ? '' : 's'}?`, message: checkMessage(selected), confirmLabel: 'Start checking' });
        if (ok && selected > Number(bulkForm.dataset.threshold || 100)) bulkForm.elements.confirm_large.value = 'yes';
      } else if (submitter?.hasAttribute('data-bulk-delete')) {
        ok = await confirmDialog({
          title: `Remove ${selected} plate${selected === 1 ? '' : 's'}?`,
          message: 'They and their check history will be deleted from this computer. This can\'t be undone.',
          confirmLabel: 'Remove', danger: true,
        });
        if (ok) bulkForm.elements.confirm_delete.value = 'yes';
      }
      if (!ok) return;
      bulkForm.dataset.confirmed = 'yes';
      if (submitter) {
        if (submitter.formAction && submitter.getAttribute('formaction')) bulkForm.action = submitter.formAction;
        if (submitter.name) {
          const hidden = document.createElement('input');
          hidden.type = 'hidden'; hidden.name = submitter.name; hidden.value = submitter.value;
          bulkForm.appendChild(hidden);
        }
      }
      bulkForm.submit();
    });
  }

  /* ------------------------------------------------------- Live run */
  let lastRunActive = null;
  function updateRun(run) {
    const panel = $('#live-run');
    if (!panel) return;
    const active = Boolean(run && ACTIVE.includes(run.status));
    if (lastRunActive === true && !active && run) {
      const summary = `${run.checked_count} checked · ${run.available_count} available · ${run.unavailable_count} unavailable`;
      const label = run.status === 'completed' ? 'Check finished' : run.status === 'stopped' ? 'Check stopped' : 'Check ended';
      toast(`<strong>${label}.</strong> ${summary}. <a href="/history?run_id=${run.id}">See results</a>`, { html: true, kind: run.status === 'failed' ? 'error' : 'info', timeout: 0 });
      if ($('[data-watch-run]')) setTimeout(() => window.location.reload(), 600);
    }
    lastRunActive = active;
    panel.hidden = !active;
    if (!active) return;
    const percent = run.total_candidates ? Math.round((run.checked_count / run.total_candidates) * 100) : 0;
    const titles = {
      queued: 'Getting ready to check…',
      running: `Checking ${run.total_candidates} plate${run.total_candidates === 1 ? '' : 's'} on the official site`,
      captcha: 'Action needed: verify you’re human',
      stopping: 'Stopping safely…',
    };
    panel.classList.toggle('is-captcha', run.status === 'captcha');
    $('#run-title', panel).textContent = titles[run.status] || 'Checking';
    $('#run-progress-bar', panel).style.width = `${percent}%`;
    $('#run-progress', panel).setAttribute('aria-valuenow', percent);
    const set = (id, value) => { const el = $(`#${id}`, panel); if (el) el.textContent = value; };
    set('run-checked', run.checked_count);
    set('run-total', run.total_candidates);
    set('run-batch', run.current_batch);
    set('run-available', run.available_count);
    set('run-unavailable', run.unavailable_count);
    set('run-review', run.invalid_count + run.unknown_count + run.error_count);
    set('run-invalid', run.invalid_count);
    set('run-unknown', run.unknown_count);
    set('run-errors', run.error_count);
    set('run-last', run.last_processed_plate || '—');
    set('run-message', run.status === 'captcha'
      ? 'Complete the verification in the Chromium window, then press Enter in the terminal running the app.'
      : run.status === 'stopping'
        ? 'Finishing the current step, then the browser will close. Results so far are saved.'
        : `${percent}% done · results save after every plate · keep the browser window open`);
  }

  let pollDelay = 2000;
  async function pollRun() {
    try {
      const response = await fetch('/api/runs/current', { headers: { Accept: 'application/json' } });
      if (response.ok) updateRun((await response.json()).run);
      pollDelay = lastRunActive ? 2000 : 5000;
    } catch (_) {
      pollDelay = 10000; // Local server stopped; back off quietly.
    }
    window.setTimeout(pollRun, pollDelay);
  }
  pollRun();

  /* ======================================================== Explore */
  const tabs = $$('[data-mode-tab]');
  function showMode(mode, push = true) {
    tabs.forEach((tab) => {
      const on = tab.dataset.modeTab === mode;
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      tab.tabIndex = on ? 0 : -1;
      $(`#${tab.getAttribute('aria-controls')}`).hidden = !on;
    });
    if (push) {
      const url = new URL(window.location.href);
      if (url.pathname.endsWith('/preview')) url.pathname = '/explore';
      url.searchParams.set('mode', mode);
      url.searchParams.delete('text');
      history.replaceState(null, '', url);
    }
    const form = $(`#panel-${mode} [data-estimate-form]`);
    if (form) form.dispatchEvent(new Event('estimate'));
  }
  if (tabs.length) {
    tabs.forEach((tab, index) => {
      tab.tabIndex = tab.getAttribute('aria-selected') === 'true' ? 0 : -1;
      tab.addEventListener('click', (event) => { event.preventDefault(); showMode(tab.dataset.modeTab); });
      tab.addEventListener('keydown', (event) => {
        const delta = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
        if (!delta) return;
        event.preventDefault();
        const next = tabs[(index + delta + tabs.length) % tabs.length];
        next.focus();
        showMode(next.dataset.modeTab);
      });
    });
    $$('[data-mode-link]').forEach((link) => link.addEventListener('click', (event) => { event.preventDefault(); showMode(link.dataset.modeLink); }));
  }

  /* ----------------------------------------------- Live combination counts */
  function wireEstimate(form) {
    const countEl = $('[data-estimate-count]', form);
    const examplesEl = $('[data-estimate-examples]', form);
    const warningEl = $('[data-estimate-warning]', form);
    const preview = $('[data-estimate-preview] [data-plate-preview]', form);
    const submit = $('button[type="submit"]:not([data-reshuffle])', form);
    const isIdeas = form.elements.pattern_type?.value === 'plate_ideas';
    const noun = (n) => (isIdeas ? (n === 1 ? 'idea' : 'ideas') : (n === 1 ? 'plate' : 'plates'));
    let seq = 0;

    const warn = (message, error = false) => {
      if (!warningEl) return;
      warningEl.hidden = !message;
      warningEl.textContent = message || '';
      warningEl.classList.toggle('is-error', error);
    };

    const run = debounce(async () => {
      if (isIdeas && !form.elements.word.value.trim()) {
        countEl.textContent = "Type something to see how many ideas you'll get.";
        examplesEl.innerHTML = '';
        setPlate(preview, '');
        return;
      }
      const id = ++seq;
      form.classList.add('is-estimating');
      try {
        const response = await fetch('/api/generator/estimate', { method: 'POST', body: new FormData(form) });
        const data = await response.json();
        if (id !== seq) return;
        examplesEl.innerHTML = (data.examples || []).map((e) => `<span class="example-chip">${escapeHtml(e)}</span>`).join('');
        setPlate(preview, (data.examples || [])[0] || '');
        if (data.count === null || data.count === undefined) {
          countEl.innerHTML = '<strong>—</strong>Fix the setting below to continue';
          warn(data.error, true);
          if (submit) submit.disabled = true;
          return;
        }
        if (data.too_large) {
          countEl.innerHTML = `<strong>Up to ${fmt(data.count)}</strong>possible combinations (estimate)`;
          warn(data.error, true);
          if (submit) submit.disabled = true;
          return;
        }
        if (submit) submit.disabled = data.count === 0;
        const extras = [];
        if (data.rejected) extras.push(`${fmt(data.rejected)} too long, skipped`);
        if (data.duplicates) extras.push(`${fmt(data.duplicates)} duplicates removed`);
        countEl.innerHTML = `<strong>${fmt(data.count)}</strong>${noun(data.count)}${extras.length ? ` <span class="small">· ${extras.join(' · ')}</span>` : ''}`;
        if (data.count === 0) warn(data.error || `Nothing fits in ${maxLen} characters. Try something shorter.`, true);
        else if (data.count > 5000) warn(`That's a lot. You'll preview them page by page, and you can check up to 500 at a time.`);
        else if (data.count > 500) warn('More than 500 combinations. You can check up to 500 at a time.');
        else warn('');
      } catch (_) {
        if (id === seq) countEl.textContent = 'Couldn’t calculate right now.';
      } finally {
        if (id === seq) form.classList.remove('is-estimating');
      }
    }, 220);

    form.addEventListener('input', run);
    form.addEventListener('change', run);
    form.addEventListener('estimate', run);
    form.addEventListener('submit', () => {
      if (submit) { submit.disabled = true; submit.innerHTML = '<span class="spinner small" aria-hidden="true"></span>Creating…'; }
      // Re-enable on back/forward cache restores.
      window.addEventListener('pageshow', () => { if (submit) { submit.disabled = false; submit.textContent = isIdeas ? 'Show ideas' : 'Preview combinations'; } }, { once: true });
    });
    if (!form.closest('[hidden]')) run();
  }

  /* --------------------------------------------------------- Ideas mode */
  const ideasForm = $('#panel-ideas [data-estimate-form]');
  if (ideasForm) {
    const surprise = $('[data-surprise]', ideasForm);
    const reshuffle = $('[data-reshuffle]', ideasForm);
    surprise?.addEventListener('change', () => { reshuffle.hidden = !surprise.checked; });
    reshuffle?.addEventListener('click', () => {
      const seed = $('[data-seed]', ideasForm);
      seed.value = String(Number(seed.value || 0) + 1);
    });
  }

  /* ------------------------------------------------------ Preset patterns */
  const presetForm = $('[data-preset-form]');
  if (presetForm) {
    const radios = $$('[data-pattern-radio]', presetForm);
    const rangeLabel = $('[data-range-label]', presetForm);
    const sync = () => {
      const chosen = radios.find((r) => r.checked)?.value;
      $$('[data-for]', presetForm).forEach((group) => {
        const on = group.dataset.for.split(' ').includes(chosen);
        group.hidden = !on;
        $$('input, select, textarea', group).forEach((field) => { field.disabled = !on; });
      });
      if (rangeLabel) rangeLabel.textContent = chosen === 'keyword_variations' ? 'Add numbers from' : 'Numbers from';
    };
    radios.forEach((r) => r.addEventListener('change', sync));
    const wanted = new URLSearchParams(window.location.search).get('pattern');
    const match = radios.find((r) => r.value === wanted);
    if (match) match.checked = true;
    sync();
    $$('[data-open-template]').forEach((link) => link.addEventListener('click', (event) => {
      event.preventDefault();
      const radio = radios.find((r) => r.value === 'custom_template');
      if (radio) { radio.checked = true; sync(); }
      showMode('patterns');
      presetForm.querySelector('[name="template"]')?.focus();
    }));
  }

  /* ------------------------------------------------------ Pattern builder */
  const builderForm = $('[data-builder-form]');
  if (builderForm) {
    const slotsInput = $('[data-slots-input]', builderForm);
    const row = $('[data-slot-row]', builderForm);
    const editor = $('[data-slot-editor]', builderForm);
    const kindSel = $('[data-slot-kind]', editor);
    const valueInput = $('[data-slot-value]', editor);
    const valueWrap = $('[data-slot-value-wrap]', editor);
    const valueLabel = $('[data-slot-value-label]', editor);
    const linkSel = $('[data-slot-link]', editor);
    const linkWrap = $('[data-slot-link-wrap]', editor);
    const optional = $('[data-slot-optional]', editor);
    const optionalWrap = $('[data-slot-optional-wrap]', editor);
    const summaryEl = $('[data-pattern-summary]', builderForm);
    const MAX_SLOTS = 12;

    const PRESETS = {
      word2: [{ kind: 'fixed', value: 'SUN' }, { kind: 'digit' }, { kind: 'digit' }],
      letter2: [{ kind: 'letter' }, { kind: 'digit' }, { kind: 'digit' }],
      letters3: [{ kind: 'letter' }, { kind: 'letter' }, { kind: 'letter' }],
      mirror: [{ kind: 'digit' }, { kind: 'digit' }, { kind: 'digit', link: 1 }, { kind: 'digit', link: 0 }],
      initials: [{ kind: 'letter' }, { kind: 'letter' }, { kind: 'fixed', value: '26' }],
    };
    let slots;
    try { slots = JSON.parse(slotsInput.value || 'null'); } catch (_) { slots = null; }
    if (!Array.isArray(slots) || !slots.length) slots = PRESETS.word2.map((s) => ({ ...s }));
    let selected = 0;

    const describe = (slot, index) => {
      if (slot.link !== null && slot.link !== undefined) return { glyph: `=${slot.link + 1}`, label: `Same as spot ${slot.link + 1}` };
      switch (slot.kind) {
        case 'fixed': return { glyph: (slot.value || '…').toUpperCase(), label: 'Fixed text' };
        case 'letter': return { glyph: 'A–Z', label: 'Any letter' };
        case 'digit': return { glyph: '0–9', label: 'Any digit' };
        case 'alnum': return { glyph: 'A·9', label: 'Letter or digit' };
        case 'custom': {
          const chars = Array.from(new Set((slot.value || '').toUpperCase().replace(/[^A-Z0-9]/g, '')));
          return { glyph: chars.length ? (chars.length > 3 ? `${chars.slice(0, 3).join('')}…` : chars.join('')) : '…', label: `One of ${chars.length || 0}` };
        }
        default: return { glyph: '?', label: `Spot ${index + 1}` };
      }
    };

    const sanitizeLinks = () => {
      slots.forEach((slot, index) => {
        if (slot.link === undefined || slot.link === '' || slot.link === null) { slot.link = null; return; }
        const target = slots[slot.link];
        if (slot.link >= index || !target || target.kind === 'fixed') slot.link = null;
        else if (target.link !== null && target.link !== undefined) slot.link = target.link;
      });
    };

    const humanSummary = () => slots.map((slot, i) => {
      const d = describe(slot, i);
      if (slot.link !== null && slot.link !== undefined) return d.label.toLowerCase();
      if (slot.kind === 'fixed') return `“${(slot.value || '').toUpperCase()}”`;
      const base = slot.kind === 'custom' ? `one of ${(slot.value || '').toUpperCase()}` : d.label.toLowerCase();
      return base + (slot.optional ? ' (optional)' : '');
    }).join(' + ');

    const save = () => {
      sanitizeLinks();
      slotsInput.value = JSON.stringify(slots.map((s) => ({
        kind: s.kind, value: s.value || '', optional: Boolean(s.optional), link: s.link ?? null,
      })));
      if (summaryEl) summaryEl.textContent = humanSummary();
      builderForm.dispatchEvent(new Event('estimate'));
    };

    const renderRow = () => {
      row.innerHTML = '';
      slots.forEach((slot, index) => {
        const d = describe(slot, index);
        const linked = slot.link !== null && slot.link !== undefined;
        const tile = document.createElement('button');
        tile.type = 'button';
        tile.className = `slot slot-${linked ? 'linked' : slot.kind}${slot.optional && !linked ? ' slot-optional' : ''}`;
        tile.setAttribute('role', 'option');
        tile.setAttribute('aria-selected', index === selected ? 'true' : 'false');
        tile.setAttribute('aria-label', `Spot ${index + 1}: ${d.label}${slot.kind === 'fixed' && !linked ? ` ${slot.value || ''}` : ''}${slot.optional ? ', optional' : ''}`);
        tile.innerHTML = `<span class="slot-num" aria-hidden="true">${index + 1}</span><span class="slot-glyph" aria-hidden="true">${escapeHtml(d.glyph)}</span><span class="slot-kind" aria-hidden="true">${escapeHtml(d.label)}</span>`;
        tile.addEventListener('click', () => { selected = index; render(); valueWrap.hidden ? kindSel.focus() : valueInput.focus(); });
        tile.addEventListener('keydown', (event) => {
          if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
            event.preventDefault();
            selected = Math.max(0, Math.min(slots.length - 1, selected + (event.key === 'ArrowRight' ? 1 : -1)));
            render();
            row.children[selected]?.focus();
          } else if (event.key === 'Delete' || event.key === 'Backspace') {
            event.preventDefault(); removeSlot();
          }
        });
        row.appendChild(tile);
      });
    };

    const renderEditor = () => {
      const slot = slots[selected];
      editor.hidden = !slot;
      if (!slot) return;
      $('[data-slot-editor-title]', editor).textContent = `Spot ${selected + 1}`;
      const linked = slot.link !== null && slot.link !== undefined;
      kindSel.value = slot.kind;
      kindSel.disabled = linked;
      valueWrap.hidden = linked || !['fixed', 'custom'].includes(slot.kind);
      valueLabel.textContent = slot.kind === 'fixed' ? 'Text (letters, numbers, spaces, hyphens)' : 'Allowed characters, e.g. AEIOU or 1379';
      valueInput.maxLength = slot.kind === 'fixed' ? maxLen : 36;
      if (document.activeElement !== valueInput) valueInput.value = (slot.value || '').toUpperCase();
      // "Same as" choices: earlier, non-fixed, non-linked spots.
      linkSel.innerHTML = '<option value="">Varies on its own</option>' + slots.slice(0, selected)
        .map((s, i) => (s.kind !== 'fixed' && (s.link === null || s.link === undefined)) ? `<option value="${i}">Same as spot ${i + 1}</option>` : '')
        .join('');
      linkSel.value = linked ? String(slot.link) : '';
      linkWrap.hidden = slot.kind === 'fixed' || linkSel.options.length <= 1;
      optional.checked = Boolean(slot.optional);
      optionalWrap.hidden = slot.kind === 'fixed' || linked;
      $('[data-move="-1"]', editor).disabled = selected === 0;
      $('[data-move="1"]', editor).disabled = selected === slots.length - 1;
      $('[data-remove-slot]', editor).disabled = slots.length <= 1;
    };

    const render = () => { renderRow(); renderEditor(); };

    function removeSlot() {
      if (slots.length <= 1) return;
      const gone = selected;
      slots.splice(gone, 1);
      slots.forEach((s) => {
        if (s.link === gone) s.link = null;
        else if (s.link !== null && s.link !== undefined && s.link > gone) s.link -= 1;
      });
      selected = Math.max(0, Math.min(selected, slots.length - 1));
      render(); save();
      row.children[selected]?.focus();
    }

    kindSel.addEventListener('change', () => {
      const slot = slots[selected];
      slot.kind = kindSel.value;
      if (slot.kind === 'fixed' && !slot.value) slot.value = 'A';
      if (slot.kind === 'custom' && !/[A-Z0-9]/i.test(slot.value || '')) slot.value = 'AEIOU';
      if (slot.kind === 'fixed') slot.optional = false;
      render(); save();
    });
    valueInput.addEventListener('input', () => {
      const slot = slots[selected];
      const cleaned = slot.kind === 'fixed'
        ? valueInput.value.toUpperCase().replace(/[^A-Z0-9 -]/g, '')
        : valueInput.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
      if (cleaned !== valueInput.value) valueInput.value = cleaned;
      slot.value = cleaned;
      renderRow(); save();
    });
    linkSel.addEventListener('change', () => {
      slots[selected].link = linkSel.value === '' ? null : Number(linkSel.value);
      render(); save();
    });
    optional.addEventListener('change', () => { slots[selected].optional = optional.checked; renderRow(); save(); });
    $$('[data-move]', editor).forEach((button) => button.addEventListener('click', () => {
      const to = selected + Number(button.dataset.move);
      if (to < 0 || to >= slots.length) return;
      const from = selected;
      [slots[from], slots[to]] = [slots[to], slots[from]];
      slots.forEach((s) => {
        if (s.link === from) s.link = to; else if (s.link === to) s.link = from;
      });
      selected = to;
      render(); save();
      button.focus();
    }));
    $('[data-remove-slot]', editor).addEventListener('click', removeSlot);
    $$('[data-add-slot]', builderForm).forEach((button) => button.addEventListener('click', () => {
      if (slots.length >= MAX_SLOTS) { toast(`Patterns can have up to ${MAX_SLOTS} spots.`); return; }
      const kind = button.dataset.addSlot;
      slots.push({ kind, value: kind === 'fixed' ? 'FL' : kind === 'custom' ? 'AEIOU' : '', optional: false, link: null });
      selected = slots.length - 1;
      render(); save();
      (valueWrap.hidden ? kindSel : valueInput).focus();
    }));
    $$('[data-preset]', builderForm).forEach((button) => button.addEventListener('click', () => {
      slots = PRESETS[button.dataset.preset].map((s) => ({ link: null, optional: false, value: '', ...s }));
      selected = 0;
      render(); save();
    }));
    // Enter inside a text field shouldn't submit the builder unexpectedly.
    valueInput.addEventListener('keydown', (event) => { if (event.key === 'Enter') event.preventDefault(); });

    render();
    save();
  }

  // Estimates are wired after the builder so its hidden slot value is ready.
  $$('[data-estimate-form]').forEach(wireEstimate);

  /* ===================================================== Results workspace */
  const resultsRoot = $('[data-results]');
  const dataEl = $('#generation-data');
  if (resultsRoot && dataEl) {
    const data = JSON.parse(dataEl.textContent);
    const all = data.candidates || [];
    const known = data.known || {};
    const selection = new Set();
    const state = { q: '', filter: 'all', sort: 'default', view: 'grid', page: 1 };
    const PER_PAGE = 60;
    const grid = $('[data-results-grid]', resultsRoot);
    const pager = $('[data-results-pager]', resultsRoot);
    const summary = $('[data-results-summary]', resultsRoot);
    const countEl = $('[data-selected-count]', resultsRoot);
    let filtered = all;

    const matches = (plate) => {
      const info = known[plate];
      switch (state.filter) {
        case 'new': return !info;
        case 'saved': return Boolean(info);
        case 'available': return info?.status === 'Available';
        case 'unavailable': return info?.status === 'Not available';
        case 'favorites': return Boolean(info?.favorite);
        default: return true;
      }
    };

    const recompute = () => {
      const q = state.q.trim().toUpperCase();
      filtered = all.filter((p) => (!q || p.includes(q)) && matches(p));
      if (state.sort === 'az') filtered = [...filtered].sort();
      else if (state.sort === 'za') filtered = [...filtered].sort().reverse();
      else if (state.sort === 'short') filtered = [...filtered].sort((a, b) => a.length - b.length || a.localeCompare(b));
      state.page = Math.min(state.page, Math.max(1, Math.ceil(filtered.length / PER_PAGE)));
    };

    const itemHtml = (plate) => {
      const info = known[plate];
      const checked = selection.has(plate);
      const status = info
        ? `${badge(info.status)}${info.checked ? `<small>Checked ${escapeHtml(info.checked)}</small>` : '<small>Saved</small>'}`
        : '<small class="muted">Not saved yet</small>';
      return `<li class="result-item${checked ? ' is-selected' : ''}" data-plate="${escapeHtml(plate)}">
        <div class="result-row">
          <label class="result-select"><input type="checkbox" ${checked ? 'checked' : ''} data-pick aria-label="Select ${escapeHtml(plate)}"><span aria-hidden="true">${escapeHtml(plate)}</span></label>
          <button type="button" class="fav-button${info?.favorite ? ' is-on' : ''}" data-fav aria-pressed="${info?.favorite ? 'true' : 'false'}" aria-label="${info?.favorite ? 'Remove' : 'Add'} ${escapeHtml(plate)} ${info?.favorite ? 'from' : 'to'} favorites">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20.3s-7.5-4.6-7.5-10.1A4.2 4.2 0 0 1 12 7.6a4.2 4.2 0 0 1 7.5 2.6c0 5.5-7.5 10.1-7.5 10.1z"/></svg>
          </button>
        </div>
        ${miniPlate(plate).replace('plate-xs', 'plate-xs result-plate')}
        <div class="result-status">${status}</div>
      </li>`;
    };

    const updateSelectionUi = () => {
      countEl.textContent = fmt(selection.size);
      $$('[data-bulk]', resultsRoot).forEach((b) => { b.disabled = selection.size === 0; });
      const bar = $('[data-action-bar]', resultsRoot);
      bar.classList.toggle('is-empty', selection.size === 0);
      summary.textContent = `Showing ${fmt(filtered.length)} of ${fmt(all.length)}${selection.size ? ` · ${fmt(selection.size)} selected` : ''}`;
    };

    const render = () => {
      const pages = Math.max(1, Math.ceil(filtered.length / PER_PAGE));
      const start = (state.page - 1) * PER_PAGE;
      const slice = filtered.slice(start, start + PER_PAGE);
      grid.classList.toggle('is-list', state.view === 'list');
      grid.innerHTML = slice.length
        ? slice.map(itemHtml).join('')
        : '<li class="empty-state"><h3>No matches</h3><p>Try a different search or filter.</p></li>';
      if (pages > 1) {
        pager.innerHTML = `<button type="button" class="button ghost small" data-page="${state.page - 1}" ${state.page === 1 ? 'disabled' : ''}>← Previous</button>
          <span class="pager-pages">Page <label class="sr-only" for="page-jump">Page number</label><input id="page-jump" class="input" style="width:5rem;min-height:38px" type="number" min="1" max="${pages}" value="${state.page}" data-page-jump> of ${fmt(pages)}</span>
          <button type="button" class="button ghost small" data-page="${state.page + 1}" ${state.page === pages ? 'disabled' : ''}>Next →</button>`;
      } else pager.innerHTML = '';
      updateSelectionUi();
    };

    const refresh = () => { recompute(); render(); };

    $('[data-results-search]', resultsRoot).addEventListener('input', debounce((e) => { state.q = e.target.value; state.page = 1; refresh(); }, 150));
    $('[data-results-filter]', resultsRoot).addEventListener('change', (e) => { state.filter = e.target.value; state.page = 1; refresh(); });
    $('[data-results-sort]', resultsRoot).addEventListener('change', (e) => { state.sort = e.target.value; state.page = 1; refresh(); });
    $$('[data-results-view]', resultsRoot).forEach((button) => button.addEventListener('click', () => {
      state.view = button.dataset.resultsView;
      $$('[data-results-view]', resultsRoot).forEach((b) => b.setAttribute('aria-pressed', b === button ? 'true' : 'false'));
      render();
    }));
    pager.addEventListener('click', (e) => {
      const button = e.target.closest('[data-page]');
      if (!button) return;
      state.page = Number(button.dataset.page);
      render();
      resultsRoot.scrollIntoView({ block: 'start' });
    });
    pager.addEventListener('change', (e) => {
      if (!e.target.matches('[data-page-jump]')) return;
      const pages = Math.max(1, Math.ceil(filtered.length / PER_PAGE));
      state.page = Math.max(1, Math.min(pages, Number(e.target.value) || 1));
      render();
    });
    $$('[data-select]', resultsRoot).forEach((button) => button.addEventListener('click', () => {
      const mode = button.dataset.select;
      if (mode === 'none') selection.clear();
      else if (mode === 'all') filtered.forEach((p) => selection.add(p));
      else filtered.slice((state.page - 1) * PER_PAGE, state.page * PER_PAGE).forEach((p) => selection.add(p));
      render();
    }));

    grid.addEventListener('change', (e) => {
      if (!e.target.matches('[data-pick]')) return;
      const item = e.target.closest('[data-plate]');
      const plate = item.dataset.plate;
      if (e.target.checked) selection.add(plate); else selection.delete(plate);
      item.classList.toggle('is-selected', e.target.checked);
      updateSelectionUi();
    });

    async function savePlates(plates, favorite) {
      const payload = { plates };
      if (favorite !== undefined) payload.favorite = favorite;
      const response = await fetch('/api/plates/save', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not save.');
      Object.entries(result.ids || {}).forEach(([plate, id]) => {
        known[plate] = known[plate] || { id, status: null, checked: null, favorite: false };
        known[plate].id = id;
        if (favorite !== undefined) known[plate].favorite = favorite;
      });
      return result;
    }

    grid.addEventListener('click', async (e) => {
      const fav = e.target.closest('[data-fav]');
      if (!fav) return;
      const plate = fav.closest('[data-plate]').dataset.plate;
      const next = !known[plate]?.favorite;
      fav.disabled = true;
      try {
        await savePlates([plate], next);
        toast(next ? `${plate} saved to favorites.` : `${plate} removed from favorites (still saved).`);
        render();
      } catch (err) { toast(err.message, { kind: 'error' }); fav.disabled = false; }
    });

    $$('[data-bulk]', resultsRoot).forEach((button) => button.addEventListener('click', async () => {
      const plates = filteredSelection();
      if (!plates.length) return;
      const action = button.dataset.bulk;
      const original = button.innerHTML;
      try {
        if (action === 'check') {
          const max = Number(document.querySelector('[data-bulk-max]')?.dataset.bulkMax || 500);
          if (plates.length > max) { toast(`You can check up to ${max} plates at a time. Select fewer plates.`, { kind: 'error' }); return; }
          const ok = await confirmDialog({ title: `Check ${plates.length} plate${plates.length === 1 ? '' : 's'}?`, message: `They'll be saved to your plates first.\n\n${checkMessage(plates.length)}`, confirmLabel: 'Save and start checking' });
          if (!ok) return;
          button.disabled = true;
          button.innerHTML = '<span class="spinner small" aria-hidden="true"></span>Starting…';
          const result = await savePlates(plates);
          const form = document.createElement('form');
          form.method = 'post';
          form.action = '/runs/start';
          const add = (name, value) => { const i = document.createElement('input'); i.type = 'hidden'; i.name = name; i.value = value; form.appendChild(i); };
          plates.forEach((p) => add('plate_ids', result.ids[p]));
          add('return_url', '/saved?sort=updated');
          add('confirm_large', 'yes');
          document.body.appendChild(form);
          form.submit();
          return;
        }
        button.disabled = true;
        button.innerHTML = '<span class="spinner small" aria-hidden="true"></span>Saving…';
        const result = await savePlates(plates, action === 'favorite' ? true : undefined);
        const what = action === 'favorite' ? 'added to favorites' : 'saved';
        toast(`${fmt(plates.length)} plate${plates.length === 1 ? '' : 's'} ${what} (${fmt(result.added)} new). <a href="/saved">View saved plates</a>`, { html: true });
        render();
      } catch (err) {
        toast(err.message || 'Something went wrong.', { kind: 'error' });
      } finally {
        button.innerHTML = original;
        updateSelectionUi();
      }
    }));

    // Selection is kept across filters; actions apply to everything selected.
    const filteredSelection = () => Array.from(selection);

    refresh();
    if (window.location.pathname.endsWith('/preview')) {
      resultsRoot.scrollIntoView({ block: 'start' });
      history.replaceState(null, '', `/explore?mode=${$('[data-mode-tab][aria-selected="true"]')?.dataset.modeTab || 'ideas'}`);
    }
  }
})();
