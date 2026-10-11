import { useRef, useEffect } from "react";
import { useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib";
import * as THREE from "three";
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
  0, 0, 0, -1.5708,
  0, 1.5708, -0.7854, 0.5,
];

/** MuJoCo 场景配置 */
const SCENE_CONFIG: SceneConfig = {
  src: "/data/panda/",
  sceneFile: "scene.xml",
  homeJoints: [0, 0, 0, -1.5708, 0, 1.5708, -0.7854],
};

interface RobotArmProps {
  jointAngles: PandaJointAngles;
  onJointAnglesChange?: (a: PandaJointAngles) => void;
  mode: RobotMode;
  /** 递增信号，变化时触发 MuJoCo 场景重置 */
  resetSignal?: number;
}

/** 加载中指示器 */
function LoadingIndicator() {
  return (
    <mesh position={[0, 0, 0.5]}>
      <boxGeometry args={[0.1, 0.1, 0.1]} />
      <meshStandardMaterial color="#3b82f6" wireframe />
    </mesh>
  );
}

/** 场景内部组件 */
function Scene({ jointAngles, mode, resetSignal }: RobotArmProps) {
  const { camera } = useThree();
  const { isPending, isReady, isError, error, api } = useMujoco();
  const ik = useIkController({ siteName: "tcp", numJoints: 7 });
  const controlsRef = useRef<OrbitControlsImpl>(null);

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

  // 设置相机 up 向量为 Z 轴，匹配 MuJoCo Z-up 坐标系
  useEffect(() => {
    camera.up.set(0, 0, 1);
  }, [camera]);

  // resetSignal 变化时重置 MuJoCo 场景（关节 + 物体位置）
  useEffect(() => {
    if (isReady && api && resetSignal !== undefined && resetSignal > 0) {
      api.reset();
    }
  }, [resetSignal, isReady, api]);

  // WASD/方向键控制视角旋转 + QE 缩放
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      const controls = controlsRef.current;
      if (!controls) return;

      const offset = new THREE.Vector3().subVectors(
        controls.object.position,
        controls.target
      );
      const spherical = new THREE.Spherical().setFromVector3(offset);

      const rotSpeed = 0.05;
      const zoomSpeed = 0.3;

      switch (e.key.toLowerCase()) {
        case "a":
        case "arrowleft":
          spherical.theta -= rotSpeed;
          break;
        case "d":
        case "arrowright":
          spherical.theta += rotSpeed;
          break;
        case "w":
        case "arrowup":
          spherical.phi = Math.max(0.2, spherical.phi - rotSpeed);
          break;
        case "s":
        case "arrowdown":
          spherical.phi = Math.min(Math.PI / 2 - 0.05, spherical.phi + rotSpeed);
          break;
        case "q":
          spherical.radius = Math.max(1.5, spherical.radius - zoomSpeed);
          break;
        case "e":
          spherical.radius = Math.min(8, spherical.radius + zoomSpeed);
          break;
        default:
          return;
      }

      offset.setFromSpherical(spherical);
      controls.object.position.copy(controls.target).add(offset);
      controls.update();
    };

    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, []);

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
        ref={controlsRef}
        enablePan={false}
        minDistance={1.5}
        maxDistance={8}
        minPolarAngle={0.2}
        maxPolarAngle={Math.PI / 2 - 0.05}
        mouseButtons={{
          LEFT: undefined as any, // 左键留给 IK gizmo 拖拽
          MIDDLE: 1,             // 中键缩放
          RIGHT: undefined as any, // 右键禁用（避免浏览器导航）
        }}
      />
    </>
  );
}

/** 机器人机械臂组件（MuJoCo 物理仿真） */
export function RobotArm({ jointAngles, onJointAnglesChange, mode, resetSignal }: RobotArmProps) {
  return (
    <MujocoProvider>
      <MujocoCanvas
        config={SCENE_CONFIG}
        shadows
        camera={{ position: [2.5, 1.0, 1.5], fov: 50 }}
        style={{ width: "100%", height: "100%" }}
      >
        <Scene
          jointAngles={jointAngles}
          onJointAnglesChange={onJointAnglesChange}
          mode={mode}
          resetSignal={resetSignal}
        />
      </MujocoCanvas>
    </MujocoProvider>
  );
}
