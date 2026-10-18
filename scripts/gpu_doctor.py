"""Read-only workspace diagnostics. Run using the Jupyter GPU Python first."""
import json
import platform
import shutil
import sys
from pathlib import Path


def main():
    report = {
        "python": sys.version.split()[0], "executable": sys.executable,
        "platform": platform.platform(), "workspace": str(Path.cwd()),
        "free_disk_gib": round(shutil.disk_usage(Path.cwd()).free / 1024**3, 1),
        "tools": {name: bool(shutil.which(name)) for name in ("git", "gh", "uv", "ffmpeg", "docker", "nvidia-smi")},
    }
    try:
        import torch
        report.update(torch=torch.__version__, torch_cuda=torch.version.cuda,
                      cuda_available=torch.cuda.is_available())
        if torch.cuda.is_available():
            report.update(gpu_name=torch.cuda.get_device_name(0),
                          compute_capability=list(torch.cuda.get_device_capability(0)),
                          compiled_arches=torch.cuda.get_arch_list())
            # A real CUDA operation catches a wheel that imports but has no compatible kernels.
            try:
                tensor = torch.ones((16, 16), device="cuda")
                report["cuda_matmul_passed"] = bool(torch.all(tensor @ tensor == 16).item())
                torch.cuda.synchronize()
            except Exception as exc:
                report["cuda_matmul_passed"] = False
                report["cuda_error_type"] = type(exc).__name__
        try:
            import torchaudio
            report["torchaudio"] = torchaudio.__version__
        except Exception as exc:
            report["torchaudio_error_type"] = type(exc).__name__
    except ImportError:
        report["torch_installed"] = False
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
