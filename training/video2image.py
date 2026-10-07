import glob
import os
import re
import tkinter as tk
from tkinter import filedialog

import cv2

# ==============================================================================
# ⚙️ INSTÄLLNINGAR & VARIABLER
# ==============================================================================
SECONDS_BETWEEN_FRAMES = 30  # Hur många sekunder mellan varje sparad bildruta
IMAGE_FORMAT = "png"  # Bildformat: 'png' eller 'jpg'
AUTO_CONTINUE_INDEX = (
    True  # True = fortsätt numrering (överskrivningsskydd), False = börja på 1
)
USE_FILE_PICKER = True  # True = öppna filväljare (Ctrl-klick för flera), False = använd SPECIFIC_VIDEOS nedan

SPECIFIC_VIDEOS = []
# ==============================================================================


def get_next_frame_index(folder, ext):
    """Hittar nästa lediga siffernummer så inga befintliga bilder skrivs över."""
    existing_files = glob.glob(os.path.join(folder, f"frame_*.{ext}"))
    if not existing_files:
        return 1

    highest_idx = 0
    for f in existing_files:
        match = re.search(r"frame_(\d+)", os.path.basename(f))
        if match:
            idx = int(match.group(1))
            highest_idx = max(highest_idx, idx)

    return highest_idx + 1


def pick_videos_gui():
    """Öppnar en Windows-fildialog för att välja en eller flera videor."""
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    print("Öppnar fildialog... Välj dina videor (håll in Ctrl för att markera flera):")
    files = filedialog.askopenfilenames(
        title="Välj videor att extrahera ifrån (håll in Ctrl för flera)",
        filetypes=[
            ("Videofiler", "*.mp4 *.mkv *.avi *.mov *.wmv *.webm *.ts"),
            ("Alla filer", "*.*"),
        ],
    )
    root.destroy()
    return list(files)


def extract_from_video(video_path, output_dir, start_idx, interval_sec, ext):
    """Extraherar bilder från en enskild video med specificerat intervall."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[FEL] Kunde inte öppna videon: {video_path}")
        return start_idx, 0

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration_sec = total_frames / fps

    print("\n" + "=" * 55)
    print(f"Video: {os.path.basename(video_path)}")
    print(
        f"Info:  {w}x{h} px | {duration_sec/60:.1f} min ({duration_sec:.0f}s) | {fps:.1f} FPS"
    )
    print(f"Start: frame_{start_idx:04d}.{ext}")
    print("=" * 55)

    interval_frames = max(1, round(fps * interval_sec))
    saved = 0
    curr_idx = start_idx

    for frame_no in range(0, total_frames, interval_frames):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_no))
        ret, frame = cap.read()
        if ret:
            sec = frame_no / fps
            filename = f"frame_{curr_idx:04d}.{ext}"
            cv2.imwrite(os.path.join(output_dir, filename), frame)
            print(f" -> {filename} sparad vid {sec/60:.1f} min ({sec:.1f}s)")
            curr_idx += 1
            saved += 1

    cap.release()
    print(f"Klar med denna video! Sparade {saved} st nya bilder.")
    return curr_idx, saved


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "raw_images")
    os.makedirs(output_dir, exist_ok=True)

    # 1. Hämta videor
    if USE_FILE_PICKER:
        videos = pick_videos_gui()
    else:
        videos = [v for v in SPECIFIC_VIDEOS if os.path.exists(v)]

    # Fallback: sök i mappen
    if not videos:
        print("Inga videofiler valda. Söker efter .mp4-filer i mappen...")
        videos = glob.glob(os.path.join(script_dir, "*.mp4"))
        if not videos:
            print("Inga videor hittades. Avslutar.")
            return

    # 2. Räkna ut start-siffra
    if AUTO_CONTINUE_INDEX:
        next_num = get_next_frame_index(output_dir, IMAGE_FORMAT)
    else:
        next_num = 1

    print(f"\nAntal videor att bearbeta: {len(videos)} st")
    print(f"Intervall: En bild var {SECONDS_BETWEEN_FRAMES}:e sekund")
    print(f"Numreringen börjar på: frame_{next_num:04d}.{IMAGE_FORMAT}")

    total_new = 0
    for v_path in videos:
        next_num, saved = extract_from_video(
            video_path=v_path,
            output_dir=output_dir,
            start_idx=next_num,
            interval_sec=SECONDS_BETWEEN_FRAMES,
            ext=IMAGE_FORMAT,
        )
        total_new += saved

    print("\n" + "=" * 55)
    print("--- ALLT KLART! ---")
    print(f"Totalt antal nya bilder: {total_new} st")
    print(f"Totalt i mappen:         {next_num - 1} st")
    print(f"Plats: {output_dir}")
    print("=" * 55)


if __name__ == "__main__":
    main()
