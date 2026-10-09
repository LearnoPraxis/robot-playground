#!/usr/bin/env python3
"""
生成 Franka Panda 7-DOF + 夹爪的预计算动作序列。

每帧格式: [j0, j1, j2, j3, j4, j5, j6, gripper]
  - j0..j6: 7 个 arm joint 角度（弧度）
  - gripper: 0=闭合, 1=全开

输出: public/data/*.json, 每个文件 60 帧
"""

import json
import math
import os

# Franka Panda home 位姿
HOME = [1.707, -1.754, 0.003, -2.702, 0.003, 0.951, 2.490]
GRIPPER_OPEN = 1.0
GRIPPER_CLOSED = 0.0
FRAMES = 60
DURATION = 2.0

# 输出目录
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "public", "data")


def ease_in_out(t: float) -> float:
    """余弦缓动：0→1 平滑过渡"""
    return 0.5 * (1 - math.cos(math.pi * t))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_joints(a: list, b: list, t: float) -> list:
    return [lerp(a[i], b[i], t) for i in range(len(a))]


def generate_trajectory(keyframes: list, frames: int) -> list:
    """
    从关键帧生成平滑轨迹。
    keyframes: [(time_frac, joints_8d), ...]
    """
    traj = []
    for i in range(frames):
        t = i / (frames - 1)
        # 找到当前 t 所在的关键帧区间
        for j in range(len(keyframes) - 1):
            t0, j0 = keyframes[j]
            t1, j1 = keyframes[j + 1]
            if t0 <= t <= t1:
                local_t = (t - t0) / (t1 - t0) if t1 > t0 else 0
                eased = ease_in_out(local_t)
                frame = lerp_joints(j0, j1, eased)
                traj.append([round(v, 4) for v in frame])
                break
        else:
            traj.append([round(v, 4) for v in keyframes[-1][1]])
    return traj


def save_task(task_id: str, instruction: str, keyframes: list):
    traj = generate_trajectory(keyframes, FRAMES)
    payload = {
        "i": instruction,
        "ja": traj,
        "d": DURATION,
        "fc": len(traj),
    }
    path = os.path.join(OUT_DIR, f"{task_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"  {task_id}: {len(traj)} 帧 → {path}")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    # 任务 1: push ball left（推球向左）
    # 从 home 位姿 → 前伸接近球 → 向左扫
    save_task("push_left_001", "push ball left", [
        (0.0, HOME + [GRIPPER_OPEN]),
        (0.25, [0.5, -0.5, 0.0, -1.5, 0.0, 1.0, 1.5, GRIPPER_OPEN]),
        (0.5, [0.5, -0.2, 0.0, -1.8, 0.0, 1.0, 1.5, GRIPPER_OPEN]),
        (0.75, [1.0, -0.2, 0.0, -1.8, 0.0, 1.0, 1.5, GRIPPER_OPEN]),
        (1.0, HOME + [GRIPPER_OPEN]),
    ])

    # 任务 2: push ball forward（推球向前）
    save_task("push_forward_001", "push ball forward", [
        (0.0, HOME + [GRIPPER_OPEN]),
        (0.3, [0.0, -0.3, 0.0, -1.5, 0.0, 1.0, 1.5, GRIPPER_OPEN]),
        (0.6, [0.0, -0.8, 0.0, -2.0, 0.0, 1.0, 1.5, GRIPPER_OPEN]),
        (0.8, [0.0, -1.0, 0.0, -2.2, 0.0, 1.0, 1.5, GRIPPER_OPEN]),
        (1.0, HOME + [GRIPPER_OPEN]),
    ])

    # 任务 3: pick up the cube（抓取立方体）
    # 前伸 → 打开夹爪 → 接近立方体 → 闭合夹爪 → 抬起
    save_task("pick_cube_001", "pick up the cube", [
        (0.0, HOME + [GRIPPER_OPEN]),
        (0.2, [0.0, -0.2, 0.0, -1.2, 0.0, 0.8, 1.5, GRIPPER_OPEN]),
        (0.4, [0.0, -0.4, 0.0, -1.8, 0.0, 0.8, 1.5, GRIPPER_OPEN]),
        (0.5, [0.0, -0.4, 0.0, -1.8, 0.0, 0.8, 1.5, GRIPPER_CLOSED]),
        (0.7, [0.0, -0.4, 0.0, -1.0, 0.0, 0.8, 1.5, GRIPPER_CLOSED]),
        (0.9, [0.0, -0.2, 0.0, -0.5, 0.0, 0.5, 1.0, GRIPPER_CLOSED]),
        (1.0, HOME + [GRIPPER_CLOSED]),
    ])

    # 任务 4: place on the shelf（放置到货架）
    # 抓取 → 移动到货架 → 打开夹爪 → 回到 home
    save_task("place_shelf_001", "place on the shelf", [
        (0.0, HOME + [GRIPPER_CLOSED]),
        (0.2, [0.3, -0.2, 0.0, -0.8, 0.0, 0.5, 1.0, GRIPPER_CLOSED]),
        (0.4, [0.8, -0.3, 0.0, -1.0, 0.0, 0.5, 1.0, GRIPPER_CLOSED]),
        (0.5, [0.8, -0.3, 0.0, -1.0, 0.0, 0.5, 1.0, GRIPPER_OPEN]),
        (0.7, [0.8, -0.1, 0.0, -0.5, 0.0, 0.3, 0.8, GRIPPER_OPEN]),
        (1.0, HOME + [GRIPPER_OPEN]),
    ])

    # 任务 5: push ball right（推球向右）
    save_task("push_right_001", "push ball right", [
        (0.0, HOME + [GRIPPER_OPEN]),
        (0.25, [-0.5, -0.5, 0.0, -1.5, 0.0, 1.0, 1.5, GRIPPER_OPEN]),
        (0.5, [-0.5, -0.2, 0.0, -1.8, 0.0, 1.0, 1.5, GRIPPER_OPEN]),
        (0.75, [-1.0, -0.2, 0.0, -1.8, 0.0, 1.0, 1.5, GRIPPER_OPEN]),
        (1.0, HOME + [GRIPPER_OPEN]),
    ])

    print(f"\n生成 5 个任务，每个 {FRAMES} 帧，输出到 {OUT_DIR}")


if __name__ == "__main__":
    main()
