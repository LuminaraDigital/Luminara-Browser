//! CLI argument parsing, `luminara://` protocol routing, and IPC injection defense (`desktop/src/protocol.rs`).
//!
//! Strictly separates trusted Luminara host flags from external OS/IPC arguments so clicking an
//! untrusted link or invoking `LuminaraBrowser.exe` from another app can NEVER inject dangerous
//! Chromium switches (`--load-extension`, `--remote-debugging-port`, `--gpu-launcher`, etc.) or
//! `javascript:` / `data:` URLs.

use std::path::Path;

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct HostCommand {
    pub show_version: bool,
    pub show_diagnostics: bool,
    pub install_mode: bool,
    pub uninstall_mode: bool,
    pub quiet: bool,
    pub purge_data: bool,
    pub force_portable: bool,
    pub no_tray: bool,
    pub new_window: bool,
    pub incognito: bool,
    pub open_workspace: bool,
    pub open_telemetry: bool,
    pub open_studio: bool,
    pub trigger_takeover: bool,
    pub quit_existing: bool,
    pub open_urls: Vec<String>,
}

const ALLOWED_LOCAL_EXTS: &[&str] = &[
    "html", "htm", "xhtml", "pdf", "svg", "webp", "png", "jpg", "jpeg", "gif", "txt", "md", "json",
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RoutedTarget {
    Url(String),
    Takeover,
    Studio,
}

pub fn parse_host_args(args: &[String], agent_port: u16) -> HostCommand {
    let mut cmd = HostCommand::default();
    for raw in args {
        let a = raw.trim();
        if a.is_empty() {
            continue;
        }
        match a {
            "--version" | "-V" => cmd.show_version = true,
            "--diagnostics" => cmd.show_diagnostics = true,
            "--install" => cmd.install_mode = true,
            "--uninstall" => cmd.uninstall_mode = true,
            "--quiet" | "-q" => cmd.quiet = true,
            "--purge-data" => cmd.purge_data = true,
            "--portable" => cmd.force_portable = true,
            "--no-tray" => cmd.no_tray = true,
            "--new-window" => cmd.new_window = true,
            "--incognito" | "--private" => cmd.incognito = true,
            "--open-workspace" => cmd.open_workspace = true,
            "--open-telemetry" => cmd.open_telemetry = true,
            "--open-studio" => cmd.open_studio = true,
            "--takeover" => cmd.trigger_takeover = true,
            "--quit" => cmd.quit_existing = true,
            _ if a.starts_with('-') => {
                // Deliberately drop unknown or dangerous Chromium flags from untrusted callers.
            }
            _ => {
                if let Some(routed) = sanitize_external_target(a, agent_port) {
                    match routed {
                        RoutedTarget::Url(u) => cmd.open_urls.push(u),
                        RoutedTarget::Takeover => cmd.trigger_takeover = true,
                        RoutedTarget::Studio => cmd.open_studio = true,
                    }
                }
            }
        }
    }
    cmd
}

pub fn sanitize_external_target(raw: &str, agent_port: u16) -> Option<RoutedTarget> {
    let trimmed = raw.trim().trim_matches('"');
    if trimmed.is_empty() || trimmed.len() > 8192 || trimmed.chars().any(|c| c.is_control()) {
        return None;
    }
    let lower = trimmed.to_ascii_lowercase();

    for blocked in [
        "javascript:",
        "data:",
        "vbscript:",
        "blob:",
        "chrome://",
        "chrome-extension://",
        "edge://",
        "about:srcdoc",
    ] {
        if lower.starts_with(blocked) {
            return None;
        }
    }

    if lower.starts_with("luminara://") {
        let after = lower.trim_start_matches("luminara://");
        let route_only = after
            .split(['?', '#'])
            .next()
            .unwrap_or("")
            .trim_matches('/');
        let base = format!("http://127.0.0.1:{agent_port}");
        return match route_only {
            "" | "newtab" | "home" => Some(RoutedTarget::Url(format!("{base}/newtab"))),
            "workspace" => Some(RoutedTarget::Url(format!("{base}/workspace"))),
            "telemetry" | "cockpit" => Some(RoutedTarget::Url(format!("{base}/workspace#view=telemetry"))),
            "takeover" | "stop" => Some(RoutedTarget::Takeover),
            "studio" => Some(RoutedTarget::Studio),
            _ => Some(RoutedTarget::Url(format!("{base}/newtab"))),
        };
    }

    if lower.starts_with("http://") || lower.starts_with("https://") {
        if trimmed.chars().any(|c| c.is_whitespace()) {
            return None;
        }
        return Some(RoutedTarget::Url(trimmed.to_string()));
    }

    let candidate = Path::new(trimmed);
    if candidate.is_file() {
        let ext = candidate
            .extension()
            .and_then(|e| e.to_str())
            .map(|e| e.to_ascii_lowercase())
            .unwrap_or_default();
        if ALLOWED_LOCAL_EXTS.contains(&ext.as_str()) {
            let canonical = candidate.canonicalize().unwrap_or_else(|_| candidate.to_path_buf());
            let raw_path = canonical.to_string_lossy();
            if let Some(unc) = raw_path
                .strip_prefix(r"\\?\UNC\")
                .or_else(|| raw_path.strip_prefix(r"\\"))
            {
                let posix = unc.replace('\\', "/");
                return Some(RoutedTarget::Url(format!("file://{}", encode_file_uri_path(&posix))));
            }
            let stripped = raw_path.strip_prefix(r"\\?\").unwrap_or(&raw_path);
            let posix = stripped.replace('\\', "/");
            return Some(RoutedTarget::Url(format!("file:///{}", encode_file_uri_path(&posix))));
        }
    }
    None
}

fn encode_file_uri_path(posix: &str) -> String {
    let mut out = String::with_capacity(posix.len() + 16);
    for b in posix.as_bytes() {
        match *b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'/' | b':' | b'-' | b'_' | b'.' | b'~' => {
                out.push(*b as char)
            }
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

pub fn encode_ipc_command(cmd: &HostCommand) -> String {
    let mut tokens: Vec<String> = Vec::new();
    if cmd.quit_existing {
        tokens.push("--quit".into());
    }
    if cmd.trigger_takeover {
        tokens.push("--takeover".into());
    }
    if cmd.new_window {
        tokens.push("--new-window".into());
    }
    if cmd.incognito {
        tokens.push("--incognito".into());
    }
    if cmd.open_workspace {
        tokens.push("--open-workspace".into());
    }
    if cmd.open_telemetry {
        tokens.push("--open-telemetry".into());
    }
    if cmd.open_studio {
        tokens.push("--open-studio".into());
    }
    for u in &cmd.open_urls {
        if !u.contains('\t') && !u.contains('\n') && !u.contains('\r') {
            tokens.push(u.clone());
        }
    }
    if tokens.is_empty() {
        tokens.push("--focus".into());
    }
    format!("LUMINARA_IPC_V1\t{}\n", tokens.join("\t"))
}

pub fn decode_ipc_command(frame: &str, agent_port: u16) -> Option<HostCommand> {
    let line = frame.lines().next()?.trim();
    let mut parts = line.split('\t');
    if parts.next()? != "LUMINARA_IPC_V1" {
        return None;
    }
    let args: Vec<String> = parts.map(|s| s.to_string()).collect();
    Some(parse_host_args(&args, agent_port))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn blocks_dangerous_schemes_and_chromium_flag_injection() {
        let args = vec![
            "--remote-debugging-port=1337".into(),
            "--load-extension=C:\\evil".into(),
            "--gpu-launcher=calc.exe".into(),
            "javascript:alert(1)".into(),
            "data:text/html,<script>alert(1)</script>".into(),
            "chrome://settings".into(),
            "--incognito".into(),
            "https://example.com/path?a=1".into(),
        ];
        let parsed = parse_host_args(&args, 8796);
        assert!(parsed.incognito);
        assert_eq!(parsed.open_urls, vec!["https://example.com/path?a=1"]);
    }

    #[test]
    fn routes_luminara_custom_protocol_including_query_params() {
        assert_eq!(
            sanitize_external_target("luminara://workspace?tab=1", 8796),
            Some(RoutedTarget::Url("http://127.0.0.1:8796/workspace".into()))
        );
        assert_eq!(
            sanitize_external_target("luminara://telemetry#pane", 8796),
            Some(RoutedTarget::Url("http://127.0.0.1:8796/workspace#view=telemetry".into()))
        );
        assert_eq!(
            sanitize_external_target("luminara://takeover", 8796),
            Some(RoutedTarget::Takeover)
        );
    }

    #[test]
    fn ipc_roundtrip_preserves_whitelisted_commands() {
        let orig = HostCommand {
            new_window: true,
            open_urls: vec!["https://luminara.example/docs".into()],
            ..Default::default()
        };
        let encoded = encode_ipc_command(&orig);
        let decoded = decode_ipc_command(&encoded, 8796).expect("decode");
        assert!(decoded.new_window);
        assert_eq!(decoded.open_urls, orig.open_urls);
    }
}
