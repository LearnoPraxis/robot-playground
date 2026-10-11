#!/usr/bin/env python3
"""
使用 MuJoCo Python 绑定计算正确的 IK 关键帧，替换手工猜测的角度。

通过 Jacobian 阻尼最小二乘法（DLS）求解逆运动学，
确保末端执行器（TCP site）实际到达目标物体位置。
"""

import mujoco
import numpy as np
import json
import math
import os

# ── 路径 ──
BASE = os.path.join(os.path.dirname(__file__), "..")
SCENE_XML = os.path.join(BASE, "public", "data", "panda", "scene.xml")
OUT_DIR = os.path.join(BASE, "public", "data")

# ── 加载模型 ──
model = mujoco.MjModel.from_xml_path(SCENE_XML)
data = mujoco.MjData(model)

# ── 查找 TCP site ──
tcp_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, "tcp")
if tcp_id < 0:
    raise RuntimeError("未找到 tcp site")
print(f"TCP site ID: {tcp_id}")

# ── 查找 7 个 arm joint 的 qpos/dof 地址 ──
arm_joints = []
for name in ["joint1", "joint2", "joint3", "joint4", "joint5", "joint6", "joint7"]:
    jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
    if jid < 0:
        raise RuntimeError(f"未找到 joint: {name}")
    arm_joints.append({
        "name": name,
        "jid": jid,
        "qposadr": model.jnt_qposadr[jid],
        "dofadr": model.jnt_dofadr[jid],
        "range": (model.jnt_range[jid][0], model.jnt_range[jid][1]),
    })
    print(f"  {name}: qpos={model.jnt_qposadr[jid]}, dof={model.jnt_dofadr[jid]}, "
          f"range=({model.jnt_range[jid][0]:.3f}, {model.jnt_range[jid][1]:.3f})")

# 查找 finger joint
finger_jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, "finger_joint1")
if finger_jid < 0:
    # 尝试其他名称
    for name in ["finger_joint1", "finger_joint2"]:
        finger_jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
        if finger_jid >= 0:
            break
finger_qposadr = model.jnt_qposadr[finger_jid] if finger_jid >= 0 else None
print(f"Finger joint qpos: {finger_qposadr}")

# ── 提取/设置 arm qpos ──
def get_arm_qpos():
    return np.array([data.qpos[j["qposadr"]] for j in arm_joints])

def set_arm_qpos(angles):
    for i, j in enumerate(arm_joints):
        data.qpos[j["qposadr"]] = angles[i]

def set_gripper(open_val):
    """open_val: 0=闭合, 1=全开"""
    if finger_qposadr is not None:
        data.qpos[finger_qposadr] = open_val * 0.04
        # 对称的另一个手指
        data.qpos[finger_qposadr + 1] = open_val * 0.04

def get_tcp_pos():
    mujoco.mj_forward(model, data)
    return data.site_xpos[tcp_id].copy()

# ── 四元数辅助 ──
def mat_to_quat(mat):
    """3x3 旋转矩阵 → 四元数 [w, x, y, z]"""
    quat = np.zeros(4)
    mujoco.mju_mat2Quat(quat, np.asarray(mat, dtype=np.float64).flatten())
    return quat

# ── DLS IK 求解器（两阶段 + 步长限制）──
def solve_ik(target_pos, target_mat=None, max_iter=500, damping=0.1, tol=1e-4):
    """6-DOF 阻尼最小二乘法 IK，两阶段求解

    阶段1: 纯位置 IK (3-DOF) 将 TCP 移动到目标附近（≤2cm）
    阶段2: 6-DOF IK 同时修正位置和朝向

    使用四元数法（mju_subQuat）计算朝向误差，正确处理 180° 旋转奇异。
    添加步长限制（max_step=0.15 rad）防止振荡。
    """
    target_quat = mat_to_quat(target_mat) if target_mat is not None else None
    max_step = 0.15  # 单次迭代最大关节角变化（弧度）

    def clip_dq(dq):
        """限制步长防止振荡"""
        n = np.linalg.norm(dq)
        if n > max_step:
            return dq * (max_step / n)
        return dq

    def apply_dq(dq):
        current = get_arm_qpos()
        new = current + dq
        for i, j in enumerate(arm_joints):
            lo, hi = j["range"]
            new[i] = np.clip(new[i], lo, hi)
        set_arm_qpos(new)

    def compute_jac():
        jacp = np.zeros((3, model.nv))
        jacr = np.zeros((3, model.nv))
        mujoco.mj_jacSite(model, data, jacp, jacr, tcp_id)
        arm_dofs = [j["dofadr"] for j in arm_joints]
        return jacp[:, arm_dofs], jacr[:, arm_dofs]

    # ── 阶段 1: 纯位置 IK（3-DOF）──
    phase1_iters = max_iter // 3 if target_quat is not None else max_iter
    for iteration in range(phase1_iters):
        mujoco.mj_forward(model, data)
        tcp_pos = data.site_xpos[tcp_id].copy()
        pos_error = target_pos - tcp_pos
        pos_norm = np.linalg.norm(pos_error)

        if pos_norm < 0.02:
            break

        J_pos, _ = compute_jac()
        JJT = J_pos @ J_pos.T + (damping ** 2) * np.eye(3)
        dq = J_pos.T @ np.linalg.solve(JJT, pos_error)
        apply_dq(clip_dq(dq))

    # ── 阶段 2: 6-DOF IK（位置 + 朝向）──
    if target_quat is not None:
        remaining = max_iter - phase1_iters
        for iteration in range(remaining):
            mujoco.mj_forward(model, data)
            tcp_pos = data.site_xpos[tcp_id].copy()
            pos_error = target_pos - tcp_pos
            pos_norm = np.linalg.norm(pos_error)

            # 朝向误差（四元数法）
            ori_error = np.zeros(3)
            cur_mat = data.site_xmat[tcp_id * 9:tcp_id * 9 + 9].copy().reshape(3, 3)
            cur_quat = mat_to_quat(cur_mat)
            mujoco.mju_subQuat(ori_error, target_quat, cur_quat)
            ori_norm = np.linalg.norm(ori_error)

            if pos_norm < tol and ori_norm < tol:
                print(f"    IK 收敛: pos={pos_norm:.6f}, ori={ori_norm:.6f}")
                return get_arm_qpos()

            J_pos, J_rot = compute_jac()
            # 朝向误差大时增加朝向权重
            w_ori = 1.0 if ori_norm < 0.5 else 2.0
            J = np.vstack([J_pos, w_ori * J_rot])
            error = np.concatenate([pos_error, w_ori * ori_error])

            JJT = J @ J.T + (damping ** 2) * np.eye(6)
            dq = J.T @ np.linalg.solve(JJT, error)
            apply_dq(clip_dq(dq))

    # ── 最终状态 ──
    mujoco.mj_forward(model, data)
    tcp_pos = data.site_xpos[tcp_id].copy()
    pos_norm = np.linalg.norm(target_pos - tcp_pos)
    ori_norm = 0.0
    if target_quat is not None:
        ori_error = np.zeros(3)
        cur_mat = data.site_xmat[tcp_id * 9:tcp_id * 9 + 9].copy().reshape(3, 3)
        cur_quat = mat_to_quat(cur_mat)
        mujoco.mju_subQuat(ori_error, target_quat, cur_quat)
        ori_norm = np.linalg.norm(ori_error)

    if pos_norm < tol and (target_quat is None or ori_norm < tol):
        print(f"    IK 收敛: pos={pos_norm:.6f}, ori={ori_norm:.6f}")
    else:
        print(f"    IK 未收敛: {max_iter} 次, pos={pos_norm:.6f}, ori={ori_norm:.6f}")
    return get_arm_qpos()

def verify_tcp(label=""):
    """验证 TCP 朝向：Z 轴应指向下方（z < 0）"""
    mujoco.mj_forward(model, data)
    mat = data.site_xmat[tcp_id * 9: tcp_id * 9 + 9].reshape(3, 3)
    z_axis = mat[:, 2]
    pos = data.site_xpos[tcp_id].copy()
    status = "✓" if z_axis[2] < -0.5 else "✗ 朝上!"
    print(f"    [验证{label}] TCP pos=[{pos[0]:.3f},{pos[1]:.3f},{pos[2]:.3f}] Z轴=[{z_axis[0]:.3f},{z_axis[1]:.3f},{z_axis[2]:.3f}] {status}")
    return z_axis[2] < -0.5


# ── 轨迹生成 ──
def ease_in_out(t):
    return 0.5 * (1 - math.cos(math.pi * t))

def generate_trajectory(keyframes, frames=60):
    """关节空间关键帧插值（用于推球等非抓取任务）"""
    traj = []
    for i in range(frames):
        t = i / (frames - 1)
        for j in range(len(keyframes) - 1):
            t0, a0 = keyframes[j]
            t1, a1 = keyframes[j + 1]
            if t0 <= t <= t1:
                lt = (t - t0) / (t1 - t0) if t1 > t0 else 0
                eased = ease_in_out(lt)
                frame = [a0[k] + (a1[k] - a0[k]) * eased for k in range(len(a0))]
                traj.append([round(v, 4) for v in frame])
                break
        else:
            traj.append([round(v, 4) for v in keyframes[-1][1]])
    return traj

def cartesian_segment(start_pos, end_pos, target_mat, n_frames, gripper, label=""):
    """笛卡尔空间直线插值：逐帧 IK 求解，TCP 沿直线移动"""
    segment = []
    for i in range(n_frames):
        t = ease_in_out(i / max(n_frames - 1, 1))
        pos = [start_pos[k] + (end_pos[k] - start_pos[k]) * t for k in range(3)]
        solve_ik(pos, target_mat)
        q = [round(v, 4) for v in list(get_arm_qpos()) + [gripper]]
        segment.append(q)
    # 验证首末帧朝向
    if label:
        set_arm_qpos(segment[0][:7])
        verify_tcp(f"{label}_cart_start")
        set_arm_qpos(segment[-1][:7])
        verify_tcp(f"{label}_cart_end")
    return segment

def joint_segment(start_q, end_q, n_frames, gripper):
    """关节空间插值"""
    segment = []
    for i in range(n_frames):
        t = ease_in_out(i / max(n_frames - 1, 1))
        q = [round(start_q[k] + (end_q[k] - start_q[k]) * t, 4) for k in range(len(start_q))] + [gripper]
        segment.append(q)
    return segment

def hold_segment(qpos, n_frames, gripper):
    """保持当前位姿"""
    return [[round(v, 4) for v in list(qpos) + [gripper]]] * n_frames

def save_segments(task_id, instruction, segments):
    """从分段拼接轨迹"""
    traj = []
    for seg in segments:
        traj.extend(seg)
    while len(traj) < FRAMES:
        traj.append(traj[-1])
    traj = traj[:FRAMES]
    payload = {"i": instruction, "ja": traj, "d": DURATION, "fc": len(traj)}
    path = os.path.join(OUT_DIR, f"{task_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"  {task_id}: {len(traj)} 帧 → {path}")

def save_task(task_id, instruction, keyframes):
    """关节空间关键帧插值（推球任务）"""
    traj = generate_trajectory(keyframes, FRAMES)
    payload = {"i": instruction, "ja": traj, "d": DURATION, "fc": len(traj)}
    path = os.path.join(OUT_DIR, f"{task_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"  {task_id}: {len(traj)} 帧 → {path}")


# ── 计算各任务的 IK 关键帧 ──
FRAMES = 60
DURATION = 2.0

# 先设为 home 位姿，计算 TCP 位置
# 从 panda.xml keyframe 读取 home
mujoco.mj_resetDataKeyframe(model, data, 0)  # keyframe 0 = home
mujoco.mj_forward(model, data)
home_qpos = get_arm_qpos()
home_tcp = get_tcp_pos()
home_tcp_mat = data.site_xmat[tcp_id * 9:tcp_id * 9 + 9].copy().reshape(3, 3)
print(f"\nHome TCP 位置: [{home_tcp[0]:.3f}, {home_tcp[1]:.3f}, {home_tcp[2]:.3f}]")
print(f"Home arm qpos: {home_qpos}")

# 场景中物体位置
BALL_POS = [0.5, 0.0, 0.04]      # 小球
CUBE_POS = [0.5, 0.3, 0.025]     # 立方体中心
SHELF_SURFACE = [0.0, 0.5, 0.405]  # 货架顶面（shelf_top z=0.4 + half 0.0025 + margin）
GRASP_ABOVE_Z = 0.15              # 接近高度（物体上方）

# 预计算各目标的 IK（6-DOF：位置 + 朝向，朝向=home 向下）
print("\n计算 IK 关键帧（6-DOF）...")
MAT = home_tcp_mat  # 目标朝向 = home 朝向（夹爪向下）
print(f"  MAT (target orientation) Z-axis: [{MAT[0,2]:.4f}, {MAT[1,2]:.4f}, {MAT[2,2]:.4f}]")
print(f"  Home TCP Z should be [0, 0, -1] for gripper pointing down")
if MAT[2, 2] > 0:
    print(f"  *** WARNING: target MAT has Z pointing UP! This is the bug! ***")
    # 翻转：使用 -Z 作为目标（夹爪朝下）
    MAT = home_tcp_mat.copy()
    MAT[:, 2] = -MAT[:, 2]  # 翻转 Z 轴
    print(f"  Corrected MAT Z-axis: [{MAT[0,2]:.4f}, {MAT[1,2]:.4f}, {MAT[2,2]:.4f}]")

# 小球（推球只需位置控制，不约束朝向）
print("  小球上方:")
set_arm_qpos(home_qpos)
ik_ball_above = solve_ik([BALL_POS[0], BALL_POS[1], GRASP_ABOVE_Z])

print("  接触小球:")
set_arm_qpos(ik_ball_above)
ik_ball_touch = solve_ik(BALL_POS)

print("  推球向左终点:")
set_arm_qpos(ik_ball_touch)
ik_push_left = solve_ik([BALL_POS[0] - 0.15, BALL_POS[1] - 0.2, BALL_POS[2]])

print("  推球向右终点:")
set_arm_qpos(ik_ball_touch)
ik_push_right = solve_ik([BALL_POS[0] - 0.15, BALL_POS[1] + 0.2, BALL_POS[2]])

print("  推球向前终点:")
set_arm_qpos(ik_ball_touch)
ik_push_forward = solve_ik([BALL_POS[0] + 0.2, BALL_POS[1], BALL_POS[2]])

# 立方体
print("  立方体上方（预抓取）:")
set_arm_qpos(home_qpos)
ik_cube_above = solve_ik([CUBE_POS[0], CUBE_POS[1], GRASP_ABOVE_Z], MAT)
verify_tcp("cube_above")

print("  接触立方体（抓取）:")
set_arm_qpos(ik_cube_above)
ik_cube_touch = solve_ik(CUBE_POS, MAT)
verify_tcp("cube_touch")

print("  抬起立方体:")
set_arm_qpos(ik_cube_touch)
ik_cube_lift = solve_ik([CUBE_POS[0], CUBE_POS[1], 0.3], MAT)
verify_tcp("cube_lift")

# 货架
print("  货架上方（预放置）:")
set_arm_qpos(ik_cube_lift)
ik_shelf_above = solve_ik([SHELF_SURFACE[0], SHELF_SURFACE[1], 0.25], MAT)
verify_tcp("shelf_above")

print("  货架表面（放置）:")
set_arm_qpos(ik_shelf_above)
ik_shelf = solve_ik(SHELF_SURFACE, MAT)
verify_tcp("shelf")

# ── 生成任务轨迹 ──
print("\n生成任务轨迹:")
GRIPPER_OPEN = 1.0
GRIPPER_CLOSED = 0.0

home_8 = list(home_qpos) + [GRIPPER_OPEN]

# 任务 1: push ball left
save_task("push_left_001", "push ball left", [
    (0.0, home_8),
    (0.3, list(ik_ball_above) + [GRIPPER_OPEN]),
    (0.5, list(ik_ball_touch) + [GRIPPER_OPEN]),
    (0.8, list(ik_push_left) + [GRIPPER_OPEN]),
    (1.0, home_8),
])

# 任务 2: push ball forward
save_task("push_forward_001", "push ball forward", [
    (0.0, home_8),
    (0.3, list(ik_ball_above) + [GRIPPER_OPEN]),
    (0.5, list(ik_ball_touch) + [GRIPPER_OPEN]),
    (0.8, list(ik_push_forward) + [GRIPPER_OPEN]),
    (1.0, home_8),
])

# 任务 3: pick up the cube（关节空间移动 + 笛卡尔直线接近/撤离）
CUBE_ABOVE = [CUBE_POS[0], CUBE_POS[1], GRASP_ABOVE_Z]
CUBE_LIFT = [CUBE_POS[0], CUBE_POS[1], 0.3]
seg1 = joint_segment(home_qpos, ik_cube_above, 10, GRIPPER_OPEN)
set_arm_qpos(ik_cube_above)
seg2 = cartesian_segment(CUBE_ABOVE, CUBE_POS, MAT, 8, GRIPPER_OPEN, "cube_approach")
seg3 = hold_segment(ik_cube_touch, 2, GRIPPER_CLOSED)
set_arm_qpos(ik_cube_touch)
seg4 = cartesian_segment(CUBE_POS, CUBE_LIFT, MAT, 8, GRIPPER_CLOSED, "cube_lift")
seg5 = joint_segment(ik_cube_lift, ik_cube_above, 8, GRIPPER_CLOSED)
seg6 = joint_segment(ik_cube_above, home_qpos, 24, GRIPPER_CLOSED)
save_segments("pick_cube_001", "pick up the cube", [seg1, seg2, seg3, seg4, seg5, seg6])

# 任务 4: place the cube on the shelf（完整抓取+放置流程，笛卡尔直线接近）
SHELF_ABOVE = [SHELF_SURFACE[0], SHELF_SURFACE[1], 0.25]
p1 = joint_segment(home_qpos, ik_cube_above, 6, GRIPPER_OPEN)
set_arm_qpos(ik_cube_above)
p2 = cartesian_segment(CUBE_ABOVE, CUBE_POS, MAT, 6, GRIPPER_OPEN, "place_cube_approach")
p3 = hold_segment(ik_cube_touch, 2, GRIPPER_CLOSED)
set_arm_qpos(ik_cube_touch)
p4 = cartesian_segment(CUBE_POS, CUBE_LIFT, MAT, 6, GRIPPER_CLOSED, "place_cube_lift")
p5 = joint_segment(ik_cube_lift, ik_shelf_above, 8, GRIPPER_CLOSED)
set_arm_qpos(ik_shelf_above)
p6 = cartesian_segment(SHELF_ABOVE, SHELF_SURFACE, MAT, 6, GRIPPER_CLOSED, "shelf_approach")
p7 = hold_segment(ik_shelf, 2, GRIPPER_OPEN)
set_arm_qpos(ik_shelf)
p8 = cartesian_segment(SHELF_SURFACE, SHELF_ABOVE, MAT, 6, GRIPPER_OPEN, "shelf_retract")
p9 = joint_segment(ik_shelf_above, home_qpos, 18, GRIPPER_OPEN)
save_segments("place_shelf_001", "place the cube on the shelf", [p1, p2, p3, p4, p5, p6, p7, p8, p9])

# 任务 5: push ball right
save_task("push_right_001", "push ball right", [
    (0.0, home_8),
    (0.3, list(ik_ball_above) + [GRIPPER_OPEN]),
    (0.5, list(ik_ball_touch) + [GRIPPER_OPEN]),
    (0.8, list(ik_push_right) + [GRIPPER_OPEN]),
    (1.0, home_8),
])

# 更新 task_index.json
task_index = {
    "push ball left": "push_left_001",
    "push ball right": "push_right_001",
    "pick up the cube": "pick_cube_001",
    "place the cube on the shelf": "place_shelf_001",
    "push ball forward": "push_forward_001",
}
with open(os.path.join(OUT_DIR, "task_index.json"), "w", encoding="utf-8") as f:
    json.dump(task_index, f, ensure_ascii=False, separators=(",", ":"))

print(f"\n生成 5 个任务（IK 求解），每个 {FRAMES} 帧，输出到 {OUT_DIR}")
print(f"task_index.json 已更新")
