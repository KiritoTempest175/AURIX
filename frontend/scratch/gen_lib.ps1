$output = & "C:\Users\Zain\.rustup\toolchains\stable-x86_64-pc-windows-gnu\lib\rustlib\x86_64-pc-windows-gnu\bin\llvm-readobj.exe" --coff-exports C:\Windows\System32\shlwapi.dll
$exports = [regex]::Matches($output, "Name:\s+([A-Za-z0-9_]+)") | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique

$defContent = "LIBRARY SHLWAPI.dll`nEXPORTS`n" + ($exports -join "`n")
Set-Content -Path "scratch\shlwapi.def" -Value $defContent

& "C:\Users\Zain\.rustup\toolchains\stable-x86_64-pc-windows-gnu\lib\rustlib\x86_64-pc-windows-gnu\bin\self-contained\dlltool.exe" -d "scratch\shlwapi.def" -l "C:\Users\Zain\.rustup\toolchains\stable-x86_64-pc-windows-gnu\lib\rustlib\x86_64-pc-windows-gnu\lib\self-contained\libshlwapi.a" -m i386:x86-64
