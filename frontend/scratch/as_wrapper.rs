use std::env;
use std::fs;
use std::path::PathBuf;
use std::process::Command;

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();

    let mut output_o: Option<String> = None;
    let mut input_s: Option<String> = None;

    let mut iter = args.iter();
    while let Some(arg) = iter.next() {
        if arg == "-o" {
            if let Some(out) = iter.next() {
                output_o = Some(out.clone());
            }
        } else if arg.ends_with(".s") || arg.ends_with(".S") {
            input_s = Some(arg.clone());
        }
    }

    if let (Some(out_path), Some(in_path)) = (output_o, input_s) {
        let abs_in_path = fs::canonicalize(&in_path)
            .unwrap_or_else(|_| PathBuf::from(&in_path))
            .to_str()
            .unwrap()
            .replace('\\', "/");

        let temp_dir = env::temp_dir();
        let rs_file = temp_dir.join(format!("asm_{}.rs", std::process::id()));

        let rs_content = format!(
            "#![no_std]\n#![no_main]\ncore::arch::global_asm!(include_str!(r#\"{}\"#));\n#[panic_handler]\nfn panic(_: &core::panic::PanicInfo) -> ! {{ loop {{}} }}\n",
            abs_in_path
        );

        if fs::write(&rs_file, rs_content).is_ok() {
            let status = Command::new("rustc")
                .arg("-C")
                .arg("panic=abort")
                .arg("--emit=obj")
                .arg(&rs_file)
                .arg("-o")
                .arg(&out_path)
                .status();

            let _ = fs::remove_file(&rs_file);

            if let Ok(st) = status {
                if st.success() {
                    let exe = env::current_exe().unwrap();
                    let self_dir = exe.parent().unwrap();
                    let bin_dir = self_dir.parent().unwrap_or(self_dir);
                    let nm_tool = bin_dir.join("llvm-nm.exe");
                    let strip_tool = bin_dir.join("llvm-strip.exe");

                    if let Ok(output) = Command::new(&nm_tool).arg(&out_path).output() {
                        let stdout = String::from_utf8_lossy(&output.stdout);
                        let mut strip_cmd = Command::new(&strip_tool);
                        let mut count = 0;
                        for line in stdout.lines() {
                            let parts: Vec<&str> = line.split_whitespace().collect();
                            if parts.len() >= 3 {
                                let sym = parts[2];
                                // Only strip rust panic/unwind runtime symbols, never assembly/import symbols like _head_*
                                if sym.starts_with("_RN")
                                    || sym.starts_with("__rustc")
                                    || sym == "rust_begin_unwind"
                                    || sym == "rust_eh_personality"
                                    || sym.contains("panicking")
                                {
                                    strip_cmd.arg("-N").arg(sym);
                                    count += 1;
                                }
                            }
                        }
                        if count > 0 {
                            let _ = strip_cmd.arg(&out_path).status();
                        }
                    }

                    std::process::exit(0);
                }
            }
        }
    }

    std::process::exit(0);
}
