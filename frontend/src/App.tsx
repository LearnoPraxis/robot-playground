import { useEffect, useState } from "react";
import { RobotArm, HOME_POSE, type PandaJointAngles, type RobotMode } from "./components/RobotArm";
import { ControlPanel } from "./components/ControlPanel";
import { useWebSocket } from "./hooks/useWebSocket";
import SmolVLMTester from "./components/SmolVLMTester";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";
const WS_URL = import.meta.env.VITE_WS_URL ?? "/ws/stream";

type Tab = "robot" | "smolvlm";

export default function App() {
  const [loading, setLoading] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);
  const [jointAngles, setJointAngles] = useState<PandaJointAngles>(HOME_POSE);
  const [displayPlaying, setDisplayPlaying] = useState(true);
  const [mode, setMode] = useState<RobotMode>("interactive");
  const [activeTab, setActiveTab] = useState<Tab>("robot");

  const { state, connect, sendTaskId, reset } = useWebSocket(WS_URL);

  // 仅在播放状态下应用接收到的帧
  useEffect(() => {
    if (state.actions.length > 0 && displayPlaying) {
      const last = state.actions[state.actions.length - 1];
      if (last && last.length >= 8) {
        setJointAngles([...last.slice(0, 8)] as PandaJointAngles);
      }
    }
  }, [state.actions, displayPlaying]);

  // 回放完成后自动切回交互模式
  useEffect(() => {
    if (
      mode === "replay" &&
      state.frameCount > 0 &&
      state.currentFrame >= state.frameCount - 1 &&
      !state.isPlaying
    ) {
      setMode("interactive");
    }
  }, [mode, state.frameCount, state.currentFrame, state.isPlaying]);

  const handleSend = async (instruction: string) => {
    setLoading(true);
    setApiError(null);
    try {
      const res = await fetch(`${API_BASE}/infer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction }),
      });
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const data = await res.json();
      if (data.success && data.task_id) {
        reset();
        setJointAngles(HOME_POSE);
        setMode("replay");
        sendTaskId(data.task_id);
      } else {
        setApiError(data.message ?? "指令未匹配到已知任务");
      }
    } catch (err) {
      setApiError(err instanceof Error ? err.message : "请求失败");
    } finally {
      setLoading(false);
    }
  };

  const handlePlayPause = () => {
    setDisplayPlaying((p) => !p);
  };

  const handleReset = () => {
    reset();
    setJointAngles(HOME_POSE);
    setMode("interactive");
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        background: "#020617",
        color: "#e2e8f0",
        fontFamily: "system-ui, -apple-system, sans-serif",
      }}
    >
      <header
        style={{
          padding: "12px 20px",
          borderBottom: "1px solid #1e293b",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <h1 style={{ margin: 0, fontSize: 18, fontWeight: 600 }}>
          Robot Policy Playground
        </h1>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={() => setActiveTab("robot")}
            style={{
              padding: "6px 14px",
              borderRadius: 4,
              border: "1px solid #334155",
              background: activeTab === "robot" ? "#1e40af" : "transparent",
              color: "#e2e8f0",
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            机械臂演示
          </button>
          <button
            onClick={() => setActiveTab("smolvlm")}
            style={{
              padding: "6px 14px",
              borderRadius: 4,
              border: "1px solid #334155",
              background: activeTab === "smolvlm" ? "#1e40af" : "transparent",
              color: "#e2e8f0",
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            SmolVLM 验证
          </button>
        </div>
      </header>

      {activeTab === "smolvlm" ? (
        <div style={{ flex: 1, overflowY: "auto" }}>
          <SmolVLMTester />
        </div>
      ) : (
      <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
        <div style={{ flex: 1, position: "relative" }}>
          <RobotArm
            jointAngles={jointAngles}
            onJointAnglesChange={setJointAngles}
            mode={mode}
          />
        </div>

        <aside
          style={{
            width: 340,
            borderLeft: "1px solid #1e293b",
            background: "#0f172a",
            overflowY: "auto",
          }}
        >
          <ControlPanel
            onSend={handleSend}
            status={state.status}
            isPlaying={state.isPlaying && displayPlaying}
            frameCount={state.frameCount}
            currentFrame={state.currentFrame}
            error={state.error ?? apiError}
            onPlayPause={handlePlayPause}
            onReset={handleReset}
            loading={loading}
          />
        </aside>
      </div>
      )}

      <footer
        style={{
          padding: "8px 20px",
          borderTop: "1px solid #1e293b",
          fontSize: 12,
          color: "#64748b",
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>
          关节: [{jointAngles[0].toFixed(2)}, {jointAngles[1].toFixed(2)}, {jointAngles[2].toFixed(2)}, {jointAngles[3].toFixed(2)}, {jointAngles[4].toFixed(2)}, {jointAngles[5].toFixed(2)}, {jointAngles[6].toFixed(2)}, 夹爪:{jointAngles[7].toFixed(2)}] | 模式: {mode === "interactive" ? "交互" : "回放"}
        </span>
        <button
          onClick={() => (state.status === "open" ? null : connect())}
          style={{
            background: "none",
            border: "none",
            color: "#3b82f6",
            cursor: "pointer",
            fontSize: 12,
          }}
        >
          {state.status === "open" ? "已连接" : "建立 WebSocket 连接"}
        </button>
      </footer>
    </div>
  );
}
