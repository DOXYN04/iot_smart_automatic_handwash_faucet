async function fetchDashboardData() {
    try {
        const response = await fetch('/api/data');
        const data = await response.json();
        
        updateIndicators(data.state);
        renderLogs(data.logs);
    } catch (error) {
        console.error("Gagal mengambil data:", error);
    }
}

function updateIndicators(state) {
    const bIdle = document.getElementById('bubble-idle');
    const bActive = document.getElementById('bubble-active');
    const bAnomaly = document.getElementById('bubble-anomaly');
    const btnResolve = document.getElementById('btn-resolve');

    // Reset semua jadi mati (dim)
    bIdle.className = 'bubble blue dim';
    bActive.className = 'bubble green dim';
    bAnomaly.className = 'bubble red dim';

    // Sembunyikan tombol secara default
    btnResolve.style.display = 'none';

    // Nyalakan satu sesuai state
    if (state === 'idle') {
        bIdle.className = 'bubble blue active';
    } else if (state === 'active') {
        bActive.className = 'bubble green active';
    } else if (state === 'anomaly') {
        bAnomaly.className = 'bubble red active';
        // Munculkan tombol JIKA status anomali
        btnResolve.style.display = 'inline-block'; 
    }
}

async function resolveAnomaly() {
    const btnResolve = document.getElementById('btn-resolve');
    btnResolve.innerText = "⏳ Memproses...";
    btnResolve.disabled = true;

    try {
        const response = await fetch('/api/resolve-anomaly', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        const result = await response.json();
        
        if (result.status === 'success') {
            // Segera ambil data terbaru agar indikator berubah
            fetchDashboardData();
        } else {
            console.warn(result.message);
        }
    } catch (error) {
        console.error("Gagal mereset anomali:", error);
        alert("Gagal mereset anomali. Periksa koneksi server.");
    } finally {
        btnResolve.innerText = "🔧 Tandai Sudah Diperbaiki";
        btnResolve.disabled = false;
    }
}

function renderLogs(logs) {
    const tbody = document.getElementById('log-table-body');
    tbody.innerHTML = '';

    logs.forEach(log => {
        const dateObj = new Date(log.timestamp);
        const timeStr = dateObj.toLocaleString('id-ID');
        
        let badge = '';
        let durationText = `${log.duration} Detik`;

        if (log.status_type === 'normal') {
            badge = `<span class="badge-normal">Normal</span>`;
        } else if (log.status_type === 'anomali') {
            badge = `<span class="badge-anomali">Anomali</span>`;
        } else if (log.status_type === 'diperbaiki') {
            badge = `<span class="badge-fix">Diperbaiki</span>`;
            durationText = '-'; // Tidak ada durasi untuk log perbaikan
        }

        const rowHTML = `
            <tr>
                <td>#${log.id}</td>
                <td>${timeStr}</td>
                <td><strong>${durationText}</strong></td>
                <td>${badge}</td>
            </tr>
        `;
        tbody.insertAdjacentHTML('beforeend', rowHTML);
    });
}

// Eksekusi pertama kali
fetchDashboardData();
// Auto-refresh setiap 2 detik
setInterval(fetchDashboardData, 2000);