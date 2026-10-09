import { useCallback, useEffect, useRef, useState } from "react";

export type ConnectionStatus =
  | "idle"
  | "connecting"
  | "open"
  | "reconnecting"
  | "closed"
  | "error";

export interface StreamState {
  status: ConnectionStatus;
  actions: number[][];
  frameCount: number;
  currentFrame: number;
  error: string | null;
  isPlaying: boolean;
}

const HEARTBEAT_INTERVAL = 30_000; // 每 30 秒发送一次 ping 以保持 WS 连接
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;

function resolveWsUrl(relativeUrl: string): string {
  // 生产环境下由 Worker 提供页面服务，因此使用同源地址。
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${relativeUrl}`;
}

export function useWebSocket(wsRelativeUrl = "/ws/stream") {
  const wsRef = useRef<WebSocket | null>(null);
  const heartbeatRef = useRef<number | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectAttempts = useRef(0);
  const pendingTaskId = useRef<string | null>(null);
  const manuallyClosed = useRef(false);

  const [state, setState] = useState<StreamState>({
    status: "idle",
    actions: [],
    frameCount: 0,
    currentFrame: -1,
    error: null,
    isPlaying: false,
  });

  const clearHeartbeat = () => {
    if (heartbeatRef.current !== null) {
      window.clearInterval(heartbeatRef.current);
      heartbeatRef.current = null;
    }
  };

  const clearReconnect = () => {
    if (reconnectTimerRef.current !== null) {
      window.clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  };

  const startHeartbeat = useCallback(() => {
    clearHeartbeat();
    heartbeatRef.current = window.setInterval(() => {
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "ping" }));
      }
    }, HEARTBEAT_INTERVAL);
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      return;
    }
    manuallyClosed.current = false;
    setState((s) => ({ ...s, status: "connecting", error: null }));

    const url = resolveWsUrl(wsRelativeUrl);
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      reconnectAttempts.current = 0;
      setState((s) => ({ ...s, status: "open" }));
      startHeartbeat();
      if (pendingTaskId.current) {
        ws.send(JSON.stringify({ task_id: pendingTaskId.current }));
      }
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data as string);
        switch (msg.type) {
          case "start":
            setState((s) => ({
              ...s,
              actions: [],
              frameCount: msg.fc ?? 0,
              currentFrame: -1,
              isPlaying: true,
            }));
            break;
          case "frame":
            setState((s) => ({
              ...s,
              actions: [...s.actions, msg.ja as number[]],
              currentFrame: msg.i as number,
            }));
            break;
          case "done":
            setState((s) => ({ ...s, isPlaying: false }));
            break;
          case "error":
            setState((s) => ({
              ...s,
              error: msg.message ?? "Stream error",
              isPlaying: false,
            }));
            break;
          default:
            break;
        }
      } catch {
        // 忽略非 JSON 帧（例如心跳响应）
      }
    };

    ws.onerror = () => {
      setState((s) => ({ ...s, status: "error", error: "WebSocket error" }));
    };

    ws.onclose = () => {
      clearHeartbeat();
      if (manuallyClosed.current) {
        setState((s) => ({ ...s, status: "closed", isPlaying: false }));
        return;
      }
      // 使用指数退避策略进行重连
      const delay = Math.min(
        RECONNECT_BASE_MS * 2 ** reconnectAttempts.current,
        RECONNECT_MAX_MS,
      );
      reconnectAttempts.current += 1;
      setState((s) => ({ ...s, status: "reconnecting", isPlaying: false }));
      clearReconnect();
      reconnectTimerRef.current = window.setTimeout(() => {
        connect();
      }, delay);
    };
  }, [wsRelativeUrl, startHeartbeat]);

  const disconnect = useCallback(() => {
    manuallyClosed.current = true;
    clearReconnect();
    clearHeartbeat();
    wsRef.current?.close();
    wsRef.current = null;
  }, []);

  const sendTaskId = useCallback(
    (taskId: string) => {
      pendingTaskId.current = taskId;
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ task_id: taskId }));
      } else {
        connect();
      }
    },
    [connect],
  );

  const reset = useCallback(() => {
    setState((s) => ({
      ...s,
      actions: [],
      frameCount: 0,
      currentFrame: -1,
      isPlaying: false,
    }));
  }, []);

  useEffect(() => {
    return () => {
      manuallyClosed.current = true;
      clearReconnect();
      clearHeartbeat();
      wsRef.current?.close();
    };
  }, []);

  return { state, connect, disconnect, sendTaskId, reset };
}
