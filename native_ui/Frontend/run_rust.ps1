$sc = "C:\Users\Zain\.rustup\toolchains\stable-x86_64-pc-windows-gnu\lib\rustlib\x86_64-pc-windows-gnu\bin\self-contained"
$env:PATH = "$sc;$env:PATH"
& "C:\Users\Zain\.cargo\bin\rustup.exe" default stable-x86_64-pc-windows-gnu
if ($args.Count -gt 0) {
    & "C:\Users\Zain\.cargo\bin\cargo.exe" $args
} else {
    & "C:\Users\Zain\.cargo\bin\cargo.exe" run
}
