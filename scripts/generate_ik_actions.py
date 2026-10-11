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

# ── 轨迹参数 ──
FRAMES = 60            # 默认帧数（推球等平滑任务）
DURATION = 2.0         # 名义时长（秒），仅写入 JSON 元数据
FRAME_DT = 0.03        # 服务端实际帧间隔（见 src/ws_stream.py 的 _FRAME_INTERVAL）
MAX_JOINT_VEL = 3.0    # 单关节角速度上限（rad/s）
# 实测依据：push_left 峰值 3.1 rad/s 时跟踪误差仅约 0.10 rad（成功）；
# pick_cube 峰值 23.3 rad/s 时执行器物理上无法跟随（失败）。
# 参见 .trae/documents/telemetry-analysis.md
FRAMES_MAX = 200       # 单任务帧数上限（远低于规范允许的 500）

# IK 求解器**单次迭代**的步长上限（rad）。这是数值求解的稳健性参数，
# 与"每帧允许移动多少"（MAX_JOINT_VEL × FRAME_DT）是**两回事**：
# 求解器需要足够大的单步才能收敛到目标构型，而帧间位移由 warm_start +
# 逐帧生成顺序保证。早期误把 max_frame_step() 当迭代步长用，
# 结果求解器收敛不了（ori_err≈3.14）。
IK_MAX_ITER_STEP = 0.15


def max_frame_step():
    """单帧允许的最大关节变化量（rad）。"""
    return MAX_JOINT_VEL * FRAME_DT


def frames_for_steps(max_delta, min_frames=4):
    """按速度上限反推需要的帧数。

    ease_in_out 在段内的峰值斜率约为 1.57×平均斜率（π/2），所以按
    max_delta / (n-1) * 1.57 ≤ max_frame_step 求解 n。
    """
    if max_delta <= 0:
        return min_frames
    n = math.ceil(max_delta * 1.57 / max_frame_step()) + 1
    return max(min_frames, n)


def trace_velocity(traj, label=""):
    """逐帧检查关节速度，返回 (峰值|Δ|/帧, 峰值 rad/s, 超限帧列表)。"""
    worst = 0.0
    violations = []
    for i in range(1, len(traj)):
        step = max(abs(traj[i][k] - traj[i - 1][k]) for k in range(min(7, len(traj[i]))))
        if step > worst:
            worst = step
        if step > max_frame_step() + 1e-9:
            violations.append((i, step))
    peak_v = worst / FRAME_DT
    if violations:
        print(f"    [速度校验{(' ' + label) if label else ''}] ✗ 峰值 {peak_v:.1f} rad/s，"
              f"{len(violations)} 帧超限（上限 {MAX_JOINT_VEL} rad/s）")
        for i, step in violations[:6]:
            print(f"        帧 {i}: |Δq|={step:.4f} rad → {step / FRAME_DT:.1f} rad/s")
        if len(violations) > 6:
            print(f"        … 其余 {len(violations) - 6} 帧省略")
    else:
        print(f"    [速度校验{(' ' + label) if label else ''}] ✓ 峰值 {peak_v:.2f} rad/s "
              f"(上限 {MAX_JOINT_VEL})")
    return worst, peak_v, violations


# ── 四元数辅助 ──
def mat_to_quat(mat):
    """3x3 旋转矩阵 → 四元数 [w, x, y, z]"""
    quat = np.zeros(4)
    mujoco.mju_mat2Quat(quat, np.asarray(mat, dtype=np.float64).flatten())
    return quat


# ── 抓取姿态度量 ──
left_finger_bid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "left_finger")
right_finger_bid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "right_finger")


def tool_tilt_deg():
    """TCP 的 Z 轴与"竖直向下"的夹角（度）。0° = 夹爪严格朝下。"""
    mujoco.mj_forward(model, data)
    z = data.site_xmat[tcp_id * 9: tcp_id * 9 + 9].reshape(3, 3)[:, 2]
    return float(np.degrees(np.arccos(np.clip(-z[2], -1.0, 1.0))))


def finger_height_gap_mm():
    """两指的高度差（mm）。差得越多，越夹不住矮物体。"""
    mujoco.mj_forward(model, data)
    if left_finger_bid < 0 or right_finger_bid < 0:
        return -1.0
    return abs(float(data.xpos[left_finger_bid][2] - data.xpos[right_finger_bid][2])) * 1000.0


def report_grasp_quality(traj, label=""):
    """报告抓取帧的夹爪姿态质量 —— 这是"能不能夹住"的硬指标。

    倾斜角 0° 表示夹爪严格竖直。倾斜越大，两指越是一高一低，
    对**矮**物体就越夹不住：倾斜约 32° 时两指高度差约 19mm，
    而原来的 5cm 立方体半高只有 25mm → 两指无法同时贴住侧面。
    """
    close_idx = next((i for i, r in enumerate(traj) if r[7] < 0.5), None)
    if close_idx is None:
        return
    set_arm_qpos(traj[close_idx][:7])
    tilt = tool_tilt_deg()
    gap = finger_height_gap_mm()
    tcp = get_tcp_pos()
    height_mm = 2.0 * CUBE_HALF_Z * 1000.0
    ok = gap >= 0 and gap < height_mm * 0.5
    status = "✓" if ok else "✗ 两指差相对物体过高，可能夹不住"
    print(f"    [抓取质量 {label}] 闭合帧={close_idx} 倾斜={tilt:.1f}° "
          f"两指高度差={gap:.1f}mm（物体高 {height_mm:.0f}mm）"
          f" TCP=({tcp[0]:.3f},{tcp[1]:.3f},{tcp[2]:.3f}) {status}")

# ── DLS IK 求解器（两阶段 + 步长限制 + 逐帧雅可比限幅）──
def solve_ik(target_pos, target_mat=None, max_iter=500, damping=0.1, tol=1e-4,
             warm_start=None):
    """6-DOF 阻尼最小二乘法 IK，两阶段求解

    阶段1: 纯位置 IK (3-DOF) 将 TCP 移动到目标附近（≤2cm）
    阶段2: 6-DOF IK 同时修正位置和朝向

    使用四元数法（mju_subQuat）计算朝向误差，正确处理 180° 旋转奇异。

    **逐帧连续性**（2026-10-11 加入）：
    原先每帧独立求解，DLS 可能落到不同构型分支，导致相邻帧关节角跳变
    （实测 pick_cube 出现 23.3 rad/s 的指令尖峰，超过 Panda 物理饱和速度）。
    现在：
      - warm_start 指定起点，保证从上一帧的解出发；
      - 每次迭代后的关节变化量按 max_frame_step 限幅，使**求解过程中**
        就不可能产生超过单帧允许量的位移。
    """
    target_quat = mat_to_quat(target_mat) if target_mat is not None else None
    max_step = IK_MAX_ITER_STEP

    def clip_dq(dq):
        """限制单次迭代步长：防止振荡，并让 DLS 在构型空间里平滑推进。

        注意这是**迭代**步长（数值稳健性），不是帧间位移上限——
        帧间位移由 cartesian_segment 的 warm_start + 帧数分配来保证。
        """
        n = np.linalg.norm(dq)
        if n > max_step:
            return dq * (max_step / n)
        return dq

    def compute_jac():
        jacp = np.zeros((3, model.nv))
        jacr = np.zeros((3, model.nv))
        mujoco.mj_jacSite(model, data, jacp, jacr, tcp_id)
        arm_dofs = [j["dofadr"] for j in arm_joints]
        return jacp[:, arm_dofs], jacr[:, arm_dofs]

    def tcp_z():
        """当前 TCP 的 Z 轴方向；[0,0,-1] 表示夹爪朝下。"""
        mujoco.mj_forward(model, data)
        return data.site_xmat[tcp_id * 9: tcp_id * 9 + 9].reshape(3, 3)[:, 2].copy()

    def apply_dq(dq):
        current = get_arm_qpos()
        new = current + dq
        for i, j in enumerate(arm_joints):
            lo, hi = j["range"]
            new[i] = np.clip(new[i], lo, hi)
        set_arm_qpos(new)

    def solve_position_from(seed):
        """阶段 1：纯位置 IK（3-DOF），返回 (q, pos_err)。"""
        if seed is not None:
            set_arm_qpos(np.asarray(seed, dtype=np.float64))
        phase1_iters = max_iter // 3 if target_quat is not None else max_iter
        for _ in range(phase1_iters):
            mujoco.mj_forward(model, data)
            pos_error = target_pos - data.site_xpos[tcp_id].copy()
            if np.linalg.norm(pos_error) < 0.02:
                break
            J_pos, _ = compute_jac()
            JJT = J_pos @ J_pos.T + (damping ** 2) * np.eye(3)
            apply_dq(clip_dq(J_pos.T @ np.linalg.solve(JJT, pos_error)))
        mujoco.mj_forward(model, data)
        return get_arm_qpos(), np.linalg.norm(target_pos - data.site_xpos[tcp_id])

    def refine_6dof():
        """阶段 2：在当前构型基础上做 6-DOF（位置 + 朝向）精修。"""
        for _ in range(max_iter):
            mujoco.mj_forward(model, data)
            pos_error = target_pos - data.site_xpos[tcp_id].copy()
            pos_norm = np.linalg.norm(pos_error)

            ori_error = np.zeros(3)
            cur_mat = data.site_xmat[tcp_id * 9: tcp_id * 9 + 9].copy().reshape(3, 3)
            mujoco.mju_subQuat(ori_error, target_quat, mat_to_quat(cur_mat))
            ori_norm = np.linalg.norm(ori_error)

            if pos_norm < tol and ori_norm < tol:
                break

            J_pos, J_rot = compute_jac()
            # 朝向误差大时增加朝向权重
            w_ori = 1.0 if ori_norm < 0.5 else 2.0
            J = np.vstack([J_pos, w_ori * J_rot])
            error = np.concatenate([pos_error, w_ori * ori_error])
            JJT = J @ J.T + (damping ** 2) * np.eye(6)
            apply_dq(clip_dq(J.T @ np.linalg.solve(JJT, error)))
        mujoco.mj_forward(model, data)
        pos_norm = np.linalg.norm(target_pos - data.site_xpos[tcp_id])
        ori_norm = 0.0
        if target_quat is not None:
            ori_error = np.zeros(3)
            cur_mat = data.site_xmat[tcp_id * 9: tcp_id * 9 + 9].copy().reshape(3, 3)
            mujoco.mju_subQuat(ori_error, target_quat, mat_to_quat(cur_mat))
            ori_norm = np.linalg.norm(ori_error)
        return get_arm_qpos(), pos_norm, ori_norm

    def as_arm(seed):
        return np.asarray(seed, dtype=np.float64) if seed is not None else None

    def attempt(seed):
        """位置阶段（+ 需要朝向时再做 6-DOF 精修），返回 (q, pos_err, ori_err)。"""
        arm_seed = as_arm(seed)
        solve_position_from(arm_seed)
        if target_quat is None:
            mujoco.mj_forward(model, data)
            return (get_arm_qpos(),
                    np.linalg.norm(target_pos - data.site_xpos[tcp_id]), 0.0)
        return refine_6dof()

    def attempt_positions(seeds):
        """对每个初值只做位置阶段（3-DOF），返回 [(q, pos_err, tcp_z2), ...]。"""
        out = []
        for seed in seeds:
            if seed is None:
                continue
            solve_position_from(as_arm(seed))
            mujoco.mj_forward(model, data)
            pe = np.linalg.norm(target_pos - data.site_xpos[tcp_id])
            out.append((get_arm_qpos(), float(pe), float(tcp_z()[2])))
        return out

    # ── 关键修复（2026-10-11）：位置-only 优先，6-DOF 只作兜底 ──
    # 位置-only（3-DOF）常常直接给出"位置准 + 夹爪朝下"的解；而 6-DOF 阶段在
    # 朝向误差接近 π 时是不稳定平衡，会把好解推成"夹爪朝上"的坏解。
    # 实测同一目标：位置-only 得 pos=0.0005 / 朝下；走 6-DOF 变成 ori_err=3.11 / 朝上。
    # 初值列表：两个永远可用的 + 已算出的其它关键帧（帮助落在正确分支）。
    seeds = [warm_start, home_qpos]
    for _name in ("ik_ball_touch", "ik_push_forward", "ik_ball_above",
                  "ik_cube_above", "ik_cube_touch", "ik_shelf_above"):
        _v = globals().get(_name)
        if _v is not None:
            seeds.append(_v)

    candidates = attempt_positions(seeds)

    if target_quat is None:
        best = min(candidates, key=lambda c: c[1]) if candidates else (get_arm_qpos(), 9.9, 0.0)
        print(f"    IK 完成(位置-only): pos={best[1]:.6f}")
        return best[0]

    # 1) 优先：位置准 + 夹爪明确朝下
    good = [c for c in candidates if c[2] < -0.5 and c[1] < 0.01]
    if good:
        best = min(good, key=lambda c: c[1])
        print(f"    IK 收敛(位置-only): pos={best[1]:.6f}, tcp_z={best[2]:+.3f}")
        return best[0]

    # 2) 兜底：对位置最好的几个候选取 6-DOF 精修
    fallback = None
    for q_c, _pe, _z in sorted(candidates, key=lambda c: c[1])[:4]:
        q_r, pos_r, ori_r = attempt(q_c)
        if pos_r < 0.01 and tcp_z()[2] < -0.5:
            print(f"    IK 收敛(6-DOF): pos={pos_r:.6f}, ori={ori_r:.6f}")
            return q_r
        if fallback is None or pos_r < fallback[1]:
            fallback = (q_r, pos_r, ori_r)

    err = fallback if fallback else (get_arm_qpos(), 9.9, 9.9)
    raise RuntimeError(
        f"IK 无法得到夹爪朝下的解（{len(candidates)} 个初值 + 6-DOF 兜底）: "
        f"target_pos={np.round(target_pos, 4)}, pos_err={err[1]:.5f}, "
        f"ori_err={err[2]:.5f}, tcp_z={np.round(tcp_z(), 3)}"
    )

    if pos_norm < tol and ori_norm < tol:
        print(f"    IK 收敛: pos={pos_norm:.6f}, ori={ori_norm:.6f}")
    else:
        print(f"    IK 完成: pos={pos_norm:.6f}, ori={ori_norm:.6f}")
    return q

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
    """笛卡尔空间直线插值：逐帧 IK 求解，TCP 沿直线移动。

    **连续性**：第一帧把 TCP 放到 start_pos 并记录得到的关节解，后续帧以
    上一帧的解为 warm_start。这样段内不会跳构型分支。
    """
    segment = []
    prev_q = None
    for i in range(n_frames):
        t = ease_in_out(i / max(n_frames - 1, 1))
        pos = [start_pos[k] + (end_pos[k] - start_pos[k]) * t for k in range(3)]
        q_arm = solve_ik(pos, target_mat, warm_start=prev_q)
        prev_q = q_arm.copy()
        segment.append([round(v, 4) for v in list(q_arm) + [gripper]])
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


def joint_delta(a, b):
    """两个关节构型之间的最大单关节差（rad）。"""
    return max(abs(float(a[k]) - float(b[k])) for k in range(7))


def smooth_velocity(traj, max_passes=12, tol=1e-6):
    """迭代消除残余速度尖峰。

    分段拼接虽然会在大的段边界插入过渡帧，但过渡帧本身可能与相邻段之间
    仍有小幅超限（实测 place_shelf 残留 4 帧 / 峰值 7.0 rad/s）。
    这里对每个超限帧，把它与前后帧各取中点插入，反复迭代直到达标或不再改善。
    """
    limit = max_frame_step()

    for _ in range(max_passes):
        worst = 0.0
        worst_i = -1
        for i in range(1, len(traj)):
            step = max(abs(traj[i][k] - traj[i - 1][k]) for k in range(7))
            if step > worst:
                worst, worst_i = step, i
        if worst <= limit + tol or worst_i < 0:
            return traj, worst

        prev_f = traj[worst_i - 1]
        cur_f = traj[worst_i]
        mid = [round((prev_f[k] + cur_f[k]) / 2, 5) for k in range(8)]
        traj.insert(worst_i, mid)

    return traj, worst

def save_segments(task_id, instruction, segments, bridge_gripper=None):
    """从分段拼接轨迹，并做逐帧速度校验。

    **分段边界连续性**：历史 bug 是各段独立生成——例如 seg1 结束于
    ik_cube_above（关节空间插值），而 seg2 的第一帧是从 CUBE_ABOVE
    重新做 IK 解出来的另一个构型，两者不是同一个关节解，于是产生
    单帧 0.7 rad 的跳变（23.3 rad/s）。这里在拼接时逐段检查，
    一旦边界跳变超限，就自动插入一段关节空间过渡（帧数按速度上限算）。
    """
    traj = []
    for idx, seg in enumerate(segments):
        if not seg:
            continue
        if traj:
            gap = joint_delta(traj[-1], seg[0])
            if gap > max_frame_step() + 1e-9:
                n_bridge = frames_for_steps(gap, min_frames=2)
                bridge_g = bridge_gripper if bridge_gripper is not None else seg[0][7]
                print(f"    [拼接] 段{idx} 边界跳变 {gap:.4f} rad → 插入 {n_bridge} 帧过渡")
                traj.extend(joint_segment(traj[-1][:7], seg[0][:7], n_bridge, bridge_g))
        traj.extend(seg)

    while len(traj) < 4:
        traj.append(traj[-1])

    if len(traj) > FRAMES_MAX:
        print(f"    [警告] {task_id} 共 {len(traj)} 帧，超过 FRAMES_MAX={FRAMES_MAX}")

    # 平滑残余速度尖峰（必要时插帧），再做最终校验
    traj, worst = smooth_velocity(traj)
    print(f"    [平滑] 迭代后最大 |Δq|={worst:.4f} rad "
          f"({worst / FRAME_DT:.2f} rad/s)，共 {len(traj)} 帧")
    trace_velocity(traj, task_id)
    report_grasp_quality(traj, task_id)

    payload = {"i": instruction, "ja": traj, "d": DURATION, "fc": len(traj)}
    path = os.path.join(OUT_DIR, f"{task_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"  {task_id}: {len(traj)} 帧 → {path}")
    return traj

def save_task(task_id, instruction, keyframes, frames=FRAMES):
    """关节空间关键帧插值（推球任务）"""
    traj = generate_trajectory(keyframes, frames)
    traj, worst = smooth_velocity(traj)
    print(f"    [平滑] {task_id} 最大 |Δq|={worst:.4f} rad ({worst / FRAME_DT:.2f} rad/s)")
    trace_velocity(traj, task_id)
    payload = {"i": instruction, "ja": traj, "d": DURATION, "fc": len(traj)}
    path = os.path.join(OUT_DIR, f"{task_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"  {task_id}: {len(traj)} 帧 → {path}")
    return traj


# ── 计算各任务的 IK 关键帧 ──
# （FRAMES / DURATION / FRAME_DT / MAX_JOINT_VEL 等参数定义在文件顶部）

# 先设为 home 位姿，计算 TCP 位置
# 从 panda.xml keyframe 读取 home
mujoco.mj_resetDataKeyframe(model, data, 0)  # keyframe 0 = home
mujoco.mj_forward(model, data)
home_qpos = get_arm_qpos()
home_tcp = get_tcp_pos()
home_tcp_mat = data.site_xmat[tcp_id * 9:tcp_id * 9 + 9].copy().reshape(3, 3)
print(f"\nHome TCP 位置: [{home_tcp[0]:.3f}, {home_tcp[1]:.3f}, {home_tcp[2]:.3f}]")
print(f"Home arm qpos: {home_qpos}")

# 场景中物体位置（抓取/放置几何**直接由 MuJoCo 模型读出**，避免与 scene.xml 不同步）
def _body_free_joint_qpos(body_name):
    """取 free body 的 qpos 起始地址；该 body 必须有 freejoint。"""
    bid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name)
    if bid < 0:
        raise RuntimeError(f"未找到 body: {body_name}")
    jadr = model.body_jntadr[bid]
    if jadr < 0:
        raise RuntimeError(f"body {body_name} 没有关节，无法作为可操作物体")
    return model.jnt_qposadr[jadr]


BALL_QADR = _body_free_joint_qpos("ball")
CUBE_QADR = _body_free_joint_qpos("cube")

BALL_POS = [float(v) for v in model.qpos0[BALL_QADR:BALL_QADR + 3]]
CUBE_CENTER0 = [float(v) for v in model.qpos0[CUBE_QADR:CUBE_QADR + 3]]
_cube_gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "cube_geom")
CUBE_HALF = [float(v) for v in model.geom_size[_cube_gid]]
CUBE_HALF_Z = CUBE_HALF[2]

# 抓取点 = 物体中心（TCP 打到这里）
CUBE_POS = list(CUBE_CENTER0)
# 预抓取高度 = 物体顶部 + 留白
GRASP_ABOVE_Z = CUBE_CENTER0[2] + CUBE_HALF_Z + 0.05
# 抬起高度
CUBE_LIFT_Z = CUBE_CENTER0[2] + 0.25

# 货架顶面（shelf_top 的顶面）
_shelf_gid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, "shelf_top")
SHELF_TOP_Z = float(model.geom_pos[_shelf_gid][2]) + float(model.geom_size[_shelf_gid][2])
# 放置目标：让物体**底面**落在货架顶面上（必须加上物体半高，
# 否则物体中心会停在货架面下方/上方，放不上去）
SHELF_SURFACE = [0.0, 0.5, SHELF_TOP_Z + CUBE_HALF_Z]

print("\n物体几何（读自模型）:")
print(f"  ball 中心={np.round(BALL_POS, 4)}")
print(f"  cube 中心={np.round(CUBE_POS, 4)} 半高={CUBE_HALF_Z:.4f}")
print(f"    抓取点 z={CUBE_POS[2]:.4f}  预抓取 z={GRASP_ABOVE_Z:.4f}  抬起 z={CUBE_LIFT_Z:.4f}")
print(f"    货架顶面 z={SHELF_TOP_Z:.4f}  放置目标(TCP) z={SHELF_SURFACE[2]:.4f}")

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
ik_ball_touch = solve_ik(BALL_POS, warm_start=ik_ball_above)

print("  推球向左终点:")
ik_push_left = solve_ik([BALL_POS[0] - 0.15, BALL_POS[1] - 0.2, BALL_POS[2]],
                        warm_start=ik_ball_touch)

print("  推球向右终点:")
ik_push_right = solve_ik([BALL_POS[0] - 0.15, BALL_POS[1] + 0.2, BALL_POS[2]],
                         warm_start=ik_ball_touch)

print("  推球向前终点:")
ik_push_forward = solve_ik([BALL_POS[0] + 0.2, BALL_POS[1], BALL_POS[2]],
                           warm_start=ik_ball_touch)

# ── 立方体 ──
# 关键：DLS 的 3-DOF 位置阶段只有约 166 次迭代，从 home 出发到不了立方体上方
# （会被夹爪朝向分支带偏，实测 ori_err≈3.14）。
# 原脚本是靠"上一个 solve 残留的机械臂状态"碰巧得到好初值，属于隐式依赖；
# 这里改为**用显式初值**：立方体在球的 +y 侧，用推球终点附近的解当种子，
# 位置阶段只需走很短一段。
ik_cube_above = solve_ik([CUBE_POS[0], CUBE_POS[1], GRASP_ABOVE_Z], MAT,
                         warm_start=ik_push_forward)
verify_tcp("cube_above")

print("  接触立方体（抓取）:")
ik_cube_touch = solve_ik(CUBE_POS, MAT, warm_start=ik_cube_above)
verify_tcp("cube_touch")

print("  抬起立方体:")
ik_cube_lift = solve_ik([CUBE_POS[0], CUBE_POS[1], CUBE_LIFT_Z], MAT, warm_start=ik_cube_touch)
verify_tcp("cube_lift")

# 货架
print("  货架上方（预放置）:")
ik_shelf_above = solve_ik([SHELF_SURFACE[0], SHELF_SURFACE[1], 0.25], MAT,
                          warm_start=ik_cube_lift)
verify_tcp("shelf_above")

print("  货架表面（放置）:")
ik_shelf = solve_ik(SHELF_SURFACE, MAT, warm_start=ik_shelf_above)
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
# 各段帧数按"关节变化量 ÷ 速度上限"自动计算，不再写死 8 帧。
CUBE_ABOVE = [CUBE_POS[0], CUBE_POS[1], GRASP_ABOVE_Z]
CUBE_LIFT = [CUBE_POS[0], CUBE_POS[1], CUBE_LIFT_Z]

n_s1 = frames_for_steps(joint_delta(home_qpos, ik_cube_above))
seg1 = joint_segment(home_qpos, ik_cube_above, n_s1, GRIPPER_OPEN)

n_s2 = frames_for_steps(joint_delta(ik_cube_above, ik_cube_touch), min_frames=6)
set_arm_qpos(ik_cube_above)
seg2 = cartesian_segment(CUBE_ABOVE, CUBE_POS, MAT, n_s2, GRIPPER_OPEN, "cube_approach")

seg3 = hold_segment(ik_cube_touch, 3, GRIPPER_CLOSED)

n_s4 = frames_for_steps(joint_delta(ik_cube_touch, ik_cube_lift), min_frames=6)
set_arm_qpos(ik_cube_touch)
seg4 = cartesian_segment(CUBE_POS, CUBE_LIFT, MAT, n_s4, GRIPPER_CLOSED, "cube_lift")

n_s5 = frames_for_steps(joint_delta(ik_cube_lift, ik_cube_above))
seg5 = joint_segment(ik_cube_lift, ik_cube_above, n_s5, GRIPPER_CLOSED)

n_s6 = frames_for_steps(joint_delta(ik_cube_above, home_qpos))
seg6 = joint_segment(ik_cube_above, home_qpos, n_s6, GRIPPER_CLOSED)

print(f"  pick_cube 分段帧数: {n_s1}+{n_s2}+3+{n_s4}+{n_s5}+{n_s6}"
      f" = {n_s1 + n_s2 + 3 + n_s4 + n_s5 + n_s6}")
save_segments("pick_cube_001", "pick up the cube", [seg1, seg2, seg3, seg4, seg5, seg6])

# 任务 4: place the cube on the shelf（完整抓取+放置流程，笛卡尔直线接近）
# 注意：本任务在 pick 之后必须把场景恢复到"已知状态"——k1 显式回到 home 位姿，
# 使工作区里的球/方块被复位，否则两次任务之间的场景状态不可控。
SHELF_ABOVE = [SHELF_SURFACE[0], SHELF_SURFACE[1], 0.25]
k1 = joint_segment(home_qpos, ik_cube_above, frames_for_steps(joint_delta(home_qpos, ik_cube_above)), GRIPPER_OPEN)

n_k2 = frames_for_steps(joint_delta(ik_cube_above, ik_cube_touch), min_frames=6)
set_arm_qpos(ik_cube_above)
k2 = cartesian_segment(CUBE_ABOVE, CUBE_POS, MAT, n_k2, GRIPPER_OPEN, "place_cube_approach")

k3 = hold_segment(ik_cube_touch, 3, GRIPPER_CLOSED)

n_k4 = frames_for_steps(joint_delta(ik_cube_touch, ik_cube_lift), min_frames=6)
set_arm_qpos(ik_cube_touch)
k4 = cartesian_segment(CUBE_POS, CUBE_LIFT, MAT, n_k4, GRIPPER_CLOSED, "place_cube_lift")

k5 = joint_segment(ik_cube_lift, ik_shelf_above, frames_for_steps(joint_delta(ik_cube_lift, ik_shelf_above)), GRIPPER_CLOSED)

n_k6 = frames_for_steps(joint_delta(ik_shelf_above, ik_shelf), min_frames=6)
set_arm_qpos(ik_shelf_above)
k6 = cartesian_segment(SHELF_ABOVE, SHELF_SURFACE, MAT, n_k6, GRIPPER_CLOSED, "shelf_approach")

k7 = hold_segment(ik_shelf, 3, GRIPPER_OPEN)

n_k8 = frames_for_steps(joint_delta(ik_shelf, ik_shelf_above), min_frames=6)
set_arm_qpos(ik_shelf)
k8 = cartesian_segment(SHELF_SURFACE, SHELF_ABOVE, MAT, n_k8, GRIPPER_OPEN, "shelf_retract")

k9 = joint_segment(ik_shelf_above, ik_cube_above, frames_for_steps(joint_delta(ik_shelf_above, ik_cube_above)), GRIPPER_OPEN)
k10 = joint_segment(ik_cube_above, home_qpos, frames_for_steps(joint_delta(ik_cube_above, home_qpos)), GRIPPER_OPEN)

print(f"  place_shelf 分段帧数: {len(k1)}+{n_k2}+3+{n_k4}+{len(k5)}+{n_k6}+3+{n_k8}+{len(k9)}+{len(k10)}")
save_segments("place_shelf_001", "place the cube on the shelf",
              [k1, k2, k3, k4, k5, k6, k7, k8, k9, k10])

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
