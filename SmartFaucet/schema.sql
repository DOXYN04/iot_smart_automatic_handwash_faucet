-- Migrasi Smart Faucet.
-- Jalankan: mysql -u root -p < schema.sql
-- app.py juga membuat tabel baru + seed admin otomatis saat pertama dijalankan.

CREATE DATABASE IF NOT EXISTS iot_database
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE iot_database;

-- Tabel yang sudah dipakai firmware (dibuat jika belum ada).
CREATE TABLE IF NOT EXISTS system_status (
    id INT NOT NULL PRIMARY KEY,
    state VARCHAR(20) NOT NULL DEFAULT 'idle'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS usage_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    `timestamp` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    duration INT NOT NULL DEFAULT 0,
    status_type VARCHAR(20) NOT NULL DEFAULT 'normal'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO system_status (id, state) VALUES (1, 'idle');

-- Tabel baru: akun teknisi (password di-hash oleh app.py, bukan plaintext).
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Tabel baru: satu baris pengaturan (id = 1).
CREATE TABLE IF NOT EXISTS settings (
    id TINYINT NOT NULL PRIMARY KEY,
    buzzer_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    led_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    pump_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    anomaly_threshold_seconds INT NOT NULL DEFAULT 30,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT IGNORE INTO settings
    (id, buzzer_enabled, led_enabled, pump_enabled, anomaly_threshold_seconds)
VALUES (1, TRUE, TRUE, TRUE, 30);

-- Tabel baru: audit perubahan pengaturan (siapa & kapan).
CREATE TABLE IF NOT EXISTS audit_logs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    `timestamp` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id INT NULL,
    username VARCHAR(50) NOT NULL,
    action VARCHAR(50) NOT NULL,
    detail TEXT NOT NULL,
    INDEX idx_audit_action (`action`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
