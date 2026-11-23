/* Smart Faucet - satu file JS untuk semua halaman (pilih berdasarkan data-page). */
(function () {
  'use strict';

  const DASHBOARD_INTERVAL_MS = 2000;

  function initSidebar() {
    const toggle = document.getElementById('menuToggle');
    if (!toggle) return;
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebarOverlay');

    function setOpen(open) {
      sidebar.classList.toggle('open', open);
      overlay.hidden = !open;
      toggle.setAttribute('aria-expanded', String(open));
    }

    toggle.addEventListener('click', () => setOpen(!sidebar.classList.contains('open')));
    overlay.addEventListener('click', () => setOpen(false));
    sidebar.querySelectorAll('a').forEach((link) => {
      link.addEventListener('click', () => {
        if (window.innerWidth <= 768) setOpen(false);
      });
    });
    window.addEventListener('resize', () => {
      if (window.innerWidth > 768) setOpen(false);
    });
  }

  function formatTime(value) {
    if (!value) return '-';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('id-ID');
  }

  const BADGE_LABELS = {
    normal: 'Normal',
    anomali: 'Anomali',
    diperbaiki: 'Diperbaiki',
    pengaturan: 'Pengaturan',
  };

  function addCell(row, text) {
    const cell = document.createElement('td');
    cell.textContent = text === null || text === undefined ? '-' : String(text);
    row.appendChild(cell);
    return cell;
  }

  function addBadgeCell(row, statusType, detail) {
    const cell = document.createElement('td');
    const key = BADGE_LABELS[statusType] ? statusType : 'normal';
    const badge = document.createElement('span');
    badge.className = 'badge badge-' + key;
    badge.textContent = BADGE_LABELS[statusType] || statusType || '-';
    cell.appendChild(badge);
    if (detail) {
      const note = document.createElement('small');
      note.className = 'detail-text';
      note.textContent = detail;
      cell.appendChild(note);
    }
    row.appendChild(cell);
    return cell;
  }

  function emptyRow(tbody, message) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 4;
    cell.className = 'muted';
    cell.textContent = message;
    row.appendChild(cell);
    tbody.replaceChildren(row);
  }

  async function requestJSON(url, options) {
    const response = await fetch(url, options);
    if (response.status === 401) {
      window.location.href = '/login';
      throw new Error('Sesi berakhir.');
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.message || data.error || 'Permintaan gagal.');
    }
    return data;
  }

  /* ---------------- DASHBOARD ---------------- */
  const PUMP_STATUS = {
    anomaly: {
      css: 'status-anomali',
      label: 'Terjadi anomali',
      detail: 'Sensor mendeteksi penggunaan tidak wajar. Periksa perangkat lalu tandai sudah diperbaiki.',
      bubble: 'bubbleAnomali',
    },
    disabled: {
      css: 'status-nonaktif',
      label: 'Tidak aktif',
      detail: 'Waterpump dinonaktifkan dari halaman Pengaturan.',
      bubble: 'bubbleTidakAktif',
    },
    in_use: {
      css: 'status-digunakan',
      label: 'Sedang digunakan',
      detail: 'Sensor mendeteksi tangan dan air sedang mengalir.',
      bubble: 'bubbleDigunakan',
    },
    active: {
      css: 'status-aktif',
      label: 'Aktif',
      detail: 'Waterpump aktif dan sistem dalam kondisi standby.',
      bubble: 'bubbleAktif',
    },
  };

  function updateMiniCard(cardId, textId, enabled) {
    document.getElementById(cardId).classList.toggle('on', enabled);
    document.getElementById(textId).textContent = enabled ? 'Aktif' : 'Nonaktif';
  }

  function renderDashboardLogs(logs) {
    const tbody = document.getElementById('dashboardLogBody');
    if (!logs.length) {
      emptyRow(tbody, 'Belum ada riwayat penggunaan.');
      return;
    }
    const rows = logs.map((log) => {
      const row = document.createElement('tr');
      addCell(row, '#' + log.id);
      addCell(row, formatTime(log.timestamp));
      addCell(row, log.status_type === 'diperbaiki' ? '-' : log.duration + ' dtk');
      addBadgeCell(row, log.status_type);
      return row;
    });
    tbody.replaceChildren(...rows);
  }

  async function loadDashboard() {
    try {
      const data = await requestJSON('/api/data');

      // Prioritas: anomali > pompa nonaktif > sedang digunakan > aktif.
      let statusKey = 'active';
      if (data.state === 'anomaly') statusKey = 'anomaly';
      else if (!data.pump_enabled) statusKey = 'disabled';
      else if (data.state === 'active') statusKey = 'in_use';

      const status = PUMP_STATUS[statusKey];
      const card = document.getElementById('pumpStatusCard');
      card.className = 'card status-card ' + status.css;
      document.getElementById('pumpStatusText').textContent = status.label;
      document.getElementById('pumpStatusDetail').textContent = status.detail;

      ['bubbleAktif', 'bubbleTidakAktif', 'bubbleDigunakan', 'bubbleAnomali']
        .forEach((id) => document.getElementById(id).classList.remove('on'));
      document.getElementById(status.bubble).classList.add('on');

      document.getElementById('btnResolve').hidden = data.state !== 'anomaly';
      updateMiniCard('buzzerCard', 'buzzerStatus', data.buzzer_enabled);
      updateMiniCard('ledCard', 'ledStatus', data.led_enabled);
      renderDashboardLogs(data.logs || []);
    } catch (error) {
      console.error('Gagal memuat dashboard:', error);
    }
  }

  function initDashboard() {
    const button = document.getElementById('btnResolve');
    button.addEventListener('click', async () => {
      const originalText = button.textContent;
      button.disabled = true;
      button.textContent = '⏳ Memproses...';
      try {
        const result = await requestJSON('/api/resolve-anomaly', { method: 'POST' });
        if (result.status === 'success') await loadDashboard();
      } catch (error) {
        console.error('Gagal menyelesaikan anomali:', error);
        window.alert('Gagal menyelesaikan anomali: ' + error.message);
      } finally {
        button.disabled = false;
        button.textContent = originalText;
      }
    });

    loadDashboard();
    setInterval(loadDashboard, DASHBOARD_INTERVAL_MS);
  }

  /* ---------------- RIWAYAT ---------------- */
  const historyState = { page: 1, filter: 'all' };

  async function loadHistory() {
    const params = new URLSearchParams({
      page: String(historyState.page),
      filter: historyState.filter,
    });
    try {
      const data = await requestJSON('/api/history?' + params.toString());
      const tbody = document.getElementById('historyTableBody');
      if (!data.items.length) {
        emptyRow(tbody, 'Tidak ada data untuk filter ini.');
      } else {
        const rows = data.items.map((item) => {
          const row = document.createElement('tr');
          const idText = item.source === 'audit' ? '#A' + item.id : '#' + item.id;
          addCell(row, idText);
          addCell(row, formatTime(item.timestamp));
          addCell(row, item.duration === null ? '-' : item.duration + ' dtk');
          addBadgeCell(row, item.status_type, item.detail);
          return row;
        });
        tbody.replaceChildren(...rows);
      }

      document.getElementById('pageInfo').textContent =
        `Halaman ${data.page} dari ${data.total_pages} (${data.total} data)`;
      document.getElementById('prevPage').disabled = data.page <= 1;
      document.getElementById('nextPage').disabled = data.page >= data.total_pages;
    } catch (error) {
      console.error('Gagal memuat riwayat:', error);
    }
  }

  function initRiwayat() {
    document.getElementById('historyFilter').addEventListener('change', (event) => {
      historyState.filter = event.target.value;
      historyState.page = 1;
      loadHistory();
    });
    document.getElementById('prevPage').addEventListener('click', () => {
      if (historyState.page > 1) {
        historyState.page -= 1;
        loadHistory();
      }
    });
    document.getElementById('nextPage').addEventListener('click', () => {
      historyState.page += 1;
      loadHistory();
    });
    loadHistory();
  }

  /* ---------------- PENGATURAN ---------------- */
  function applySettingsToForm(settings) {
    document.getElementById('toggleBuzzer').checked = settings.buzzer_enabled;
    document.getElementById('toggleLed').checked = settings.led_enabled;
    document.getElementById('togglePump').checked = settings.pump_enabled;
    document.getElementById('anomalyThreshold').value = settings.anomaly_threshold_seconds;
  }

  async function loadSettings() {
    try {
      const data = await requestJSON('/api/settings');
      applySettingsToForm(data.settings);
    } catch (error) {
      console.error('Gagal memuat pengaturan:', error);
    }
  }

  function initPengaturan() {
    const pumpToggle = document.getElementById('togglePump');
    pumpToggle.addEventListener('change', () => {
      if (!pumpToggle.checked) {
        const confirmOff = window.confirm(
          'Menonaktifkan Waterpump akan menghentikan aliran air walaupun sensor mendeteksi tangan. Lanjutkan?'
        );
        if (!confirmOff) pumpToggle.checked = true;
      }
    });

    document.getElementById('settingsForm').addEventListener('submit', async (event) => {
      event.preventDefault();
      const message = document.getElementById('settingsMessage');
      const thresholdError = document.getElementById('thresholdError');
      const submitButton = document.getElementById('btnSaveSettings');
      message.textContent = '';
      message.className = 'save-message';
      thresholdError.hidden = true;

      const payload = {
        buzzer_enabled: document.getElementById('toggleBuzzer').checked,
        led_enabled: document.getElementById('toggleLed').checked,
        pump_enabled: pumpToggle.checked,
        anomaly_threshold_seconds: document.getElementById('anomalyThreshold').value,
      };

      submitButton.disabled = true;
      try {
        const response = await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (response.status === 401) {
          window.location.href = '/login';
          return;
        }
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
          const errorText = data.errors
            ? Object.values(data.errors).join(' ')
            : (data.message || 'Gagal menyimpan pengaturan.');
          if (data.errors && data.errors.anomaly_threshold_seconds) {
            thresholdError.textContent = data.errors.anomaly_threshold_seconds;
            thresholdError.hidden = false;
          }
          message.textContent = errorText;
          message.className = 'save-message fail';
          return;
        }
        applySettingsToForm(data.settings);
        message.textContent = data.message || 'Pengaturan berhasil disimpan.';
        message.className = 'save-message ok';
      } catch (error) {
        message.textContent = 'Gagal menyimpan pengaturan: ' + error.message;
        message.className = 'save-message fail';
      } finally {
        submitButton.disabled = false;
      }
    });

    loadSettings();
  }

  document.addEventListener('DOMContentLoaded', () => {
    initSidebar();
    const page = document.body.dataset.page;
    if (page === 'dashboard') initDashboard();
    else if (page === 'riwayat') initRiwayat();
    else if (page === 'pengaturan') initPengaturan();
  });
})();
