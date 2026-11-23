use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

fn escape_rc_path(path: &Path) -> String {
    let raw = path.to_string_lossy();
    let cleaned = if let Some(rest) = raw.strip_prefix(r"\\?\UNC\") {
        format!(r"\\{rest}")
    } else if let Some(rest) = raw.strip_prefix(r"\\?\") {
        rest.to_string()
    } else {
        raw.into_owned()
    };
    cleaned.replace('\\', "\\\\")
}

fn find_windows_rc() -> Option<PathBuf> {
    if let Ok(path_var) = env::var("PATH") {
        for dir in env::split_paths(&path_var) {
            let cand = dir.join("rc.exe");
            if cand.is_file() {
                return Some(cand);
            }
        }
    }
    let kits_root = PathBuf::from(r"C:\Program Files (x86)\Windows Kits\10\bin");
    if let Ok(entries) = fs::read_dir(&kits_root) {
        let mut versions: Vec<PathBuf> = entries
            .filter_map(|e| e.ok())
            .map(|e| e.path().join("x64").join("rc.exe"))
            .filter(|p| p.is_file())
            .collect();
        versions.sort();
        if let Some(latest) = versions.pop() {
            return Some(latest);
        }
    }
    None
}

fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed=luminara.manifest");
    println!("cargo:rerun-if-changed=../chromium-forge/forge/ui/luminara.ico");

    if env::var("CARGO_CFG_TARGET_OS").unwrap_or_default() != "windows" {
        return;
    }

    let pkg_ver = env::var("CARGO_PKG_VERSION").unwrap_or_else(|_| "4.0.0".into());
    let mut nums: Vec<u16> = pkg_ver
        .split('.')
        .take(4)
        .map(|p| p.parse::<u16>().unwrap_or(0))
        .collect();
    while nums.len() < 4 {
        nums.push(0);
    }
    let comma_ver = format!("{},{},{},{}", nums[0], nums[1], nums[2], nums[3]);
    let dot_ver4 = format!("{}.{}.{}.{}", nums[0], nums[1], nums[2], nums[3]);

    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));
    let out_dir = PathBuf::from(env::var("OUT_DIR").expect("OUT_DIR"));
    let ico_path = manifest_dir
        .join("..")
        .join("chromium-forge")
        .join("forge")
        .join("ui")
        .join("luminara.ico");
    let manifest_path = manifest_dir.join("luminara.manifest");

    assert!(
        ico_path.is_file(),
        "Luminara icon not found at {}",
        ico_path.display()
    );
    assert!(
        manifest_path.is_file(),
        "Luminara Win32 manifest not found at {}",
        manifest_path.display()
    );

    let rc_content = format!(
        r#"#pragma code_page(65001)
1 ICON "{ico}"
1 24 "{manifest}"

1 VERSIONINFO
FILEVERSION {comma_ver}
PRODUCTVERSION {comma_ver}
FILEFLAGSMASK 0x3fL
FILEFLAGS 0x0L
FILEOS 0x40004L
FILETYPE 0x1L
FILESUBTYPE 0x0L
BEGIN
  BLOCK "StringFileInfo"
  BEGIN
    BLOCK "040904B0"
    BEGIN
      VALUE "CompanyName", "Luminara Engineering"
      VALUE "FileDescription", "Luminara Browser"
      VALUE "FileVersion", "{dot_ver4}"
      VALUE "InternalName", "LuminaraBrowser"
      VALUE "LegalCopyright", "MIT License - Luminara Engineering"
      VALUE "OriginalFilename", "LuminaraBrowser.exe"
      VALUE "ProductName", "Luminara Browser"
      VALUE "ProductVersion", "{pkg_ver}"
    END
  END
  BLOCK "VarFileInfo"
  BEGIN
    VALUE "Translation", 0x0409, 1200
  END
END
"#,
        ico = escape_rc_path(&ico_path.canonicalize().unwrap_or(ico_path)),
        manifest = escape_rc_path(&manifest_path.canonicalize().unwrap_or(manifest_path)),
    );

    let rc_file = out_dir.join("luminara.rc");
    let res_file = out_dir.join("luminara.res");
    fs::write(&rc_file, rc_content).expect("write luminara.rc");

    let rc_exe = find_windows_rc()
        .expect("Windows SDK rc.exe not found on PATH or in C:\\Program Files (x86)\\Windows Kits\\10\\bin");
    let status = Command::new(&rc_exe)
        .args(["/nologo", "/c65001", "/fo"])
        .arg(&res_file)
        .arg(&rc_file)
        .status()
        .expect("invoke rc.exe");
    assert!(status.success(), "rc.exe failed with status {status}");

    println!(
        "cargo:rustc-link-arg-bin=LuminaraBrowser={}",
        res_file.display()
    );
}
