import { useRef } from "react";
import { OrbitControls } from "@react-three/drei";
import {
  MujocoProvider,
  MujocoCanvas,
  useMujoco,
  useIkController,
  IkGizmo,
  useCtrl,
  useBeforePhysicsStep,
} from "mujoco-react";
import type { SceneConfig } from "mujoco-react";

/** 8-DOF：7 关节 + 1 夹爪（0=闭合，1=全开） */
export type PandaJointAngles = [
  number, number, number, number,
  number, number, number, number
];

/** 机械臂模式：交互式（IK 拖拽）/ 回放（WebSocket 帧） */
export type RobotMode = "interactive" | "replay";

/** 初始位姿（Franka Panda home） */
export const HOME_POSE: PandaJointAngles = [
  1.707, -1.754, 0.003, -2.702,
  0.003, 0.951, 2.490, 0.5,
];

/** MuJoCo 场景配置 */
const SCENE_CONFIG: SceneConfig = {
  src: "/data/panda/",
  sceneFile: "scene.xml",
  homeJoints: [1.707, -1.754, 0.003, -2.702, 0.003, 0.951, 2.490],
};

interface RobotArmProps {
  jointAngles: PandaJointAngles;
  onJointAnglesChange?: (a: PandaJointAngles) => void;
  mode: RobotMode;
}

/** 加载中指示器 */
function LoadingIndicator() {
  return (
    <mesh position={[0, 0.5, 0]}>
      <boxGeometry args={[0.1, 0.1, 0.1]} />
      <meshStandardMaterial color="#3b82f6" wireframe />
    </mesh>
  );
}

/** 场景内部组件 */
function Scene({ jointAngles, mode }: RobotArmProps) {
  const { isPending, isError, error } = useMujoco();
  const ik = useIkController({ siteName: "tcp", numJoints: 7 });

  // 7 个 arm actuator + 1 个 gripper actuator
  const a1 = useCtrl("actuator1");
  const a2 = useCtrl("actuator2");
  const a3 = useCtrl("actuator3");
  const a4 = useCtrl("actuator4");
  const a5 = useCtrl("actuator5");
  const a6 = useCtrl("actuator6");
  const a7 = useCtrl("actuator7");
  const a8 = useCtrl("actuator8");

  // 保持最新引用，避免 useBeforePhysicsStep 闭包过期
  const anglesRef = useRef(jointAngles);
  anglesRef.current = jointAngles;
  const modeRef = useRef(mode);
  modeRef.current = mode;

  // replay 模式：每帧将关节角度写入 actuator 目标
  useBeforePhysicsStep(() => {
    if (modeRef.current !== "replay") return;
    const [j0, j1, j2, j3, j4, j5, j6, g] = anglesRef.current;
    a1?.write(j0);
    a2?.write(j1);
    a3?.write(j2);
    a4?.write(j3);
    a5?.write(j4);
    a6?.write(j5);
    a7?.write(j6);
    // 夹爪：g ∈ [0,1] → [0,255]
    a8?.write(g * 255);
  });

  if (isPending) return <LoadingIndicator />;
  if (isError) {
    console.error("MuJoCo 加载失败:", error);
    return null;
  }

  return (
    <>
      <ambientLight intensity={0.7} />
      <directionalLight
        position={[3, 5, 3]}
        intensity={1.2}
        castShadow
        shadow-mapSize-width={1024}
        shadow-mapSize-height={1024}
      />
      {mode === "interactive" && ik && <IkGizmo controller={ik} />}
      <OrbitControls
        enablePan={false}
        minDistance={1.5}
        maxDistance={8}
        minPolarAngle={0.2}
        maxPolarAngle={Math.PI / 2 - 0.05}
      />
    </>
  );
}

/** 机器人机械臂组件（MuJoCo 物理仿真） */
export function RobotArm({ jointAngles, onJointAnglesChange, mode }: RobotArmProps) {
  return (
    <MujocoProvider>
      <MujocoCanvas
        config={SCENE_CONFIG}
        shadows
        camera={{ position: [2, 2, 3], fov: 45 }}
        style={{ width: "100%", height: "100%" }}
      >
        <Scene
          jointAngles={jointAngles}
          onJointAnglesChange={onJointAnglesChange}
          mode={mode}
        />
      </MujocoCanvas>
    </MujocoProvider>
  );
}
