//! Pure-Rust loopback HTTP/1.0 client for communicating with the local Luminara Agent Daemon (`desktop/src/http_client.rs`).
//!
//! Uses `HTTP/1.0` (forbidding RFC 9112 chunked transfer encoding) + `Content-Length` framing
//! and strips CR/LF from headers to prevent header injection or keep-alive stalls.

use std::io::{Read, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::Duration;

use crate::config::{json_get_bool, json_get_string, json_get_u64};

const MAX_RESPONSE_BYTES: usize = 256 * 1024;

#[derive(Debug, Clone, Default)]
pub struct DesktopHeartbeat {
    pub daemon_online: bool,
    pub cdp_connected: bool,
    pub open_tabs: u64,
    pub active_leases_count: u64,
    pub pending_handoffs_count: u64,
    pub pending_mutations_count: u64,
    pub sequence_blocks_count: u64,
    pub alert_id: String,
    pub alert_title: String,
    pub alert_body: String,
}

#[derive(Clone)]
pub struct DaemonClient {
    port: u16,
    ui_key: String,
}

impl DaemonClient {
    pub fn new(port: u16, ui_key: String) -> Self {
        let clean_key = ui_key
            .chars()
            .filter(|c| !matches!(c, '\r' | '\n' | '\0'))
            .collect();
        Self {
            port,
            ui_key: clean_key,
        }
    }

    pub fn is_daemon_ready(&self) -> bool {
        self.fetch_heartbeat().daemon_online
    }

    pub fn is_port_open(&self) -> bool {
        let addr = SocketAddr::from(([127, 0, 0, 1], self.port));
        TcpStream::connect_timeout(&addr, Duration::from_millis(250)).is_ok()
    }

    pub fn fetch_heartbeat(&self) -> DesktopHeartbeat {
        let Ok((status, body)) = self.request("GET", "/api/agent/desktop/status", None) else {
            return DesktopHeartbeat::default();
        };
        if status != 200 {
            return DesktopHeartbeat::default();
        }
        DesktopHeartbeat {
            daemon_online: true,
            cdp_connected: json_get_bool(&body, "cdp_connected").unwrap_or(false),
            open_tabs: json_get_u64(&body, "open_tabs").unwrap_or(0),
            active_leases_count: json_get_u64(&body, "active_leases_count").unwrap_or(0),
            pending_handoffs_count: json_get_u64(&body, "pending_handoffs_count").unwrap_or(0),
            pending_mutations_count: json_get_u64(&body, "pending_mutations_count").unwrap_or(0),
            sequence_blocks_count: json_get_u64(&body, "sequence_blocks_count").unwrap_or(0),
            alert_id: json_get_string(&body, "alert_id").unwrap_or_default(),
            alert_title: json_get_string(&body, "alert_title").unwrap_or_default(),
            alert_body: json_get_string(&body, "alert_body").unwrap_or_default(),
        }
    }

    pub fn trigger_human_takeover(&self) -> Result<String, String> {
        let (status, body) = self.request("POST", "/api/agent/desktop/takeover", Some("{}"))?;
        if (200..300).contains(&status) {
            Ok(body)
        } else {
            Err(format!("takeover HTTP {status}: {body}"))
        }
    }

    pub fn request_shutdown(&self, close_browser: bool) -> Result<(), String> {
        let body = if close_browser {
            "{\"close_browser\":true}"
        } else {
            "{}"
        };
        let (status, resp) = self.request("POST", "/api/agent/shutdown", Some(body))?;
        if (200..300).contains(&status) {
            Ok(())
        } else {
            Err(format!("shutdown HTTP {status}: {resp}"))
        }
    }

    fn request(&self, method: &str, path: &str, json_body: Option<&str>) -> Result<(u16, String), String> {
        let addr = SocketAddr::from(([127, 0, 0, 1], self.port));
        let mut stream = TcpStream::connect_timeout(&addr, Duration::from_millis(800))
            .map_err(|e| format!("connect 127.0.0.1:{}: {e}", self.port))?;
        let _ = stream.set_read_timeout(Some(Duration::from_millis(2500)));
        let _ = stream.set_write_timeout(Some(Duration::from_millis(1500)));

        let body_bytes = json_body.unwrap_or("").as_bytes();
        let mut req = format!(
            "{method} {path} HTTP/1.0\r\nHost: 127.0.0.1:{}\r\nConnection: close\r\n",
            self.port
        );
        if !self.ui_key.is_empty() {
            req.push_str(&format!("X-Luminara-UI-Key: {}\r\n", self.ui_key));
        }
        if json_body.is_some() {
            req.push_str("Content-Type: application/json\r\n");
            req.push_str(&format!("Content-Length: {}\r\n", body_bytes.len()));
        }
        req.push_str("\r\n");

        stream
            .write_all(req.as_bytes())
            .map_err(|e| format!("write headers: {e}"))?;
        if !body_bytes.is_empty() {
            stream
                .write_all(body_bytes)
                .map_err(|e| format!("write body: {e}"))?;
        }

        let mut buf = Vec::with_capacity(4096);
        let mut chunk = [0u8; 4096];
        let mut header_end: Option<usize> = None;
        let mut expected_body_len: Option<usize> = None;

        loop {
            match stream.read(&mut chunk) {
                Ok(0) => break,
                Ok(n) => {
                    let take = n.min(MAX_RESPONSE_BYTES.saturating_sub(buf.len()));
                    buf.extend_from_slice(&chunk[..take]);
                    if header_end.is_none() {
                        if let Some(pos) = find_double_crlf(&buf) {
                            let b_start = pos + 4;
                            header_end = Some(b_start);
                            let head_str = String::from_utf8_lossy(&buf[..pos]);
                            expected_body_len = parse_content_length(&head_str);
                        }
                    }
                    if let (Some(b_start), Some(exp_len)) = (header_end, expected_body_len) {
                        if buf.len() >= b_start + exp_len {
                            buf.truncate(b_start + exp_len);
                            break;
                        }
                    }
                    if buf.len() >= MAX_RESPONSE_BYTES {
                        break;
                    }
                }
                Err(e) => {
                    if let (Some(b_start), Some(exp_len)) = (header_end, expected_body_len) {
                        if buf.len() >= b_start + exp_len {
                            break;
                        }
                    }
                    return Err(format!("read response: {e}"));
                }
            }
        }

        let Some(b_start) = header_end else {
            return Err("malformed HTTP response".into());
        };
        if let Some(exp_len) = expected_body_len {
            if buf.len() < b_start + exp_len && buf.len() < MAX_RESPONSE_BYTES {
                return Err("truncated HTTP response body".into());
            }
        }
        let head = String::from_utf8_lossy(&buf[..b_start - 4]);
        let body = String::from_utf8_lossy(&buf[b_start..]).into_owned();
        let status = head
            .lines()
            .next()
            .and_then(|l| l.split_whitespace().nth(1))
            .and_then(|code| code.parse::<u16>().ok())
            .unwrap_or(0);
        Ok((status, body))
    }
}

fn find_double_crlf(buf: &[u8]) -> Option<usize> {
    buf.windows(4).position(|w| w == b"\r\n\r\n")
}

fn parse_content_length(headers: &str) -> Option<usize> {
    for line in headers.lines().skip(1) {
        if let Some((k, v)) = line.split_once(':') {
            if k.trim().eq_ignore_ascii_case("content-length") {
                return v.trim().parse::<usize>().ok();
            }
        }
    }
    None
}
