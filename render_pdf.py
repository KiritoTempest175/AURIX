import os
import subprocess
import shutil

OUTPUT_PDF = os.path.abspath("AURIX_Comprehensive_System_Guide.pdf")
HTML_FILE = os.path.abspath("aurix_guide.html")

def build_pdf():
    if not os.path.exists(HTML_FILE):
        print(f"Error: {HTML_FILE} does not exist.")
        return False
        
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        shutil.which("chrome"),
        shutil.which("google-chrome"),
        shutil.which("msedge"),
    ]
    
    browser_bin = None
    for p in chrome_paths:
        if p and os.path.exists(p):
            browser_bin = p
            break
            
    if not browser_bin:
        raise RuntimeError("No headless Chrome/Edge browser found to generate PDF.")
        
    print(f"Rendering PDF using {browser_bin}...")
    cmd = [
        browser_bin,
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={OUTPUT_PDF}",
        HTML_FILE
    ]
    
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Error rendering PDF: {res.stderr}")
        return False
        
    if os.path.exists(OUTPUT_PDF):
        size_kb = os.path.getsize(OUTPUT_PDF) / 1024
        print(f"SUCCESS: Generated PDF at {OUTPUT_PDF} ({size_kb:.1f} KB)")
        return True
    else:
        print("PDF output file was not created.")
        return False

if __name__ == "__main__":
    build_pdf()
