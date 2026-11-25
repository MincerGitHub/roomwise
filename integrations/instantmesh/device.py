"""Device and dtype selection for InstantMesh inference.

The upstream project assumes an NVIDIA CUDA device.  Roomwise also runs on
Windows machines with Intel GPUs, where ``torch-directml`` exposes a
``privateuseone`` device.  Keeping the selection in one small module makes the
CLI and the application use the same behaviour and leaves CUDA untouched.
"""

from __future__ import annotations

import os

import torch


def resolve_device(requested: str | None = None) -> torch.device:
    """Resolve ``auto``, ``cuda``, ``directml`` or ``cpu`` to a torch device."""

    choice = (requested or os.getenv("INSTANTMESH_DEVICE", "auto")).strip().lower()
    if choice in {"auto", "cuda"} and torch.cuda.is_available():
        return torch.device("cuda")
    if choice == "cuda":
        raise RuntimeError("INSTANTMESH_DEVICE=cuda was requested, but CUDA is unavailable.")
    if choice in {"auto", "directml", "dml"}:
        try:
            import torch_directml

            return torch_directml.device()
        except (ImportError, RuntimeError) as exc:
            if choice in {"directml", "dml"}:
                raise RuntimeError("DirectML is unavailable; install torch-directml.") from exc
    if choice in {"auto", "cpu"}:
        return torch.device("cpu")
    raise ValueError(f"Unsupported InstantMesh device: {choice}")


def resolve_dtype(device: torch.device) -> torch.dtype:
    """Return a safe inference dtype, overridable with INSTANTMESH_DTYPE."""

    requested = os.getenv("INSTANTMESH_DTYPE", "auto").strip().lower()
    dtypes = {"float16": torch.float16, "fp16": torch.float16,
              "float32": torch.float32, "fp32": torch.float32}
    if requested in dtypes:
        return dtypes[requested]
    if requested not in {"", "auto"}:
        raise ValueError(f"Unsupported INSTANTMESH_DTYPE: {requested}")
    # CUDA and DirectML both support half precision on the target hardware.
    # CPU uses float32 because PyTorch's half convolutions are incomplete.
    return torch.float32 if device.type == "cpu" else torch.float16


def device_label(device: torch.device) -> str:
    return "DirectML" if device.type == "privateuseone" else str(device)
