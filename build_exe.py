"""
Blackjack Pilot - Standalone Executable Builder
Packages server.py and all dependencies (PyTorch, YOLO11, WebSockets, OpenCV)
into a self-contained Windows executable and portable distribution folder.
"""

import os
import sys
import shutil
import subprocess
import zipfile

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DIST_DIR = os.path.join(PROJECT_DIR, "dist")
BUILD_DIR = os.path.join(PROJECT_DIR, "build")
APP_NAME = "BlackjackPilotServer"
OUTPUT_FOLDER = os.path.join(DIST_DIR, APP_NAME)
ZIP_OUTPUT = os.path.join(DIST_DIR, f"{APP_NAME}-Windows-x64.zip")


def clean_previous_builds():
    print("[1/5] Cleaning previous build artifacts...")
    for d in [BUILD_DIR, OUTPUT_FOLDER]:
        if os.path.exists(d):
            try:
                shutil.rmtree(d)
            except Exception as e:
                print(f"      Warning cleaning {d}: {e}")
    if os.path.exists(ZIP_OUTPUT):
        try:
            os.remove(ZIP_OUTPUT)
        except Exception:
            pass


def run_pyinstaller():
    print("[2/5] Running PyInstaller to build standalone executable...")
    py_cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--console",
        "--name",
        APP_NAME,
        "--collect-all",
        "ultralytics",
        "--collect-all",
        "torchvision",
        "--copy-metadata",
        "ultralytics",
        "--hidden-import",
        "websockets",
        "--hidden-import",
        "cv2",
        "--hidden-import",
        "PIL",
        "--hidden-import",
        "numpy",
        "--hidden-import",
        "torch",
        "--hidden-import",
        "torchvision",
        os.path.join(PROJECT_DIR, "server.py"),
    ]

    print("      Executing:", " ".join(py_cmd[:10]), "...")
    res = subprocess.run(py_cmd, cwd=PROJECT_DIR)
    if res.returncode != 0:
        raise RuntimeError(f"PyInstaller failed with exit code {res.returncode}")
    print("[OK] PyInstaller build succeeded!")


def copy_assets():
    print("[3/5] Bundling required assets and models...")
    # Copy models/
    models_src = os.path.join(PROJECT_DIR, "models")
    models_dst = os.path.join(OUTPUT_FOLDER, "models")
    if os.path.exists(models_src):
        shutil.copytree(models_src, models_dst, dirs_exist_ok=True)
        print("      Copied models/ folder.")

    # Copy native_host/
    nh_src = os.path.join(PROJECT_DIR, "native_host")
    nh_dst = os.path.join(OUTPUT_FOLDER, "native_host")
    if os.path.exists(nh_src):
        shutil.copytree(nh_src, nh_dst, dirs_exist_ok=True)
        print("      Copied native_host/ folder.")

    # Copy extension/ folder so users get both the server and extension in one download!
    ext_src = os.path.join(PROJECT_DIR, "extension")
    ext_dst = os.path.join(OUTPUT_FOLDER, "extension")
    if os.path.exists(ext_src):
        shutil.copytree(ext_src, ext_dst, dirs_exist_ok=True)
        print("      Copied extension/ folder.")

    # Create 1-click launcher inside the folder
    launcher_bat = os.path.join(OUTPUT_FOLDER, "Start-Blackjack-Server.bat")
    with open(launcher_bat, "w", encoding="utf-8") as f:
        f.write("@echo off\n")
        f.write("cd /d \"%~dp0\"\n")
        f.write(f"start \"Blackjack Pilot AI Server\" \"{APP_NAME}.exe\"\n")

    # Create README instructions
    readme_path = os.path.join(OUTPUT_FOLDER, "README-INSTALLATION.txt")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("============================================================\n")
        f.write("   🃏 Blackjack Pilot - Standalone Release (No Python Needed)\n")
        f.write("   GitHub: https://github.com/MaximilianHq/blackjack-pilot\n")
        f.write("============================================================\n\n")
        f.write("HUR DU ANVANDER PROGRAMMET (SWEDISH):\n")
        f.write("1. Starta servern:\n")
        f.write("   Dubbelklicka pa 'Start-Blackjack-Server.bat' (eller BlackjackPilotServer.exe).\n")
        f.write("   Ett konsolfonster oppnas som laddar AI-modellen och startar servern.\n")
        f.write("   Lat detta fonster vara oppet medan du spelar!\n\n")
        f.write("2. Installera Chrome/Edge-tillagget:\n")
        f.write("   - Ga till chrome://extensions/ (eller edge://extensions/)\n")
        f.write("   - Aktivera 'Utvecklarlage' (Developer mode)\n")
        f.write("   - Klicka 'Las in okomprimerat' (Load unpacked)\n")
        f.write("   - Valj mappen 'extension' som ligger har i mappen!\n\n")
        f.write("3. Klart!\n")
        f.write("   Ga till ditt live-casino, klicka pa Blackjack Pilot-ikonen och spela!\n")
    print("[OK] Assets bundled successfully.")


def create_release_zip():
    print("[4/5] Creating release ZIP archive...")
    with zipfile.ZipFile(ZIP_OUTPUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(OUTPUT_FOLDER):
            for file in files:
                abs_path = os.path.join(root, file)
                rel_path = os.path.relpath(abs_path, DIST_DIR)
                zf.write(abs_path, rel_path)
    zip_size_mb = os.path.getsize(ZIP_OUTPUT) / (1024 * 1024)
    print(f"[OK] Created release ZIP: {ZIP_OUTPUT} ({zip_size_mb:.1f} MB)")


def main():
    print("============================================================")
    print("    Building Blackjack Pilot Standalone Windows Package     ")
    print("============================================================")
    clean_previous_builds()
    run_pyinstaller()
    copy_assets()
    create_release_zip()
    print("\n[5/5] BUILD COMPLETE!")
    print(f"      Portable Folder: {OUTPUT_FOLDER}")
    print(f"      Executable:      {os.path.join(OUTPUT_FOLDER, APP_NAME + '.exe')}")
    print(f"      Release ZIP:     {ZIP_OUTPUT}")


if __name__ == "__main__":
    main()

