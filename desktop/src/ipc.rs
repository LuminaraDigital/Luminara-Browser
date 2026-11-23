//! Single-instance Win32 Named Mutex & Overlapped Named Pipe IPC router (`desktop/src/ipc.rs`).
//!
//! Security & Concurrency Guarantees:
//! - `profile_instance_hash` canonicalizes the deepest existing ancestor + relative suffix (immune to
//!   8.3 short-name or pre-creation `ENOENT` drift) and salts with the current user's Windows SID.
//! - Primary creates the Named Pipe ONCE upfront with `FILE_FLAG_FIRST_PIPE_INSTANCE | FILE_FLAG_OVERLAPPED`,
//!   `PIPE_REJECT_REMOTE_CLIENTS`, `nMaxInstances = 1`, and an owner-only SDDL (`OwnerPipeSecurity`),
//!   eliminating pipe squatting and reopen gaps.
//! - Overlapped `ConnectNamedPipe` / `ReadFile` / `WriteFile` wait on `[io_event, shutdown_event]` with
//!   1,000 ms client I/O timeouts + `CancelIoEx`, preventing stalled-client DoS and shutdown deadlocks.
//! - Secondary clients connect with `SECURITY_SQOS_ANONYMOUS` so pipe servers can never impersonate tokens.

use std::mem::zeroed;
use std::path::{Path, PathBuf};
use std::ptr::{null, null_mut};
use std::sync::Arc;
use std::thread;
use std::time::Duration;

use crate::protocol::{decode_ipc_command, encode_ipc_command, HostCommand};
use crate::win32::{
    current_user_sid_string, to_wide, CancelIoEx, CloseHandle, ConnectNamedPipe, CreateEventW,
    CreateFileW, CreateMutexW, CreateNamedPipeW, DisconnectNamedPipe, GetLastError,
    GetOverlappedResult, OwnedHandle, OwnerPipeSecurity, ReadFile, ResetEvent, SetEvent,
    WaitForMultipleObjects, WaitNamedPipeW, WriteFile, DWORD, ERROR_ACCESS_DENIED,
    ERROR_ALREADY_EXISTS, ERROR_IO_PENDING, ERROR_NOT_FOUND, ERROR_PIPE_CONNECTED,
    FILE_FLAG_FIRST_PIPE_INSTANCE, FILE_FLAG_OVERLAPPED, GENERIC_READ, GENERIC_WRITE, HANDLE,
    INFINITE, INVALID_HANDLE_VALUE, OPEN_EXISTING, OVERLAPPED, PIPE_ACCESS_DUPLEX,
    PIPE_READMODE_BYTE, PIPE_REJECT_REMOTE_CLIENTS, PIPE_TYPE_BYTE, PIPE_WAIT,
    SECURITY_SQOS_ANONYMOUS, WAIT_OBJECT_0,
};

const MAX_IPC_BYTES: usize = 32 * 1024;
const CLIENT_IO_TIMEOUT_MS: DWORD = 1000;

fn canonicalize_stable(path: &Path) -> PathBuf {
    let mut existing = path;
    let mut suffix_parts: Vec<& std::ffi::OsStr> = Vec::new();
    while !existing.exists() {
        let Some(name) = existing.file_name() else {
            break;
        };
        suffix_parts.push(name);
        let Some(parent) = existing.parent() else {
            break;
        };
        if parent == existing {
            break;
        }
        existing = parent;
    }
    let mut resolved = existing
        .canonicalize()
        .unwrap_or_else(|_| existing.to_path_buf());
    for part in suffix_parts.into_iter().rev() {
        resolved.push(part);
    }
    resolved
}

pub fn profile_instance_hash(profile_dir: &Path) -> String {
    let resolved = canonicalize_stable(profile_dir);
    let s = resolved.to_string_lossy();
    let stripped = if let Some(rest) = s.strip_prefix(r"\\?\UNC\") {
        format!(r"\\{rest}")
    } else if let Some(rest) = s.strip_prefix(r"\\?\") {
        rest.to_string()
    } else {
        s.into_owned()
    };
    let norm = stripped
        .replace('/', "\\")
        .trim_end_matches('\\')
        .to_ascii_lowercase();
    let sid = current_user_sid_string();

    // 64-bit FNV-1a over `<sid>|<normalized_profile_path>`
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in sid.as_bytes().iter().chain(b"|").chain(norm.as_bytes()) {
        h ^= u64::from(*b);
        h = h.wrapping_mul(0x0000_0100_0000_01b3);
    }
    format!("{h:016x}")
}

pub fn pipe_name_for(instance_hash: &str) -> String {
    format!(r"\\.\pipe\LuminaraBrowserHost_{instance_hash}")
}

pub fn mutex_name_for(instance_hash: &str) -> String {
    format!(r"Local\LuminaraBrowserHost_{instance_hash}")
}

pub enum InstanceLock {
    Primary(OwnedHandle),
    Secondary,
}

pub fn acquire_single_instance(instance_hash: &str) -> Result<InstanceLock, String> {
    let w_name = to_wide(&mutex_name_for(instance_hash));
    let handle = unsafe { CreateMutexW(null_mut(), 1, w_name.as_ptr()) };
    if handle == 0 {
        let err = unsafe { GetLastError() };
        if err == ERROR_ACCESS_DENIED {
            return Ok(InstanceLock::Secondary);
        }
        return Err(format!("CreateMutexW failed ({err})"));
    }
    let err = unsafe { GetLastError() };
    if err == ERROR_ALREADY_EXISTS {
        unsafe {
            CloseHandle(handle);
        }
        return Ok(InstanceLock::Secondary);
    }
    Ok(InstanceLock::Primary(OwnedHandle(handle)))
}

/// Forward a sanitized command from a secondary process to the active primary host.
pub fn send_ipc_command(instance_hash: &str, cmd: &HostCommand) -> Result<(), String> {
    let pipe_path = pipe_name_for(instance_hash);
    let w_pipe = to_wide(&pipe_path);
    let payload = encode_ipc_command(cmd);
    let bytes = payload.as_bytes();
    if bytes.len() > MAX_IPC_BYTES {
        return Err("IPC payload exceeds 32 KiB safety bound".into());
    }

    let mut handle = INVALID_HANDLE_VALUE;
    for _ in 0..10 {
        handle = unsafe {
            CreateFileW(
                w_pipe.as_ptr(),
                GENERIC_READ | GENERIC_WRITE,
                0,
                null_mut(),
                OPEN_EXISTING,
                SECURITY_SQOS_ANONYMOUS,
                0,
            )
        };
        if handle != INVALID_HANDLE_VALUE {
            break;
        }
        unsafe {
            let _ = WaitNamedPipeW(w_pipe.as_ptr(), 250);
        }
        thread::sleep(Duration::from_millis(60));
    }
    if handle == INVALID_HANDLE_VALUE {
        return Err(format!(
            "Could not connect to primary Luminara IPC pipe ({})",
            unsafe { GetLastError() }
        ));
    }
    let _owned = OwnedHandle(handle);

    let mut written: DWORD = 0;
    let ok = unsafe {
        WriteFile(
            handle,
            bytes.as_ptr(),
            bytes.len() as DWORD,
            &mut written,
            null_mut(),
        )
    };
    if ok == 0 {
        return Err(format!("WriteFile to IPC pipe failed ({})", unsafe {
            GetLastError()
        }));
    }

    let mut ack = [0u8; 32];
    let mut read_n: DWORD = 0;
    let _ = unsafe { ReadFile(handle, ack.as_mut_ptr(), ack.len() as DWORD, &mut read_n, null_mut()) };
    Ok(())
}

pub struct IpcServer {
    shutdown_event: Arc<OwnedHandle>,
    join_handle: Option<thread::JoinHandle<()>>,
}

impl IpcServer {
    pub fn start<F>(
        instance_hash: &str,
        agent_port: u16,
        on_command: F,
    ) -> Result<Self, String>
    where
        F: Fn(HostCommand) + Send + Sync + 'static,
    {
        let ev = unsafe { CreateEventW(null_mut(), 1, 0, null()) };
        if ev == 0 {
            return Err(format!("CreateEventW failed ({})", unsafe { GetLastError() }));
        }
        let shutdown_event = Arc::new(OwnedHandle(ev));

        let mut sec_opt = OwnerPipeSecurity::new();
        let sa_ptr = sec_opt
            .as_mut()
            .map(|s| &mut s.attrs as *mut _)
            .unwrap_or(null_mut());

        let w_pipe = to_wide(&pipe_name_for(instance_hash));
        let pipe_raw = unsafe {
            CreateNamedPipeW(
                w_pipe.as_ptr(),
                PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED | FILE_FLAG_FIRST_PIPE_INSTANCE,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                1,
                4096,
                MAX_IPC_BYTES as DWORD,
                CLIENT_IO_TIMEOUT_MS,
                sa_ptr,
            )
        };
        if pipe_raw == INVALID_HANDLE_VALUE {
            return Err(format!(
                "CreateNamedPipeW failed ({}) — pipe may be squatted or busy",
                unsafe { GetLastError() }
            ));
        }

        let pipe = OwnedHandle(pipe_raw);
        let stop_ev = Arc::clone(&shutdown_event);
        let join_handle = thread::spawn(move || ipc_accept_loop(pipe, stop_ev, agent_port, on_command));

        Ok(Self {
            shutdown_event,
            join_handle: Some(join_handle),
        })
    }

    pub fn stop_and_join(&mut self) {
        unsafe {
            let _ = SetEvent(self.shutdown_event.raw());
        }
        if let Some(jh) = self.join_handle.take() {
            let _ = jh.join();
        }
    }
}

impl Drop for IpcServer {
    fn drop(&mut self) {
        self.stop_and_join();
    }
}

fn ipc_accept_loop<F>(
    pipe: OwnedHandle,
    shutdown_event: Arc<OwnedHandle>,
    agent_port: u16,
    on_command: F,
) where
    F: Fn(HostCommand) + Send + Sync + 'static,
{
    let io_ev_raw = unsafe { CreateEventW(null_mut(), 1, 0, null()) };
    if io_ev_raw == 0 {
        return;
    }
    let io_event = OwnedHandle(io_ev_raw);

    loop {
        let mut ov: OVERLAPPED = unsafe { zeroed() };
        ov.hEvent = io_event.raw();
        unsafe {
            let _ = ResetEvent(io_event.raw());
        }

        let ok = unsafe { ConnectNamedPipe(pipe.raw(), &mut ov) };
        if ok == 0 {
            let err = unsafe { GetLastError() };
            if err == ERROR_IO_PENDING {
                let handles = [io_event.raw(), shutdown_event.raw()];
                let wait = unsafe { WaitForMultipleObjects(2, handles.as_ptr(), 0, INFINITE) };
                if wait != WAIT_OBJECT_0 {
                    cancel_and_drain(pipe.raw(), &mut ov);
                    break;
                }
                let mut dummy: DWORD = 0;
                if unsafe { GetOverlappedResult(pipe.raw(), &mut ov, &mut dummy, 0) } == 0 {
                    continue;
                }
            } else if err != ERROR_PIPE_CONNECTED {
                break;
            }
        }

        let mut buf = vec![0u8; MAX_IPC_BYTES];
        let mut total = 0usize;
        while total < MAX_IPC_BYTES {
            match overlapped_read(pipe.raw(), io_event.raw(), shutdown_event.raw(), &mut buf[total..]) {
                Some(0) | None => break,
                Some(n) => {
                    total += n;
                    if buf[..total].contains(&b'\n') {
                        break;
                    }
                }
            }
        }

        let _ = overlapped_write(pipe.raw(), io_event.raw(), shutdown_event.raw(), b"OK\n");
        unsafe {
            let _ = DisconnectNamedPipe(pipe.raw());
        }

        if unsafe { WaitForMultipleObjects(1, &shutdown_event.raw(), 0, 0) } == WAIT_OBJECT_0 {
            break;
        }
        if total > 0 {
            let text = String::from_utf8_lossy(&buf[..total]);
            if let Some(cmd) = decode_ipc_command(&text, agent_port) {
                on_command(cmd);
            }
        }
    }
}

fn cancel_and_drain(pipe: HANDLE, ov: &mut OVERLAPPED) {
    unsafe {
        let cancelled = CancelIoEx(pipe, ov);
        if cancelled != 0 || GetLastError() != ERROR_NOT_FOUND {
            let mut dummy: DWORD = 0;
            let _ = GetOverlappedResult(pipe, ov, &mut dummy, 1);
        }
    }
}

fn overlapped_read(
    pipe: HANDLE,
    io_ev: HANDLE,
    stop_ev: HANDLE,
    dst: &mut [u8],
) -> Option<usize> {
    let mut ov: OVERLAPPED = unsafe { zeroed() };
    ov.hEvent = io_ev;
    unsafe {
        let _ = ResetEvent(io_ev);
    }
    let mut read_n: DWORD = 0;
    let ok = unsafe { ReadFile(pipe, dst.as_mut_ptr(), dst.len() as DWORD, &mut read_n, &mut ov) };
    if ok != 0 {
        return Some(read_n as usize);
    }
    if unsafe { GetLastError() } != ERROR_IO_PENDING {
        return None;
    }
    let handles = [io_ev, stop_ev];
    let wait = unsafe { WaitForMultipleObjects(2, handles.as_ptr(), 0, CLIENT_IO_TIMEOUT_MS) };
    if wait != WAIT_OBJECT_0 {
        cancel_and_drain(pipe, &mut ov);
        return None;
    }
    if unsafe { GetOverlappedResult(pipe, &mut ov, &mut read_n, 0) } == 0 {
        return None;
    }
    Some(read_n as usize)
}

fn overlapped_write(pipe: HANDLE, io_ev: HANDLE, stop_ev: HANDLE, src: &[u8]) -> bool {
    let mut ov: OVERLAPPED = unsafe { zeroed() };
    ov.hEvent = io_ev;
    unsafe {
        let _ = ResetEvent(io_ev);
    }
    let mut written: DWORD = 0;
    let ok = unsafe { WriteFile(pipe, src.as_ptr(), src.len() as DWORD, &mut written, &mut ov) };
    if ok != 0 {
        return true;
    }
    if unsafe { GetLastError() } != ERROR_IO_PENDING {
        return false;
    }
    let handles = [io_ev, stop_ev];
    let wait = unsafe { WaitForMultipleObjects(2, handles.as_ptr(), 0, CLIENT_IO_TIMEOUT_MS) };
    if wait != WAIT_OBJECT_0 {
        cancel_and_drain(pipe, &mut ov);
        return false;
    }
    unsafe { GetOverlappedResult(pipe, &mut ov, &mut written, 0) != 0 }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    #[test]
    fn deterministic_profile_hash_is_16_hex_across_creation() {
        let a = profile_instance_hash(Path::new(r"C:\Luminara\ProfileA"));
        let b = profile_instance_hash(Path::new(r"c:\luminara\profilea\"));
        let c = profile_instance_hash(Path::new(r"C:\Luminara\ProfileB"));
        assert_eq!(a.len(), 16);
        assert_eq!(a, b);
        assert_ne!(a, c);

        let tmp = std::env::temp_dir().join("lum_ipc_hash_nested").join("ProfileSub");
        let _ = std::fs::remove_dir_all(tmp.parent().unwrap());
        let before = profile_instance_hash(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        let after = profile_instance_hash(&tmp);
        let _ = std::fs::remove_dir_all(tmp.parent().unwrap());
        assert_eq!(before, after);
    }

    #[test]
    fn overlapped_ipc_server_roundtrips_and_stops_instantly_without_client() {
        let hash = format!("test{:012x}", std::process::id());
        let received = Arc::new(AtomicUsize::new(0));
        let rx_clone = Arc::clone(&received);
        let mut srv = IpcServer::start(&hash, 8796, move |cmd| {
            if cmd.open_workspace {
                rx_clone.fetch_add(1, Ordering::SeqCst);
            }
        })
        .expect("start overlapped ipc");

        send_ipc_command(
            &hash,
            &HostCommand {
                open_workspace: true,
                ..Default::default()
            },
        )
        .expect("send ipc");
        thread::sleep(Duration::from_millis(40));
        assert_eq!(received.load(Ordering::SeqCst), 1);

        // Must stop immediately via shutdown_event with zero client wakeup needed!
        srv.stop_and_join();
    }

    #[test]
    fn stalled_client_timeout_cancels_cleanly_and_recovers() {
        let hash = format!("stalled{:09x}", std::process::id());
        let received = Arc::new(AtomicUsize::new(0));
        let rx_clone = Arc::clone(&received);
        let mut srv = IpcServer::start(&hash, 8796, move |cmd| {
            if cmd.open_telemetry {
                rx_clone.fetch_add(1, Ordering::SeqCst);
            }
        })
        .expect("start overlapped ipc");

        // Connect a stalled client that writes 0 bytes (triggers 1000ms CLIENT_IO_TIMEOUT_MS + cancel_and_drain)
        let pipe_w = to_wide(&pipe_name_for(&hash));
        let stalled_handle = unsafe {
            CreateFileW(
                pipe_w.as_ptr(),
                GENERIC_READ | GENERIC_WRITE,
                0,
                null_mut(),
                OPEN_EXISTING,
                SECURITY_SQOS_ANONYMOUS,
                0,
            )
        };
        assert_ne!(stalled_handle, INVALID_HANDLE_VALUE);
        thread::sleep(Duration::from_millis(CLIENT_IO_TIMEOUT_MS as u64 + 180));
        unsafe {
            CloseHandle(stalled_handle);
        }

        // Next valid client must succeed immediately without pipe corruption
        send_ipc_command(
            &hash,
            &HostCommand {
                open_telemetry: true,
                ..Default::default()
            },
        )
        .expect("send recovery ipc");
        thread::sleep(Duration::from_millis(50));
        assert_eq!(received.load(Ordering::SeqCst), 1);

        srv.stop_and_join();
    }
}
