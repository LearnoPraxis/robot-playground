#!/usr/bin/env python3
"""诊断 IK 求解结果：验证 TCP 位置和朝向是否正确"""

import numpy as np
import mujoco

MODEL_PATH = "/mnt/e/robot-policy-playground/public/data/panda/scene.xml"

def main():
    model = mujoco.MjModel.from_xml_path(MODEL_PATH)
    data = mujoco.MjData(model)

    # 找到 TCP site
    tcp_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, "tcp")
    print(f"TCP site ID: {tcp_id}")

    # 找到 7 个 arm joints
    arm_joint_ids = []
    arm_joint_names = []
    for i in range(model.njnt):
        name = mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, i)
        if name and name.startswith("joint"):
            arm_joint_ids.append(i)
            arm_joint_names.append(name)
    print(f"Arm joints: {arm_joint_names}")

    # 获取 joint qpos 地址
    arm_qpos_adrs = [model.jnt_qposadr[jid] for jid in arm_joint_ids]
    arm_dof_adrs = [model.jnt_dofadr[jid] for jid in arm_joint_ids]

    def set_arm_qpos(qpos):
        for i, adr in enumerate(arm_qpos_adrs):
            data.qpos[adr] = qpos[i]
        mujoco.mj_forward(model, data)

    def get_arm_qpos():
        return [data.qpos[adr] for adr in arm_qpos_adrs]

    def get_tcp_pos():
        return data.site_xpos[tcp_id].copy()

    def get_tcp_mat():
        return data.site_xmat[tcp_id * 9: tcp_id * 9 + 9].copy().reshape(3, 3)

    def get_tcp_z_axis():
        """TCP site 的 Z 轴在世界坐标中的方向"""
        mat = get_tcp_mat()
        return mat[:, 2]  # 第三列 = Z 轴

    # 1. 检查 home 位姿
    print("\n=== Home 位姿 ===")
    mujoco.mj_resetDataKeyframe(model, data, 0)
    mujoco.mj_forward(model, data)
    home_qpos = get_arm_qpos()
    home_pos = get_tcp_pos()
    home_mat = get_tcp_mat()
    home_z = get_tcp_z_axis()
    print(f"Home qpos: {home_qpos}")
    print(f"Home TCP pos: [{home_pos[0]:.4f}, {home_pos[1]:.4f}, {home_pos[2]:.4f}]")
    print(f"Home TCP Z-axis (world): [{home_z[0]:.4f}, {home_z[1]:.4f}, {home_z[2]:.4f}]")
    if home_z[2] < 0:
        print(f"  -> Z-axis 指向下方 ✓ (z={home_z[2]:.4f})")
    else:
        print(f"  -> Z-axis 指向上方 ✗ (z={home_z[2]:.4f}) — 这就是问题所在！")
    print(f"Home TCP rotation matrix:")
    print(f"  [{home_mat[0,0]:.4f}, {home_mat[0,1]:.4f}, {home_mat[0,2]:.4f}]")
    print(f"  [{home_mat[1,0]:.4f}, {home_mat[1,1]:.4f}, {home_mat[1,2]:.4f}]")
    print(f"  [{home_mat[2,0]:.4f}, {home_mat[2,1]:.4f}, {home_mat[2,2]:.4f}]")

    # 2. IK 求解到方块位置
    CUBE_POS = [0.5, 0.3, 0.025]
    print(f"\n=== IK 到方块位置 {CUBE_POS} ===")

    set_arm_qpos(home_qpos)
    # 先到上方
    above_pos = [CUBE_POS[0], CUBE_POS[1], 0.15]
    target_mat = home_mat.copy()

    # DLS IK 求解
    for iteration in range(200):
        mujoco.mj_forward(model, data)
        tcp_pos = get_tcp_pos()
        tcp_mat = get_tcp_mat()

        pos_error = np.array(CUBE_POS) - tcp_pos
        pos_norm = np.linalg.norm(pos_error)

        R_err = tcp_mat.T @ target_mat
        ori_error = np.array([
            R_err[2, 1] - R_err[1, 2],
            R_err[0, 2] - R_err[2, 0],
            R_err[1, 0] - R_err[0, 1],
        ]) * 0.5
        ori_norm = np.linalg.norm(ori_error)

        if pos_norm < 1e-4 and ori_norm < 1e-4:
            print(f"IK 收敛: {iteration} 次迭代")
            break

        jacp = np.zeros((3, model.nv))
        jacr = np.zeros((3, model.nv))
        mujoco.mj_jacSite(model, data, jacp, jacr, tcp_id)

        J = np.vstack([jacp[:, arm_dof_adrs], jacr[:, arm_dof_adrs]])
        error = np.concatenate([pos_error, ori_error])
        JJT = J @ J.T + 0.01 * np.eye(6)
        dq = J.T @ np.linalg.solve(JJT, error)

        current = np.array(get_arm_qpos())
        new = current + dq
        for i, jid in enumerate(arm_joint_ids):
            jrange = model.jnt_range[jid]
            new[i] = np.clip(new[i], jrange[0], jrange[1])
        set_arm_qpos(new.tolist())
    else:
        print(f"IK 未收敛: pos={pos_norm:.6f}, ori={ori_norm:.6f}")

    # 验证结果
    result_pos = get_tcp_pos()
    result_mat = get_tcp_mat()
    result_z = get_tcp_z_axis()
    result_qpos = get_arm_qpos()

    print(f"\n结果 qpos: [{', '.join(f'{v:.4f}' for v in result_qpos)}]")
    print(f"结果 TCP pos: [{result_pos[0]:.4f}, {result_pos[1]:.4f}, {result_pos[2]:.4f}]")
    print(f"目标 TCP pos: [{CUBE_POS[0]:.4f}, {CUBE_POS[1]:.4f}, {CUBE_POS[2]:.4f}]")
    print(f"位置误差: {np.linalg.norm(np.array(CUBE_POS) - result_pos):.6f}")
    print(f"\n结果 TCP Z-axis (world): [{result_z[0]:.4f}, {result_z[1]:.4f}, {result_z[2]:.4f}]")
    if result_z[2] < 0:
        print(f"  -> Z-axis 指向下方 ✓ (夹爪朝下)")
    else:
        print(f"  -> Z-axis 指向上方 ✗ (夹爪朝上 — 问题！)")

    print(f"\n结果 TCP rotation matrix:")
    print(f"  [{result_mat[0,0]:.4f}, {result_mat[0,1]:.4f}, {result_mat[0,2]:.4f}]")
    print(f"  [{result_mat[1,0]:.4f}, {result_mat[1,1]:.4f}, {result_mat[1,2]:.4f}]")
    print(f"  [{result_mat[2,0]:.4f}, {result_mat[2,1]:.4f}, {result_mat[2,2]:.4f}]")

    # 检查朝向误差
    R_err = result_mat.T @ target_mat
    ori_error = np.array([
        R_err[2, 1] - R_err[1, 2],
        R_err[0, 2] - R_err[2, 0],
        R_err[1, 0] - R_err[0, 1],
    ]) * 0.5
    print(f"\n朝向误差向量: [{ori_error[0]:.6f}, {ori_error[1]:.6f}, {ori_error[2]:.6f}]")
    print(f"朝向误差范数: {np.linalg.norm(ori_error):.6f}")

    # 3. 对比：纯位置 IK（不约束朝向）
    print(f"\n=== 对比：纯位置 IK（3-DOF，不约束朝向）===")
    set_arm_qpos(home_qpos)
    for iteration in range(200):
        mujoco.mj_forward(model, data)
        tcp_pos = get_tcp_pos()
        pos_error = np.array(CUBE_POS) - tcp_pos
        pos_norm = np.linalg.norm(pos_error)
        if pos_norm < 1e-4:
            print(f"位置 IK 收敛: {iteration} 次迭代")
            break
        jacp = np.zeros((3, model.nv))
        mujoco.mj_jacSite(model, data, jacp, None, tcp_id)
        J = jacp[:, arm_dof_adrs]
        JJT = J @ J.T + 0.01 * np.eye(3)
        dq = J.T @ np.linalg.solve(JJT, pos_error)
        current = np.array(get_arm_qpos())
        new = current + dq
        for i, jid in enumerate(arm_joint_ids):
            jrange = model.jnt_range[jid]
            new[i] = np.clip(new[i], jrange[0], jrange[1])
        set_arm_qpos(new.tolist())
    else:
        print(f"位置 IK 未收敛: pos={pos_norm:.6f}")

    result_z_3dof = get_tcp_z_axis()
    print(f"3-DOF IK 结果 TCP Z-axis: [{result_z_3dof[0]:.4f}, {result_z_3dof[1]:.4f}, {result_z_3dof[2]:.4f}]")
    if result_z_3dof[2] < 0:
        print(f"  -> Z-axis 指向下方 ✓")
    else:
        print(f"  -> Z-axis 指向上方 ✗")


if __name__ == "__main__":
    main()
