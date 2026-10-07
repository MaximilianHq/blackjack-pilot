import glob
import os
import re
import tkinter as tk
from tkinter import filedialog

import cv2

# ==============================================================================
# SETTINGS & CONFIGURATION
# ==============================================================================
SECONDS_BETWEEN_FRAMES = 30  # Seconds between each extracted frame
IMAGE_FORMAT = "png"  # Image format: 'png' or 'jpg'
AUTO_CONTINUE_INDEX = (
    True  # True = continue numbering (overwrite protection), False = start at 1
)
USE_FILE_PICKER = True  # True = open file dialog (Ctrl-click for multi-select), False = use SPECIFIC_VIDEOS
SPECIFIC_VIDEOS = []
# ==============================================================================


def get_next_frame_index(folder, ext):
    """Finds the next available index so existing images are not overwritten."""
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
    """Opens a file dialog to select one or more videos."""
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)

    print("Opening file dialog... Select your videos (hold Ctrl to select multiple):")
    files = filedialog.askopenfilenames(
        title="Select videos to extract from (hold Ctrl for multiple)",
        filetypes=[
            ("Video files", "*.mp4 *.mkv *.avi *.mov *.wmv *.webm *.ts"),
            ("All files", "*.*"),
        ],
    )
    root.destroy()
    return list(files)


def extract_from_video(video_path, output_dir, start_idx, interval_sec, ext):
    """Extracts frames from a single video at the specified interval."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"[ERROR] Could not open video: {video_path}")
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
            print(f" -> {filename} saved at {sec/60:.1f} min ({sec:.1f}s)")
            curr_idx += 1
            saved += 1

    cap.release()
    print(f"Finished processing video! Saved {saved} new frames.")
    return curr_idx, saved


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, "raw_images")
    os.makedirs(output_dir, exist_ok=True)

    # 1. Retrieve videos
    if USE_FILE_PICKER:
        videos = pick_videos_gui()
    else:
        videos = [v for v in SPECIFIC_VIDEOS if os.path.exists(v)]

    # Search directory if none selected
    if not videos:
        print("No video files selected. Searching for .mp4 files in directory...")
        videos = glob.glob(os.path.join(script_dir, "*.mp4"))
        if not videos:
            print("No videos found. Exiting.")
            return

    # 2. Determine start index
    if AUTO_CONTINUE_INDEX:
        next_num = get_next_frame_index(output_dir, IMAGE_FORMAT)
    else:
        next_num = 1

    print(f"\nVideos to process: {len(videos)}")
    print(f"Interval: One frame every {SECONDS_BETWEEN_FRAMES} seconds")
    print(f"Numbering starts at: frame_{next_num:04d}.{IMAGE_FORMAT}")

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
    print("--- ALL DONE! ---")
    print(f"Total new frames:    {total_new}")
    print(f"Total in directory:  {next_num - 1}")
    print(f"Output directory:    {output_dir}")
    print("=" * 55)


if __name__ == "__main__":
    main()
