import { useSyncExternalStore } from "react";
import {
  getLastRun,
  isRecording,
  subscribeTelemetry,
  telemetryRevision,
  type TelemetryRun,
} from "./telemetry";

export interface TelemetrySnapshot {
  recording: boolean;
  lastRun: TelemetryRun | null;
  revision: number;
}

/**
 * 订阅遥测状态。录制过程中每秒最多触发几次重渲染（只在开始/结束时刷新），
 * 物理步进的逐帧数据不经过 React，避免拖慢仿真。
 */
export function useTelemetry(): TelemetrySnapshot {
  const revision = useSyncExternalStore(subscribeTelemetry, telemetryRevision, telemetryRevision);
  return { recording: isRecording(), lastRun: getLastRun(), revision };
}
