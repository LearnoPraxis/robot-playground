#!/usr/bin/env python3
"""检查生成的 JSON 轨迹值"""
import json

for task_id in ["pick_cube_001", "place_shelf_001"]:
    with open(f"/mnt/e/robot-policy-playground/public/data/{task_id}.json") as f:
        d = json.load(f)
    print(f"\n=== {task_id} ===")
    print(f"Instruction: {d['i']}")
    print(f"Frames: {d['fc']}")
    indices = [0, 10, 15, 20, 25, 30, 40, 50, 59]
    for i in indices:
        if i < len(d['ja']):
            frame = d['ja'][i]
            print(f"  Frame {i:2d}: j=[{', '.join(f'{v:7.3f}' for v in frame[:7])}] g={frame[7]:.1f}")
