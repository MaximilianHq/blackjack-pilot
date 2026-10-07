import glob
import os
import tkinter as tk
from tkinter import filedialog

import cv2
from ultralytics import YOLO

# ==============================================================================
# SETTINGS & CONFIGURATION
# ==============================================================================
# 1. Model path (leave empty for default models/yolo11m_blackjack_1280.pt)
MODEL_PATH = ""

# 2. Confidence threshold (0.10 to 0.90)
CONF_THRESHOLD = 0.35

# 3. Test images folder (leave empty for dialog or dataset/test/images)
TEST_FOLDER = ""

# 4. Save annotated result images in test_results/
SAVE_RESULTS = True
# ==============================================================================


def pick_folder_gui():
    """Opens a file dialog to select the image directory."""
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    print("Opening dialog... Select the folder containing test images:")
    folder = filedialog.askdirectory(title="Select folder with test images")
    root.destroy()
    return folder


def resolve_model(script_dir):
    """Finds default model in models/ or runs/."""
    root_dir = os.path.dirname(script_dir)
    default_model = os.path.join(root_dir, "models", "yolo11m_blackjack_1280.pt")
    if os.path.exists(default_model):
        return default_model

    # Search for best.pt in training runs
    found = glob.glob(os.path.join(script_dir, "runs", "**", "best.pt"), recursive=True)
    if found:
        return found[-1]

    return "yolo11m.pt"


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(script_dir)

    # 1. Determine model
    model_file = (
        MODEL_PATH
        if (MODEL_PATH and os.path.exists(MODEL_PATH))
        else resolve_model(script_dir)
    )
    print(f"Loading model: {model_file}")
    model = YOLO(model_file)

    # 2. Select image folder
    if TEST_FOLDER and os.path.exists(TEST_FOLDER):
        target_dir = TEST_FOLDER
    else:
        default_test = os.path.join(root_dir, "dataset", "test", "images")
        if os.path.exists(default_test) and any(os.scandir(default_test)):
            print(f"Using default test folder: {default_test}")
            target_dir = default_test
        else:
            target_dir = pick_folder_gui()

    if not target_dir or not os.path.exists(target_dir):
        print("No valid folder selected. Exiting.")
        return

    # 3. Retrieve all images in folder
    extensions = ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp")
    img_files = []
    for ext in extensions:
        img_files.extend(glob.glob(os.path.join(target_dir, ext)))

    img_files = sorted(img_files)
    if not img_files:
        print(f"No images found in: {target_dir}")
        return

    output_dir = os.path.join(script_dir, "test_results")
    if SAVE_RESULTS:
        os.makedirs(output_dir, exist_ok=True)

    print("\n==================================================")
    print(f"Testing {len(img_files)} images from: {target_dir}")
    print(f"Confidence threshold: {CONF_THRESHOLD*100:.0f}%")
    print("Controls: Click image window and press:")
    print(" -> Space / Enter / Any key: Next image")
    print(" -> 'q' or 'ESC': Exit test")
    print("==================================================\n")

    window_name = "Blackjack YOLO Test (Press Space for next image, 'q' to exit)"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1280, 800)

    total_cards_detected = 0

    for i, img_path in enumerate(img_files):
        img_name = os.path.basename(img_path)
        frame = cv2.imread(img_path)
        if frame is None:
            continue

        results = model(frame, conf=CONF_THRESHOLD, verbose=False)[0]
        annotated = results.plot()

        num_cards = len(results.boxes)
        total_cards_detected += num_cards

        info_text = f"[{i+1}/{len(img_files)}] {img_name} | Detected cards: {num_cards}"
        print(info_text)

        cv2.imshow(window_name, annotated)

        if SAVE_RESULTS:
            cv2.imwrite(os.path.join(output_dir, f"tested_{img_name}"), annotated)

        key = cv2.waitKey(0) & 0xFF
        if key == ord("q") or key == 27:
            print("Manually stopped.")
            break

    cv2.destroyAllWindows()
    print("\n--- COMPLETE! ---")
    print(
        f"Average cards detected per image: {total_cards_detected / max(1, len(img_files)):.1f}"
    )
    if SAVE_RESULTS:
        print(f"All saved results available in: {output_dir}")


if __name__ == "__main__":
    main()
