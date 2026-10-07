import glob
import os
import tkinter as tk
from tkinter import filedialog

import cv2
from ultralytics import YOLO

# ==============================================================================
# ⚙️ INSTÄLLNINGAR & VARIABLER
# ==============================================================================
# 1. Modell-sökväg (lämna tom för models/yolo11m_blackjack_1280.pt)
MODEL_PATH = ""

# 2. Confidence-tröskel (0.10 till 0.90)
CONF_THRESHOLD = 0.35

# 3. Mapp med bilder att testa på (lämna tom för att öppna fildialog eller standard dataset/test/images)
TEST_FOLDER = ""

# 4. Spara annoterade resultatbilder i test_results/
SAVE_RESULTS = True
# ==============================================================================


def pick_folder_gui():
    """Öppnar en Windows-dialog där du kan välja bildmapp."""
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    print("Öppnar fönster... Välj mappen med bilder du vill testa på:")
    folder = filedialog.askdirectory(title="Välj mapp med testbilder")
    root.destroy()
    return folder


def resolve_model(script_dir):
    """Hittar standardmodellen i models/ eller runs/."""
    rot_dir = os.path.dirname(script_dir)
    default_model = os.path.join(rot_dir, "models", "yolo11m_blackjack_1280.pt")
    if os.path.exists(default_model):
        return default_model

    # Leta efter best.pt i träningsruns
    found = glob.glob(os.path.join(script_dir, "runs", "**", "best.pt"), recursive=True)
    if found:
        return found[-1]

    return "yolo11m.pt"


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    rot_dir = os.path.dirname(script_dir)

    # 1. Bestäm modell
    model_file = (
        MODEL_PATH
        if (MODEL_PATH and os.path.exists(MODEL_PATH))
        else resolve_model(script_dir)
    )
    print(f"Laddar modell: {model_file}")
    model = YOLO(model_file)

    # 2. Välj bildmapp
    if TEST_FOLDER and os.path.exists(TEST_FOLDER):
        target_dir = TEST_FOLDER
    else:
        default_test = os.path.join(rot_dir, "dataset", "test", "images")
        if os.path.exists(default_test) and any(os.scandir(default_test)):
            print(f"Använder standard testmapp: {default_test}")
            target_dir = default_test
        else:
            target_dir = pick_folder_gui()

    if not target_dir or not os.path.exists(target_dir):
        print("Ingen giltig mapp valdes. Avslutar.")
        return

    # 3. Hämta alla bilder i mappen
    extensions = ("*.png", "*.jpg", "*.jpeg", "*.webp", "*.bmp")
    img_files = []
    for ext in extensions:
        img_files.extend(glob.glob(os.path.join(target_dir, ext)))

    img_files = sorted(img_files)
    if not img_files:
        print(f"Inga bilder hittades i: {target_dir}")
        return

    output_dir = os.path.join(script_dir, "test_results")
    if SAVE_RESULTS:
        os.makedirs(output_dir, exist_ok=True)

    print("\n==================================================")
    print(f"Testar {len(img_files)} bilder från: {target_dir}")
    print(f"Confidence threshold: {CONF_THRESHOLD*100:.0f}%")
    print("Styrning: Klicka på bildfönstret och tryck på:")
    print(" -> Mellanslag / Enter / Valfri tangent: Nästa bild")
    print(" -> 'q' eller 'ESC': Avsluta testet")
    print("==================================================\n")

    window_name = (
        "Blackjack YOLO Test (Tryck mellanslag for nasta bild, 'q' for avsluta)"
    )
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

        info_text = (
            f"[{i+1}/{len(img_files)}] {img_name} | Hittade kort: {num_cards} st"
        )
        print(info_text)

        cv2.imshow(window_name, annotated)

        if SAVE_RESULTS:
            cv2.imwrite(os.path.join(output_dir, f"tested_{img_name}"), annotated)

        key = cv2.waitKey(0) & 0xFF
        if key == ord("q") or key == 27:
            print("Avbröt manuellt.")
            break

    cv2.destroyAllWindows()
    print("\n--- KLART! ---")
    print(
        f"Genomsnittligt antal hittade kort per bild: {total_cards_detected / max(1, len(img_files)):.1f} st"
    )
    if SAVE_RESULTS:
        print(f"Alla sparade resultat finns i: {output_dir}")


if __name__ == "__main__":
    main()
