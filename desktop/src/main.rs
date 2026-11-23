//! Luminara Browser Native Win32 Desktop Application Host (`LuminaraBrowser.exe`).
//!
//! Zero-console GUI subsystem entrypoint coordinating:
//! - Explicit Windows AppUserModelID (`Luminara.Browser.Desktop`)
//! - Single-instance Named Mutex & Owner-SDDL Overlapped Named Pipe IPC URL/command router
//! - Win32 Job-Object supervised Agent Daemon with generation-fenced crash auto-restart & rotating logs
//! - Native Windows System Tray with live co-browsing telemetry & handoff/firewall alerts
//! - Built-in `--install` / `--uninstall` delegation to `forge.desktop_installer`

#![windows_subsystem = "windows"]

mod config;
mod http_client;
mod ipc;
mod logging;
mod protocol;
mod supervisor;
mod tray;
mod win32;

use std::env;
use std::io::Write;
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::{Command, ExitCode};
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

use crate::config::{
    ensure_and_sync_ui_key, find_python_executable, read_existing_ui_key,
    rotate_farbling_session_key, DesktopLayout, APP_USER_MODEL_ID, APP_VERSION,
};
use crate::ipc::{
    acquire_single_instance, profile_instance_hash, send_ipc_command, InstanceLock, IpcServer,
};
use crate::logging::RotatingLogger;
use crate::protocol::parse_host_args;
use crate::supervisor::Supervisor;
use crate::win32::{
    attach_parent_console_if_needed, message_box, set_app_user_model_id, CREATE_NO_WINDOW, IDYES,
    MB_ICONERROR, MB_ICONINFORMATION, MB_ICONWARNING, MB_OK, MB_YESNO,
};

fn main() -> ExitCode {
    set_app_user_model_id(APP_USER_MODEL_ID);

    let raw_args: Vec<String> = env::args().skip(1).collect();
    let force_portable = raw_args.iter().any(|a| a == "--portable");
    let layout = match DesktopLayout::resolve(force_portable) {
        Ok(l) => l,
        Err(e) => {
            message_box("Luminara Browser — Startup Error", &e, MB_OK | MB_ICONERROR);
            return ExitCode::from(1);
        }
    };

    let cmd = parse_host_args(&raw_args, layout.fork.agent_port);

    if cmd.show_version {
        attach_parent_console_if_needed();
        let _ = writeln!(
            std::io::stdout(),
            "Luminara Browser Desktop Host v{APP_VERSION} (Chromium {} · AppID {APP_USER_MODEL_ID})",
            layout.fork.chromium_version
        );
        return ExitCode::SUCCESS;
    }

    if cmd.show_diagnostics {
        attach_parent_console_if_needed();
        let py = find_python_executable(&layout)
            .map(|p| p.display().to_string())
            .unwrap_or_else(|| "NOT_FOUND".into());
        let _ = writeln!(
            std::io::stdout(),
            "{{\n  \"app_version\": \"{APP_VERSION}\",\n  \"app_user_model_id\": \"{APP_USER_MODEL_ID}\",\n  \"mode\": \"{}\",\n  \"exe_path\": \"{}\",\n  \"chrome_exe\": \"{}\",\n  \"chrome_present\": {},\n  \"agent_code_dir\": \"{}\",\n  \"agent_data_dir\": \"{}\",\n  \"profile_dir\": \"{}\",\n  \"log_dir\": \"{}\",\n  \"python_exe\": \"{}\",\n  \"agent_port\": {},\n  \"cdp_port\": {},\n  \"instance_hash\": \"{}\"\n}}",
            if layout.is_installed { "installed" } else { "portable" },
            escape_json(&layout.exe_path.display().to_string()),
            escape_json(&layout.chrome_exe.display().to_string()),
            layout.chrome_exe.is_file(),
            escape_json(&layout.agent_code_dir.display().to_string()),
            escape_json(&layout.agent_data_dir.display().to_string()),
            escape_json(&layout.profile_dir.display().to_string()),
            escape_json(&layout.log_dir.display().to_string()),
            escape_json(&py),
            layout.fork.agent_port,
            layout.fork.cdp_port,
            profile_instance_hash(&layout.profile_dir),
        );
        return ExitCode::SUCCESS;
    }

    if cmd.install_mode {
        return run_installer_action(&layout, true, cmd.quiet, false);
    }
    if cmd.uninstall_mode {
        return run_installer_action(&layout, false, cmd.quiet, cmd.purge_data);
    }

    let instance_hash = profile_instance_hash(&layout.profile_dir);
    match acquire_single_instance(&instance_hash) {
        Ok(InstanceLock::Secondary) => {
            if send_ipc_command(&instance_hash, &cmd).is_err() {
                if !cmd.quit_existing && layout.chrome_exe.is_file() {
                    let ui_key = read_existing_ui_key(&layout);
                    let fallback_log = Arc::new(RotatingLogger::new(layout.log_dir.join("host.log")));
                    if !ui_key.is_empty() {
                        fallback_log.register_secret(&ui_key);
                    }
                    let sup = Supervisor::new(
                        layout,
                        ui_key,
                        Arc::clone(&fallback_log),
                        fallback_log,
                    );
                    sup.handle_routed_command(&cmd);
                    return ExitCode::SUCCESS;
                }
                return ExitCode::from(1);
            }
            ExitCode::SUCCESS
        }
        Ok(InstanceLock::Primary(_instance_guard)) => {
            if cmd.quit_existing {
                return ExitCode::SUCCESS;
            }
            run_primary_host(layout, cmd, instance_hash)
        }
        Err(e) => {
            message_box("Luminara Browser — Instance Lock Error", &e, MB_OK | MB_ICONERROR);
            ExitCode::from(1)
        }
    }
}

fn run_primary_host(
    layout: DesktopLayout,
    initial_cmd: protocol::HostCommand,
    instance_hash: String,
) -> ExitCode {
    let host_log = Arc::new(RotatingLogger::new(layout.log_dir.join("host.log")));
    let daemon_log = Arc::new(RotatingLogger::new(layout.log_dir.join("daemon.log")));
    host_log.log(
        "INFO",
        &format!(
            "Luminara Browser Desktop Host v{APP_VERSION} starting (mode={}, profile={})",
            if layout.is_installed { "installed" } else { "portable" },
            layout.profile_dir.display()
        ),
    );

    let ui_key = match ensure_and_sync_ui_key(&layout) {
        Ok(k) => {
            host_log.register_secret(&k);
            daemon_log.register_secret(&k);
            k
        }
        Err(e) => {
            host_log.log("WARN", &format!("UI key synchronization warning: {e}"));
            String::new()
        }
    };
    if let Err(e) = rotate_farbling_session_key(&layout) {
        host_log.log("WARN", &format!("Farbling seed rotation warning: {e}"));
    }

    let supervisor = Arc::new(Supervisor::new(
        layout.clone(),
        ui_key,
        Arc::clone(&host_log),
        Arc::clone(&daemon_log),
    ));

    // Create owner-only Overlapped Named Pipe server upfront before launching browser!
    let ipc_sup = Arc::clone(&supervisor);
    let ipc_no_tray = initial_cmd.no_tray;
    let mut ipc_server = match IpcServer::start(
        &instance_hash,
        layout.fork.agent_port,
        move |incoming| {
            if incoming.quit_existing {
                ipc_sup.host_log.log("INFO", "Received --quit over IPC.");
                if ipc_no_tray {
                    let s = Arc::clone(&ipc_sup);
                    thread::spawn(move || s.shutdown_cleanly(true));
                } else {
                    tray::post_shutdown();
                }
                return;
            }
            ipc_sup.handle_routed_command(&incoming);
        },
    ) {
        Ok(s) => Some(s),
        Err(e) => {
            host_log.log("WARN", &format!("Named Pipe IPC startup warning: {e}"));
            None
        }
    };

    if !initial_cmd.no_tray && tray::is_shutdown_requested() {
        supervisor.shutdown_cleanly(true);
        if let Some(mut srv) = ipc_server.take() {
            srv.stop_and_join();
        }
        return ExitCode::SUCCESS;
    }

    if let Err(e) = supervisor.start_daemon_watchdog() {
        host_log.log("WARN", &format!("Daemon startup warning: {e}"));
    }

    if !initial_cmd.no_tray && tray::is_shutdown_requested() {
        supervisor.shutdown_cleanly(true);
        if let Some(mut srv) = ipc_server.take() {
            srv.stop_and_join();
        }
        return ExitCode::SUCCESS;
    }

    let exit_sup = Arc::clone(&supervisor);
    let no_tray = initial_cmd.no_tray;
    if let Err(e) = supervisor.launch_primary_browser(&initial_cmd, move || {
        if no_tray {
            exit_sup.shutdown_cleanly(false);
        } else {
            tray::post_browser_exited();
        }
    }) {
        host_log.log("ERROR", &e);
        message_box("Luminara Browser — Launch Error", &e, MB_OK | MB_ICONERROR);
        supervisor.shutdown_cleanly(false);
        if let Some(mut srv) = ipc_server.take() {
            srv.stop_and_join();
        }
        return ExitCode::from(1);
    }

    let explicit_quit = if initial_cmd.no_tray {
        supervisor.wait_until_stopped();
        false
    } else {
        match tray::run_tray_loop(Arc::clone(&supervisor)) {
            Ok(eq) => eq,
            Err(e) => {
                host_log.log("ERROR", &format!("Tray loop failed: {e}"));
                true
            }
        }
    };

    supervisor.shutdown_cleanly(explicit_quit);
    if let Some(mut srv) = ipc_server.take() {
        srv.stop_and_join();
    }
    ExitCode::SUCCESS
}

fn quit_and_wait_instance(profile_dir: &std::path::Path) {
    let hash = profile_instance_hash(profile_dir);
    let _ = send_ipc_command(
        &hash,
        &protocol::HostCommand {
            quit_existing: true,
            ..Default::default()
        },
    );
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        if let Ok(InstanceLock::Primary(_guard)) = acquire_single_instance(&hash) {
            break;
        }
        thread::sleep(Duration::from_millis(80));
    }
}

fn run_installer_action(
    layout: &DesktopLayout,
    is_install: bool,
    quiet: bool,
    purge_data: bool,
) -> ExitCode {
    let mut effective_purge = purge_data;
    if !quiet {
        if is_install {
            let resp = message_box(
                "Install Luminara Browser",
                "Install Luminara Browser for the current Windows user (%LOCALAPPDATA%\\Programs\\Luminara Browser) with Start Menu & Desktop shortcuts and Apps & Features entry?\n\nNo Administrator privileges required.",
                MB_YESNO | MB_ICONINFORMATION,
            );
            if resp != IDYES {
                return ExitCode::SUCCESS;
            }
        } else {
            let resp = message_box(
                "Uninstall Luminara Browser",
                "Uninstall Luminara Browser, remove Start Menu & Desktop shortcuts, and unregister from Windows Apps & Features?",
                MB_YESNO | MB_ICONWARNING,
            );
            if resp != IDYES {
                return ExitCode::SUCCESS;
            }
            if !effective_purge {
                let data_resp = message_box(
                    "Remove Browsing Data?",
                    "Also delete your Luminara Browser profile, saved workspaces, vault, and logs in %LOCALAPPDATA%\\Luminara Browser?\n\nChoose No to keep your data for future reinstalls.",
                    MB_YESNO | MB_ICONWARNING,
                );
                effective_purge = data_resp == IDYES;
            }
        }
    }

    let Some(py_exe) = find_python_executable(layout) else {
        if !quiet {
            message_box(
                "Luminara Browser Setup",
                "Python 3.11+ was not found to run the installer backend. Install Python 3.12 or bundle Runtime/python.",
                MB_OK | MB_ICONERROR,
            );
        }
        return ExitCode::from(1);
    };

    // Stop both portable and installed instances cleanly and wait for file locks to release.
    quit_and_wait_instance(&layout.profile_dir);
    if let Ok(local_app) = env::var("LOCALAPPDATA") {
        let installed_prof = PathBuf::from(local_app).join("Luminara Browser").join("User Data");
        if installed_prof != layout.profile_dir {
            quit_and_wait_instance(&installed_prof);
        }
    }

    let mut args = vec![
        "-m".to_string(),
        "forge".to_string(),
        if is_install { "install-desktop" } else { "uninstall-desktop" }.to_string(),
    ];
    if is_install {
        args.push("--source-dir".into());
        args.push(layout.root_dir.display().to_string());
    } else {
        args.push("--install-dir".into());
        args.push(layout.root_dir.display().to_string());
        if effective_purge {
            args.push("--purge-data".into());
        }
    }

    let work_dir = if is_install {
        layout.agent_code_dir.clone()
    } else {
        env::temp_dir()
    };

    let status = Command::new(&py_exe)
        .current_dir(&work_dir)
        .env("PYTHONUTF8", "1")
        .env("PYTHONPATH", &layout.agent_code_dir)
        .args(&args)
        .creation_flags(CREATE_NO_WINDOW)
        .status();

    match status {
        Ok(s) if s.success() => {
            if !quiet {
                let msg = if is_install {
                    "Luminara Browser has been installed! You can launch it from the Start Menu or Desktop shortcut."
                } else {
                    "Luminara Browser has been uninstalled."
                };
                message_box("Luminara Browser Setup", msg, MB_OK | MB_ICONINFORMATION);
            }
            ExitCode::SUCCESS
        }
        Ok(s) => {
            if !quiet {
                message_box(
                    "Luminara Browser Setup Failed",
                    &format!("Setup helper exited with code {:?}.", s.code()),
                    MB_OK | MB_ICONERROR,
                );
            }
            ExitCode::from(1)
        }
        Err(e) => {
            if !quiet {
                message_box("Luminara Browser Setup Failed", &format!("{e}"), MB_OK | MB_ICONERROR);
            }
            ExitCode::from(1)
        }
    }
}

fn escape_json(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for ch in s.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn escape_json_encodes_control_chars_and_quotes() {
        assert_eq!(escape_json("C:\\dir\"a\x01b"), r#"C:\\dir\"a\u0001b"#);
    }
}
