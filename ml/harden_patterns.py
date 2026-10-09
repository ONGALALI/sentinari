"""§80 — PINN pattern hardening (runs in .venv-ml, torch lives here only).

Implements the ml/ scientific-ML templates (scientific_ml.py's hybrid
data+physics loop, sci_ml_core.py's SiLU Jacobian network) against REAL
Sentinari pattern data instead of synthetic curves:

- Inputs: feature matrix written by app/ml_hardening.py — one row per
  discovered pattern, features measured from its extraction record.
- Output head: sustainability score y-hat in [0,1] per pattern.
- Data loss: fit the stored labels (patterns that survived benefit analysis).
- Physics loss (the hardening): autograd sensitivity of y-hat w.r.t. the
  Risk-related features (sd_risk, speculation_gap) must be NON-POSITIVE —
  the Assessment Matrix's volatility-anchor law (Risk is the volatility
  anchor: more of it, less sustainability) enforced as a differentiable
  constraint, exactly like sci_ml_core.py's governing-equation residual.

CLI:
  python harden_patterns.py --input features.json --output result.json --epochs 600
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import torch
import torch.nn as nn
import torch.optim as optim

RISK_FEATURE_INDICES = []  # filled from feature_order at runtime


class HardeningNet(nn.Module):
    """SiLU MLP after sci_ml_core.py's UniversalSciNet — smooth for autograd."""

    def __init__(self, input_dim: int, hidden_dims=(64, 64), output_dim: int = 1):
        super().__init__()
        layers = []
        prev = input_dim
        for h in hidden_dims:
            layers += [nn.Linear(prev, h), nn.SiLU()]
            prev = h
        layers.append(nn.Linear(prev, output_dim))
        self.network = nn.Sequential(*layers)

    def forward(self, x):
        return torch.sigmoid(self.network(x))


def physics_residual(model: HardeningNet, inputs: torch.Tensor, risk_cols: list[int]) -> torch.Tensor:
    """d(y)/d(risk features) must be <= 0 (volatility-anchor law).

    Autograd Jacobian of the output w.r.t. the inputs, then penalise the
    positive part of the risk-column sensitivities — the model may not learn
    'more risk speculation = more sustainable'.
    """
    x = inputs.clone().detach().requires_grad_(True)
    y = model(x)
    grads = torch.autograd.grad(
        outputs=y,
        inputs=x,
        grad_outputs=torch.ones_like(y),
        create_graph=True,
        retain_graph=True,
        only_inputs=True,
    )[0]  # shape (N, input_dim)
    risk_grads = grads[:, risk_cols]
    # Violation = positive sensitivity; penalise its square (like the templates).
    violation = torch.relu(risk_grads + 1e-3)  # small tolerance band
    return torch.mean(violation ** 2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--epochs", type=int, default=600)
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    order: list[str] = payload["feature_order"]
    patterns: list[dict] = payload["patterns"]
    risk_cols = [i for i, name in enumerate(order) if name in ("sd_risk", "speculation_gap")]

    if not patterns:
        Path(args.output).write_text(json.dumps({"ok": False, "error": "no patterns supplied"}))
        return 1

    X = torch.tensor([[p["features"][k] for k in order] for p in patterns], dtype=torch.float32, device=device)
    y = torch.tensor([[p["label"]] for p in patterns], dtype=torch.float32, device=device)

    model = HardeningNet(input_dim=len(order)).to(device)
    optimizer = optim.AdamW(model.parameters(), lr=3e-3, weight_decay=1e-4)
    data_weight = 1.0
    science_weight = 0.25

    final_data = final_physics = 0.0
    for epoch in range(1, max(100, int(args.epochs)) + 1):
        optimizer.zero_grad()
        preds = model(X)
        loss_data = nn.functional.mse_loss(preds, y)
        loss_physics = physics_residual(model, X, risk_cols)
        total = data_weight * loss_data + science_weight * loss_physics
        total.backward()
        optimizer.step()
        final_data, final_physics = float(loss_data.item()), float(loss_physics.item())

    # Per-pattern verdicts from the trained, physics-constrained net.
    with torch.no_grad():
        scores = model(X).squeeze(1).tolist()
    verdicts = []
    for p, score in zip(patterns, scores):
        feats = p["features"]
        risk_pressure = (feats.get("sd_risk", 0) + feats.get("speculation_gap", 0)) / 2.0
        support = (feats.get("evidence_depth", 0) + feats.get("source_breadth", 0) + feats.get("confidence", 0)) / 3.0
        if support < 0.25:
            verdict = "insufficient-data"
        elif score >= 0.5 and risk_pressure <= 0.6:
            verdict = "stable"
        elif risk_pressure > 0.6:
            verdict = "volatile"
        else:
            verdict = "weak"
        verdicts.append(
            {
                "pattern_id": p["pattern_id"],
                "title": p["title"],
                "status": p["status"],
                "sustainability_score": round(float(score), 4),
                "risk_pressure": round(float(risk_pressure), 4),
                "evidence_support": round(float(support), 4),
                "verdict": verdict,
            }
        )

    result = {
        "ok": True,
        "device": str(device),
        "epochs": args.epochs,
        "patterns_evaluated": len(patterns),
        "final_data_loss": round(final_data, 6),
        "final_physics_residual": round(final_physics, 6),
        "verdicts": verdicts,
        "notes": "Data loss fits stored analysis outcomes; physics residual enforces d(sustainability)/d(risk) <= 0 (Assessment Matrix volatility-anchor law).",
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"hardening complete on {device}: data={final_data:.6f} physics={final_physics:.6f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
