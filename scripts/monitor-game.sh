#!/bin/bash
# Optional game-only wrapper; caller supplies real private paths and GPU index.
set -euo pipefail
mode=${1:-}
case "$mode" in off|hud|log) shift ;; *) echo 'Usage: monitor-game.sh off|hud|log command [args...]' >&2; exit 2 ;; esac
[ "$#" -gt 0 ] || { echo 'Missing game command' >&2; exit 2; }
: "${GPUIP_ROOT:?Set GPUIP_ROOT to your private deployment directory}"
: "${GPUIP_GPU_INDEX:?Set GPUIP_GPU_INDEX to the validated Vulkan device index}"
: "${GPUIP_COMPAT_DATA_PATH:?Set GPUIP_COMPAT_DATA_PATH to the existing game prefix parent}"
[[ "$GPUIP_GPU_INDEX" =~ ^[0-9]+$ ]] || { echo 'GPU index must be a nonnegative integer' >&2; exit 2; }
[[ "$GPUIP_ROOT" = /* && "$GPUIP_COMPAT_DATA_PATH" = /* ]] || { echo 'Use absolute Linux paths' >&2; exit 2; }
# Never silently create a replacement prefix when the caller mistypes its path.
[ -d "$GPUIP_COMPAT_DATA_PATH/pfx" ] || { echo 'Existing pfx not found; configure the game prefix first' >&2; exit 2; }
ulimit -n 65536
export STEAM_COMPAT_DATA_PATH="$GPUIP_COMPAT_DATA_PATH"
if [ "${GPUIP_DEVICE_VIEW:-0}" = 1 ]; then
    # The private Steam view exposes one Vulkan adapter; its local ordinal is 0.
    export VKD3D_VULKAN_DEVICE=0
else
    export VKD3D_VULKAN_DEVICE="$GPUIP_GPU_INDEX"
fi
export VK_ICD_FILENAMES="${GPUIP_NVIDIA_ICD:-/usr/share/vulkan/icd.d/nvidia_icd.json}"
[ -r "$VK_ICD_FILENAMES" ] || { echo 'NVIDIA ICD not readable; set GPUIP_NVIDIA_ICD' >&2; exit 2; }
layers=":${VK_INSTANCE_LAYERS:-}:"
layers=${layers//:VK_LAYER_MANGOHUD_overlay:/:}
layers=${layers#:}; layers=${layers%:}
if [ -n "$layers" ]; then export VK_INSTANCE_LAYERS="$layers"; else unset VK_INSTANCE_LAYERS; fi
unset MANGOHUD_CONFIGFILE MANGOHUD_CONFIG
export MANGOHUD=0 DXVK_HUD='' PROTON_LOG=0
if [ "$mode" != off ]; then
    layer_dir="${GPUIP_MANGOHUD_LAYER_DIR:-$GPUIP_ROOT/runtime/mangohud/layers}"
    [ -d "$layer_dir" ] || { echo 'Install/configure private MangoHud layers first' >&2; exit 2; }
    export MANGOHUD=1
    export VK_LAYER_PATH="$layer_dir${VK_LAYER_PATH:+:$VK_LAYER_PATH}"
    export VK_INSTANCE_LAYERS="VK_LAYER_MANGOHUD_overlay${VK_INSTANCE_LAYERS:+:$VK_INSTANCE_LAYERS}"
    export MANGOHUD_CONFIG='fps,frametime,frame_timing,position=top-right,font_size=24,toggle_hud=Shift_R+F12,toggle_logging=Shift_L+F2,permit_upload=0'
    if [ "$mode" = log ]; then
        output="$STEAM_COMPAT_DATA_PATH/mangohud/game-fps"
        mkdir -p "$output"
        export MANGOHUD_CONFIG="$MANGOHUD_CONFIG,output_folder=$output,log_interval=0,log_duration=120"
    fi
fi
exec "$@"
