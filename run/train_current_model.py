"""
train_current_model.py — Depth map -> gripper motor current (mA) regressor.

Standalone, no dependency on 9DTact-main internals. Consumes data from
collect_current_data.py:
    <data>/images/<idx>.npy   (float32 HxW depth maps, mm)
    <data>/current.csv        (idx, t, current_mA, gripper_pos_bit, image_file)

Usage:
    python train_current_model.py --data data/left --out models/left --epochs 100

Outputs (in --out):
    model.pt                  - trained PyTorch weights + normalization stats
    train_history.csv         - per-epoch train/val loss
    test_predictions.csv      - per-sample ground truth vs prediction (test split)
    test_metrics.csv          - RMSE/MAE/R2/MaxErr
    training_curve.png
    predicted_vs_measured.png
    current_timeseries.png
"""

import os
import csv
import argparse
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader, random_split
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

class TactileCurrentDataset(Dataset):
    def __init__(self, data_dir, img_mean=None, img_std=None, cur_mean=None, cur_std=None):
        self.data_dir = data_dir
        self.img_dir = os.path.join(data_dir, "images")
        self.rows = []
        with open(os.path.join(data_dir, "current.csv"), "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.rows.append(row)

        if img_mean is None or img_std is None:
            sample = np.stack([
                np.load(os.path.join(self.img_dir, r["image_file"]))
                for r in self.rows[:: max(1, len(self.rows) // 200)]
            ])
            self.img_mean = float(sample.mean())
            self.img_std = float(sample.std() + 1e-6)
        else:
            self.img_mean, self.img_std = img_mean, img_std

        currents = np.array([float(r["current_mA"]) for r in self.rows], dtype=np.float32)
        if cur_mean is None or cur_std is None:
            self.cur_mean = float(currents.mean())
            self.cur_std = float(currents.std() + 1e-6)
        else:
            self.cur_mean, self.cur_std = cur_mean, cur_std

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, idx):
        row = self.rows[idx]
        img = np.load(os.path.join(self.img_dir, row["image_file"])).astype(np.float32)
        img = (img - self.img_mean) / self.img_std
        img = torch.from_numpy(img).unsqueeze(0)  # (1, H, W)

        current_raw = float(row["current_mA"])
        current_norm = (current_raw - self.cur_mean) / self.cur_std
        return img, torch.tensor(current_norm, dtype=torch.float32), torch.tensor(current_raw, dtype=torch.float32)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

class TactileCurrentNet(nn.Module):
    """Small CNN regressor: depth map -> scalar current (mA)."""

    def __init__(self, in_channels=1):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(in_channels, 16, 5, stride=2, padding=2), nn.BatchNorm2d(16), nn.ReLU(inplace=True),
            nn.Conv2d(16, 32, 5, stride=2, padding=2), nn.BatchNorm2d(32), nn.ReLU(inplace=True),
            nn.Conv2d(32, 64, 3, stride=2, padding=1), nn.BatchNorm2d(64), nn.ReLU(inplace=True),
            nn.Conv2d(64, 64, 3, stride=2, padding=1), nn.BatchNorm2d(64), nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((1, 1)),
        )
        self.head = nn.Sequential(
            nn.Flatten(),
            nn.Linear(64, 32), nn.ReLU(inplace=True),
            nn.Linear(32, 1),
        )

    def forward(self, x):
        x = self.features(x)
        return self.head(x).squeeze(-1)


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(args):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    full_ds = TactileCurrentDataset(args.data)
    n = len(full_ds)
    n_test = max(1, int(n * args.test_frac))
    n_val = max(1, int(n * args.val_frac))
    n_train = n - n_val - n_test
    if n_train <= 0:
        raise ValueError(f"Not enough samples ({n}) for the requested val/test split.")

    train_ds, val_ds, test_ds = random_split(
        full_ds, [n_train, n_val, n_test],
        generator=torch.Generator().manual_seed(args.seed)
    )

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True, num_workers=2)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size, shuffle=False, num_workers=2)
    test_loader = DataLoader(test_ds, batch_size=args.batch_size, shuffle=False, num_workers=2)

    model = TactileCurrentNet().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=args.weight_decay)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5, factor=0.5)
    criterion = nn.MSELoss()

    os.makedirs(args.out, exist_ok=True)
    history_path = os.path.join(args.out, "train_history.csv")
    best_val = float("inf")
    best_state = None

    with open(history_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["epoch", "train_loss", "val_loss", "lr"])

        for epoch in range(args.epochs):
            model.train()
            train_loss = 0.0
            for img, cur_norm, _ in train_loader:
                img, cur_norm = img.to(device), cur_norm.to(device)
                optimizer.zero_grad()
                pred = model(img)
                loss = criterion(pred, cur_norm)
                loss.backward()
                optimizer.step()
                train_loss += loss.item() * img.size(0)
            train_loss /= len(train_ds)

            model.eval()
            val_loss = 0.0
            with torch.no_grad():
                for img, cur_norm, _ in val_loader:
                    img, cur_norm = img.to(device), cur_norm.to(device)
                    pred = model(img)
                    loss = criterion(pred, cur_norm)
                    val_loss += loss.item() * img.size(0)
            val_loss /= len(val_ds)

            scheduler.step(val_loss)
            lr_now = optimizer.param_groups[0]["lr"]
            writer.writerow([epoch, train_loss, val_loss, lr_now])
            f.flush()

            if val_loss < best_val:
                best_val = val_loss
                best_state = {
                    "model_state": model.state_dict(),
                    "img_mean": full_ds.img_mean,
                    "img_std": full_ds.img_std,
                    "cur_mean": full_ds.cur_mean,
                    "cur_std": full_ds.cur_std,
                }

            if epoch % max(1, args.epochs // 20) == 0 or epoch == args.epochs - 1:
                print(f"Epoch {epoch:4d}  train={train_loss:.5f}  val={val_loss:.5f}  lr={lr_now:.2e}")

    torch.save(best_state, os.path.join(args.out, "model.pt"))
    print(f"Best val loss: {best_val:.5f}")

    # ---- final evaluation on held-out test set ----
    model.load_state_dict(best_state["model_state"])
    model.eval()

    preds, gts = [], []
    with torch.no_grad():
        for img, _, cur_raw in test_loader:
            img = img.to(device)
            pred_norm = model(img).cpu().numpy()
            pred = pred_norm * full_ds.cur_std + full_ds.cur_mean
            preds.append(pred)
            gts.append(cur_raw.numpy())
    preds = np.concatenate(preds, axis=0)
    gts = np.concatenate(gts, axis=0)

    pred_csv = os.path.join(args.out, "test_predictions.csv")
    with open(pred_csv, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_idx", "current_true_mA", "current_pred_mA"])
        for i in range(len(preds)):
            writer.writerow([i, gts[i], preds[i]])

    # ---- metrics ----
    err = preds - gts
    rmse = float(np.sqrt(np.mean(err ** 2)))
    mae = float(np.mean(np.abs(err)))
    ss_res = np.sum(err ** 2)
    ss_tot = np.sum((gts - gts.mean()) ** 2) + 1e-9
    r2 = float(1 - ss_res / ss_tot)
    max_err = float(np.max(np.abs(err)))

    metrics_path = os.path.join(args.out, "test_metrics.csv")
    with open(metrics_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["rmse_mA", "mae_mA", "r2", "max_abs_error_mA"])
        writer.writerow([rmse, mae, r2, max_err])
    print(f"Test: RMSE={rmse:.2f} mA  MAE={mae:.2f} mA  R2={r2:.4f}  MaxErr={max_err:.2f} mA")

    # ---- plots ----
    epochs_arr, tr_l, va_l = [], [], []
    with open(history_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            epochs_arr.append(int(row["epoch"]))
            tr_l.append(float(row["train_loss"]))
            va_l.append(float(row["val_loss"]))
    plt.figure(figsize=(6, 4))
    plt.plot(epochs_arr, tr_l, label="train")
    plt.plot(epochs_arr, va_l, label="val")
    plt.xlabel("epoch")
    plt.ylabel("normalized MSE loss")
    plt.yscale("log")
    plt.legend()
    plt.title("Training history")
    plt.tight_layout()
    plt.savefig(os.path.join(args.out, "training_curve.png"), dpi=150)
    plt.close()

    plt.figure(figsize=(5, 5))
    plt.scatter(gts, preds, s=10, alpha=0.4)
    lims = [min(gts.min(), preds.min()), max(gts.max(), preds.max())]
    plt.plot(lims, lims, 'r--', linewidth=1)
    plt.xlabel("measured current (mA)")
    plt.ylabel("predicted current (mA)")
    plt.title("Predicted vs Measured Motor Current (test set)")
    plt.tight_layout()
    plt.savefig(os.path.join(args.out, "predicted_vs_measured.png"), dpi=150)
    plt.close()

    plt.figure(figsize=(10, 4))
    plt.plot(gts, label="measured", linewidth=1)
    plt.plot(preds, label="predicted", linewidth=1, alpha=0.7)
    plt.xlabel("test sample index")
    plt.ylabel("current (mA)")
    plt.legend()
    plt.title("Motor current: measured vs predicted (test set order)")
    plt.tight_layout()
    plt.savefig(os.path.join(args.out, "current_timeseries.png"), dpi=150)
    plt.close()

    print(f"\nAll outputs written to {args.out}/")
    print("  model.pt                  - trained weights + normalization stats")
    print("  train_history.csv         - loss curves")
    print("  test_predictions.csv      - per-sample ground truth vs prediction")
    print("  test_metrics.csv          - RMSE/MAE/R2/MaxErr")
    print("  training_curve.png")
    print("  predicted_vs_measured.png")
    print("  current_timeseries.png")


def main():
    parser = argparse.ArgumentParser(description="Train tactile depth -> gripper current regressor.")
    parser.add_argument("--data", required=True, help="Directory containing images/ and current.csv")
    parser.add_argument("--out", required=True, help="Output directory for model and analysis files")
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--weight-decay", type=float, default=1e-5)
    parser.add_argument("--val-frac", type=float, default=0.15)
    parser.add_argument("--test-frac", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    train(args)


if __name__ == "__main__":
    main()
