# Smart Automatic Handwash Faucet

Dashboard Flask + MySQL untuk monitoring wastafel otomatis, dengan API untuk ESP.

## 1. Instalasi

```bash
cd SmartFaucet
python -m venv venv
venv\Scripts\activate        # Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
```

## 2. Database & environment

1. Pastikan MySQL (XAMPP) berjalan.
2. Import migrasi: `mysql -u root -p < schema.sql`
   (atau biarkan `app.py` membuat tabel baru otomatis saat pertama dijalankan).
3. Salin `.env.example` menjadi `.env`, lalu isi:
   - `SECRET_KEY`: string acak panjang (session login).
   - `DB_*`: kredensial MySQL.
   - `ESP_API_KEY`: API key untuk `GET /api/esp-config` (header `X-API-KEY`).
   - `TELEGRAM_TOKEN` & `CHAT_ID`: opsional; kosongkan jika belum dipakai.

> **PENTING:** token Telegram lama yang pernah tertulis di `app.py` harus di-revoke
> melalui [@BotFather](https://t.me/BotFather) perintah `/revoke`, lalu gunakan token
> baru hanya di `.env`. Jangan pernah commit file `.env`.

Akun teknisi awal dibuat otomatis: **admin / admin1234** (password disimpan sebagai hash).

## 3. Menjalankan

```bash
python app.py
```

Buka `http://localhost:5000/login`, lalu login sebagai `admin`.

## 4. Endpoint

| Endpoint | Login web | Keterangan |
| --- | --- | --- |
| `/`, `/riwayat`, `/pengaturan` | Ya | Halaman teknisi |
| `/api/data`, `/api/history`, `/api/settings`, `/api/resolve-anomaly` | Ya (401 JSON) | Dashboard & pengaturan |
| `/api/iot-update` (POST) | Tidak | Update status dari ESP |
| `/api/esp-state` (GET) | Tidak | Status untuk ESP (field lama tetap ada) |
| `/api/esp-config` (GET) | Tidak, tapi `X-API-KEY` | Konfigurasi untuk ESP |

Contoh firmware ada di `docs/esp32_example.ino` (bukan firmware asli proyek).

## 5. Checklist pengujian

- [ ] Login dengan `admin` / `admin1234` berhasil; password salah atau username salah
      sama-sama menampilkan pesan "Username atau password salah".
- [ ] 5 kali gagal berturut-turut memicu lock 60 detik.
- [ ] Akses `/`, `/riwayat`, `/pengaturan`, `/api/data` tanpa login → redirect `/login` / 401 JSON.
- [ ] `POST /api/iot-update` tanpa login tetap `200`, dan `GET /api/esp-state` tetap `200`.
- [ ] `GET /api/esp-config` tanpa `X-API-KEY` → 401; dengan key benar → JSON konfigurasi.
- [ ] Card Waterpump menampilkan 4 kondisi:
      anomali (state `anomaly`) > tidak aktif (`pump_enabled=false`) >
      sedang digunakan (`state=active`) > aktif (`state=idle`).
- [ ] Tombol "Tandai Sudah Diperbaiki" hanya muncul saat anomali; anomali tidak
      ditimpa `idle` oleh ESP sebelum tombol ini ditekan.
- [ ] Buzzer/LED di card mengikuti toggle Pengaturan; data dashboard refresh tiap 2 detik.
- [ ] Toggle Buzzer/LED/Waterpump tersimpan; mematikan Waterpump memunculkan konfirmasi;
      `pump_on` pada respons `iot-update` menjadi `false`.
- [ ] Batas anomali diisi 4 atau 601 → gagal; 5–600 → berhasil; audit muncul di
      Riwayat dengan keterangan "Pengaturan".
- [ ] Riwayat: 20 data per halaman, filter per keterangan, tombol hamburger di layar kecil.
- [ ] Logout menghapus session dan kembali ke `/login`.
