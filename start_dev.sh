#!/bin/bash
export PATH="$HOME/.local/bin:$PATH"
export UV_SYSTEM_CERTS=1
cd /mnt/e/robot-policy-playground
pywrangler dev "$@"
