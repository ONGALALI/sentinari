# Sentinari ML Environment (§48)

The machine-learning workshop for Sentinari's Training Phase 1: physics-
informed neural networks and the scientific model stack, kept **separate**
from the app's runtime venv on purpose — training libraries are heavy and
move on their own schedule. The app never imports torch; this venv never
runs the server.

## Layout

| File | Role |
| --- | --- |
| `pytorch.py` | Hardware verification + baseline GPU training loop |
| `scientific_ml.py` | PINN template: data loss + physics constraint (autograd) |
| `sci_ml_core.py` | PINN core: multi-output Jacobian residual (autograd.grad) |
| `requirements-ml.txt` | Day-1 spec (Windows laptop, CUDA wheel pinned) |
| `environment.yml` | Rig-day spec (miniconda, Ubuntu, RTX 5070 Ti) |

## Status: verified live on GPU (§48)

- Device: NVIDIA GeForce RTX 4050 Laptop GPU (Ada, sm_89) — driver 610.62
- Build: `torch 2.11.0+cu128` (CUDA wheel bundles its own CUDA runtime; no
  toolkit install needed)
- `pytorch.py` — 100 epochs GPU training, loss 0.99 → 0.77 ✅
- `scientific_ml.py` — 2000 epochs PINN, data error 0.086 → 0.065 ✅
- `sci_ml_core.py` — 1000 epochs, **5.31 s** on GPU ✅ (after the §48
  grad-graph fix below)

## Fix applied to sci_ml_core.py (§48)

Inputs/labels must not carry `requires_grad=True`. Building
`y_experimental = torch.sin(X_experimental[...])` from a grad-tracked tensor
tied the labels into the autograd graph; the first `backward()` freed it and
epoch 2 crashed ("backward through the graph a second time"). Data tensors
are now grad-free; the physics loss creates fresh grad tracking per call —
the correct PINN pattern.

## Day-1 (this laptop)

```
.venv-ml\Scripts\python.exe -m pip install -r ml\requirements-ml.txt
cd ml
..\.venv-ml\Scripts\python.exe pytorch.py
..\.venv-ml\Scripts\python.exe scientific_ml.py
..\.venv-ml\Scripts\python.exe sci_ml_core.py
```

## Rig day (Ubuntu / RTX 5070 Ti / miniconda)

```
conda env create -f ml/environment.yml
conda activate sentinari-ml
cd ml && python pytorch.py     # expect: NVIDIA GeForce RTX 5070 Ti, sm_120
```

- Same `torch==2.11.0+cu128` build covers Blackwell (sm_120). If a newer
  CUDA build ships by then, bump the index URL (`cu129`/`cu130`) — nothing
  else changes.
- Wheels bundle CUDA; install the NVIDIA driver only (570+). No toolkit.
- The conda env is the training home on Linux; the app's runtime remains
  requirements-inference.txt and stays torch-free by design.

## Where this feeds the ladder

Training Phase 1 (assessment pipeline, stage 2) draws its engines from
here: the PINN templates become the scientific model family the examiner
and HLE stage drive. `ml/` stays a self-contained workshop folder — it
migrates with Sentinari.
