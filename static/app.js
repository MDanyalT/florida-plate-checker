(() => {
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const ACTIVE_RUN_STATUSES = ['queued', 'running', 'captcha', 'stopping'];
  let observedRunStatus = null;

  function tablePlateChecks() {
    return $$('input[type="checkbox"][data-plate-id][form="bulk-run"]:not(:disabled)');
  }

  function selectedTablePlateIds() {
    const seen = new Set();
    return tablePlateChecks()
      .filter((item) => item.checked)
      .map((item) => item.value.trim())
      .filter((value) => /^\d+$/.test(value) && Number(value) > 0)
      .filter((value) => {
        if (seen.has(value)) return false;
        seen.add(value);
        return true;
      });
  }

  function setBulkSelectionError(message = '') {
    const target = document.querySelector('#bulk-run-error');
    if (!target) return;
    target.textContent = message;
    target.hidden = !message;
  }

  function refreshTableSelection() {
    const checks = tablePlateChecks();
    const selected = checks.filter((item) => item.checked);
    const toggle = document.querySelector('[data-table-select-all]');
    const button = document.querySelector('#bulk-run-label');
    const count = document.querySelector('#bulk-selection-count');
    if (toggle) {
      toggle.checked = selected.length === checks.length && checks.length > 0;
      toggle.indeterminate = selected.length > 0 && selected.length < checks.length;
      toggle.disabled = checks.length === 0;
    }
    if (count) count.textContent = `${selected.length} selected`;
    if (selected.length) setBulkSelectionError();
    if (!button) return;
    const checkedBefore = selected.filter((item) => item.dataset.checked === 'true').length;
    if (checkedBefore === 0) button.textContent = 'Check selected';
    else if (checkedBefore === selected.length) button.textContent = 'Recheck selected';
    else button.textContent = 'Check selected plates';
  }

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
      form.querySelector('[data-clear-selection]')?.addEventListener('click', () => {
        checks.forEach((item) => { item.checked = false; });
        refresh();
      });
      checks.forEach((item) => item.addEventListener('change', refresh));
      refresh();
    });

    const tableToggle = document.querySelector('[data-table-select-all]');
    const tableChecks = tablePlateChecks();
    tableToggle?.addEventListener('change', () => {
      tableChecks.forEach((item) => { item.checked = tableToggle.checked; });
      refreshTableSelection();
    });
    tableChecks.forEach((item) => item.addEventListener('change', refreshTableSelection));
    refreshTableSelection();
  }

  function selectedPlateCount(form) {
    const listedCount = Number(form.dataset.runCount || 0);
    if (listedCount) return listedCount;
    if (form.matches('[data-visible-plate-selection]')) return selectedTablePlateIds().length;
    return new Set(
      $$('input[name="plate_ids"][type="hidden"]', form)
        .map((item) => item.value.trim())
        .filter((value) => /^\d+$/.test(value) && Number(value) > 0),
    ).size;
  }

  function wireConfirmations() {
    $$('form[data-confirm]').forEach((form) => {
      form.addEventListener('submit', (event) => {
        if (!window.confirm(form.dataset.confirm)) event.preventDefault();
      });
    });
    $$('[data-large-run-form]').forEach((form) => {
      form.addEventListener('submit', (event) => {
        const selected = selectedPlateCount(form);
        const isVisibleSelection = form.matches('[data-visible-plate-selection]');
        if (!selected) {
          event.preventDefault();
          if (isVisibleSelection) setBulkSelectionError('Select at least one plate first.');
          else window.alert('Select at least one plate first.');
          return;
        }
        const maximum = Number(form.dataset.maxPlates || 1000);
        if (selected > maximum) {
          event.preventDefault();
          const message = `You selected ${selected} plates; the configured maximum is ${maximum}.`;
          if (isVisibleSelection) setBulkSelectionError(message);
          else window.alert(message);
          return;
        }
        if (isVisibleSelection && form.dataset.development === 'true') {
          const ids = selectedTablePlateIds();
          const payload = [...new FormData(form).entries()].map(([key, value]) => [key, String(value)]);
          console.debug('[Plate Research] checked boxes found:', ids.length);
          console.debug('[Plate Research] selected plate IDs:', ids);
          console.debug('[Plate Research] request payload:', payload);
        }
        const threshold = Number(form.dataset.threshold || 100);
        if (selected > threshold) {
          const ok = window.confirm(`This will check ${selected} plates serially and may take a while. Start the run?`);
          if (!ok) event.preventDefault();
          else form.querySelector('input[name="confirm_large"]').value = 'yes';
        }
      });
    });
    $$('[data-add-check-form]').forEach((form) => {
      form.addEventListener('submit', (event) => {
        const selected = $$('input[name="plates"]:checked', form).length;
        if (!selected) {
          event.preventDefault();
          window.alert('Select at least one plate first.');
          return;
        }
        const action = event.submitter?.value;
        const threshold = Number(form.dataset.threshold || 100);
        const maximum = Number(form.dataset.maxPlates || 1000);
        if (action === 'check_now' && selected > maximum) {
          event.preventDefault();
          window.alert(`You selected ${selected} plates; the configured maximum is ${maximum}.`);
          return;
        }
        if (action === 'check_now' && selected > threshold) {
          const ok = window.confirm(`This will add and check up to ${selected} plates serially and may take a while. Start the run?`);
          if (!ok) event.preventDefault();
          else form.querySelector('input[name="confirm_large"]').value = 'yes';
        }
      });
    });
    $$('[data-large-import-form]').forEach((form) => {
      form.addEventListener('submit', (event) => {
        const selected = $$('input[name="plates"]:checked', form).length;
        if (event.submitter?.value === 'library' && selected > 500) {
          const ok = window.confirm(`Add ${selected} generated plates to the local library?`);
          if (!ok) event.preventDefault();
          else form.querySelector('input[name="confirm_large"]').value = 'yes';
        }
      });
    });
  }

  function wireGeneratorFields() {
    const form = document.querySelector('[data-generator-form]');
    if (!form) return;
    const radios = $$('input[name="pattern_type"]', form);
    const groups = $$('[data-pattern-group]', form);
    const refresh = () => {
      const selected = radios.find((radio) => radio.checked)?.value;
      groups.forEach((group) => {
        const visible = (group.dataset.for || '').split(',').includes(selected);
        group.hidden = !visible;
        $$('input, select, textarea', group).forEach((field) => { field.disabled = !visible; });
      });
      radios.forEach((radio) => {
        radio.closest('.pattern-option')?.classList.toggle('selected', radio.checked);
      });
    };
    radios.forEach((radio) => radio.addEventListener('change', refresh));
    refresh();
  }

  function wireFirstRunWelcome() {
    const panel = document.querySelector('[data-first-run-welcome]');
    if (!panel) return;
    const storageKey = 'plate-research-welcome-dismissed';
    try {
      panel.hidden = window.localStorage.getItem(storageKey) === '1';
    } catch (_) {
      panel.hidden = false;
    }
    panel.querySelector('[data-dismiss-welcome]')?.addEventListener('click', () => {
      panel.hidden = true;
      try {
        window.localStorage.setItem(storageKey, '1');
      } catch (_) {
        // Dismissal still works for this page when browser storage is unavailable.
      }
    });
  }

  function updateRun(run) {
    const panel = document.querySelector('#live-run');
    const headerIndicator = document.querySelector('#header-run-indicator');
    const active = ACTIVE_RUN_STATUSES.includes(run?.status);
    if (headerIndicator) {
      headerIndicator.hidden = !active;
      if (active) headerIndicator.textContent = `Checking ${run.checked_count} of ${run.total_candidates}`;
    }
    if (!panel) return;
    panel.hidden = !active;
    if (!active) return;
    const percent = run.total_candidates ? Math.round((run.checked_count / run.total_candidates) * 100) : 0;
    panel.querySelector('#run-title').textContent = `Run #${run.id} · ${run.status}`;
    panel.querySelector('#run-progress-bar').style.width = `${percent}%`;
    panel.querySelector('#run-checked').textContent = run.checked_count;
    panel.querySelector('#run-total').textContent = run.total_candidates;
    panel.querySelector('#run-batch').textContent = run.current_batch;
    panel.querySelector('#run-batches-completed').textContent = run.batches_completed;
    panel.querySelector('#run-elapsed').textContent = `${run.elapsed_seconds.toFixed(1)}s`;
    panel.querySelector('#run-average').textContent = run.checked_count
      ? `${run.average_seconds_per_plate.toFixed(1)}s/plate`
      : '—';
    panel.querySelector('#run-retries').textContent = run.retry_count;
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

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function renderLatestRun(run) {
    const container = document.querySelector('#latest-run-content');
    if (!container) return;
    if (!run) {
      const empty = element('div', 'empty-state');
      empty.append(element('strong', '', 'No runs yet'), element('p', '', 'Add plates, then choose when to check them.'));
      container.replaceChildren(empty);
      return;
    }
    const summary = element('div', 'run-summary');
    const heading = element('div');
    heading.append(element('span', `status-badge status-${run.status.toLowerCase()}`, run.status), element('strong', '', `Run #${run.id}`));
    summary.append(heading, element('p', '', `${run.checked_count} of ${run.total_candidates} checked`));
    const progress = element('div', 'mini-progress');
    const bar = element('span');
    bar.style.width = `${run.total_candidates ? (run.checked_count / run.total_candidates) * 100 : 0}%`;
    progress.append(bar);
    summary.append(progress);
    const metrics = element('dl');
    [['Available', run.available_count], ['Unavailable', run.unavailable_count], ['Started', run.started_at]].forEach(([label, value]) => {
      const group = element('div');
      group.append(element('dt', '', label), element('dd', '', value));
      metrics.append(group);
    });
    summary.append(metrics);
    if (run.error_message) summary.append(element('p', 'inline-error', run.error_message));
    container.replaceChildren(summary);
  }

  function renderRecentChanges(changes) {
    const container = document.querySelector('#recent-changes-content');
    if (!container) return;
    if (!changes.length) {
      const empty = element('div', 'empty-state');
      empty.append(element('strong', '', 'No changes recorded yet'), element('p', '', 'Recheck saved plates later to see movement here.'));
      container.replaceChildren(empty);
      return;
    }
    const list = element('div', 'activity-list');
    changes.forEach((change) => {
      const row = element('a', 'activity-row');
      row.href = `/history?plate_id=${change.id}`;
      row.append(
        element('span', 'plate-mini', change.plate),
        element('span', '', `${change.previous_status} → ${change.current_status}`),
        element('time', '', change.changed_at),
      );
      list.append(row);
    });
    container.replaceChildren(list);
  }

  async function refreshDashboardSummary() {
    if (!document.querySelector('[data-dashboard-page]')) return;
    try {
      const response = await fetch('/api/dashboard-summary', { headers: { Accept: 'application/json' } });
      if (!response.ok) return;
      const summary = await response.json();
      const stats = summary.stats;
      const values = {
        '#stat-total': stats.total,
        '#stat-available': stats.available,
        '#stat-unavailable': stats.unavailable,
        '#stat-needs-review': stats.invalid + stats.unknown + stats.error,
        '#stat-favorites': stats.favorites,
        '#stat-today': stats.today,
        '#stat-review-detail': `${stats.invalid} invalid · ${stats.unknown} unknown · ${stats.error} errors`,
      };
      Object.entries(values).forEach(([selector, value]) => {
        const target = document.querySelector(selector);
        if (target) target.textContent = value;
      });
      renderLatestRun(summary.latest_run);
      renderRecentChanges(summary.recent_changes);
    } catch (_) {
      // A stopped local server needs no intrusive browser error.
    }
  }

  async function pollRun() {
    try {
      const response = await fetch('/api/runs/current', { headers: { Accept: 'application/json' } });
      if (!response.ok) return;
      const run = (await response.json()).run;
      const nextStatus = run?.status || null;
      const wasActive = ACTIVE_RUN_STATUSES.includes(observedRunStatus);
      const isActive = ACTIVE_RUN_STATUSES.includes(nextStatus);
      updateRun(run);
      if (wasActive && !isActive) {
        if (document.querySelector('[data-results-page]')) window.location.reload();
        else await refreshDashboardSummary();
      }
      observedRunStatus = nextStatus;
    } catch (_) {
      // A stopped local server needs no intrusive browser error.
    }
  }

  wireSelections();
  wireConfirmations();
  wireGeneratorFields();
  wireFirstRunWelcome();
  pollRun();
  window.setInterval(pollRun, 2000);
})();
