//! Desktop layout discovery, RFC 8259 top-level `fork.json` / `install_manifest.json` parsing,
//! Python runtime lookup, and CSPRNG UI-key / Privacy Shield v3 farbling rotation (`desktop/src/config.rs`).

use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use crate::win32::csprng_hex;

pub const APP_VERSION: &str = env!("CARGO_PKG_VERSION");
pub const APP_USER_MODEL_ID: &str = "Luminara.Browser.Desktop";

const BLOCKED_SWITCH_PREFIXES: &[&str] = &[
    "--gpu-launcher",
    "--renderer-cmd-prefix",
    "--utility-cmd-prefix",
    "--browser-subprocess-path",
    "--ppapi-plugin-launcher",
    "--no-sandbox",
    "--load-extension",
    "--user-data-dir",
    "--remote-debugging-port",
];

pub fn strip_verbatim(path: PathBuf) -> PathBuf {
    let s = path.to_string_lossy();
    if let Some(unc) = s.strip_prefix(r"\\?\UNC\") {
        return PathBuf::from(format!(r"\\{unc}"));
    }
    if let Some(drive) = s.strip_prefix(r"\\?\") {
        return PathBuf::from(drive);
    }
    path
}

#[derive(Debug, Clone)]
pub struct ForkConfig {
    pub brand_name: String,
    pub slug: String,
    pub chromium_version: String,
    pub cdp_port: u16,
    pub agent_port: u16,
    pub enable_agent_cobrowsing: bool,
    pub portable_mode: bool,
    pub roaming_unencrypted_cookies: bool,
    pub canvas_noise: bool,
    pub client_rects_noise: bool,
    pub webgl_spoof: bool,
    pub popups_to_tabs: bool,
    pub force_punycode: bool,
    pub allow_crx_install: bool,
    pub extra_cli_switches: Vec<String>,
}

impl Default for ForkConfig {
    fn default() -> Self {
        Self {
            brand_name: "Luminara Browser".into(),
            slug: "luminara-browser".into(),
            chromium_version: "157.0.8103.78".into(),
            cdp_port: 9229,
            agent_port: 8796,
            enable_agent_cobrowsing: true,
            portable_mode: true,
            roaming_unencrypted_cookies: false,
            canvas_noise: true,
            client_rects_noise: true,
            webgl_spoof: false,
            popups_to_tabs: true,
            force_punycode: true,
            allow_crx_install: true,
            extra_cli_switches: Vec::new(),
        }
    }
}

impl ForkConfig {
    pub fn load_from_file(path: &Path) -> Self {
        let Ok(raw) = fs::read_to_string(path) else {
            return Self::default();
        };
        Self::parse_json(&raw)
    }

    pub fn parse_json(raw: &str) -> Self {
        let mut cfg = Self::default();
        if let Some(s) = json_get_string(raw, "brand_name") {
            if !s.trim().is_empty() {
                cfg.brand_name = s;
            }
        }
        if let Some(s) = json_get_string(raw, "slug") {
            if !s.trim().is_empty() {
                cfg.slug = s;
            }
        }
        if let Some(s) = json_get_string(raw, "chromium_version") {
            if !s.trim().is_empty() {
                cfg.chromium_version = s;
            }
        }
        if let Some(n) = json_get_u16(raw, "cdp_port") {
            if n >= 1024 {
                cfg.cdp_port = n;
            }
        }
        if let Some(n) = json_get_u16(raw, "agent_port") {
            if n >= 1024 && n != cfg.cdp_port {
                cfg.agent_port = n;
            }
        }
        if let Some(b) = json_get_bool(raw, "enable_agent_cobrowsing") {
            cfg.enable_agent_cobrowsing = b;
        }
        if let Some(b) = json_get_bool(raw, "portable_mode") {
            cfg.portable_mode = b;
        }
        if let Some(b) = json_get_bool(raw, "roaming_unencrypted_cookies") {
            cfg.roaming_unencrypted_cookies = b;
        }
        if let Some(b) = json_get_bool(raw, "canvas_noise") {
            cfg.canvas_noise = b;
        }
        if let Some(b) = json_get_bool(raw, "client_rects_noise") {
            cfg.client_rects_noise = b;
        }
        if let Some(b) = json_get_bool(raw, "webgl_spoof") {
            cfg.webgl_spoof = b;
        }
        if let Some(b) = json_get_bool(raw, "popups_to_tabs") {
            cfg.popups_to_tabs = b;
        }
        if let Some(b) = json_get_bool(raw, "force_punycode") {
            cfg.force_punycode = b;
        }
        if let Some(b) = json_get_bool(raw, "allow_crx_install") {
            cfg.allow_crx_install = b;
        }
        cfg.extra_cli_switches = json_get_string_array(raw, "extra_cli_switches");
        cfg
    }

    pub fn runtime_switches(&self) -> Vec<String> {
        let mut sw = vec![
            "--no-default-browser-check".into(),
            "--no-pings".into(),
            "--disable-background-networking".into(),
            "--disable-Breakpad".into(),
            "--disable-component-update".into(),
            "--disable-domain-reliability".into(),
        ];
        if self.portable_mode && self.roaming_unencrypted_cookies {
            sw.push("--disable-encryption".into());
            sw.push("--disable-machine-id".into());
        }
        if self.canvas_noise {
            sw.push("--fingerprinting-canvas-image-data-noise".into());
        }
        if self.client_rects_noise {
            sw.push("--fingerprinting-client-rects-noise".into());
        }
        if self.webgl_spoof {
            sw.push("--ungoogled-webgl-renderer=Generic GPU".into());
        }
        if self.popups_to_tabs {
            sw.push("--popups-to-tabs".into());
        }
        if self.force_punycode {
            sw.push("--force-punycode-hostnames".into());
        }
        if self.allow_crx_install {
            sw.push("--extension-mime-request-handling=always-prompt-for-install".into());
        }
        for extra in &self.extra_cli_switches {
            let clean = extra.trim();
            if clean.is_empty()
                || clean.chars().any(|c| {
                    c.is_control()
                        || matches!(c, '"' | '\'' | '`' | '$' | '&' | '|' | ';' | '<' | '>' | '(' | ')')
                })
            {
                continue;
            }
            let normalized = if clean.starts_with("--") {
                clean.to_string()
            } else {
                format!("--{clean}")
            };
            let low = normalized.to_ascii_lowercase();
            if BLOCKED_SWITCH_PREFIXES.iter().any(|p| low == *p || low.starts_with(&format!("{p}="))) {
                continue;
            }
            sw.push(normalized);
        }
        sw
    }
}

#[derive(Debug, Clone)]
pub struct DesktopLayout {
    pub exe_path: PathBuf,
    pub root_dir: PathBuf,
    pub app_dir: PathBuf,
    pub chrome_exe: PathBuf,
    pub agent_code_dir: PathBuf,
    pub agent_data_dir: PathBuf,
    pub profile_dir: PathBuf,
    pub log_dir: PathBuf,
    pub is_installed: bool,
    pub fork: ForkConfig,
}

impl DesktopLayout {
    pub fn resolve(force_portable: bool) -> Result<Self, String> {
        let exe_path = strip_verbatim(env::current_exe().map_err(|e| format!("current_exe failed: {e}"))?);
        let root_dir = exe_path
            .parent()
            .ok_or_else(|| "exe has no parent directory".to_string())?
            .to_path_buf();
        Self::resolve_from_root(exe_path, root_dir, force_portable)
    }

    pub fn resolve_from_root(exe_path: PathBuf, root_dir: PathBuf, force_portable: bool) -> Result<Self, String> {
        let root_dir = strip_verbatim(root_dir);
        let app_dir = root_dir.join("App");
        let chrome_exe = app_dir.join("chrome.exe");

        let manifest_path = root_dir.join("install_manifest.json");
        let manifest_raw = fs::read_to_string(&manifest_path).unwrap_or_default();
        let is_installed = !force_portable
            && json_get_string(&manifest_raw, "mode").as_deref() == Some("installed");

        let dev_forge = root_dir.join("..").join("..");
        let is_dev_checkout = !is_installed && dev_forge.join("forge").join("__main__.py").is_file();

        let agent_code_dir = if is_dev_checkout {
            strip_verbatim(dev_forge.canonicalize().unwrap_or(dev_forge))
        } else {
            root_dir.join("Agent")
        };

        let (profile_dir, agent_data_dir, log_dir) = if is_installed {
            let local_app = env::var("LOCALAPPDATA")
                .map(PathBuf::from)
                .unwrap_or_else(|_| root_dir.clone());
            let base = local_app.join("Luminara Browser");
            let prof = json_get_string(&manifest_raw, "profile_dir")
                .filter(|s| !s.trim().is_empty())
                .map(PathBuf::from)
                .unwrap_or_else(|| base.join("User Data"));
            let data = json_get_string(&manifest_raw, "agent_data_dir")
                .filter(|s| !s.trim().is_empty())
                .map(PathBuf::from)
                .unwrap_or_else(|| base.join("AgentData"));
            let logs = base.join("Logs");
            (strip_verbatim(prof), strip_verbatim(data), strip_verbatim(logs))
        } else {
            let prof = root_dir.join("Profile");
            let data = agent_code_dir.clone();
            let logs = root_dir.join("Logs");
            (prof, data, logs)
        };

        let fork_path = if agent_data_dir.join("fork.json").is_file() {
            agent_data_dir.join("fork.json")
        } else {
            agent_code_dir.join("fork.json")
        };
        let fork = ForkConfig::load_from_file(&fork_path);

        Ok(Self {
            exe_path,
            root_dir,
            app_dir,
            chrome_exe,
            agent_code_dir,
            agent_data_dir,
            profile_dir,
            log_dir,
            is_installed,
            fork,
        })
    }

    pub fn extension_dirs(&self) -> Vec<PathBuf> {
        let ext_root = self.app_dir.join("extensions");
        let mut dirs = Vec::new();
        for name in ["forge-shield", "luminara-copilot", "luminara-newtab", "luminara-theme"] {
            if name == "luminara-copilot" && !self.fork.enable_agent_cobrowsing {
                continue;
            }
            let cand = ext_root.join(name);
            if cand.is_dir() {
                dirs.push(cand);
            }
        }
        dirs
    }
}

pub fn find_python_executable(layout: &DesktopLayout) -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = vec![
        layout.root_dir.join("Runtime").join("python").join("pythonw.exe"),
        layout.root_dir.join("Runtime").join("python").join("python.exe"),
    ];
    if let Some(repo_parent) = layout.agent_code_dir.parent() {
        candidates.push(repo_parent.join(".venv").join("Scripts").join("pythonw.exe"));
        candidates.push(repo_parent.join(".venv").join("Scripts").join("python.exe"));
    }
    candidates.push(layout.agent_code_dir.join(".venv").join("Scripts").join("pythonw.exe"));
    candidates.push(layout.agent_code_dir.join(".venv").join("Scripts").join("python.exe"));

    if let Ok(path_var) = env::var("PATH") {
        for exe_name in ["pythonw.exe", "python.exe"] {
            for dir in env::split_paths(&path_var) {
                let s = dir.to_string_lossy().to_ascii_lowercase();
                if s.contains(r"\windowsapps") {
                    continue;
                }
                candidates.push(dir.join(exe_name));
            }
        }
    }

    if let Ok(local_app) = env::var("LOCALAPPDATA") {
        let py_base = PathBuf::from(local_app).join("Programs").join("Python");
        for ver in ["Python313", "Python312", "Python311"] {
            candidates.push(py_base.join(ver).join("pythonw.exe"));
            candidates.push(py_base.join(ver).join("python.exe"));
        }
    }

    for cand in candidates {
        if cand.is_file() {
            let lower = cand.to_string_lossy().to_ascii_lowercase();
            if !lower.contains(r"\windowsapps\") {
                return Some(strip_verbatim(cand));
            }
        }
    }
    None
}

fn is_valid_ui_key_token(s: &str) -> bool {
    s.len() >= 32
        && s.len() <= 256
        && s.bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}

pub fn read_existing_ui_key(layout: &DesktopLayout) -> String {
    let key_file = layout.agent_data_dir.join("outputs").join("local_ui_key.txt");
    let raw = fs::read_to_string(&key_file).unwrap_or_default();
    let trimmed = raw.trim();
    if is_valid_ui_key_token(trimmed) {
        trimmed.to_string()
    } else {
        String::new()
    }
}

pub fn ensure_and_sync_ui_key(layout: &DesktopLayout) -> Result<String, String> {
    let outputs_dir = layout.agent_data_dir.join("outputs");
    fs::create_dir_all(&outputs_dir).map_err(|e| format!("create outputs dir: {e}"))?;
    fs::create_dir_all(&layout.profile_dir).map_err(|e| format!("create profile dir: {e}"))?;

    let data_fork = layout.agent_data_dir.join("fork.json");
    let code_fork = layout.agent_code_dir.join("fork.json");
    if !data_fork.is_file() && code_fork.is_file() {
        let _ = fs::copy(&code_fork, &data_fork);
    }

    let key_file = outputs_dir.join("local_ui_key.txt");
    let ledger_file = outputs_dir.join("action_ledger.jsonl");
    let init_marker = layout.profile_dir.join(".ui_key_initialized");

    let existing = fs::read_to_string(&key_file).unwrap_or_default().trim().to_string();
    let needs_gen = !is_valid_ui_key_token(&existing)
        || (!init_marker.is_file() && !ledger_file.is_file());

    let active_key = if needs_gen {
        let generated = csprng_hex(32)?;
        atomic_write_text(&key_file, &format!("{generated}\n"))?;
        generated
    } else {
        existing
    };

    if !init_marker.is_file() {
        let _ = atomic_write_text(&init_marker, "ok\n");
    }

    let bundled_key = layout.root_dir.join("Agent").join("outputs").join("local_ui_key.txt");
    if bundled_key != key_file {
        if let Some(p) = bundled_key.parent() {
            if p.is_dir() {
                let _ = atomic_write_text(&bundled_key, &format!("{active_key}\n"));
            }
        }
    }
    if let Ok(home) = env::var("USERPROFILE") {
        let home_dir = PathBuf::from(home).join(".luminara-browser");
        let _ = fs::create_dir_all(&home_dir);
        let _ = atomic_write_text(&home_dir.join("local_ui_key.txt"), &format!("{active_key}\n"));
    }

    let targets = [
        "App/luminara_pages/newtab.html",
        "App/luminara_pages/workspace.html",
        "App/forge_ntp/index.html",
        "App/extensions/luminara-copilot/sidepanel.js",
        "App/extensions/luminara-newtab/newtab.js",
        "App/extensions/luminara-newtab/newtab_bg.js",
        "App/extensions/luminara-newtab/workspace.js",
        "App/extensions/forge-shield/popup.js",
    ];
    for rel in targets {
        let p = layout.root_dir.join(rel);
        if p.is_file() {
            let _ = replace_js_const(&p, "UI_KEY", &active_key);
        }
    }
    Ok(active_key)
}

pub fn rotate_farbling_session_key(layout: &DesktopLayout) -> Result<(), String> {
    let farble_path = layout.app_dir.join("extensions").join("forge-shield").join("farble.js");
    if !farble_path.is_file() {
        return Ok(());
    }
    let session_hex = csprng_hex(16)?;
    replace_js_const(&farble_path, "SESSION_KEY", &session_hex)
}

fn escape_js_double_quoted(val: &str) -> String {
    let mut out = String::with_capacity(val.len());
    for ch in val.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\r' => out.push_str("\\r"),
            '\n' => out.push_str("\\n"),
            _ => out.push(ch),
        }
    }
    out
}

fn replace_js_const(path: &Path, var_name: &str, new_val: &str) -> Result<(), String> {
    let raw = fs::read_to_string(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    let safe_val = escape_js_double_quoted(new_val);
    let prefix = format!("const {var_name} = \"");
    let mut out = String::with_capacity(raw.len() + 64);
    let mut cursor = 0usize;
    let mut changed = false;
    while let Some(rel) = raw[cursor..].find(&prefix) {
        let start = cursor + rel;
        let val_start = start + prefix.len();
        if let Some(end_rel) = raw[val_start..].find("\";") {
            out.push_str(&raw[cursor..val_start]);
            out.push_str(&safe_val);
            out.push_str("\";");
            cursor = val_start + end_rel + 2;
            changed = true;
        } else {
            break;
        }
    }
    if changed {
        out.push_str(&raw[cursor..]);
        atomic_write_text(path, &out)?;
    }
    Ok(())
}

pub fn atomic_write_text(path: &Path, content: &str) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("mkdir {}: {e}", parent.display()))?;
    }
    let pid = std::process::id();
    let fname = path.file_name().and_then(|s| s.to_str()).unwrap_or("luminara");
    let tmp = path.with_file_name(format!(".{fname}.{pid}.tmp"));
    fs::write(&tmp, content.as_bytes()).map_err(|e| format!("write {}: {e}", tmp.display()))?;
    fs::rename(&tmp, path)
        .or_else(|_| {
            let _ = fs::remove_file(path);
            fs::rename(&tmp, path)
        })
        .map_err(|e| {
            let _ = fs::remove_file(&tmp);
            format!("replace {}: {e}", path.display())
        })
}

// --- Zero-dependency RFC 8259 Top-Level JSON Object Scanner (supports \uXXXX & surrogate pairs) ---

fn json_parse_string(input: &str) -> Option<(String, &str)> {
    let s = input.trim_start();
    let mut bytes_idx = s.char_indices();
    if bytes_idx.next()?.1 != '"' {
        return None;
    }
    let mut out = String::new();
    while let Some((idx, ch)) = bytes_idx.next() {
        if ch == '"' {
            return Some((out, &s[idx + 1..]));
        }
        if ch != '\\' {
            out.push(ch);
            continue;
        }
        let (_, esc) = bytes_idx.next()?;
        match esc {
            '"' => out.push('"'),
            '\\' => out.push('\\'),
            '/' => out.push('/'),
            'b' => out.push('\u{0008}'),
            'f' => out.push('\u{000C}'),
            'n' => out.push('\n'),
            'r' => out.push('\r'),
            't' => out.push('\t'),
            'u' => {
                let mut hex = String::with_capacity(4);
                for _ in 0..4 {
                    hex.push(bytes_idx.next()?.1);
                }
                let code = u16::from_str_radix(&hex, 16).ok()?;
                if (0xD800..=0xDBFF).contains(&code) {
                    // Decode UTF-16 surrogate pair (\uD8xx\uDCxx)
                    let (_, b1) = bytes_idx.next()?;
                    let (_, b2) = bytes_idx.next()?;
                    if b1 != '\\' || b2 != 'u' {
                        return None;
                    }
                    let mut hex2 = String::with_capacity(4);
                    for _ in 0..4 {
                        hex2.push(bytes_idx.next()?.1);
                    }
                    let low = u16::from_str_radix(&hex2, 16).ok()?;
                    if !(0xDC00..=0xDFFF).contains(&low) {
                        return None;
                    }
                    let combined = 0x1_0000 + (((u32::from(code) - 0xD800) << 10) | (u32::from(low) - 0xDC00));
                    out.push(char::from_u32(combined)?);
                } else {
                    out.push(char::from_u32(u32::from(code))?);
                }
            }
            _ => out.push(esc),
        }
    }
    None
}

fn json_skip_value(input: &str) -> Option<&str> {
    let s = input.trim_start();
    let first = s.chars().next()?;
    if first == '"' {
        let (_, rest) = json_parse_string(s)?;
        return Some(rest);
    }
    if first == '{' || first == '[' {
        let (open, close) = if first == '{' { ('{', '}') } else { ('[', ']') };
        let mut depth = 0usize;
        let mut cur = s;
        while !cur.is_empty() {
            let c = cur.chars().next()?;
            if c == '"' {
                let (_, rest) = json_parse_string(cur)?;
                cur = rest;
            } else {
                if c == open {
                    depth += 1;
                } else if c == close {
                    depth -= 1;
                    if depth == 0 {
                        return Some(&cur[c.len_utf8()..]);
                    }
                }
                cur = &cur[c.len_utf8()..];
            }
        }
        return None;
    }
    let end = s
        .find(|c: char| c.is_whitespace() || matches!(c, ',' | '}' | ']'))
        .unwrap_or(s.len());
    if end == 0 {
        None
    } else {
        Some(&s[end..])
    }
}

fn json_find_top_level_value<'a>(raw: &'a str, target_key: &str) -> Option<&'a str> {
    let s = raw.trim_start();
    let mut cur = s.strip_prefix('{')?.trim_start();
    if let Some(_rest) = cur.strip_prefix('}') {
        return None;
    }
    loop {
        let (k, after_k) = json_parse_string(cur)?;
        let after_colon = after_k.trim_start().strip_prefix(':')?.trim_start();
        if k == target_key {
            return Some(after_colon);
        }
        let after_val = json_skip_value(after_colon)?.trim_start();
        cur = after_val.strip_prefix(',')?.trim_start();
    }
}

pub fn json_get_string(raw: &str, key: &str) -> Option<String> {
    let val_slice = json_find_top_level_value(raw, key)?;
    json_parse_string(val_slice).map(|(s, _)| s)
}

pub fn json_get_bool(raw: &str, key: &str) -> Option<bool> {
    let val = json_find_top_level_value(raw, key)?;
    if val.starts_with("true") {
        Some(true)
    } else if val.starts_with("false") {
        Some(false)
    } else {
        None
    }
}

pub fn json_get_u16(raw: &str, key: &str) -> Option<u16> {
    json_get_u64(raw, key).and_then(|v| u16::try_from(v).ok())
}

pub fn json_get_u64(raw: &str, key: &str) -> Option<u64> {
    let val = json_find_top_level_value(raw, key)?;
    let digits: String = val.chars().take_while(|c| c.is_ascii_digit()).collect();
    digits.parse::<u64>().ok()
}

fn json_get_string_array(raw: &str, key: &str) -> Vec<String> {
    let Some(val) = json_find_top_level_value(raw, key) else {
        return Vec::new();
    };
    let Some(mut cur) = val.strip_prefix('[').map(str::trim_start) else {
        return Vec::new();
    };
    let mut items = Vec::new();
    if cur.starts_with(']') {
        return items;
    }
    while let Some((item, rest)) = json_parse_string(cur) {
        items.push(item);
        let rest_trim = rest.trim_start();
        if let Some(after_comma) = rest_trim.strip_prefix(',') {
            cur = after_comma.trim_start();
        } else {
            break;
        }
    }
    items
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_fork_json_unicode_surrogates_ipv6_brackets_and_ignores_nested_spoofs() {
        let sample = r#"{
          "extra_gn_flags": { "cdp_port": "9999", "brand_name": "NestedSpoof" },
          "note": "contains \"brand_name\": \"FakeInsideString\" literal",
          "brand_name": "Luminara \u00fc\u6797 \ud83d\ude80",
          "slug": "luminara-browser",
          "cdp_port": 9231,
          "agent_port": 8799,
          "enable_agent_cobrowsing": true,
          "webgl_spoof": true,
          "extra_cli_switches": ["--proxy-server=http://[::1]:8080", "--gpu-launcher=calc.exe", "bad(sub)"]
        }"#;
        let cfg = ForkConfig::parse_json(sample);
        assert_eq!(cfg.brand_name, "Luminara ü林 🚀");
        assert_eq!(cfg.cdp_port, 9231);
        assert_eq!(cfg.agent_port, 8799);
        assert!(cfg.webgl_spoof);
        let sw = cfg.runtime_switches();
        assert!(sw.iter().any(|s| s == "--proxy-server=http://[::1]:8080"));
        assert!(!sw.iter().any(|s| s.contains("gpu-launcher")));
        assert!(!sw.iter().any(|s| s.contains("bad(sub)")));
    }

    #[test]
    fn replaces_and_escapes_js_const_safely() {
        let dir = env::temp_dir().join("lum_cfg_js_test");
        let _ = fs::create_dir_all(&dir);
        let p = dir.join("sidepanel.js");
        fs::write(&p, "const UI_KEY = \"\";\nconsole.log('ok');\n").unwrap();
        replace_js_const(&p, "UI_KEY", "abc\"def").unwrap();
        let updated = fs::read_to_string(&p).unwrap();
        assert_eq!(updated, "const UI_KEY = \"abc\\\"def\";\nconsole.log('ok');\n");
        let _ = fs::remove_dir_all(&dir);
    }
}
