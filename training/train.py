import os
import shutil

import torch
from ultralytics import YOLO


def main():
    skript_mapp = os.path.dirname(os.path.abspath(__file__))
    rot_mapp = os.path.dirname(skript_mapp)
    yaml_sokvag = os.path.join(rot_mapp, "dataset", "data.yaml")

    # 1. Kontrollera hårdvara: GPU
    use_cuda = torch.cuda.is_available()
    device_target = 0 if use_cuda else "cpu"

    if use_cuda:
        gpu_name = torch.cuda.get_device_name(0)
        vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
        print(
            f"[HW] GPU identifierad: {gpu_name} ({vram_gb:.1f} GB VRAM) - Träning på CUDA aktiverad!"
        )
        batch_size = 8
        worker_threads = 4
    else:
        cpu_cores = os.cpu_count() or 8
        print(f"[HW] Körs på CPU med {cpu_cores} trådar.")
        batch_size = 4
        worker_threads = 2

    # 2. Ladda basmodell (YOLO11 Medium)
    base_model_path = "yolo11m.pt"
    print(f"Laddar basmodell: {base_model_path}...")
    model = YOLO(base_model_path)

    print("\n=======================================================")
    print("STARTAR TRÄNING MED YOLO11 MEDIUM PÅ DATASET @ 1280p")
    print(f"Data: {yaml_sokvag}")
    print("Upplösning: 1280 (rect=True för optimal 16:9 widescreen)")
    print(f"Batch: {batch_size} | Enhet: {device_target}")
    print("=======================================================\n")

    # 3. Träna modellen på 1280p
    runs_dir = os.path.join(skript_mapp, "runs")
    run_name = "yolo11m_blackjack_1280"

    model.train(
        data=yaml_sokvag,
        epochs=120,
        patience=15,
        imgsz=1280,
        rect=True,
        batch=batch_size,
        device=device_target,
        workers=worker_threads,
        amp=use_cuda,
        # Tränings-stabilisering
        lr0=0.005,
        lrf=0.01,
        cos_lr=True,
        warmup_epochs=5.0,
        # Augmentering anpassad för kasinobord
        scale=0.3,
        degrees=10.0,
        shear=8.0,
        fliplr=0.0,  # Vänd ej horisontellt (siffror/färger blir spegelvända)
        flipud=0.0,  # Vänd ej upp-och-ned
        project=runs_dir,
        name=run_name,
        exist_ok=True,
    )

    best_weights = os.path.join(runs_dir, run_name, "weights", "best.pt")
    target_model_file = os.path.join(rot_mapp, "models", "yolo11m_blackjack_1280.pt")

    print("\n--- TRÄNINGEN ÄR KLAR! ---")
    if os.path.exists(best_weights):
        print(f"Bästa vikter sparade i:\n{best_weights}")
        shutil.copy(best_weights, target_model_file)
        print(f"Uppdaterade app-modellen automatiskt:\n{target_model_file}")
    else:
        print(f"Kunde inte hitta best.pt i {best_weights}")


if __name__ == "__main__":
    main()
