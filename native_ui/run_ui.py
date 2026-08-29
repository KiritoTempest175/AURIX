import os
import sys
import slint

def main():
    slint_file = os.path.join(os.path.dirname(__file__), "ui", "main.slint")
    print(f"Loading Slint UI from {slint_file}...")
    ui = slint.load_file(slint_file)
    app = ui.AurixCommandCenter()

    print("Launching A.U.R.I.X Command Center GUI with native 60 FPS Slint animations...")
    app.run()

if __name__ == "__main__":
    main()
