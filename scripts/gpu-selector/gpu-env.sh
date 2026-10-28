#!/bin/bash
# Source this from run-steam.sh and per-game wrappers, after legacy GPU exports.
# The caller must set GPUIP_STREAM_ROOT to its own deployment directory.
_gpu_env=$(python3 "${GPUIP_STREAM_ROOT:?Set GPUIP_STREAM_ROOT}/scripts/gpu-selector/gpu_control.py" --root "$GPUIP_STREAM_ROOT" env) || return 1
eval "$_gpu_env"
unset _gpu_env
