from flask import Flask, render_template, request, jsonify
import mysql.connector
import requests
from datetime import datetime

app = Flask(__name__)

# --- KONFIGURASI DATABASE ---
db_config = {
    'host': 'localhost',
    'user': 'root',       # Sesuaikan jika user bukan root
    'password': '',       # Kosongkan jika default XAMPP
    'database': 'iot_database'
}

# --- KONFIGURASI TELEGRAM ---
TELEGRAM_TOKEN = '9200813108:AAGkVAvq-WUUq9VetyKjIg0T4HgAl-FEsRA'
CHAT_ID = '-5310128219'

def get_db_connection():
    return mysql.connector.connect(**db_config)

def send_telegram_alert(message):
    if TELEGRAM_TOKEN == 'TOKEN_BOT_KAMU_DI_SINI':
        print("Telegram Alert (Token belum diisi):", message)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        'chat_id': CHAT_ID,
        'text': message,
        'parse_mode': 'Markdown'
    }
    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        print(f"Gagal mengirim Telegram: {e}")

# --- RUTE WEB & API ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data')
def get_data():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    # Ambil status saat ini
    cursor.execute("SELECT state FROM system_status WHERE id = 1")
    row = cursor.fetchone()
    current_state = row['state'] if row else 'idle'
    
    # Ambil log penggunaan terbaru
    cursor.execute("SELECT * FROM usage_logs ORDER BY timestamp DESC LIMIT 15")
    logs = cursor.fetchall()
    
    conn.close()
    return jsonify({'state': current_state, 'logs': logs})

@app.route('/api/esp-state', methods=['GET'])
def esp_state():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT state FROM system_status WHERE id = 1")
    row = cursor.fetchone()
    conn.close()
    return jsonify({'state': row['state'] if row else 'idle'})

@app.route('/api/iot-update', methods=['POST'])
def iot_update():
    data = request.json
    new_state = data.get('state', 'idle')
    duration = data.get('duration', 0) 

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Cek status saat ini di database sebelum menimpa
    cursor.execute("SELECT state FROM system_status WHERE id = 1")
    row = cursor.fetchone()
    db_state = row['state'] if row else 'idle'

    # Jangan timpa status 'anomaly' dengan 'idle' dari ESP sebelum admin klik Resolve di Web
    if not (db_state == 'anomaly' and new_state == 'idle'):
        cursor.execute("UPDATE system_status SET state = %s WHERE id = 1", (new_state,))
        db_state = new_state
    
    # Catat ke Log jika ada durasi pemakaian
    if duration > 0:
        log_type = 'anomali' if new_state == 'anomaly' else 'normal'
        cursor.execute(
            "INSERT INTO usage_logs (duration, status_type) VALUES (%s, %s)",
            (duration, log_type)
        )
    
    conn.commit()
    conn.close()

    # Kirim Alert Telegram jika anomali baru saja terpicu
    if new_state == 'anomaly':
        waktu = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        pesan = (
            f"🚨 *ANOMALI KRITIS - SMART FAUCET* 🚨\n\n"
            f"Sensor mendeteksi penggunaan tak wajar selama *{duration} detik* nonstop.\n"
            f"Kemungkinan sensor terhalang.\n\n"
            f"Waktu: {waktu}"
        )
        send_telegram_alert(pesan)

    return jsonify({'status': 'success', 'current_state': db_state})

@app.route('/api/resolve-anomaly', methods=['POST'])
def resolve_anomaly():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT state FROM system_status WHERE id = 1")
        row = cursor.fetchone()

        if row and row['state'] == 'anomaly':
            cursor.execute("UPDATE system_status SET state = 'idle' WHERE id = 1")
            cursor.execute("INSERT INTO usage_logs (duration, status_type) VALUES (0, 'diperbaiki')")
            conn.commit()

            waktu = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            pesan = (
                f"✅ *ANOMALI DISELESAIKAN* ✅\n\n"
                f"Sensor Smart Faucet telah diperiksa dan kembali ke status Standby (Normal).\n\n"
                f"Waktu: {waktu}"
            )
            send_telegram_alert(pesan)

            conn.close()
            return jsonify({'status': 'success', 'message': 'Anomali berhasil diselesaikan.'})
        else:
            conn.close()
            return jsonify({'status': 'ignored', 'message': 'Tidak ada anomali saat ini.'})
            
    except Exception as e:
        print(f"Error Reset Anomali: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)