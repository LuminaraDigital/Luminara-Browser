//! Thread-safe rotating structured log writer with multi-occurrence secret redaction (`desktop/src/logging.rs`).

use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

pub const MAX_LOG_BYTES: u64 = 5 * 1024 * 1024;
pub const MAX_ROTATIONS: usize = 3;

pub struct RotatingLogger {
    path: PathBuf,
    max_bytes: u64,
    secrets: Mutex<Vec<String>>,
    writer: Mutex<Option<(File, u64)>>,
}

impl RotatingLogger {
    pub fn new(path: PathBuf) -> Self {
        Self::with_limit(path, MAX_LOG_BYTES)
    }

    pub fn with_limit(path: PathBuf, max_bytes: u64) -> Self {
        if let Some(parent) = path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        Self {
            path,
            max_bytes: max_bytes.max(1024),
            secrets: Mutex::new(Vec::new()),
            writer: Mutex::new(None),
        }
    }

    pub fn register_secret(&self, secret: &str) {
        let trimmed = secret.trim();
        if trimmed.len() < 8 {
            return;
        }
        if let Ok(mut guard) = self.secrets.lock() {
            if !guard.iter().any(|s| s == trimmed) {
                guard.push(trimmed.to_string());
            }
        }
    }

    pub fn redact(&self, text: &str) -> String {
        let mut out = text.to_string();
        if let Ok(guard) = self.secrets.lock() {
            for sec in guard.iter() {
                if !sec.is_empty() && out.contains(sec.as_str()) {
                    out = out.replace(sec.as_str(), "[REDACTED]");
                }
            }
        }
        // Case-insensitively scrub ALL occurrences of UI-Key & Bearer headers on a line without swallowing trailing text.
        for marker in ["x-luminara-ui-key:", "authorization: bearer "] {
            let mut search_from = 0usize;
            while search_from < out.len() {
                let lower_tail = out[search_from..].to_ascii_lowercase();
                let Some(rel_idx) = lower_tail.find(marker) else {
                    break;
                };
                let val_start = search_from + rel_idx + marker.len();
                let ws_len: usize = out[val_start..]
                    .chars()
                    .take_while(|c| *c == ' ' || *c == '\t')
                    .map(char::len_utf8)
                    .sum();
                let tok_start = val_start + ws_len;
                let tok_len = out[tok_start..]
                    .find(|c: char| {
                        c.is_whitespace() || matches!(c, '"' | '\'' | ',' | ';' | '}' | ']' | ')')
                    })
                    .unwrap_or(out.len() - tok_start);
                let replacement = if marker.ends_with(':') {
                    " [REDACTED]"
                } else {
                    "[REDACTED]"
                };
                out.replace_range(val_start..tok_start + tok_len, replacement);
                search_from = val_start + replacement.len();
            }
        }
        out
    }

    pub fn log(&self, level: &str, msg: &str) {
        let ts = unix_ms();
        let safe_msg = self.redact(msg).replace('\r', "");
        self.write_formatted(&format!("[{ts}] [{level}] {safe_msg}\n"));
    }

    pub fn append_raw_line(&self, line: &str) {
        let safe_line = self.redact(line).replace('\r', "");
        self.write_formatted(&format!("{safe_line}\n"));
    }

    fn write_formatted(&self, line: &str) {
        let Ok(mut guard) = self.writer.lock() else {
            return;
        };
        let cur_len = guard
            .as_ref()
            .map(|(_, len)| *len)
            .or_else(|| fs::metadata(&self.path).ok().map(|m| m.len()))
            .unwrap_or(0);
        if cur_len >= self.max_bytes {
            *guard = None; // close active handle before renaming on Windows
            self.rotate_files();
        }
        if guard.is_none() {
            if let Some(parent) = self.path.parent() {
                let _ = fs::create_dir_all(parent);
            }
            if let Ok(file) = OpenOptions::new().create(true).append(true).open(&self.path) {
                let initial = file.metadata().map(|m| m.len()).unwrap_or(0);
                *guard = Some((file, initial));
            }
        }
        if let Some((file, len)) = guard.as_mut() {
            let bytes = line.as_bytes();
            if file.write_all(bytes).is_ok() {
                let _ = file.flush();
                *len += bytes.len() as u64;
            }
        }
    }

    fn rotate_files(&self) {
        for idx in (1..=MAX_ROTATIONS).rev() {
            let dst = rotated_path(&self.path, idx);
            let src = if idx == 1 {
                self.path.clone()
            } else {
                rotated_path(&self.path, idx - 1)
            };
            if src.exists() {
                let _ = fs::remove_file(&dst);
                let _ = fs::rename(&src, &dst);
            }
        }
    }
}

fn rotated_path(base: &Path, index: usize) -> PathBuf {
    let mut name = base.file_name().unwrap_or_default().to_os_string();
    name.push(format!(".{index}"));
    base.with_file_name(name)
}

fn unix_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_millis())
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;

    #[test]
    fn redacts_multiple_case_insensitive_headers_and_rotates() {
        let dir = env::temp_dir().join(format!("lum_log_test_{}", unix_ms()));
        let log_path = dir.join("host.log");
        let logger = RotatingLogger::with_limit(log_path.clone(), 1024);
        let fake_key = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2";
        logger.register_secret(fake_key);
        for i in 0..40 {
            logger.log(
                "INFO",
                &format!(
                    "ev {i} key={fake_key} x-luminara-ui-key: secA, X-Luminara-UI-Key: secB authorization: bearer tokC tail=kept"
                ),
            );
        }
        drop(logger);
        let current = fs::read_to_string(&log_path).expect("read active log");
        assert!(!current.contains(fake_key));
        assert!(!current.contains("secA"));
        assert!(!current.contains("secB"));
        assert!(!current.contains("tokC"));
        assert!(current.contains("tail=kept"));
        assert!(rotated_path(&log_path, 1).exists());
        let _ = fs::remove_dir_all(&dir);
    }
}
