import os
import sys
import json
import winreg

HOST_NAME = "com.blackjackpilot.host"
DIR_PATH = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(DIR_PATH)
MANIFEST_PATH = os.path.join(DIR_PATH, f"{HOST_NAME}.json")
LAUNCHER_PATH = os.path.join(DIR_PATH, "launcher.bat")


def update_manifest(extra_extension_id=None):
    """Ensure manifest JSON has correct absolute path and allowed origins."""
    data = {
        "name": HOST_NAME,
        "description": "Blackjack Pilot Native Messaging Server Launcher",
        "path": LAUNCHER_PATH,
        "type": "stdio",
        "allowed_origins": [
            "chrome-extension://podfclammipadjiimlcodaobphalfhak/",
        ],
    }

    if extra_extension_id:
        extra_id = extra_extension_id.strip().strip("/")
        if not extra_id.startswith("chrome-extension://"):
            extra_id = f"chrome-extension://{extra_id}/"
        if extra_id not in data["allowed_origins"]:
            data["allowed_origins"].append(extra_id)

    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    print(f"[1/3] Updated host manifest at: {MANIFEST_PATH}")
    print(f"      Launcher path set to: {LAUNCHER_PATH}")
    print(f"      Allowed origins: {data['allowed_origins']}")


def register_registry_keys():
    """Register the native messaging host in Windows HKCU registry for all Chromium browsers."""
    registry_targets = [
        (r"Software\Google\Chrome\NativeMessagingHosts", "Google Chrome"),
        (r"Software\Microsoft\Edge\NativeMessagingHosts", "Microsoft Edge"),
        (r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts", "Brave Browser"),
        (r"Software\Chromium\NativeMessagingHosts", "Chromium"),
    ]

    registered_count = 0
    for subkey, browser_name in registry_targets:
        full_key_path = f"{subkey}\\{HOST_NAME}"
        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, full_key_path)
            winreg.SetValueEx(key, "", 0, winreg.REG_SZ, MANIFEST_PATH)
            winreg.CloseKey(key)
            print(f"[2/3] Registered for {browser_name} -> HKCU\\{full_key_path}")
            registered_count += 1
        except Exception as exc:
            print(f"      Warning: Could not register for {browser_name}: {exc}")

    return registered_count


def create_startup_shortcut(enable=False):
    """Optionally create a silent Windows startup VBS script in shell:startup."""
    startup_dir = os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup")
    vbs_path = os.path.join(startup_dir, "BlackjackPilot_AutoStart.vbs")

    if enable:
        vbs_code = (
            'Set WshShell = CreateObject("WScript.Shell")\n'
            f'WshShell.CurrentDirectory = "{PROJECT_DIR}"\n'
            'WshShell.Run "python -u server.py", 0, False\n'
        )
        try:
            with open(vbs_path, "w", encoding="utf-8") as f:
                f.write(vbs_code)
            print(f"[3/3] Created Windows Auto-Start script in: {vbs_path}")
            print("      (server.py will now automatically start silently when Windows boots!)")
        except Exception as e:
            print(f"      Could not create startup shortcut: {e}")
    else:
        print("[3/3] Skipping Windows startup shortcut (Native Messaging will launch on-demand).")


def main():
    extra_id = None
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        extra_id = sys.argv[1]

    enable_startup = "--startup" in sys.argv

    print("=======================================================")
    print("  Blackjack Pilot - Native Host Registration")
    print("=======================================================")

    update_manifest(extra_extension_id=extra_id)
    reg_count = register_registry_keys()
    create_startup_shortcut(enable=enable_startup)

    print("=======================================================")
    print(f"  SUCCESS: Native messaging host registered ({reg_count} browsers)!")
    print("  The Chrome/Edge extension can now launch python server.py directly.")
    print("=======================================================")


if __name__ == "__main__":
    main()

