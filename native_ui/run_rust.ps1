$env:PATH = "C:\Users\Zain\.rustup\toolchains\stable-x86_64-pc-windows-gnu\lib\rustlib\x86_64-pc-windows-gnu\bin\self-contained;" + $env:PATH
rustup default stable-x86_64-pc-windows-gnu
cargo $args --offline
