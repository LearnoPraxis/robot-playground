/**
 * 机械臂动作遥测（telemetry）
 *
 * 目的：把"下发的关节目标"与"仿真里实际发生的关节角度"同时记录下来，
 * 用一个可复制/可下载的 JSON 回答两个问题：
 *
 *   1. 轨迹本身对不对？  —— TCP 有没有走到物体、夹爪闭合时离物体多远
 *   2. 仿真跟不跟得上？  —— 实际关节角与下发目标的误差有多大
 *
 * 这两种问题的修法完全不同（前者改 IK 目标，后者改控制器/帧间隔/物理参数），
 * 而画面肉眼很难区分，所以必须有量化记录。
 *
 * 采样发生在物理引擎内部：`useBeforePhysicsStep` 里记下发目标，
 * `useAfterPhysicsStep` 里记仿真真实状态。因此记录的是**引擎实际执行**的结果，
 * 不是 React 状态里的期望值。
 */

// ---------------------------------------------------------------- 常量

/** 采样间隔（物理步数）。0.002 s × 5 = 10 ms，够密且不至于产生上万帧。 */
const SAMPLE_EVERY_N_STEPS = 5;
/** 最后一条指令之后继续观察多久（秒），用于确认是否稳定。 */
const SETTLE_SECONDS = 1.2;
/** 判定"夹爪已闭合"的阈值：g < 0.5（g=1 全开、g=0 全闭）。 */
const GRIPPER_CLOSED_THRESHOLD = 0.5;
/** 判定"长时间跟踪不上"的目标跟随误差阈值（弧度）。 */
const TRACKING_ERROR_THRESHOLD = 0.15;

const ARM_LABELS = ['j0', 'j1', 'j2', 'j3', 'j4', 'j5', 'j6'] as const;

// ---------------------------------------------------------------- 类型

export interface TelemetryFrame {
  /** 仿真时间（秒） */
  t: number;
  /** 采样序号 */
  i: number;
  /** 该时刻起作用的帧指令（长度 8：7 关节 + 夹爪） */
  cmd: number[];
  /** 实际关节角（rad，来自 data.qpos） */
  arm: number[];
  /** 实际夹爪指节位置（m） */
  grip: [number, number];
  /** 实际夹爪控制量（0..255） */
  gripCmd: number;
  /** TCP 实际世界坐标 */
  tcp: number[];
  /** 自由体世界坐标 */
  bodies: Record<string, number[]>;
  /** 接触点数 */
  ncon: number;
}

export interface JointTracking {
  name: string;
  maxErr: number;
  meanErr: number;
  /** 录制结束时的误差（最能反映"是否稳定"） */
  finalErr: number;
}

export interface TelemetryMetrics {
  /** 仿真时长（秒） */
  duration: number;
  frames: number;
  joints: JointTracking[];
  /** 7 个关节里最大的平均跟踪误差 */
  worstJointMeanErr: number;
  /** 夹爪实际指节位移（m），反映"到底闭没闭" */
  gripperTravel: number;
  /** 夹爪最闭合时的指节位置 */
  gripperMinPos: number;
  /** 每个自由体的位移（原点 → 终点） */
  objectDisplacement: Record<string, number>;
  /**
   * 夹爪闭合时刻（g 首次 < 0.5）TCP 到各自由体的距离。
   * 这是判断"抓取时机对不对"的关键数字。
   */
  tcpToObjectAtClose: Record<string, number>;
  /** 夹爪闭合发生在第几帧；-1 表示整段都没闭合 */
  gripperCloseFrame: number;
}

export interface TelemetryRun {
  schemaVersion: 2;
  startedAt: string;
  finishedAt: string | null;
  instruction: string;
  taskId: string;
  /** 数据来源：ws=实时流回放，local=本地回放，manual=手动 */
  source: 'ws' | 'local' | 'manual';
  metrics: TelemetryMetrics | null;
  frames: TelemetryFrame[];
}

interface MutableRun {
  schemaVersion: 2;
  startedAt: string;
  finishedAt: string | null;
  instruction: string;
  taskId: string;
  source: 'ws' | 'local' | 'manual';
  frames: TelemetryFrame[];
}

// ---------------------------------------------------------------- 内部引用

/** 由 Scene 注入：把 MuJoCo 模型索引解析一次，之后每步只做数组读取。 */
export interface TelemetryBindings {
  timestep: number;
  /** qpos 中 7 个臂关节的地址 */
  armQposAdr: number[];
  /** qpos 中 2 个指节的地址 */
  fingerQposAdr: number[];
  /** actuator8 的 ctrl 下标 */
  gripperCtrlAdr: number;
  /** tcp site 在 data.site_xpos 中的下标 */
  tcpSiteAdr: number;
  /** 自由体名 → 在 data.xpos 中的下标 */
  bodyXposAdr: Record<string, number>;
}

let bindings: TelemetryBindings | null = null;
let current: MutableRun | null = null;
/**
 * 本地回放（localPlayback）期间不采样。
 * 回放只是把已存的帧重放一遍，不产生新的物理执行信息，
 * 混进来会把"首次执行"的指标冲淡。
 */
let localReplayActive = false;
let stepCounter = 0;
let sampleIndex = 0;
/** 最后一次收到帧指令（长度 8）。 */
let lastCmd: number[] | null = null;
/** 结算定时器句柄。 */
let settleTimer: number | null = null;
/** 上一段落盘的结果，供 UI 展示与下载。 */
let lastRun: TelemetryRun | null = null;

const listeners = new Set<() => void>();

/** 版本号自增，配合 useSyncExternalStore 触发重渲染。 */
let revision = 0;

function emit() {
  revision += 1;
  listeners.forEach((fn) => fn());
}

function clearSettleTimer() {
  if (settleTimer !== null) {
    window.clearTimeout(settleTimer);
    settleTimer = null;
  }
}

// ---------------------------------------------------------------- 公开 API

export function telemetryBindings(b: TelemetryBindings | null) {
  bindings = b;
}

export function subscribeTelemetry(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function telemetryRevision(): number {
  return revision;
}

export function isRecording(): boolean {
  return current !== null;
}

export function getLiveRun(): MutableRun | null {
  return current;
}

export function getLastRun(): TelemetryRun | null {
  return lastRun;
}

/** 由 Scene 在每次收到 WS 帧、写入 actuator 之前调用。 */
export function noteCommand(cmd: number[]) {
  lastCmd = cmd.slice(0, 8);
}

/** App 在本地回放开关变化时调用，用于把回放帧排除在采样之外。 */
export function setLocalReplayActive(active: boolean) {
  localReplayActive = active;
}

/** 开始录制。instruction/taskId 仅作为标签写入结果。 */
export function beginTelemetry(opts: {
  instruction: string;
  taskId: string;
  source: 'ws' | 'local' | 'manual';
}) {
  clearSettleTimer();
  current = {
    schemaVersion: 2,
    startedAt: new Date().toISOString(),
    finishedAt: null,
    instruction: opts.instruction,
    taskId: opts.taskId,
    source: opts.source,
    frames: [],
  };
  stepCounter = 0;
  sampleIndex = 0;
  lastCmd = null;
  emit();
}

/**
 * 停止录制：再观察 SETTLE_SECONDS，然后结算指标并落盘。
 * 观察期用于回答"指令停发之后，仿真是否还在动/是否稳定"。
 */
export function endTelemetry() {
  if (!current) return;
  clearSettleTimer();
  settleTimer = window.setTimeout(() => {
    settleTimer = null;
    finish();
  }, SETTLE_SECONDS * 1000);
  emit();
}

/** 立即结算（不等观察期）。 */
export function finishTelemetryNow() {
  if (!current) return;
  clearSettleTimer();
  finish();
}

function finish() {
  if (!current) return;
  const run: TelemetryRun = {
    ...current,
    finishedAt: new Date().toISOString(),
    metrics: computeMetrics(current.frames),
  };
  lastRun = run;
  current = null;
  emit();
}

/** 由 Scene 在物理步进前后调用。 */
export function recordPhysicsStep(data: {
  time: number;
  qpos: ArrayLike<number>;
  ctrl: ArrayLike<number>;
  siteXpos: ArrayLike<number>;
  xpos: ArrayLike<number>;
  ncon: number;
  timestep: number;
}) {
  if (!current || !bindings) return;
  if (localReplayActive) return;
  stepCounter += 1;
  if (stepCounter % SAMPLE_EVERY_N_STEPS !== 0) return;

  const b = bindings;
  const arm = b.armQposAdr.map((adr) => round(data.qpos[adr], 4));
  const grip: [number, number] = [
    round(data.qpos[b.fingerQposAdr[0]], 5),
    round(data.qpos[b.fingerQposAdr[1]], 5),
  ];
  const bodies: Record<string, number[]> = {};
  for (const [name, adr] of Object.entries(b.bodyXposAdr)) {
    bodies[name] = [
      round(data.xpos[adr * 3], 4),
      round(data.xpos[adr * 3 + 1], 4),
      round(data.xpos[adr * 3 + 2], 4),
    ];
  }

  current.frames.push({
    t: round(data.time, 4),
    i: sampleIndex++,
    cmd: (lastCmd ?? []).slice(),
    arm,
    grip,
    gripCmd: round(data.ctrl[b.gripperCtrlAdr], 1),
    tcp: [
      round(data.siteXpos[b.tcpSiteAdr * 3], 4),
      round(data.siteXpos[b.tcpSiteAdr * 3 + 1], 4),
      round(data.siteXpos[b.tcpSiteAdr * 3 + 2], 4),
    ],
    bodies,
    ncon: data.ncon,
  });

  // 上限保护：长时间录制不至于撑爆内存
  if (current.frames.length > 20000) {
    clearSettleTimer();
    finish();
  }
}

export function resetTelemetry() {
  clearSettleTimer();
  current = null;
  lastRun = null;
  lastCmd = null;
  emit();
}

/** 导出为可下载的 JSON 字符串。 */
export function serializeRun(run: TelemetryRun): string {
  return JSON.stringify(run, null, 2);
}

// ---------------------------------------------------------------- 指标计算

function round(v: number, digits: number): number {
  const f = 10 ** digits;
  return Math.round(v * f) / f;
}

function dist(a: number[], b: number[]): number {
  return Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
}

function computeMetrics(frames: TelemetryFrame[]): TelemetryMetrics | null {
  if (frames.length === 0) return null;

  const withCmd = frames.filter((f) => f.cmd.length >= 8);
  const first = frames[0];
  const last = frames[frames.length - 1];

  // --- 关节跟踪误差：实际 qpos 与下发帧指令之差 ---
  const joints: JointTracking[] = ARM_LABELS.map((name, j) => {
    let maxErr = 0;
    let sum = 0;
    let n = 0;
    let finalErr = 0;
    for (const f of withCmd) {
      if (f.arm[j] === undefined) continue;
      const e = Math.abs(f.arm[j] - f.cmd[j]);
      if (e > maxErr) maxErr = e;
      sum += e;
      n += 1;
      finalErr = e;
    }
    return {
      name,
      maxErr: round(maxErr, 4),
      meanErr: round(n > 0 ? sum / n : 0, 4),
      finalErr: round(finalErr, 4),
    };
  });

  // --- 夹爪：实际指节行程 ---
  const gripVals = frames.map((f) => f.grip[0]);
  const gripperTravel = round(Math.max(...gripVals) - Math.min(...gripVals), 5);
  const gripperMinPos = round(Math.min(...gripVals), 5);

  // --- 物体位移 ---
  const objectDisplacement: Record<string, number> = {};
  for (const name of Object.keys(first.bodies)) {
    if (last.bodies[name]) {
      objectDisplacement[name] = round(dist(first.bodies[name], last.bodies[name]), 4);
    }
  }

  // --- 夹爪闭合时刻，TCP 到各物体的距离 ---
  const closeIdx = frames.findIndex((f) => f.cmd.length >= 8 && f.cmd[7] < GRIPPER_CLOSED_THRESHOLD);
  const tcpToObjectAtClose: Record<string, number> = {};
  if (closeIdx >= 0) {
    const f = frames[closeIdx];
    for (const [name, pos] of Object.entries(f.bodies)) {
      tcpToObjectAtClose[name] = round(dist(f.tcp, pos), 4);
    }
  }

  return {
    duration: round(last.t - first.t, 3),
    frames: frames.length,
    joints,
    worstJointMeanErr: round(Math.max(...joints.map((j) => j.meanErr)), 4),
    gripperTravel,
    gripperMinPos,
    objectDisplacement,
    tcpToObjectAtClose,
    gripperCloseFrame: closeIdx,
  };
}

/**
 * 人类可读的结论。用文字代替"看图"，便于把结果复制给他人/工具判断。
 * 注意：这些是启发式判据，用于提示可疑点，不是最终结论。
 */
export function describeRun(run: TelemetryRun): string[] {
  const out: string[] = [];
  const m = run.metrics;
  if (!m) return ['没有采集到任何物理帧。'];

  out.push(`采集 ${m.frames} 帧 / ${m.duration}s（来源 ${run.source}，任务 ${run.taskId || 'n/a'}）`);

  const worst = m.joints.reduce((a, b) => (b.meanErr > a.meanErr ? b : a), m.joints[0]);
  out.push(
    `关节跟踪误差：最大平均 ${worst.meanErr} rad（${worst.name}），` +
      `全程最大 ${Math.max(...m.joints.map((j) => j.maxErr))} rad`,
  );

  if (m.gripperCloseFrame < 0) {
    out.push('夹爪：整段轨迹里从未闭合（cmd[7] 一直 ≥ 0.5）——抓取类任务可能根本没进入抓取阶段');
  } else {
    out.push(
      `夹爪：第 ${m.gripperCloseFrame} 帧开始闭合，实际指节行程 ${m.gripperTravel} m` +
        `（闭合位置 ${m.gripperMinPos} m）`,
    );
  }

  for (const [name, d] of Object.entries(m.objectDisplacement)) {
    if (name === 'shelf') continue;
    out.push(`物体 ${name}：位移 ${d} m`);
  }

  if (m.gripperCloseFrame >= 0) {
    for (const [name, d] of Object.entries(m.tcpToObjectAtClose)) {
      if (name === 'shelf') continue;
      out.push(`夹爪闭合瞬间 TCP → ${name} 距离 ${d} m`);
    }
  }

  // --- 启发式判据 ---
  if (m.worstJointMeanErr > TRACKING_ERROR_THRESHOLD) {
    out.push(
      `⚠ 关节平均跟踪误差偏大（>${TRACKING_ERROR_THRESHOLD} rad）：` +
        '更可能是下发节奏/控制器跟不上，而不是轨迹算错（考虑拉长帧间隔或降低速度）。',
    );
  }
  const grabbed = Object.entries(m.objectDisplacement).find(
    ([name, d]) => name !== 'shelf' && d > 0.02,
  );
  if (m.gripperCloseFrame >= 0 && !grabbed) {
    out.push(
      '⚠ 夹爪闭合了，但没有任何物体位移 >2cm：' +
        '抓取没成立。此时若"闭合瞬间 TCP→物体距离"明显大于夹爪尺寸，问题在 IK 目标位置；若距离很小，问题在摩擦力/夹持力。',
    );
  }
  return out;
}
