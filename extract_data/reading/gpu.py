"""
Running the OCR on an NVIDIA GPU, when there is one.

Everything about the GPU is here, so ocr.py only asks `cuda_config()` to switch it on while it
creates the engine.  Without the GPU build of onnxruntime and the CUDA libraries (see
requirements.txt) nothing changes and the OCR runs on the CPU.
"""

from contextlib import contextmanager
from functools import lru_cache

from rapidocr_onnxruntime import rapid_ocr_api  # its config reader is wrapped to switch the models to the GPU

# Turned off by the --cpu option of main.py and upload_filings.py.
enabled = True


@lru_cache(maxsize=None)  # the answer cannot change while the program runs
def available():
    """
    True if onnxruntime can run on an NVIDIA GPU here.

    That needs the GPU build of onnxruntime (`pip install onnxruntime-gpu` instead of
    `onnxruntime`) and the CUDA and cuDNN libraries it loads.  When either is missing this is
    False and the OCR runs on the CPU.
    """
    try:
        import onnxruntime
        if "CUDAExecutionProvider" not in onnxruntime.get_available_providers():
            return False

        if hasattr(onnxruntime, "preload_dlls"):
            onnxruntime.preload_dlls()  # finds the CUDA libraries installed as pip packages
        return True

    except Exception:  # missing libraries, driver problems, ...
        return False


def in_use():
    """
    True if the OCR will run on the GPU: it is enabled (no --cpu) and available.
    """
    return enabled and available()


@contextmanager
def setting(use_gpu):
    """
    Allow (or, with False, forbid) the GPU inside a `with` block; the old setting comes back afterwards.
    """
    global enabled
    previous, enabled = enabled, use_gpu

    try:
        yield

    finally:
        enabled = previous


@contextmanager
def cuda_config():
    """
    While active, a RapidOCR engine created inside it runs its three models on the GPU.

    RapidOCR 1.2 has no working option for this (its keyword arguments cannot set it), so its
    config file is read through a wrapper that turns CUDA on for each model.  Does nothing when
    the GPU is not in use.
    """
    if not in_use():
        yield
        return

    original = rapid_ocr_api.read_yaml

    def gpu_config(path):
        config = original(path)

        for model in ("Det", "Cls", "Rec"):
            config[model]["use_cuda"] = True

        return config

    rapid_ocr_api.read_yaml = gpu_config
    try:
        yield

    finally:
        rapid_ocr_api.read_yaml = original
