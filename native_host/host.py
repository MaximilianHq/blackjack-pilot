import sys
import os
import json
import struct
import socket
import subprocess
import time

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_SCRIPT = os.path.join(PROJECT_DIR, "server.py")
HOST = "127.0.0.1"
PORT = 8765


def is_server_running():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.6)
        s.connect((HOST, PORT))
        s.close()
        return True
    except Exception:
        return False


def start_server():
    if is_server_running():
        return {
            "status": "already_running",
            "message": "Blackjack Pilot server is already running on port 8765",
            "port": PORT,
        }

    start_bat = os.path.join(PROJECT_DIR, "start_server.bat")
    if os.path.exists(start_bat):
        cmd = f'cmd.exe /c start "Blackjack Pilot AI Server" "{start_bat}"'
    else:
        python_exe = sys.executable
        cmd = f'cmd.exe /c start "Blackjack Pilot AI Server" "{python_exe}" -u "{SERVER_SCRIPT}"'

    proc = subprocess.Popen(
        cmd,
        cwd=PROJECT_DIR,
        shell=True,
    )

    # Poll port for up to 3.5 seconds
    for _ in range(35):
        time.sleep(0.1)
        if is_server_running():
            return {
                "status": "started",
                "pid": proc.pid,
                "message": "Blackjack Pilot server started successfully",
                "port": PORT,
            }

    return {
        "status": "starting",
        "pid": proc.pid,
        "message": "Server process launched, waiting for port to bind",
        "port": PORT,
    }


def read_message():
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) < 4:
        return None
    msg_len = struct.unpack("<I", raw_length)[0]
    raw_data = sys.stdin.buffer.read(msg_len).decode("utf-8")
    return json.loads(raw_data)


def send_message(obj):
    encoded = json.dumps(obj).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(encoded)))
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()


def main():
    while True:
        try:
            msg = read_message()
            if msg is None:
                break
            action = msg.get("action")
            if action == "start_server":
                res = start_server()
                send_message(res)
            elif action == "get_status":
                running = is_server_running()
                send_message({
                    "status": "running" if running else "stopped",
                    "running": running,
                    "port": PORT,
                })
            else:
                send_message({"status": "unknown_action", "action": action})
        except Exception as e:
            send_message({"status": "error", "error": str(e)})
            break


if __name__ == "__main__":
    main()

