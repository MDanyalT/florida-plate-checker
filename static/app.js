(() => {
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function wireSelections() {
    $$('[data-selection-form]').forEach((form) => {
      const toggle = form.querySelector('[data-select-all]');
      const checks = $$('input[name="plates"]', form);
      const count = form.querySelector('[data-selection-count]');
      const refresh = () => {
        const selected = checks.filter((item) => item.checked).length;
        if (count) count.textContent = `${selected} selected`;
        if (toggle) {
          toggle.checked = selected === checks.length && checks.length > 0;
          toggle.indeterminate = selected > 0 && selected < checks.length;
        }
      };
      toggle?.addEventListener('change', () => {
        checks.forEach((item) => { item.checked = toggle.checked; });
        refresh();
      });
      checks.forEach((item) => item.addEventListener('change', refresh));
      refresh();
    });

    const tableToggle = document.querySelector('[data-table-select-all]');
    const tableChecks = $$('[data-row-check]');
    tableToggle?.addEventListener('change', () => {
      tableChecks.forEach((item) => { item.checked = tableToggle.checked; });
    });
  }

  function wireConfirmations() {
    $$('form[data-confirm]').forEach((form) => {
      form.addEventListener('submit', (event) => {
        if (!window.confirm(form.dataset.confirm)) event.preventDefault();
      });
    });
    $$('[data-large-run-form]').forEach((form) => {
      form.addEventListener('submit', (event) => {
        const selected = $$('input[name="plate_ids"]:checked').length;
        if (!selected) {
          event.preventDefault();
          window.alert('Select at least one plate first.');
          return;
        }
        const threshold = Number(form.dataset.threshold || 100);
        if (selected > threshold) {
          const ok = window.confirm(`This will check ${selected} plates serially and may take a while. Start the run?`);
          if (!ok) event.preventDefault();
          else form.querySelector('input[name="confirm_large"]').value = 'yes';
        }
      });
    });
    $$('[data-large-import-form]').forEach((form) => {
      form.addEventListener('submit', (event) => {
        const selected = $$('input[name="plates"]:checked', form).length;
        if (!selected) {
          event.preventDefault();
          window.alert('Select at least one generated plate.');
          return;
        }
        if (selected > 500) {
          const ok = window.confirm(`Import ${selected} generated plates? You can still choose only 500 per checking run.`);
          if (!ok) event.preventDefault();
          else form.querySelector('input[name="confirm_large"]').value = 'yes';
        }
      });
    });
  }

  function updateRun(run) {
    const panel = document.querySelector('#live-run');
    if (!panel) return;
    const active = ['queued', 'running', 'captcha', 'stopping'].includes(run?.status);
    panel.hidden = !active;
    if (!active) return;
    const percent = run.total_candidates ? Math.round((run.checked_count / run.total_candidates) * 100) : 0;
    panel.querySelector('#run-title').textContent = `Run #${run.id} · ${run.status}`;
    panel.querySelector('#run-progress-bar').style.width = `${percent}%`;
    panel.querySelector('#run-checked').textContent = run.checked_count;
    panel.querySelector('#run-total').textContent = run.total_candidates;
    panel.querySelector('#run-batch').textContent = run.current_batch;
    panel.querySelector('#run-available').textContent = run.available_count;
    panel.querySelector('#run-unavailable').textContent = run.unavailable_count;
    panel.querySelector('#run-invalid').textContent = run.invalid_count;
    panel.querySelector('#run-unknown').textContent = run.unknown_count;
    panel.querySelector('#run-errors').textContent = run.error_count;
    panel.querySelector('#run-last').textContent = run.last_processed_plate || '—';
    const message = panel.querySelector('#run-message');
    message.textContent = run.status === 'captcha'
      ? 'Complete the human verification in Chromium, then press Enter in the terminal.'
      : run.status === 'stopping'
        ? 'Finishing the current safe step, then the browser will close.'
        : `${percent}% complete · Results save after every plate.`;
  }

  async function pollRun() {
    try {
      const response = await fetch('/api/runs/current', { headers: { Accept: 'application/json' } });
      if (response.ok) updateRun((await response.json()).run);
    } catch (_) {
      // A stopped local server needs no intrusive browser error.
    }
  }

  wireSelections();
  wireConfirmations();
  pollRun();
  window.setInterval(pollRun, 2000);
})();
