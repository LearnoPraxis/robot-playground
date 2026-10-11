import {
  beginTelemetry,
  finishTelemetryNow,
  getLastRun,
  isRecording,
  resetTelemetry,
  serializeRun,
  type TelemetryRun,
} from "./telemetry";

/** 手动开始录制（走的是同一条物理采集通路，不依赖指令）。 */
export function startManualTelemetry() {
  if (isRecording()) return;
  beginTelemetry({ instruction: '(manual)', taskId: '', source: 'manual' });
}

/** 手动结束录制并立即结算。 */
export function stopManualTelemetry() {
  finishTelemetryNow();
}

/** 导出最近一次结果为可下载的 JSON 文件。 */
export function downloadRun(run: TelemetryRun) {
  const blob = new Blob([serializeRun(run)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const stamp = (run.finishedAt ?? run.startedAt).replace(/[:.]/g, '-');
  const name = `telemetry-${run.taskId || 'manual'}-${stamp}.json`;
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** 取最近一次结果（供 UI 事件处理器使用）。 */
export function latestRun(): TelemetryRun | null {
  return getLastRun();
}

export { resetTelemetry };
