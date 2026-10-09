import { useState } from "react";
import type { ConnectionStatus } from "../hooks/useWebSocket";

const PRESET_INSTRUCTIONS = [
  "push ball left",
  "push ball right",
  "pick up the cube",
  "place the cube on the shelf",
  "push ball forward",
];

interface ControlPanelProps {
  onSend: (instruction: string) => void;
  status: ConnectionStatus;
  isPlaying: boolean;
  frameCount: number;
  currentFrame: number;
  error: string | null;
  onPlayPause: () => void;
  onReset: () => void;
  loading: boolean;
}

const STATUS_LABEL: Record<ConnectionStatus, string> = {
  idle: "空闲",
  connecting: "连接中…",
  open: "已连接",
  reconnecting: "重连中…",
  closed: "已关闭",
  error: "错误",
};

export function ControlPanel({
  onSend,
  status,
  isPlaying,
  frameCount,
  currentFrame,
  error,
  onPlayPause,
  onReset,
  loading,
}: ControlPanelProps) {
  const [instruction, setInstruction] = useState("");

  const handleSend = () => {
    const text = instruction.trim();
    if (!text) return;
    onSend(text);
  };

  const progress = frameCount > 0 ? Math.round(((currentFrame + 1) / frameCount) * 100) : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: 16 }}>
      <h2 style={{ margin: 0, fontSize: 18 }}>控制面板</h2>

      <div>
        <label style={{ display: "block", marginBottom: 6, fontSize: 13, color: "#94a3b8" }}>
          选择预设指令
        </label>
        <select
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          style={{ width: "100%", padding: 8, borderRadius: 6, border: "1px solid #334155", background: "#1e293b", color: "#e2e8f0" }}
        >
          <option value="">-- 选择 --</option>
          {PRESET_INSTRUCTIONS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label style={{ display: "block", marginBottom: 6, fontSize: 13, color: "#94a3b8" }}>
          或输入自定义指令
        </label>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            type="text"
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSend();
            }}
            placeholder="push ball left"
            style={{ flex: 1, padding: 8, borderRadius: 6, border: "1px solid #334155", background: "#1e293b", color: "#e2e8f0" }}
          />
          <button
            onClick={handleSend}
            disabled={loading || !instruction.trim()}
            style={{
              padding: "8px 16px",
              borderRadius: 6,
              border: "none",
              background: loading ? "#475569" : "#3b82f6",
              color: "white",
              cursor: loading ? "not-allowed" : "pointer",
            }}
          >
            {loading ? "请求中…" : "发送指令"}
          </button>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 13 }}>
        <span style={{ color: "#94a3b8" }}>状态：</span>
        <span
          style={{
            color:
              status === "error"
                ? "#f87171"
                : isPlaying
                  ? "#4ade80"
                  : status === "reconnecting" || status === "connecting"
                    ? "#fbbf24"
                    : "#e2e8f0",
          }}
        >
          {STATUS_LABEL[status]}
          {isPlaying ? " · 播放中" : ""}
        </span>
      </div>

      {error && (
        <div style={{ padding: 8, borderRadius: 6, background: "#450a0a", color: "#fca5a5", fontSize: 13 }}>
          {error}
        </div>
      )}

      {frameCount > 0 && (
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#94a3b8", marginBottom: 4 }}>
            <span>帧进度</span>
            <span>{currentFrame + 1} / {frameCount} ({progress}%)</span>
          </div>
          <div style={{ height: 6, borderRadius: 3, background: "#1e293b", overflow: "hidden" }}>
            <div
              style={{ height: "100%", width: `${progress}%`, background: "#3b82f6", transition: "width 0.1s linear" }}
            />
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: 8 }}>
        <button
          onClick={onPlayPause}
          style={{ flex: 1, padding: 8, borderRadius: 6, border: "1px solid #334155", background: "#1e293b", color: "#e2e8f0", cursor: "pointer" }}
        >
          {isPlaying ? "暂停" : "播放"}
        </button>
        <button
          onClick={onReset}
          style={{ flex: 1, padding: 8, borderRadius: 6, border: "1px solid #334155", background: "#1e293b", color: "#e2e8f0", cursor: "pointer" }}
        >
          重置
        </button>
      </div>
    </div>
  );
}
