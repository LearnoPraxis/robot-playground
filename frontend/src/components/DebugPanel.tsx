import { useState } from "react";
import { useTelemetry } from "../telemetry/useTelemetry";
import { describeRun, serializeRun } from "../telemetry/telemetry";
import {
  downloadRun,
  resetTelemetry,
  startManualTelemetry,
  stopManualTelemetry,
} from "../telemetry/actions";

const mono = { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" } as const;

const btn = {
  padding: "4px 8px",
  borderRadius: 4,
  border: "1px solid #334155",
  background: "#1e293b",
  color: "#e2e8f0",
  cursor: "pointer",
  fontSize: 12,
} as const;

/**
 * 动作遥测面板：把"下发目标 vs 仿真实际"的差异摊开成数字。
 *
 * 录制本身不经过 React（在物理回调里写普通数组），这里只在开始/结束时刷新。
 */
export function DebugPanel() {
  const { recording, lastRun } = useTelemetry();
  const [copied, setCopied] = useState<string | null>(null);

  const summary = lastRun ? describeRun(lastRun) : [];
  const json = lastRun ? serializeRun(lastRun) : "";

  const flash = (what: string) => {
    setCopied(what);
    window.setTimeout(() => setCopied(null), 1600);
  };

  const copy = async (text: string, what: string) => {
    try {
      await navigator.clipboard.writeText(text);
      flash(`${what} 已复制`);
    } catch {
      // 剪贴板不可用（非 https / 无权限）时回退到下载
      if (lastRun) downloadRun(lastRun);
      flash('剪贴板不可用，已改为下载');
    }
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        padding: 12,
        borderTop: "1px solid #1e293b",
        background: "#0b1220",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <strong style={{ fontSize: 13 }}>动作遥测</strong>
        <span style={{ fontSize: 11, color: recording ? "#4ade80" : "#64748b" }}>
          {recording ? "● 录制中" : lastRun ? "已结束" : "空闲"}
        </span>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {recording ? (
          <button style={btn} onClick={stopManualTelemetry}>
            停止并结算
          </button>
        ) : (
          <button style={btn} onClick={startManualTelemetry}>
            手动开始录制
          </button>
        )}
        <button
          style={{ ...btn, opacity: lastRun ? 1 : 0.5 }}
          disabled={!lastRun}
          onClick={() => lastRun && downloadRun(lastRun)}
        >
          下载 JSON
        </button>
        <button
          style={{ ...btn, opacity: lastRun ? 1 : 0.5 }}
          disabled={!lastRun}
          onClick={() => lastRun && copy(summary.join("\n"), "摘要")}
        >
          复制摘要
        </button>
        <button
          style={{ ...btn, opacity: lastRun ? 1 : 0.5 }}
          disabled={!lastRun}
          onClick={() => lastRun && copy(json, "完整 JSON")}
        >
          复制完整 JSON
        </button>
        <button
          style={{ ...btn, opacity: lastRun ? 1 : 0.5 }}
          disabled={!lastRun}
          onClick={() => resetTelemetry()}
        >
          清除
        </button>
      </div>

      {copied && <div style={{ fontSize: 11, color: "#4ade80" }}>{copied}</div>}

      {!lastRun && !recording && (
        <div style={{ fontSize: 11, color: "#64748b", lineHeight: 1.6 }}>
          发送一条指令会自动开始录制，播完后（含 1.2s 观察期）自动结算。
          结果包含逐帧「下发目标 / 实际关节角 / TCP / 物体位置 / 接触数」，
          以及关节跟踪误差与抓取判据。
        </div>
      )}

      {summary.length > 0 && (
        <div
          style={{
            ...mono,
            fontSize: 11,
            lineHeight: 1.7,
            color: "#cbd5e1",
            background: "#020617",
            border: "1px solid #1e293b",
            borderRadius: 4,
            padding: 8,
            whiteSpace: "pre-wrap",
            maxHeight: 260,
            overflowY: "auto",
          }}
        >
          {summary.map((line, i) => (
            <div key={i} style={{ color: line.startsWith("⚠") ? "#fbbf24" : undefined }}>
              {line}
            </div>
          ))}
        </div>
      )}

      {lastRun?.metrics && (
        <div style={{ fontSize: 11, color: "#64748b" }}>
          共 {lastRun.frames.length} 帧原始数据 · 任务 {lastRun.taskId || '(manual)'} ·{" "}
          {lastRun.finishedAt ?? lastRun.startedAt}
        </div>
      )}
    </div>
  );
}
