"""Generate placeholder precomputed action sequences for the demo tasks.

This script is a stand-in for the real PocketVLA inference pipeline.
Replace the frame-generation logic with actual model outputs when
available. Output: compact JSON files (short keys, no whitespace) under
public/data/, plus task_index.json.

Constraints honored:
- Each sequence <= 500 frames
- Short key names (i, ja, d, fc)
- json.dumps(..., separators=(",", ":"))
"""

import json
import math
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "public" / "data"

# (task_id, instruction, base_joint_angles, amplitude, phase_offset)
TASKS = [
    ("push_left_001", "push ball left", [0.3, 0.2], 0.4, 0.0),
    ("push_right_001", "push ball right", [0.3, 0.2], 0.4, math.pi),
    ("pick_cube_001", "pick up the cube", [0.5, 0.6], 0.3, 0.0),
    ("place_shelf_001", "place the cube on the shelf", [0.2, 0.8], 0.5, 0.0),
    ("push_forward_001", "push ball forward", [0.4, 0.3], 0.35, math.pi / 2),
]

FRAME_COUNT = 60
DURATION = 2.0


def make_frames(base, amplitude, phase_offset, frames):
    """Generate a smooth sinusoidal trajectory for a 2-DoF arm."""
    out = []
    for f in range(frames):
        t = f / (frames - 1)
        # joint 0 sweeps, joint 1 follows a slightly shifted curve
        j0 = base[0] + amplitude * math.sin(t * math.pi + phase_offset)
        j1 = base[1] + amplitude * 0.7 * math.sin(t * math.pi * 1.3 + phase_offset)
        out.append([round(j0, 4), round(j1, 4)])
    return out


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    index = {}
    for task_id, instruction, base, amp, phase in TASKS:
        frames = make_frames(base, amp, phase, FRAME_COUNT)
        payload = {
            "i": instruction,
            "ja": frames,
            "d": DURATION,
            "fc": len(frames),
        }
        out_path = DATA_DIR / f"{task_id}.json"
        with out_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        index[instruction] = task_id
        size_kb = out_path.stat().st_size / 1024
        print(f"  wrote {out_path.name}: {len(frames)} frames, {size_kb:.2f} KB")

    index_path = DATA_DIR / "task_index.json"
    with index_path.open("w", encoding="utf-8") as fh:
        json.dump(index, fh, separators=(",", ":"))
    print(f"  wrote {index_path.name}: {len(index)} entries")


if __name__ == "__main__":
    main()
