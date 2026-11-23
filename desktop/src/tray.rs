//! Native Windows System Tray (`Shell_NotifyIconW` v4), live agent status tooltip,
//! deduplicated Handoff/Firewall/Sequence notifications, and context menu (`desktop/src/tray.rs`).

use std::mem::{size_of, zeroed};
use std::ptr::{null, null_mut};
use std::sync::atomic::{AtomicBool, AtomicIsize, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::thread;
use std::time::Duration;

use crate::http_client::DesktopHeartbeat;
use crate::supervisor::Supervisor;
use crate::win32::{
    load_embedded_icon, open_shell_target, to_wide, write_wide_buf, AppendMenuW, CreatePopupMenu,
    CreateWindowExW, DefWindowProcW, DestroyMenu, DestroyWindow, DispatchMessageW, GetCursorPos,
    GetMessageW, GetModuleHandleW, PostMessageW, PostQuitMessage, RegisterClassExW,
    RegisterWindowMessageW, SetForegroundWindow, Shell_NotifyIconW, TrackPopupMenu,
    TranslateMessage, DWORD, HICON, HWND, LPARAM, LRESULT, MF_CHECKED, MF_GRAYED, MF_SEPARATOR,
    MF_STRING, MF_UNCHECKED, MSG, NIF_ICON, NIF_INFO, NIF_MESSAGE, NIF_SHOWTIP, NIF_TIP,
    NIIF_INFO, NIIF_WARNING, NIM_ADD, NIM_DELETE, NIM_MODIFY, NIM_SETVERSION, NIN_BALLOONUSERCLICK,
    NIN_KEYSELECT, NIN_SELECT, NOTIFYICONDATAW, NOTIFYICON_VERSION_4, POINT, TPM_BOTTOMALIGN,
    TPM_RIGHTBUTTON, UINT, WM_CLOSE, WM_COMMAND, WM_CONTEXTMENU, WM_DESTROY, WM_NULL, WM_USER,
    WNDCLASSEXW, WPARAM,
};

pub const WM_TRAY_CALLBACK: UINT = WM_USER + 20;
pub const WM_HOST_SHUTDOWN: UINT = WM_USER + 21;
pub const WM_BROWSER_EXITED: UINT = WM_USER + 22;

const TRAY_UID: UINT = 1001;

const CMD_NEW_WINDOW: usize = 2001;
const CMD_NEW_PRIVATE: usize = 2002;
const CMD_OPEN_NEWTAB: usize = 2003;
const CMD_OPEN_WORKSPACE: usize = 2004;
const CMD_OPEN_TELEMETRY: usize = 2005;
const CMD_HUMAN_TAKEOVER: usize = 2006;
const CMD_RESTART_DAEMON: usize = 2007;
const CMD_TOGGLE_KEEP_TRAY: usize = 2008;
const CMD_OPEN_LOGS: usize = 2009;
const CMD_INSTALL_DESKTOP: usize = 2010;
const CMD_QUIT: usize = 2011;

struct TrayRuntime {
    supervisor: Arc<Supervisor>,
    hwnd: AtomicIsize,
    icon: HICON,
    taskbar_created_msg: UINT,
    last_heartbeat: Mutex<DesktopHeartbeat>,
    last_alert_id: Mutex<String>,
}

impl TrayRuntime {
    fn notify_balloon(&self, title: &str, body: &str, warning: bool) {
        if self.supervisor.is_shutting_down() {
            return;
        }
        let hwnd = self.hwnd.load(Ordering::SeqCst);
        if hwnd != 0 {
            show_tray_balloon(hwnd, title, body, warning);
        }
    }
}

static TRAY_STATE: OnceLock<Arc<TrayRuntime>> = OnceLock::new();
static SHUTDOWN_REQUESTED: AtomicBool = AtomicBool::new(false);

pub fn is_shutdown_requested() -> bool {
    SHUTDOWN_REQUESTED.load(Ordering::SeqCst)
}

pub fn post_browser_exited() {
    if let Some(st) = TRAY_STATE.get() {
        let hwnd = st.hwnd.load(Ordering::SeqCst);
        if hwnd != 0 {
            unsafe {
                let _ = PostMessageW(hwnd, WM_BROWSER_EXITED, 0, 0);
            }
        }
    }
}

pub fn post_shutdown() {
    SHUTDOWN_REQUESTED.store(true, Ordering::SeqCst);
    if let Some(st) = TRAY_STATE.get() {
        let hwnd = st.hwnd.load(Ordering::SeqCst);
        if hwnd != 0 {
            unsafe {
                let _ = PostMessageW(hwnd, WM_HOST_SHUTDOWN, 0, 0);
            }
        }
    }
}

/// Returns `true` when the user explicitly chose Quit (or `--quit` arrived), `false` when Chrome closed naturally.
pub fn run_tray_loop(supervisor: Arc<Supervisor>) -> Result<bool, String> {
    let class_name = to_wide("LuminaraBrowserTrayHostClass");
    let title = to_wide("Luminara Browser");
    let hinst = unsafe { GetModuleHandleW(null()) };
    let icon = load_embedded_icon(32, 32);
    let taskbar_msg = unsafe { RegisterWindowMessageW(to_wide("TaskbarCreated").as_ptr()) };

    let state = Arc::new(TrayRuntime {
        supervisor: Arc::clone(&supervisor),
        hwnd: AtomicIsize::new(0),
        icon,
        taskbar_created_msg: taskbar_msg,
        last_heartbeat: Mutex::new(DesktopHeartbeat::default()),
        last_alert_id: Mutex::new(String::new()),
    });
    let _ = TRAY_STATE.set(Arc::clone(&state));

    let wc = WNDCLASSEXW {
        cbSize: size_of::<WNDCLASSEXW>() as UINT,
        style: 0,
        lpfnWndProc: Some(tray_wnd_proc),
        cbClsExtra: 0,
        cbWndExtra: 0,
        hInstance: hinst,
        hIcon: icon,
        hCursor: 0,
        hbrBackground: 0,
        lpszMenuName: null(),
        lpszClassName: class_name.as_ptr(),
        hIconSm: icon,
    };
    unsafe {
        RegisterClassExW(&wc);
    }

    let hwnd = unsafe {
        CreateWindowExW(
            0,
            class_name.as_ptr(),
            title.as_ptr(),
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            hinst,
            null_mut(),
        )
    };
    if hwnd == 0 {
        return Err("CreateWindowExW for tray host failed".into());
    }
    state.hwnd.store(hwnd, Ordering::SeqCst);
    add_tray_icon(hwnd, icon, "Luminara Browser — Starting Agent Daemon...");

    // Catch early `--quit` or immediate browser exit that occurred before `hwnd` was registered!
    if is_shutdown_requested() || supervisor.is_shutting_down() {
        unsafe {
            let _ = PostMessageW(hwnd, WM_HOST_SHUTDOWN, 0, 0);
        }
    } else if !supervisor.is_browser_alive() && !supervisor.keep_in_tray() {
        unsafe {
            let _ = PostMessageW(hwnd, WM_BROWSER_EXITED, 0, 0);
        }
    }

    let poll_state = Arc::clone(&state);
    thread::spawn(move || heartbeat_loop(poll_state));

    let mut msg: MSG = unsafe { zeroed() };
    let mut explicit_quit = true;
    unsafe {
        while GetMessageW(&mut msg, 0, 0, 0) > 0 {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
        if msg.wParam == 2 {
            explicit_quit = false;
        }
    }

    // Invalidate `hwnd` atomically BEFORE removing the icon and destroying the window!
    state.hwnd.store(0, Ordering::SeqCst);
    remove_tray_icon(hwnd);
    unsafe {
        let _ = DestroyWindow(hwnd);
    }
    Ok(explicit_quit)
}

fn heartbeat_loop(state: Arc<TrayRuntime>) {
    while !state.supervisor.is_shutting_down() {
        let hb = state.supervisor.client.fetch_heartbeat();
        let hwnd = state.hwnd.load(Ordering::SeqCst);
        if hwnd != 0 && !state.supervisor.is_shutting_down() {
            let tip = format_tooltip(&hb);
            update_tray_tooltip(hwnd, &tip);

            if !hb.alert_id.is_empty() {
                let should_notify = state
                    .last_alert_id
                    .lock()
                    .map(|mut prev| {
                        if *prev != hb.alert_id {
                            *prev = hb.alert_id.clone();
                            true
                        } else {
                            false
                        }
                    })
                    .unwrap_or(false);
                if should_notify {
                    let title = if hb.alert_title.is_empty() {
                        "Luminara Browser — Attention Needed"
                    } else {
                        &hb.alert_title
                    };
                    state.notify_balloon(title, &hb.alert_body, true);
                }
            }
        }
        if let Ok(mut guard) = state.last_heartbeat.lock() {
            *guard = hb;
        }
        for _ in 0..30 {
            if state.supervisor.is_shutting_down() {
                return;
            }
            thread::sleep(Duration::from_millis(100));
        }
    }
}

fn format_tooltip(hb: &DesktopHeartbeat) -> String {
    if !hb.daemon_online {
        return "Luminara Browser — Agent Daemon Offline".into();
    }
    let alerts = hb.pending_handoffs_count + hb.pending_mutations_count + hb.sequence_blocks_count;
    if alerts > 0 {
        return format!(
            "Luminara Browser — Action Needed ({alerts} pending · {} tabs)",
            hb.open_tabs
        );
    }
    if hb.active_leases_count > 0 {
        return format!(
            "Luminara Browser — Agent Active ({} leased · {} tabs)",
            hb.active_leases_count, hb.open_tabs
        );
    }
    if hb.cdp_connected {
        format!("Luminara Browser — Online ({} tabs · CDP Ready)", hb.open_tabs)
    } else {
        "Luminara Browser — Daemon Online (Waiting for Browser)".into()
    }
}

fn make_nid(hwnd: HWND) -> NOTIFYICONDATAW {
    let mut nid: NOTIFYICONDATAW = unsafe { zeroed() };
    nid.cbSize = size_of::<NOTIFYICONDATAW>() as DWORD;
    nid.hWnd = hwnd;
    nid.uID = TRAY_UID;
    nid
}

fn add_tray_icon(hwnd: HWND, icon: HICON, tip: &str) {
    let mut nid = make_nid(hwnd);
    nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP;
    nid.uCallbackMessage = WM_TRAY_CALLBACK;
    nid.hIcon = icon;
    write_wide_buf(&mut nid.szTip, tip);
    unsafe {
        Shell_NotifyIconW(NIM_ADD, &nid);
        nid.uTimeoutOrVersion = NOTIFYICON_VERSION_4;
        Shell_NotifyIconW(NIM_SETVERSION, &nid);
    }
}

fn update_tray_tooltip(hwnd: HWND, tip: &str) {
    let mut nid = make_nid(hwnd);
    nid.uFlags = NIF_TIP | NIF_SHOWTIP;
    write_wide_buf(&mut nid.szTip, tip);
    unsafe {
        let _ = Shell_NotifyIconW(NIM_MODIFY, &nid);
    }
}

pub fn show_tray_balloon(hwnd: HWND, title: &str, body: &str, warning: bool) {
    let mut nid = make_nid(hwnd);
    // Preserve `NIF_SHOWTIP` under `NOTIFYICON_VERSION_4` so standard hover tooltips stay active!
    nid.uFlags = NIF_INFO | NIF_SHOWTIP;
    nid.dwInfoFlags = if warning { NIIF_WARNING } else { NIIF_INFO };
    write_wide_buf(&mut nid.szInfoTitle, title);
    write_wide_buf(&mut nid.szInfo, body);
    unsafe {
        let _ = Shell_NotifyIconW(NIM_MODIFY, &nid);
    }
}

fn remove_tray_icon(hwnd: HWND) {
    let nid = make_nid(hwnd);
    unsafe {
        let _ = Shell_NotifyIconW(NIM_DELETE, &nid);
    }
}

fn show_context_menu(hwnd: HWND, state: &TrayRuntime) {
    let menu = unsafe { CreatePopupMenu() };
    if menu == 0 {
        return;
    }

    let hb = state
        .last_heartbeat
        .lock()
        .map(|g| g.clone())
        .unwrap_or_default();
    let status_label = format_tooltip(&hb).replace('&', "&&");
    let keep_checked = if state.supervisor.keep_in_tray() {
        MF_CHECKED
    } else {
        MF_UNCHECKED
    };

    unsafe {
        AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, to_wide(&status_label).as_ptr());
        AppendMenuW(menu, MF_SEPARATOR, 0, null());
        AppendMenuW(menu, MF_STRING, CMD_NEW_WINDOW, to_wide("New Browser Window").as_ptr());
        AppendMenuW(menu, MF_STRING, CMD_NEW_PRIVATE, to_wide("New Private Window").as_ptr());
        AppendMenuW(menu, MF_STRING, CMD_OPEN_NEWTAB, to_wide("Open Command Deck").as_ptr());
        AppendMenuW(menu, MF_STRING, CMD_OPEN_WORKSPACE, to_wide("Open Generative UI Workspace").as_ptr());
        AppendMenuW(menu, MF_STRING, CMD_OPEN_TELEMETRY, to_wide("Open Telemetry Cockpit").as_ptr());
        AppendMenuW(menu, MF_SEPARATOR, 0, null());
        AppendMenuW(menu, MF_STRING, CMD_HUMAN_TAKEOVER, to_wide("Human Takeover (Stop Agents)").as_ptr());
        AppendMenuW(menu, MF_STRING, CMD_RESTART_DAEMON, to_wide("Restart Agent Daemon").as_ptr());
        AppendMenuW(
            menu,
            MF_STRING | keep_checked,
            CMD_TOGGLE_KEEP_TRAY,
            to_wide("Keep Agent Daemon in Tray on Close").as_ptr(),
        );
        AppendMenuW(menu, MF_SEPARATOR, 0, null());
        AppendMenuW(menu, MF_STRING, CMD_OPEN_LOGS, to_wide("Open Diagnostics Logs Folder").as_ptr());
        if !state.supervisor.layout.is_installed {
            AppendMenuW(
                menu,
                MF_STRING,
                CMD_INSTALL_DESKTOP,
                to_wide("Install for Current User (Start Menu && Desktop)...").as_ptr(),
            );
        }
        AppendMenuW(menu, MF_STRING, CMD_QUIT, to_wide("Quit Luminara Browser").as_ptr());

        let mut pt = POINT { x: 0, y: 0 };
        GetCursorPos(&mut pt);
        SetForegroundWindow(hwnd);
        TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_BOTTOMALIGN, pt.x, pt.y, 0, hwnd, null());
        PostMessageW(hwnd, WM_NULL, 0, 0);
        DestroyMenu(menu);
    }
}

unsafe extern "system" fn tray_wnd_proc(
    hwnd: HWND,
    msg: UINT,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    if let Some(state) = TRAY_STATE.get() {
        if state.taskbar_created_msg != 0 && msg == state.taskbar_created_msg {
            add_tray_icon(hwnd, state.icon, "Luminara Browser");
            return 0;
        }
        match msg {
            WM_TRAY_CALLBACK => {
                // Under NOTIFYICON_VERSION_4, low-word of lParam carries NIN_* / WM_CONTEXTMENU.
                let event = (lparam & 0xFFFF) as UINT;
                match event {
                    WM_CONTEXTMENU => show_context_menu(hwnd, state),
                    NIN_SELECT | NIN_KEYSELECT => {
                        state.supervisor.open_in_browser(&[], false, false);
                    }
                    NIN_BALLOONUSERCLICK => {
                        let url = format!(
                            "http://127.0.0.1:{}/workspace#view=telemetry",
                            state.supervisor.layout.fork.agent_port
                        );
                        state.supervisor.open_in_browser(&[url], false, false);
                    }
                    _ => {}
                }
                return 0;
            }
            WM_COMMAND => {
                let cmd_id = wparam & 0xFFFF;
                let base = format!("http://127.0.0.1:{}", state.supervisor.layout.fork.agent_port);
                match cmd_id {
                    CMD_NEW_WINDOW => state.supervisor.open_in_browser(&[], true, false),
                    CMD_NEW_PRIVATE => state.supervisor.open_in_browser(&[], false, true),
                    CMD_OPEN_NEWTAB => state.supervisor.open_in_browser(&[format!("{base}/newtab")], false, false),
                    CMD_OPEN_WORKSPACE => state.supervisor.open_in_browser(&[format!("{base}/workspace")], false, false),
                    CMD_OPEN_TELEMETRY => state
                        .supervisor
                        .open_in_browser(&[format!("{base}/workspace#view=telemetry")], false, false),
                    CMD_HUMAN_TAKEOVER => {
                        let rt = Arc::clone(state);
                        thread::spawn(move || match rt.supervisor.client.trigger_human_takeover() {
                            Ok(_) => rt.notify_balloon(
                                "Human Takeover Activated",
                                "All active AI agent tab leases have been preempted.",
                                false,
                            ),
                            Err(e) => rt.supervisor.host_log.log("WARN", &format!("Tray takeover failed: {e}")),
                        });
                    }
                    CMD_RESTART_DAEMON => {
                        let rt = Arc::clone(state);
                        thread::spawn(move || {
                            rt.supervisor.restart_daemon();
                            rt.notify_balloon(
                                "Agent Daemon Restarting",
                                "Luminara Agent Daemon is restarting cleanly.",
                                false,
                            );
                        });
                    }
                    CMD_TOGGLE_KEEP_TRAY => {
                        let _ = state.supervisor.toggle_keep_in_tray();
                    }
                    CMD_OPEN_LOGS => {
                        let dir_str = state.supervisor.layout.log_dir.to_string_lossy().into_owned();
                        open_shell_target(&dir_str);
                    }
                    CMD_INSTALL_DESKTOP => {
                        let exe = state.supervisor.layout.exe_path.clone();
                        let _ = std::process::Command::new(exe).arg("--install").spawn();
                    }
                    CMD_QUIT => {
                        PostQuitMessage(0);
                    }
                    _ => {}
                }
                return 0;
            }
            WM_BROWSER_EXITED => {
                if !state.supervisor.keep_in_tray() {
                    // Exit code 2 signals natural browser exit (`explicit_quit = false`)
                    PostQuitMessage(2);
                }
                return 0;
            }
            WM_HOST_SHUTDOWN | WM_CLOSE => {
                PostQuitMessage(0);
                return 0;
            }
            WM_DESTROY => {
                PostQuitMessage(0);
                return 0;
            }
            _ => {}
        }
    }
    DefWindowProcW(hwnd, msg, wparam, lparam)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn early_post_shutdown_latches_shutdown_requested() {
        SHUTDOWN_REQUESTED.store(false, Ordering::SeqCst);
        assert!(!is_shutdown_requested());
        post_shutdown();
        assert!(is_shutdown_requested());
        SHUTDOWN_REQUESTED.store(false, Ordering::SeqCst);
    }
}
