//! Win32 Job-Object Process Supervisor for Agent Daemon & Chromium (`desktop/src/supervisor.rs`).
//!
//! Unified `Mutex<LifecycleState> + Condvar` architecture guarantees:
//! - Concurrent callers to `shutdown_cleanly` block until `Phase::Stopped`, preventing `main()`
//!   from dropping `JobObject` (`KILL_ON_JOB_CLOSE`) mid-SQLite WAL checkpoint.
//! - Zero orphan `pythonw.exe` spawn race: newly spawned children are assigned to `JobObject`
//!   under the state lock or immediately reaped if shutdown started concurrently.
//! - Generation-fenced `restart_daemon` revives a tripped circuit-breaker via `Condvar` and
//!   never kills a newly spawned replacement daemon.
//! - `open_in_browser` reuses `build_chromium_args` so reopening after `Keep in Tray` preserves
//!   Privacy Shield v3, Copilot, NewTab, and CDP flags.

use std::io::{BufRead, BufReader};
use std::os::windows::io::AsRawHandle;
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Condvar, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use crate::config::{find_python_executable, DesktopLayout};
use crate::http_client::DaemonClient;
use crate::logging::RotatingLogger;
use crate::protocol::HostCommand;
use crate::win32::{JobObject, CREATE_NO_WINDOW};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Phase {
    Running,
    ShuttingDown,
    Stopped,
}

struct LifecycleState {
    phase: Phase,
    keep_in_tray: bool,
    owned_daemon: bool,
    browser_alive: bool,
    restart_requested: bool,
    generation: u64,
    daemon_job: Option<JobObject>,
    daemon_child: Option<Child>,
    browser_child: Option<Child>,
}

pub struct Supervisor {
    pub layout: DesktopLayout,
    pub host_log: Arc<RotatingLogger>,
    pub daemon_log: Arc<RotatingLogger>,
    pub client: DaemonClient,
    state: Mutex<LifecycleState>,
    cv: Condvar,
}

impl Supervisor {
    pub fn new(
        layout: DesktopLayout,
        ui_key: String,
        host_log: Arc<RotatingLogger>,
        daemon_log: Arc<RotatingLogger>,
    ) -> Self {
        let client = DaemonClient::new(layout.fork.agent_port, ui_key);
        Self {
            layout,
            host_log,
            daemon_log,
            client,
            state: Mutex::new(LifecycleState {
                phase: Phase::Running,
                keep_in_tray: false,
                owned_daemon: false,
                browser_alive: false,
                restart_requested: false,
                generation: 0,
                daemon_job: None,
                daemon_child: None,
                browser_child: None,
            }),
            cv: Condvar::new(),
        }
    }

    pub fn is_shutting_down(&self) -> bool {
        self.state
            .lock()
            .map(|g| g.phase != Phase::Running)
            .unwrap_or(true)
    }

    pub fn is_browser_alive(&self) -> bool {
        let Ok(mut g) = self.state.lock() else {
            return false;
        };
        if let Some(ch) = g.browser_child.as_mut() {
            if matches!(ch.try_wait(), Ok(Some(_)) | Err(_)) {
                g.browser_child = None;
                g.browser_alive = false;
            }
        }
        g.browser_alive
    }

    pub fn keep_in_tray(&self) -> bool {
        self.state.lock().map(|g| g.keep_in_tray).unwrap_or(false)
    }

    pub fn toggle_keep_in_tray(&self) -> bool {
        if let Ok(mut g) = self.state.lock() {
            g.keep_in_tray = !g.keep_in_tray;
            return g.keep_in_tray;
        }
        false
    }

    pub fn wait_until_stopped(&self) {
        if let Ok(guard) = self.state.lock() {
            drop(self.cv.wait_while(guard, |st| st.phase != Phase::Stopped));
        }
    }

    pub fn start_daemon_watchdog(self: &Arc<Self>) -> Result<bool, String> {
        if !self.layout.fork.enable_agent_cobrowsing {
            self.host_log
                .log("INFO", "Agent co-browsing disabled in fork.json; skipping daemon startup.");
            return Ok(false);
        }
        if self.client.is_daemon_ready() {
            self.host_log.log(
                "INFO",
                &format!(
                    "Agent Daemon already healthy on 127.0.0.1:{}; attaching without spawning duplicate.",
                    self.layout.fork.agent_port
                ),
            );
            return Ok(true);
        }

        let Some(py_exe) = find_python_executable(&self.layout) else {
            self.host_log.log(
                "WARN",
                "Python 3.11+ runtime not found (checked Runtime/python, .venv, PATH, LocalAppData). Browser will start without Agent Daemon.",
            );
            return Ok(false);
        };

        if let Ok(mut st) = self.state.lock() {
            st.owned_daemon = true;
            if st.daemon_job.is_none() {
                st.daemon_job = JobObject::create_kill_on_close().ok();
            }
        }
        self.host_log
            .log("INFO", &format!("Starting supervised Agent Daemon via {}", py_exe.display()));

        let sup = Arc::clone(self);
        thread::spawn(move || sup.daemon_watchdog_loop(py_exe));

        for _ in 0..35 {
            if self.is_shutting_down() {
                return Ok(false);
            }
            if self.client.is_daemon_ready() {
                self.host_log.log(
                    "INFO",
                    &format!("Agent Daemon ready on 127.0.0.1:{}", self.layout.fork.agent_port),
                );
                return Ok(true);
            }
            thread::sleep(Duration::from_millis(100));
        }
        self.host_log
            .log("WARN", "Agent Daemon is still initializing; continuing browser startup.");
        Ok(true)
    }

    fn daemon_watchdog_loop(self: Arc<Self>, py_exe: PathBuf) {
        let mut crash_timestamps: Vec<Instant> = Vec::new();
        let mut backoff_sec = 1u64;

        loop {
            {
                let Ok(mut st) = self.state.lock() else { break };
                if st.phase != Phase::Running {
                    break;
                }
                st.restart_requested = false;
                st.generation = st.generation.wrapping_add(1);
                self.cv.notify_all();
            }

            let mut cmd = Command::new(&py_exe);
            cmd.current_dir(&self.layout.agent_code_dir)
                .env("PYTHONUTF8", "1")
                .env("PYTHONUNBUFFERED", "1")
                .env("PYTHONPATH", &self.layout.agent_code_dir)
                .args(["-m", "forge", "agent-daemon", "--forge-root"])
                .arg(&self.layout.agent_data_dir)
                .args([
                    "--port",
                    &self.layout.fork.agent_port.to_string(),
                    "--cdp-port",
                    &self.layout.fork.cdp_port.to_string(),
                ])
                .creation_flags(CREATE_NO_WINDOW)
                .stdin(Stdio::null())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());

            let started_at = Instant::now();
            let mut child = match cmd.spawn() {
                Ok(c) => c,
                Err(e) => {
                    self.host_log.log("ERROR", &format!("Failed to spawn Agent Daemon: {e}"));
                    break;
                }
            };

            let pid = child.id();
            if let Some(stdout) = child.stdout.take() {
                let log = Arc::clone(&self.daemon_log);
                thread::spawn(move || {
                    for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                        log.append_raw_line(&format!("[stdout] {line}"));
                    }
                });
            }
            if let Some(stderr) = child.stderr.take() {
                let log = Arc::clone(&self.daemon_log);
                thread::spawn(move || {
                    for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                        log.append_raw_line(&format!("[stderr] {line}"));
                    }
                });
            }

            // Assign child to JobObject atomically under lock; reap immediately if shutdown raced!
            {
                let Ok(mut st) = self.state.lock() else {
                    let _ = child.kill();
                    let _ = child.wait();
                    break;
                };
                if st.phase != Phase::Running {
                    let _ = child.kill();
                    let _ = child.wait();
                    break;
                }
                if let Some(job) = st.daemon_job.as_ref() {
                    let _ = job.assign(child.as_raw_handle() as isize);
                }
                st.daemon_child = Some(child);
                self.cv.notify_all();
            }
            self.host_log.log("INFO", &format!("Spawned Agent Daemon (pid={pid})"));

            let exit_code = loop {
                let Ok(mut st) = self.state.lock() else { break None };
                let Some(ch) = st.daemon_child.as_mut() else {
                    break None;
                };
                match ch.try_wait() {
                    Ok(Some(status)) => {
                        st.daemon_child = None;
                        self.cv.notify_all();
                        break status.code();
                    }
                    Ok(None) => {}
                    Err(_) => {
                        st.daemon_child = None;
                        self.cv.notify_all();
                        break None;
                    }
                }
                let _ = self.cv.wait_timeout(st, Duration::from_millis(150));
            };

            let (shutting_down, manual_restart) = match self.state.lock() {
                Ok(st) => (st.phase != Phase::Running, st.restart_requested),
                Err(_) => (true, false),
            };
            if shutting_down {
                self.host_log
                    .log("INFO", &format!("Agent Daemon exited cleanly (code={exit_code:?})"));
                break;
            }
            if manual_restart {
                self.host_log.log("INFO", "Restarting Agent Daemon per user request.");
                backoff_sec = 1;
                crash_timestamps.clear();
                continue;
            }

            let uptime = started_at.elapsed();
            self.host_log.log(
                "WARN",
                &format!(
                    "Agent Daemon exited unexpectedly after {}s (code={exit_code:?})",
                    uptime.as_secs()
                ),
            );
            if uptime >= Duration::from_secs(30) {
                backoff_sec = 1;
                crash_timestamps.clear();
            } else {
                let now = Instant::now();
                crash_timestamps.retain(|t| now.duration_since(*t) < Duration::from_secs(60));
                crash_timestamps.push(now);
                if crash_timestamps.len() >= 5 {
                    self.host_log.log(
                        "ERROR",
                        "Agent Daemon crash-loop circuit breaker tripped (5 crashes within 60s). Use Tray -> Restart Agent Daemon to retry.",
                    );
                    let Ok(guard) = self.state.lock() else { break };
                    let Ok(after_park) = self.cv.wait_while(guard, |st| {
                        st.phase == Phase::Running && !st.restart_requested
                    }) else {
                        break;
                    };
                    if after_park.phase != Phase::Running {
                        break;
                    }
                    crash_timestamps.clear();
                    backoff_sec = 1;
                    continue;
                }
            }

            if let Ok(guard) = self.state.lock() {
                let _ = self.cv.wait_timeout_while(
                    guard,
                    Duration::from_secs(backoff_sec),
                    |st| st.phase == Phase::Running && !st.restart_requested,
                );
            }
            backoff_sec = (backoff_sec * 2).min(15);
        }
    }

    pub fn restart_daemon(self: &Arc<Self>) {
        let (gen_before, was_owned) = match self.state.lock() {
            Ok(mut st) => {
                if st.phase != Phase::Running {
                    return;
                }
                st.restart_requested = true;
                self.cv.notify_all();
                (st.generation, st.owned_daemon)
            }
            Err(_) => return,
        };
        if !was_owned {
            let _ = self.start_daemon_watchdog();
            return;
        }
        let _ = self.client.request_shutdown(false);
        if let Ok(guard) = self.state.lock() {
            if let Ok((mut st, _)) = self.cv.wait_timeout_while(
                guard,
                Duration::from_millis(500),
                |s| s.phase == Phase::Running && s.generation == gen_before && s.daemon_child.is_some(),
            ) {
                // Only force-kill if the SAME generation child is still stuck (never kill the respawned child!).
                if st.generation == gen_before {
                    if let Some(ch) = st.daemon_child.as_mut() {
                        let _ = ch.kill();
                    }
                }
            }
        }
    }

    pub fn build_chromium_args(&self, cmd: &HostCommand) -> Vec<String> {
        let mut args = vec![format!("--user-data-dir={}", self.layout.profile_dir.display())];

        let exts = self.layout.extension_dirs();
        if !exts.is_empty() {
            let joined = exts
                .iter()
                .map(|p| p.to_string_lossy().into_owned())
                .collect::<Vec<_>>()
                .join(",");
            args.push(format!("--load-extension={joined}"));
        }

        args.extend(self.layout.fork.runtime_switches());

        if self.layout.fork.enable_agent_cobrowsing {
            args.push(format!("--remote-debugging-port={}", self.layout.fork.cdp_port));
            args.push(format!(
                "--remote-allow-origins=http://127.0.0.1:{}",
                self.layout.fork.agent_port
            ));
        }

        if cmd.incognito {
            args.push("--incognito".into());
        } else if cmd.new_window {
            args.push("--new-window".into());
        }

        let urls = self.resolve_urls_for_command(cmd);
        if urls.is_empty() {
            let home = if self.layout.fork.enable_agent_cobrowsing {
                "chrome://newtab"
            } else {
                "about:blank"
            };
            args.push(home.into());
        } else {
            args.extend(urls);
        }
        args
    }

    fn resolve_urls_for_command(&self, cmd: &HostCommand) -> Vec<String> {
        let mut urls = cmd.open_urls.clone();
        let base = format!("http://127.0.0.1:{}", self.layout.fork.agent_port);
        if cmd.open_workspace {
            urls.push(format!("{base}/workspace"));
        }
        if cmd.open_telemetry {
            urls.push(format!("{base}/workspace#view=telemetry"));
        }
        if cmd.open_studio {
            urls.push("http://127.0.0.1:8795".into());
        }
        urls
    }

    /// Launch the primary Chromium browser process and spawn a watcher that marks `browser_alive = false` on exit.
    pub fn launch_primary_browser<F>(
        self: &Arc<Self>,
        initial_cmd: &HostCommand,
        on_browser_exit: F,
    ) -> Result<(), String>
    where
        F: FnOnce() + Send + 'static,
    {
        if !self.layout.chrome_exe.is_file() {
            return Err(format!(
                "Luminara Chromium binary missing at {}",
                self.layout.chrome_exe.display()
            ));
        }
        let args = self.build_chromium_args(initial_cmd);
        self.host_log.log(
            "INFO",
            &format!(
                "Launching Chromium ({}) with {} args",
                self.layout.chrome_exe.display(),
                args.len()
            ),
        );
        let child = Command::new(&self.layout.chrome_exe)
            .args(&args)
            .spawn()
            .map_err(|e| format!("Failed to launch chrome.exe: {e}"))?;

        if let Ok(mut st) = self.state.lock() {
            st.browser_alive = true;
            st.browser_child = Some(child);
        }

        let sup = Arc::clone(self);
        thread::spawn(move || {
            loop {
                thread::sleep(Duration::from_millis(150));
                let exited = match sup.state.lock() {
                    Ok(mut st) => match st.browser_child.as_mut() {
                        Some(ch) => match ch.try_wait() {
                            Ok(Some(status)) => {
                                st.browser_child = None;
                                st.browser_alive = false;
                                sup.cv.notify_all();
                                Some(Some(status))
                            }
                            Ok(None) => None,
                            Err(_) => {
                                st.browser_child = None;
                                st.browser_alive = false;
                                sup.cv.notify_all();
                                Some(None)
                            }
                        },
                        None => {
                            st.browser_alive = false;
                            Some(None)
                        }
                    },
                    Err(_) => Some(None),
                };
                if let Some(status_opt) = exited {
                    sup.host_log
                        .log("INFO", &format!("Primary Chromium process exited ({status_opt:?})"));
                    on_browser_exit();
                    break;
                }
            }
        });
        Ok(())
    }

    /// Open a URL, new window, or private window preserving full Luminara extensions, Shield v3 & CDP switches.
    pub fn open_in_browser(&self, urls: &[String], new_window: bool, incognito: bool) {
        if !self.layout.chrome_exe.is_file() {
            return;
        }
        let cmd = HostCommand {
            new_window,
            incognito,
            open_urls: urls.to_vec(),
            ..Default::default()
        };
        let args = self.build_chromium_args(&cmd);
        match Command::new(&self.layout.chrome_exe).args(&args).spawn() {
            Ok(child) => {
                if let Ok(mut st) = self.state.lock() {
                    if let Some(ch) = st.browser_child.as_mut() {
                        if matches!(ch.try_wait(), Ok(Some(_)) | Err(_)) {
                            st.browser_child = None;
                            st.browser_alive = false;
                        }
                    }
                    if !st.browser_alive {
                        st.browser_child = Some(child);
                        st.browser_alive = true;
                        self.cv.notify_all();
                    }
                }
            }
            Err(e) => self.host_log.log("ERROR", &format!("open_in_browser failed: {e}")),
        }
    }

    pub fn handle_routed_command(&self, cmd: &HostCommand) {
        if cmd.trigger_takeover {
            match self.client.trigger_human_takeover() {
                Ok(_) => self.host_log.log("INFO", "Human Takeover triggered via host command."),
                Err(e) => self
                    .host_log
                    .log("WARN", &format!("Human Takeover request failed: {e}")),
            }
        }
        let urls = self.resolve_urls_for_command(cmd);
        if !urls.is_empty() || cmd.new_window || cmd.incognito || !cmd.trigger_takeover {
            self.open_in_browser(&urls, cmd.new_window, cmd.incognito);
        }
    }

    /// Synchronized graceful teardown: concurrent callers block until `Phase::Stopped` so `JobObject`
    /// is never dropped mid-SQLite WAL checkpoint.
    pub fn shutdown_cleanly(&self, explicit_quit: bool) {
        let (should_close_browser, was_owned) = {
            let Ok(mut st) = self.state.lock() else { return };
            if st.phase == Phase::Stopped {
                return;
            }
            if st.phase == Phase::ShuttingDown {
                drop(self.cv.wait_while(st, |s| s.phase != Phase::Stopped));
                return;
            }
            st.phase = Phase::ShuttingDown;
            if let Some(ch) = st.browser_child.as_mut() {
                if matches!(ch.try_wait(), Ok(Some(_)) | Err(_)) {
                    st.browser_child = None;
                    st.browser_alive = false;
                }
            }
            let close_br = explicit_quit && st.browser_alive;
            let owned = st.owned_daemon;
            self.cv.notify_all();
            (close_br, owned)
        };

        self.host_log.log(
            "INFO",
            &format!("Initiating clean Luminara Desktop Host shutdown (close_browser={should_close_browser})."),
        );

        if was_owned {
            let _ = self.client.request_shutdown(should_close_browser);
            let deadline = Instant::now() + Duration::from_secs(3);
            while Instant::now() < deadline {
                let child_running = self
                    .state
                    .lock()
                    .map(|g| g.daemon_child.is_some())
                    .unwrap_or(false);
                if !child_running && !self.client.is_port_open() {
                    break;
                }
                thread::sleep(Duration::from_millis(60));
            }
            if let Ok(mut st) = self.state.lock() {
                if let Some(mut ch) = st.daemon_child.take() {
                    let _ = ch.kill();
                    let _ = ch.wait();
                }
                if let Some(job) = st.daemon_job.take() {
                    job.terminate(0);
                }
            }
        }

        if should_close_browser {
            // Wait briefly for CDP `Browser.close` if daemon ran, then ensure browser_child is closed.
            if was_owned {
                let wait_until = Instant::now() + Duration::from_millis(1200);
                while Instant::now() < wait_until && self.is_browser_alive() {
                    thread::sleep(Duration::from_millis(60));
                }
            }
            if let Ok(mut st) = self.state.lock() {
                if let Some(mut bch) = st.browser_child.take() {
                    let _ = bch.kill();
                    let _ = bch.wait();
                }
                st.browser_alive = false;
            }
        }

        if let Ok(mut st) = self.state.lock() {
            st.phase = Phase::Stopped;
            self.cv.notify_all();
        }
        self.host_log.log("INFO", "Luminara Desktop Host shutdown complete.");
    }
}
