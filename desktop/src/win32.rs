//! Minimal, zero-dependency Win32 FFI bindings and safe RAII helpers (`desktop/src/win32.rs`).
//!
//! Compile-time `size_of` assertions guarantee exact x86_64 Windows ABI compatibility.

#![allow(non_snake_case, non_camel_case_types, clippy::upper_case_acronyms)]

use std::ffi::OsStr;
use std::mem::{size_of, zeroed};
use std::os::windows::ffi::OsStrExt;
use std::ptr::{null, null_mut};

pub type BOOL = i32;
pub type DWORD = u32;
pub type UINT = u32;
pub type LONG = i32;
pub type LRESULT = isize;
pub type WPARAM = usize;
pub type LPARAM = isize;
pub type HANDLE = isize;
pub type HWND = isize;
pub type HINSTANCE = isize;
pub type HICON = isize;
pub type HCURSOR = isize;
pub type HBRUSH = isize;
pub type HMENU = isize;
pub type ATOM = u16;

pub const INVALID_HANDLE_VALUE: HANDLE = -1;
pub const ERROR_ACCESS_DENIED: DWORD = 5;
pub const ERROR_ALREADY_EXISTS: DWORD = 183;
pub const ERROR_PIPE_CONNECTED: DWORD = 535;
pub const ERROR_IO_PENDING: DWORD = 997;
pub const ERROR_NOT_FOUND: DWORD = 1168;
pub const CREATE_NO_WINDOW: DWORD = 0x0800_0000;
pub const WAIT_OBJECT_0: DWORD = 0;
pub const INFINITE: DWORD = 0xFFFF_FFFF;
pub const STD_OUTPUT_HANDLE: DWORD = (-11i32) as DWORD;
pub const ATTACH_PARENT_PROCESS: DWORD = 0xFFFF_FFFF;
pub const TOKEN_QUERY: DWORD = 0x0008;
pub const TOKEN_USER_CLASS: u32 = 1;
pub const SDDL_REVISION_1: DWORD = 1;

// Job Object constants
pub const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS: u32 = 9;
pub const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: DWORD = 0x0000_2000;

// Named Pipe & File constants
pub const PIPE_ACCESS_DUPLEX: DWORD = 0x0000_0003;
pub const FILE_FLAG_FIRST_PIPE_INSTANCE: DWORD = 0x0008_0000;
pub const FILE_FLAG_OVERLAPPED: DWORD = 0x4000_0000;
pub const PIPE_TYPE_BYTE: DWORD = 0x0000_0000;
pub const PIPE_READMODE_BYTE: DWORD = 0x0000_0000;
pub const PIPE_WAIT: DWORD = 0x0000_0000;
pub const PIPE_REJECT_REMOTE_CLIENTS: DWORD = 0x0000_0008;
pub const GENERIC_READ: DWORD = 0x8000_0000;
pub const GENERIC_WRITE: DWORD = 0x4000_0000;
pub const OPEN_EXISTING: DWORD = 3;
// SECURITY_SQOS_PRESENT | SECURITY_ANONYMOUS (prevents server impersonation of client token)
pub const SECURITY_SQOS_ANONYMOUS: DWORD = 0x0010_0000;

// Window & Tray constants
pub const WM_NULL: UINT = 0x0000;
pub const WM_DESTROY: UINT = 0x0002;
pub const WM_CLOSE: UINT = 0x0010;
pub const WM_COMMAND: UINT = 0x0111;
pub const WM_USER: UINT = 0x0400;
pub const WM_CONTEXTMENU: UINT = 0x007B;
pub const NIN_SELECT: UINT = WM_USER;
pub const NIN_KEYSELECT: UINT = WM_USER + 1;
pub const NIN_BALLOONUSERCLICK: UINT = WM_USER + 5;

pub const NIM_ADD: DWORD = 0x0000_0000;
pub const NIM_MODIFY: DWORD = 0x0000_0001;
pub const NIM_DELETE: DWORD = 0x0000_0002;
pub const NIM_SETVERSION: DWORD = 0x0000_0004;
pub const NOTIFYICON_VERSION_4: UINT = 4;

pub const NIF_MESSAGE: UINT = 0x0000_0001;
pub const NIF_ICON: UINT = 0x0000_0002;
pub const NIF_TIP: UINT = 0x0000_0004;
pub const NIF_INFO: UINT = 0x0000_0010;
pub const NIF_SHOWTIP: UINT = 0x0000_0080;
pub const NIIF_INFO: DWORD = 0x0000_0001;
pub const NIIF_WARNING: DWORD = 0x0000_0002;

pub const MF_STRING: UINT = 0x0000_0000;
pub const MF_SEPARATOR: UINT = 0x0000_0800;
pub const MF_CHECKED: UINT = 0x0000_0008;
pub const MF_UNCHECKED: UINT = 0x0000_0000;
pub const MF_GRAYED: UINT = 0x0000_0001;
pub const TPM_RIGHTBUTTON: UINT = 0x0002;
pub const TPM_BOTTOMALIGN: UINT = 0x0020;

pub const MB_OK: UINT = 0x0000_0000;
pub const MB_YESNO: UINT = 0x0000_0004;
pub const MB_ICONINFORMATION: UINT = 0x0000_0040;
pub const MB_ICONWARNING: UINT = 0x0000_0030;
pub const MB_ICONERROR: UINT = 0x0000_0010;
pub const IDYES: i32 = 6;

pub const IMAGE_ICON: UINT = 1;
pub const LR_DEFAULTSIZE: UINT = 0x0040;
pub const LR_SHARED: UINT = 0x8000;
pub const SW_SHOWNORMAL: i32 = 1;
pub const BCRYPT_USE_SYSTEM_PREFERRED_RNG: DWORD = 0x0000_0002;

#[repr(C)]
#[derive(Clone, Copy)]
pub struct POINT {
    pub x: LONG,
    pub y: LONG,
}

#[repr(C)]
pub struct MSG {
    pub hwnd: HWND,
    pub message: UINT,
    pub wParam: WPARAM,
    pub lParam: LPARAM,
    pub time: DWORD,
    pub pt: POINT,
}

#[repr(C)]
pub struct OVERLAPPED {
    pub Internal: usize,
    pub InternalHigh: usize,
    pub Offset: DWORD,
    pub OffsetHigh: DWORD,
    pub hEvent: HANDLE,
}

#[repr(C)]
pub struct SECURITY_ATTRIBUTES {
    pub nLength: DWORD,
    pub lpSecurityDescriptor: *mut u8,
    pub bInheritHandle: BOOL,
}

#[repr(C)]
pub struct SID_AND_ATTRIBUTES {
    pub Sid: *mut u8,
    pub Attributes: DWORD,
}

pub type WNDPROC = unsafe extern "system" fn(HWND, UINT, WPARAM, LPARAM) -> LRESULT;

#[repr(C)]
pub struct WNDCLASSEXW {
    pub cbSize: UINT,
    pub style: UINT,
    pub lpfnWndProc: Option<WNDPROC>,
    pub cbClsExtra: i32,
    pub cbWndExtra: i32,
    pub hInstance: HINSTANCE,
    pub hIcon: HICON,
    pub hCursor: HCURSOR,
    pub hbrBackground: HBRUSH,
    pub lpszMenuName: *const u16,
    pub lpszClassName: *const u16,
    pub hIconSm: HICON,
}

#[repr(C)]
pub struct NOTIFYICONDATAW {
    pub cbSize: DWORD,
    pub hWnd: HWND,
    pub uID: UINT,
    pub uFlags: UINT,
    pub uCallbackMessage: UINT,
    pub hIcon: HICON,
    pub szTip: [u16; 128],
    pub dwState: DWORD,
    pub dwStateMask: DWORD,
    pub szInfo: [u16; 256],
    pub uTimeoutOrVersion: UINT,
    pub szInfoTitle: [u16; 64],
    pub dwInfoFlags: DWORD,
    pub guidItem: [u8; 16],
    pub hBalloonIcon: HICON,
}

#[repr(C)]
pub struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
    pub PerProcessUserTimeLimit: i64,
    pub PerJobUserTimeLimit: i64,
    pub LimitFlags: DWORD,
    pub MinimumWorkingSetSize: usize,
    pub MaximumWorkingSetSize: usize,
    pub ActiveProcessLimit: DWORD,
    pub Affinity: usize,
    pub PriorityClass: DWORD,
    pub SchedulingClass: DWORD,
}

#[repr(C)]
pub struct IO_COUNTERS {
    pub ReadOperationCount: u64,
    pub WriteOperationCount: u64,
    pub OtherOperationCount: u64,
    pub ReadTransferCount: u64,
    pub WriteTransferCount: u64,
    pub OtherTransferCount: u64,
}

#[repr(C)]
pub struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
    pub BasicLimitInformation: JOBOBJECT_BASIC_LIMIT_INFORMATION,
    pub IoInfo: IO_COUNTERS,
    pub ProcessMemoryLimit: usize,
    pub JobMemoryLimit: usize,
    pub PeakProcessMemoryUsed: usize,
    pub PeakJobMemoryUsed: usize,
}

#[cfg(target_arch = "x86_64")]
const _: () = {
    assert!(size_of::<POINT>() == 8);
    assert!(size_of::<MSG>() == 48);
    assert!(size_of::<OVERLAPPED>() == 32);
    assert!(size_of::<SECURITY_ATTRIBUTES>() == 24);
    assert!(size_of::<WNDCLASSEXW>() == 80);
    assert!(size_of::<JOBOBJECT_BASIC_LIMIT_INFORMATION>() == 64);
    assert!(size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() == 144);
    assert!(size_of::<NOTIFYICONDATAW>() == 976);
};

#[link(name = "kernel32")]
extern "system" {
    pub fn GetLastError() -> DWORD;
    pub fn CloseHandle(hObject: HANDLE) -> BOOL;
    pub fn LocalFree(hMem: *mut u8) -> *mut u8;
    pub fn GetCurrentProcess() -> HANDLE;
    pub fn GetModuleHandleW(lpModuleName: *const u16) -> HINSTANCE;
    pub fn GetStdHandle(nStdHandle: DWORD) -> HANDLE;
    pub fn AttachConsole(dwProcessId: DWORD) -> BOOL;
    pub fn CreateMutexW(lpMutexAttributes: *mut u8, bInitialOwner: BOOL, lpName: *const u16) -> HANDLE;
    pub fn CreateEventW(
        lpEventAttributes: *mut u8,
        bManualReset: BOOL,
        bInitialState: BOOL,
        lpName: *const u16,
    ) -> HANDLE;
    pub fn SetEvent(hEvent: HANDLE) -> BOOL;
    pub fn ResetEvent(hEvent: HANDLE) -> BOOL;
    pub fn WaitForMultipleObjects(
        nCount: DWORD,
        lpHandles: *const HANDLE,
        bWaitAll: BOOL,
        dwMilliseconds: DWORD,
    ) -> DWORD;
    pub fn CancelIoEx(hFile: HANDLE, lpOverlapped: *mut OVERLAPPED) -> BOOL;
    pub fn GetOverlappedResult(
        hFile: HANDLE,
        lpOverlapped: *mut OVERLAPPED,
        lpNumberOfBytesTransferred: *mut DWORD,
        bWait: BOOL,
    ) -> BOOL;
    pub fn CreateJobObjectW(lpJobAttributes: *mut u8, lpName: *const u16) -> HANDLE;
    pub fn SetInformationJobObject(
        hJob: HANDLE,
        JobObjectInformationClass: u32,
        lpJobObjectInformation: *const u8,
        cbJobObjectInformationLength: DWORD,
    ) -> BOOL;
    pub fn AssignProcessToJobObject(hJob: HANDLE, hProcess: HANDLE) -> BOOL;
    pub fn TerminateJobObject(hJob: HANDLE, uExitCode: UINT) -> BOOL;
    pub fn CreateNamedPipeW(
        lpName: *const u16,
        dwOpenMode: DWORD,
        dwPipeMode: DWORD,
        nMaxInstances: DWORD,
        nOutBufferSize: DWORD,
        nInBufferSize: DWORD,
        nDefaultTimeOut: DWORD,
        lpSecurityAttributes: *mut SECURITY_ATTRIBUTES,
    ) -> HANDLE;
    pub fn ConnectNamedPipe(hNamedPipe: HANDLE, lpOverlapped: *mut OVERLAPPED) -> BOOL;
    pub fn DisconnectNamedPipe(hNamedPipe: HANDLE) -> BOOL;
    pub fn WaitNamedPipeW(lpNamedPipeName: *const u16, nTimeOut: DWORD) -> BOOL;
    pub fn CreateFileW(
        lpFileName: *const u16,
        dwDesiredAccess: DWORD,
        dwShareMode: DWORD,
        lpSecurityAttributes: *mut u8,
        dwCreationDisposition: DWORD,
        dwFlagsAndAttributes: DWORD,
        hTemplateFile: HANDLE,
    ) -> HANDLE;
    pub fn ReadFile(
        hFile: HANDLE,
        lpBuffer: *mut u8,
        nNumberOfBytesToRead: DWORD,
        lpNumberOfBytesRead: *mut DWORD,
        lpOverlapped: *mut OVERLAPPED,
    ) -> BOOL;
    pub fn WriteFile(
        hFile: HANDLE,
        lpBuffer: *const u8,
        nNumberOfBytesToWrite: DWORD,
        lpNumberOfBytesWritten: *mut DWORD,
        lpOverlapped: *mut OVERLAPPED,
    ) -> BOOL;
}

#[link(name = "advapi32")]
extern "system" {
    pub fn OpenProcessToken(
        ProcessHandle: HANDLE,
        DesiredAccess: DWORD,
        TokenHandle: *mut HANDLE,
    ) -> BOOL;
    pub fn GetTokenInformation(
        TokenHandle: HANDLE,
        TokenInformationClass: u32,
        TokenInformation: *mut u8,
        TokenInformationLength: DWORD,
        ReturnLength: *mut DWORD,
    ) -> BOOL;
    pub fn ConvertSidToStringSidW(Sid: *mut u8, StringSid: *mut *mut u16) -> BOOL;
    pub fn ConvertStringSecurityDescriptorToSecurityDescriptorW(
        StringSecurityDescriptor: *const u16,
        StringSDRevision: DWORD,
        SecurityDescriptor: *mut *mut u8,
        SecurityDescriptorSize: *mut DWORD,
    ) -> BOOL;
}

#[link(name = "user32")]
extern "system" {
    pub fn RegisterClassExW(lpwcx: *const WNDCLASSEXW) -> ATOM;
    pub fn CreateWindowExW(
        dwExStyle: DWORD,
        lpClassName: *const u16,
        lpWindowName: *const u16,
        dwStyle: DWORD,
        X: i32,
        Y: i32,
        nWidth: i32,
        nHeight: i32,
        hWndParent: HWND,
        hMenu: HMENU,
        hInstance: HINSTANCE,
        lpParam: *mut u8,
    ) -> HWND;
    pub fn DestroyWindow(hWnd: HWND) -> BOOL;
    pub fn DefWindowProcW(hWnd: HWND, Msg: UINT, wParam: WPARAM, lParam: LPARAM) -> LRESULT;
    pub fn GetMessageW(lpMsg: *mut MSG, hWnd: HWND, wMsgFilterMin: UINT, wMsgFilterMax: UINT) -> BOOL;
    pub fn TranslateMessage(lpMsg: *const MSG) -> BOOL;
    pub fn DispatchMessageW(lpMsg: *const MSG) -> LRESULT;
    pub fn PostMessageW(hWnd: HWND, Msg: UINT, wParam: WPARAM, lParam: LPARAM) -> BOOL;
    pub fn PostQuitMessage(nExitCode: i32);
    pub fn RegisterWindowMessageW(lpString: *const u16) -> UINT;
    pub fn CreatePopupMenu() -> HMENU;
    pub fn AppendMenuW(hMenu: HMENU, uFlags: UINT, uIDNewItem: usize, lpNewItem: *const u16) -> BOOL;
    pub fn TrackPopupMenu(
        hMenu: HMENU,
        uFlags: UINT,
        x: i32,
        y: i32,
        nReserved: i32,
        hWnd: HWND,
        prcRect: *const u8,
    ) -> BOOL;
    pub fn DestroyMenu(hMenu: HMENU) -> BOOL;
    pub fn SetForegroundWindow(hWnd: HWND) -> BOOL;
    pub fn GetCursorPos(lpPoint: *mut POINT) -> BOOL;
    pub fn LoadImageW(
        hInst: HINSTANCE,
        name: *const u16,
        r#type: UINT,
        cx: i32,
        cy: i32,
        fuLoad: UINT,
    ) -> HANDLE;
    pub fn MessageBoxW(hWnd: HWND, lpText: *const u16, lpCaption: *const u16, uType: UINT) -> i32;
}

#[link(name = "shell32")]
extern "system" {
    pub fn Shell_NotifyIconW(dwMessage: DWORD, lpData: *const NOTIFYICONDATAW) -> BOOL;
    pub fn SetCurrentProcessExplicitAppUserModelID(AppID: *const u16) -> i32;
    pub fn ShellExecuteW(
        hwnd: HWND,
        lpOperation: *const u16,
        lpFile: *const u16,
        lpParameters: *const u16,
        lpDirectory: *const u16,
        nShowCmd: i32,
    ) -> HINSTANCE;
}

#[link(name = "bcrypt")]
extern "system" {
    pub fn BCryptGenRandom(
        hAlgorithm: HANDLE,
        pbBuffer: *mut u8,
        cbBuffer: DWORD,
        dwFlags: DWORD,
    ) -> i32;
}

pub fn to_wide(s: &str) -> Vec<u16> {
    OsStr::new(s).encode_wide().chain(std::iter::once(0)).collect()
}

pub fn write_wide_buf<const N: usize>(buf: &mut [u16; N], s: &str) {
    buf.fill(0);
    for (dst, src) in buf.iter_mut().take(N.saturating_sub(1)).zip(OsStr::new(s).encode_wide()) {
        *dst = src;
    }
}

pub fn set_app_user_model_id(app_id: &str) {
    let wide = to_wide(app_id);
    unsafe {
        let _ = SetCurrentProcessExplicitAppUserModelID(wide.as_ptr());
    }
}

/// Attach to parent console ONLY when stdout is unattached (interactive shell run),
/// leaving piped subprocess captures (`capture_output=True` / `| Out-String`) untouched.
pub fn attach_parent_console_if_needed() {
    unsafe {
        let h = GetStdHandle(STD_OUTPUT_HANDLE);
        if h == 0 || h == INVALID_HANDLE_VALUE {
            let _ = AttachConsole(ATTACH_PARENT_PROCESS);
        }
    }
}

/// Return current user SID string (`S-1-5-21-...`) to namespace Named Pipes per Windows user.
pub fn current_user_sid_string() -> String {
    unsafe {
        let mut token: HANDLE = 0;
        if OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &mut token) == 0 || token == 0 {
            return String::new();
        }
        let _tok_guard = OwnedHandle(token);
        let mut needed: DWORD = 0;
        let _ = GetTokenInformation(token, TOKEN_USER_CLASS, null_mut(), 0, &mut needed);
        if needed == 0 || needed > 4096 {
            return String::new();
        }
        let mut buf = vec![0u8; needed as usize];
        if GetTokenInformation(token, TOKEN_USER_CLASS, buf.as_mut_ptr(), needed, &mut needed) == 0 {
            return String::new();
        }
        let tu = &*(buf.as_ptr() as *const SID_AND_ATTRIBUTES);
        if tu.Sid.is_null() {
            return String::new();
        }
        let mut str_ptr: *mut u16 = null_mut();
        if ConvertSidToStringSidW(tu.Sid, &mut str_ptr) == 0 || str_ptr.is_null() {
            return String::new();
        }
        let mut len = 0usize;
        while *str_ptr.add(len) != 0 {
            len += 1;
        }
        let sid_str = String::from_utf16_lossy(std::slice::from_raw_parts(str_ptr, len));
        LocalFree(str_ptr as *mut u8);
        sid_str
    }
}

/// RAII security descriptor restricting a Named Pipe strictly to the current user (plus SYSTEM/Admins).
pub struct OwnerPipeSecurity {
    sd_ptr: *mut u8,
    pub attrs: SECURITY_ATTRIBUTES,
}

impl OwnerPipeSecurity {
    pub fn new() -> Option<Self> {
        let sid = current_user_sid_string();
        let sddl = if sid.starts_with("S-1-") {
            format!("D:P(A;;GA;;;{sid})(A;;GA;;;SY)(A;;GA;;;BA)")
        } else {
            "D:P(A;;GA;;;OW)(A;;GA;;;SY)(A;;GA;;;BA)".to_string()
        };
        let wide = to_wide(&sddl);
        let mut sd: *mut u8 = null_mut();
        let ok = unsafe {
            ConvertStringSecurityDescriptorToSecurityDescriptorW(
                wide.as_ptr(),
                SDDL_REVISION_1,
                &mut sd,
                null_mut(),
            )
        };
        if ok == 0 || sd.is_null() {
            return None;
        }
        Some(Self {
            sd_ptr: sd,
            attrs: SECURITY_ATTRIBUTES {
                nLength: size_of::<SECURITY_ATTRIBUTES>() as DWORD,
                lpSecurityDescriptor: sd,
                bInheritHandle: 0,
            },
        })
    }
}

impl Drop for OwnerPipeSecurity {
    fn drop(&mut self) {
        if !self.sd_ptr.is_null() {
            unsafe {
                LocalFree(self.sd_ptr);
            }
        }
    }
}

pub fn csprng_hex(num_bytes: usize) -> Result<String, String> {
    let mut buf = vec![0u8; num_bytes];
    let status = unsafe {
        BCryptGenRandom(0, buf.as_mut_ptr(), buf.len() as DWORD, BCRYPT_USE_SYSTEM_PREFERRED_RNG)
    };
    if status != 0 {
        return Err(format!("BCryptGenRandom failed with NTSTATUS 0x{:08x}", status as u32));
    }
    let mut out = String::with_capacity(num_bytes * 2);
    for b in buf {
        out.push_str(&format!("{b:02x}"));
    }
    Ok(out)
}

pub fn message_box(title: &str, text: &str, flags: UINT) -> i32 {
    let w_title = to_wide(title);
    let w_text = to_wide(text);
    unsafe { MessageBoxW(0, w_text.as_ptr(), w_title.as_ptr(), flags) }
}

pub fn open_shell_target(target: &str) {
    let verb = to_wide("open");
    let file = to_wide(target);
    unsafe {
        let _ = ShellExecuteW(0, verb.as_ptr(), file.as_ptr(), null(), null(), SW_SHOWNORMAL);
    }
}

#[allow(clippy::manual_dangling_ptr)]
pub fn load_embedded_icon(cx: i32, cy: i32) -> HICON {
    unsafe {
        let hinst = GetModuleHandleW(null());
        LoadImageW(hinst, 1usize as *const u16, IMAGE_ICON, cx, cy, LR_SHARED | LR_DEFAULTSIZE)
    }
}

pub struct JobObject {
    handle: HANDLE,
}

impl JobObject {
    pub fn create_kill_on_close() -> Result<Self, String> {
        unsafe {
            let h = CreateJobObjectW(null_mut(), null());
            if h == 0 {
                return Err(format!("CreateJobObjectW failed ({})", GetLastError()));
            }
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = zeroed();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            let ok = SetInformationJobObject(
                h,
                JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
                (&info as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast::<u8>(),
                size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as DWORD,
            );
            if ok == 0 {
                let err = GetLastError();
                CloseHandle(h);
                return Err(format!("SetInformationJobObject failed ({err})"));
            }
            Ok(Self { handle: h })
        }
    }

    pub fn assign(&self, proc_handle: HANDLE) -> bool {
        unsafe { AssignProcessToJobObject(self.handle, proc_handle) != 0 }
    }

    pub fn terminate(&self, exit_code: UINT) {
        unsafe {
            let _ = TerminateJobObject(self.handle, exit_code);
        }
    }
}

impl Drop for JobObject {
    fn drop(&mut self) {
        if self.handle != 0 && self.handle != INVALID_HANDLE_VALUE {
            unsafe {
                CloseHandle(self.handle);
            }
        }
    }
}

pub struct OwnedHandle(pub HANDLE);

impl OwnedHandle {
    pub fn raw(&self) -> HANDLE {
        self.0
    }
}

impl Drop for OwnedHandle {
    fn drop(&mut self) {
        if self.0 != 0 && self.0 != INVALID_HANDLE_VALUE {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn csprng_hex_length_and_entropy() {
        let a = csprng_hex(32).expect("csprng a");
        let b = csprng_hex(32).expect("csprng b");
        assert_eq!(a.len(), 64);
        assert_eq!(b.len(), 64);
        assert_ne!(a, b);
        assert!(a.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn user_sid_and_owner_pipe_sddl_valid() {
        let sid = current_user_sid_string();
        assert!(sid.starts_with("S-1-"));
        let sec = OwnerPipeSecurity::new();
        assert!(sec.is_some());
    }

    #[test]
    fn wide_buffer_truncates_with_nul() {
        let mut buf = [0u16; 6];
        write_wide_buf(&mut buf, "LuminaraBrowser");
        assert_eq!(buf[5], 0);
        assert_eq!(String::from_utf16_lossy(&buf[..5]), "Lumin");
    }
}
