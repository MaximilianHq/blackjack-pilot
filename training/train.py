import os
import shutil

import torch
from ultralytics import YOLO


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(script_dir)
    yaml_path = os.path.join(root_dir, "dataset", "data.yaml")

    # 1. Hardware verification: GPU
    use_cuda = torch.cuda.is_available()
    device_target = 0 if use_cuda else "cpu"

    if use_cuda:
        gpu_name = torch.cuda.get_device_name(0)
        vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
        print(
            f"[HW] GPU detected: {gpu_name} ({vram_gb:.1f} GB VRAM) - CUDA training enabled!"
        )
        batch_size = 8
        worker_threads = 4
    else:
        cpu_cores = os.cpu_count() or 8
        print(f"[HW] Running on CPU with {cpu_cores} threads.")
        batch_size = 4
        worker_threads = 2

    # 2. Load base model (YOLO11 Medium)
    base_model_path = "yolo11m.pt"
    print(f"Loading base model: {base_model_path}...")
    model = YOLO(base_model_path)

    print("\n=======================================================")
    print("STARTING TRAINING WITH YOLO11 MEDIUM ON DATASET @ 1280p")
    print(f"Data: {yaml_path}")
    print("Resolution: 1280 (rect=True for optimal 16:9 widescreen)")
    print(f"Batch: {batch_size} | Device: {device_target}")
    print("=======================================================\n")

    # 3. Train model at 1280p
    runs_dir = os.path.join(script_dir, "runs")
    run_name = "yolo11m_blackjack_1280"

    model.train(
        data=yaml_path,
        epochs=120,
        patience=15,
        imgsz=1280,
        rect=True,
        batch=batch_size,
        device=device_target,
        workers=worker_threads,
        amp=use_cuda,
        # Training stabilization
        lr0=0.005,
        lrf=0.01,
        cos_lr=True,
        warmup_epochs=5.0,
        # Augmentations customized for casino tables
        scale=0.3,
        degrees=10.0,
        shear=8.0,
        fliplr=0.0,  # Do not flip horizontally (suits and numbers would mirror)
        flipud=0.0,  # Do not flip upside-down
        project=runs_dir,
        name=run_name,
        exist_ok=True,
    )

    best_weights = os.path.join(runs_dir, run_name, "weights", "best.pt")
    target_model_file = os.path.join(root_dir, "models", "yolo11m_blackjack_1280.pt")

    print("\n--- TRAINING COMPLETE! ---")
    if os.path.exists(best_weights):
        print(f"Best weights saved to:\n{best_weights}")
        shutil.copy(best_weights, target_model_file)
        print(f"Automatically updated application model:\n{target_model_file}")
    else:
        print(f"Could not find best.pt in {best_weights}")


if __name__ == "__main__":
    main()
