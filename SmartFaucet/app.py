"""Smart Automatic Handwash Faucet - dashboard teknisi & API ESP.

Jalankan: python app.py
Pastikan MySQL sudah berjalan dan schema.sql sudah diimport (atau biarkan
initialize_database() membuat tabel baru saat aplikasi pertama dijalankan).
"""
import hmac
import os
import secrets
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import wraps

import mysql.connector
import requests
from dotenv import load_dotenv
from flask import (Flask, flash, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

app = Flask(__name__)

# --- KONFIGURASI UMUM ---
_secret_key = os.environ.get('SECRET_KEY', '').strip()
if not _secret_key:
    # Fallback hanya untuk development agar `python app.py` tetap bisa dijalankan.
    # Simpan SECRET_KEY di .env untuk produksi agar session tidak hilang saat restart.
    _secret_key = secrets.token_hex(32)
    print('PERINGATAN: SECRET_KEY belum diset di .env; session akan reset saat server restart.')

app.config.update(
    SECRET_KEY=_secret_key,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', '0') == '1',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

# --- KONFIGURASI DATABASE ---
db_config = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'port': int(os.environ.get('DB_PORT', '3306')),
    'user': os.environ.get('DB_USER', 'root'),
    'password': os.environ.get('DB_PASSWORD', ''),
    'database': os.environ.get('DB_NAME', 'iot_database'),
}

# --- KONFIGURASI TELEGRAM & ESP ---
# Token/chat id TIDAK pernah ditulis di kode. Token lama yang pernah
# ter-commit harus di-revoke lewat BotFather sebelum memakai token baru.
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '').strip()
CHAT_ID = os.environ.get('CHAT_ID', '').strip()
ESP_API_KEY = os.environ.get('ESP_API_KEY', '').strip()

# Firmware asli tidak disertakan repository ini, sehingga nilai yang dipakai
# firmware tidak dapat diverifikasi. Default 30 detik dipakai sesuai instruksi.
DEFAULT_ANOMALY_THRESHOLD = 30

MAX_LOGIN_ATTEMPTS = 5
LOGIN_LOCK_SECONDS = 60
HISTORY_PER_PAGE = 20
ALLOWED_FILTERS = {'all', 'normal', 'anomali', 'diperbaiki', 'pengaturan'}

# Rate limit login sederhana (in-memory): {ip: {'count': int, 'locked_until': float}}
login_attempts = {}


def get_db_connection():
    return mysql.connector.connect(**db_config)


@contextmanager
def db_cursor(dictionary=True):
    """Jamin kursor dan koneksi selalu ditutup, termasuk saat exception."""
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=dictionary)
    try:
        yield conn, cursor
    finally:
        cursor.close()
        conn.close()


def initialize_database():
    """Buat tabel baru + seed akun teknisi awal bila belum ada."""
    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS system_status (
            id INT NOT NULL PRIMARY KEY,
            state VARCHAR(20) NOT NULL DEFAULT 'idle'
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS usage_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            `timestamp` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            duration INT NOT NULL DEFAULT 0,
            status_type VARCHAR(20) NOT NULL DEFAULT 'normal'
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(50) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS settings (
            id TINYINT NOT NULL PRIMARY KEY,
            buzzer_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            led_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            pump_enabled BOOLEAN NOT NULL DEFAULT TRUE,
            anomaly_threshold_seconds INT NOT NULL DEFAULT 30,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            `timestamp` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            user_id INT NULL,
            username VARCHAR(50) NOT NULL,
            action VARCHAR(50) NOT NULL,
            detail TEXT NOT NULL,
            INDEX idx_audit_action (`action`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """,
    ]

    with db_cursor() as (conn, cursor):
        for statement in ddl_statements:
            cursor.execute(statement)

        cursor.execute("INSERT IGNORE INTO system_status (id, state) VALUES (1, 'idle')")
        cursor.execute(
            """
            INSERT IGNORE INTO settings
                (id, buzzer_enabled, led_enabled, pump_enabled, anomaly_threshold_seconds)
            VALUES (1, TRUE, TRUE, TRUE, %s)
            """,
            (DEFAULT_ANOMALY_THRESHOLD,),
        )
        cursor.execute("SELECT id FROM users WHERE username = %s", ('admin',))
        if cursor.fetchone() is None:
            cursor.execute(
                "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                ('admin', generate_password_hash('admin1234')),
            )
        conn.commit()


def get_settings(conn, cursor):
    """Ambil satu baris settings; buat default bila belum ada."""
    cursor.execute(
        """
        SELECT buzzer_enabled, led_enabled, pump_enabled,
               anomaly_threshold_seconds, updated_at
        FROM settings WHERE id = 1
        """
    )
    row = cursor.fetchone()
    if row is None:
        cursor.execute(
            """
            INSERT INTO settings
                (id, buzzer_enabled, led_enabled, pump_enabled, anomaly_threshold_seconds)
            VALUES (1, TRUE, TRUE, TRUE, %s)
            """,
            (DEFAULT_ANOMALY_THRESHOLD,),
        )
        conn.commit()
        return get_settings(conn, cursor)
    return {
        'buzzer_enabled': bool(row['buzzer_enabled']),
        'led_enabled': bool(row['led_enabled']),
        'pump_enabled': bool(row['pump_enabled']),
        'anomaly_threshold_seconds': int(row['anomaly_threshold_seconds']),
        'updated_at': row['updated_at'],
    }


def send_telegram_alert(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        # Jangan cetak isi pesan: emoji di dalamnya bisa gagal ditulis ke
        # konsol Windows (cp1252) dan membuat endpoint ESP return 500.
        print('[Telegram tidak dikonfigurasi] notifikasi dilewati.')
        return
    url = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'
    payload = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.post(url, data=payload, timeout=5)
    except requests.RequestException as exc:
        print(f'Gagal mengirim Telegram: {exc}')


# --- AUTH & PROTEKSI RUTE ---
def web_login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.path))
        return view(*args, **kwargs)
    return wrapper


def api_login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'ok': False, 'error': 'Anda belum login.'}), 401
        return view(*args, **kwargs)
    return wrapper


def client_ip():
    return request.remote_addr or 'unknown'


def lock_remaining(ip):
    attempt = login_attempts.get(ip)
    if not attempt:
        return 0
    if attempt['locked_until']:
        remaining = attempt['locked_until'] - time.monotonic()
        if remaining <= 0:
            login_attempts.pop(ip, None)
            return 0
        return int(remaining) + 1
    return 0


def record_failed_login(ip):
    attempt = login_attempts.setdefault(ip, {'count': 0, 'locked_until': 0.0})
    attempt['count'] += 1
    if attempt['count'] >= MAX_LOGIN_ATTEMPTS:
        attempt['count'] = 0
        attempt['locked_until'] = time.monotonic() + LOGIN_LOCK_SECONDS


def clear_failed_logins(ip):
    login_attempts.pop(ip, None)


def parse_boolean(payload, key, default):
    """Terima boolean asli maupun string dari form ('on', 'true', '1', ...)."""
    if key not in payload:
        return default, None
    value = payload.get(key)
    if isinstance(value, bool):
        return value, None
    if isinstance(value, (int, float)):
        return bool(value), None
    text = str(value).strip().lower()
    if text in {'true', '1', 'on', 'yes'}:
        return True, None
    if text in {'false', '0', 'off', 'no', ''}:
        return False, None
    return None, f'{key} harus berupa nilai aktif/nonaktif.'


# --- HALAMAN WEB ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))

    ip = client_ip()
    if request.method == 'POST':
        remaining = lock_remaining(ip)
        if remaining > 0:
            flash(f'Terlalu banyak percobaan gagal. Coba lagi dalam {remaining} detik.', 'error')
        else:
            username = request.form.get('username', '').strip()
            password = request.form.get('password', '')

            with db_cursor() as (conn, cursor):
                cursor.execute(
                    'SELECT id, username, password_hash FROM users WHERE username = %s',
                    (username,),
                )
                user = cursor.fetchone()

            # Pesan yang sama untuk username salah maupun password salah.
            if user and check_password_hash(user['password_hash'], password):
                clear_failed_logins(ip)
                session.clear()
                session['user_id'] = user['id']
                session['username'] = user['username']
                session.permanent = True

                next_url = request.args.get('next', '')
                if not next_url.startswith('/') or next_url.startswith('//'):
                    next_url = url_for('index')
                return redirect(next_url)

            record_failed_login(ip)
            flash('Username atau password salah', 'error')

    return render_template(
        'login.html', show_sidebar=False, page='login', title='Login Teknisi'
    )


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@web_login_required
def index():
    return render_template('index.html', page='dashboard', title='Dashboard')


@app.route('/riwayat')
@web_login_required
def riwayat():
    return render_template('riwayat.html', page='riwayat', title='Riwayat Penggunaan')


@app.route('/pengaturan')
@web_login_required
def pengaturan():
    return render_template(
        'pengaturan.html',
        page='pengaturan',
        title='Pengaturan',
        default_threshold=DEFAULT_ANOMALY_THRESHOLD,
    )


# --- API DASHBOARD (WAJIB LOGIN) ---
@app.route('/api/data')
@api_login_required
def get_data():
    with db_cursor() as (conn, cursor):
        settings = get_settings(conn, cursor)

        cursor.execute('SELECT state FROM system_status WHERE id = 1')
        row = cursor.fetchone()
        current_state = row['state'] if row else 'idle'

        cursor.execute(
            """
            SELECT id, `timestamp`, duration, status_type
            FROM usage_logs
            ORDER BY `timestamp` DESC, id DESC
            LIMIT 5
            """
        )
        logs = cursor.fetchall()

    return jsonify({
        'state': current_state,
        'pump_enabled': settings['pump_enabled'],
        'buzzer_enabled': settings['buzzer_enabled'],
        'led_enabled': settings['led_enabled'],
        'logs': logs,
    })


@app.route('/api/history')
@api_login_required
def api_history():
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1
    filter_type = request.args.get('filter', 'all')
    if filter_type not in ALLOWED_FILTERS:
        filter_type = 'all'

    fetch_limit = page * HISTORY_PER_PAGE
    items = []

    with db_cursor() as (conn, cursor):
        if filter_type in {'all', 'normal', 'anomali', 'diperbaiki'}:
            where, params = ('', []) if filter_type == 'all' else (
                ' WHERE status_type = %s', [filter_type]
            )
            cursor.execute('SELECT COUNT(*) AS total FROM usage_logs' + where, params)
            total_usage = cursor.fetchone()['total']
            cursor.execute(
                'SELECT id, `timestamp`, duration, status_type FROM usage_logs'
                + where + ' ORDER BY `timestamp` DESC, id DESC LIMIT %s',
                params + [fetch_limit],
            )
            for row in cursor.fetchall():
                items.append({
                    'id': row['id'],
                    'source': 'usage',
                    'timestamp': row['timestamp'],
                    'duration': row['duration'],
                    'status_type': row['status_type'],
                    'username': None,
                    'detail': None,
                })
        else:
            total_usage = 0

        if filter_type in {'all', 'pengaturan'}:
            where, params = ('', []) if filter_type == 'all' else (
                ' WHERE action = %s', [filter_type]
            )
            cursor.execute('SELECT COUNT(*) AS total FROM audit_logs' + where, params)
            total_audit = cursor.fetchone()['total']
            cursor.execute(
                'SELECT id, `timestamp`, username, action, detail FROM audit_logs'
                + where + ' ORDER BY `timestamp` DESC, id DESC LIMIT %s',
                params + [fetch_limit],
            )
            for row in cursor.fetchall():
                items.append({
                    'id': row['id'],
                    'source': 'audit',
                    'timestamp': row['timestamp'],
                    'duration': None,
                    'status_type': row['action'],
                    'username': row['username'],
                    'detail': row['detail'],
                })
        else:
            total_audit = 0

    items.sort(key=lambda item: (str(item['timestamp']), item['id']), reverse=True)
    total = total_usage + total_audit
    start = (page - 1) * HISTORY_PER_PAGE

    return jsonify({
        'ok': True,
        'items': items[start:start + HISTORY_PER_PAGE],
        'page': page,
        'per_page': HISTORY_PER_PAGE,
        'total': total,
        'total_pages': max(1, (total + HISTORY_PER_PAGE - 1) // HISTORY_PER_PAGE),
        'filter': filter_type,
    })


@app.route('/api/resolve-anomaly', methods=['POST'])
@api_login_required
def resolve_anomaly():
    try:
        with db_cursor() as (conn, cursor):
            cursor.execute('SELECT state FROM system_status WHERE id = 1')
            row = cursor.fetchone()

            if row and row['state'] == 'anomaly':
                cursor.execute("UPDATE system_status SET state = 'idle' WHERE id = 1")
                cursor.execute(
                    "INSERT INTO usage_logs (duration, status_type) VALUES (0, 'diperbaiki')"
                )
                conn.commit()

                waktu = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                pesan = (
                    f"✅ *ANOMALI DISELESAIKAN* ✅\n\n"
                    f"Sensor Smart Faucet telah diperiksa dan kembali ke status Standby (Normal).\n\n"
                    f"Waktu: {waktu}"
                )
                send_telegram_alert(pesan)
                return jsonify({
                    'status': 'success',
                    'message': 'Anomali berhasil diselesaikan.',
                })
            return jsonify({'status': 'ignored', 'message': 'Tidak ada anomali saat ini.'})
    except mysql.connector.Error as exc:
        print(f'Error Reset Anomali: {exc}')
        return jsonify({'status': 'error', 'message': 'Gagal memproses anomali.'}), 500


# --- API PENGATURAN (WAJIB LOGIN) ---
@app.route('/api/settings', methods=['GET', 'POST'])
@api_login_required
def api_settings():
    if request.method == 'GET':
        with db_cursor() as (conn, cursor):
            settings = get_settings(conn, cursor)
        return jsonify({'ok': True, 'settings': settings})

    payload = request.get_json(silent=True)
    if payload is None:
        payload = request.form

    errors = {}
    values = {}
    for key, default in (
        ('buzzer_enabled', True),
        ('led_enabled', True),
        ('pump_enabled', True),
    ):
        value, error = parse_boolean(payload, key, default)
        if error:
            errors[key] = error
        else:
            values[key] = value

    raw_threshold = payload.get('anomaly_threshold_seconds', '')
    try:
        threshold = int(str(raw_threshold).strip())
        if not 5 <= threshold <= 600:
            raise ValueError
        values['anomaly_threshold_seconds'] = threshold
    except (TypeError, ValueError):
        errors['anomaly_threshold_seconds'] = 'Harus bilangan bulat antara 5 dan 600 detik.'

    if errors:
        return jsonify({
            'ok': False,
            'message': 'Validasi gagal.',
            'errors': errors,
        }), 400

    with db_cursor() as (conn, cursor):
        current = get_settings(conn, cursor)
        keys = ('buzzer_enabled', 'led_enabled', 'pump_enabled',
                'anomaly_threshold_seconds')
        changes = [f'{key}: {current[key]} -> {values[key]}'
                   for key in keys if current[key] != values[key]]

        if changes:
            cursor.execute(
                """
                UPDATE settings
                SET buzzer_enabled = %s, led_enabled = %s, pump_enabled = %s,
                    anomaly_threshold_seconds = %s
                WHERE id = 1
                """,
                (values['buzzer_enabled'], values['led_enabled'],
                 values['pump_enabled'], values['anomaly_threshold_seconds']),
            )
            cursor.execute(
                """
                INSERT INTO audit_logs (user_id, username, action, detail)
                VALUES (%s, %s, %s, %s)
                """,
                (session['user_id'], session['username'], 'pengaturan',
                 '; '.join(changes)),
            )
            conn.commit()
            updated = get_settings(conn, cursor)
            message = 'Pengaturan berhasil disimpan.'
        else:
            updated = current
            message = 'Tidak ada perubahan pengaturan.'

    return jsonify({
        'ok': True,
        'message': message,
        'settings': updated,
        'changed': bool(changes),
    })


# --- API ESP (TANPA LOGIN) ---
@app.route('/api/esp-state', methods=['GET'])
def esp_state():
    """Endpoint lama dipertahankan; field baru bersifat tambahan."""
    with db_cursor() as (conn, cursor):
        cursor.execute('SELECT state FROM system_status WHERE id = 1')
        row = cursor.fetchone()
        settings = get_settings(conn, cursor)

    return jsonify({
        'state': row['state'] if row else 'idle',
        'pump_enabled': settings['pump_enabled'],
    })


@app.route('/api/iot-update', methods=['POST'])
def iot_update():
    data = request.get_json(silent=True) or {}
    new_state = str(data.get('state', 'idle')).strip().lower()
    if new_state not in {'idle', 'active', 'anomaly'}:
        new_state = 'idle'
    try:
        duration = int(float(data.get('duration', 0) or 0))
    except (TypeError, ValueError):
        duration = 0

    with db_cursor() as (conn, cursor):
        cursor.execute('SELECT state FROM system_status WHERE id = 1')
        row = cursor.fetchone()
        db_state = row['state'] if row else 'idle'

        # Perilaku lama: anomali tidak boleh ditimpa 'idle' oleh ESP
        # sebelum teknisi menekan tombol resolve.
        if not (db_state == 'anomaly' and new_state == 'idle'):
            cursor.execute('UPDATE system_status SET state = %s WHERE id = 1', (new_state,))
            db_state = new_state

        if duration > 0:
            log_type = 'anomali' if new_state == 'anomaly' else 'normal'
            cursor.execute(
                'INSERT INTO usage_logs (duration, status_type) VALUES (%s, %s)',
                (duration, log_type),
            )

        settings = get_settings(conn, cursor)
        conn.commit()

    # Jika teknisi mematikan pompa, update dari ESP tetap diterima dan
    # tercatat, tetapi server tidak mengizinkan pompa menyala.
    pump_on = bool(settings['pump_enabled'] and db_state == 'active')

    if new_state == 'anomaly':
        waktu = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        pesan = (
            f"🚨 *ANOMALI KRITIS - SMART FAUCET* 🚨\n\n"
            f"Sensor mendeteksi penggunaan tak wajar selama *{duration} detik* nonstop.\n"
            f"Kemungkinan sensor terhalang.\n\n"
            f"Waktu: {waktu}"
        )
        send_telegram_alert(pesan)

    return jsonify({
        'status': 'success',
        'current_state': db_state,
        'pump_enabled': settings['pump_enabled'],
        'pump_on': pump_on,
    })


@app.route('/api/esp-config', methods=['GET'])
def esp_config():
    """Dilindungi X-API-KEY (bukan session login) agar ESP tetap bisa akses."""
    if not ESP_API_KEY:
        return jsonify({'error': 'ESP_API_KEY belum dikonfigurasi di server.'}), 503
    provided_key = request.headers.get('X-API-KEY', '')
    if not hmac.compare_digest(provided_key, ESP_API_KEY):
        return jsonify({'error': 'API key tidak valid.'}), 401

    with db_cursor() as (conn, cursor):
        settings = get_settings(conn, cursor)

    return jsonify({
        'buzzer_enabled': settings['buzzer_enabled'],
        'led_enabled': settings['led_enabled'],
        'pump_enabled': settings['pump_enabled'],
        'anomaly_threshold_seconds': settings['anomaly_threshold_seconds'],
    })


if __name__ == '__main__':
    try:
        initialize_database()
    except mysql.connector.Error as exc:
        raise SystemExit(
            f'Gagal menghubungkan ke MySQL: {exc}\n'
            'Pastikan MySQL berjalan dan konfigurasi DB_* di .env sudah benar.'
        ) from exc
    app.run(debug=True, host='0.0.0.0', port=5000)
