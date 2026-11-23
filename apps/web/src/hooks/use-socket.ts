"use client";

import * as React from "react";

import {
  parseLiveEvent,
  reconnectDelay,
  type LiveEvent,
  type SocketStatus,
} from "@/lib/live-events";

/**
 * One WebSocket with reconnect and exponential backoff (lib/live-events.ts). The URL
 * carries a session token, so it is built fresh by `resolveUrl` before every attempt (a
 * token minted for an earlier attempt may have expired); `null` means "do not connect".
 *
 * A close code in the 44xx range is the API refusing the credentials (4401), the origin
 * (4403) or the project (4404): retrying will not help, so the hook stops and reports
 * `refused`.
 */
export function useSocket(
  resolveUrl: (() => Promise<string | null>) | null,
  onEvent: (event: LiveEvent) => void,
  onRefused?: (code: number) => void
) {
  const [status, setStatus] = React.useState<SocketStatus>("idle");
  const handler = React.useRef(onEvent);
  const refused = React.useRef(onRefused);
  React.useEffect(() => {
    handler.current = onEvent;
  }, [onEvent]);
  React.useEffect(() => {
    refused.current = onRefused;
  }, [onRefused]);

  React.useEffect(() => {
    if (!resolveUrl || typeof WebSocket === "undefined") {
      setStatus("idle");
      return;
    }
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let stopped = false;
    let socket: WebSocket | null = null;

    const schedule = () => {
      if (stopped) return;
      setStatus("closed");
      timer = setTimeout(() => void connect(), reconnectDelay(attempt++));
    };

    const connect = async () => {
      if (stopped) return;
      setStatus("connecting");
      let url: string | null;
      try {
        url = await resolveUrl();
      } catch {
        schedule();
        return;
      }
      if (stopped) return;
      if (!url) {
        setStatus("refused");
        refused.current?.(4401);
        return;
      }
      let ws: WebSocket;
      try {
        ws = new WebSocket(url);
      } catch {
        schedule();
        return;
      }
      socket = ws;
      ws.onopen = () => {
        attempt = 0;
        setStatus("open");
      };
      ws.onmessage = (msg) => {
        const event = parseLiveEvent(msg.data);
        if (event) handler.current(event);
      };
      ws.onclose = (ev) => {
        socket = null;
        if (stopped) return;
        if (ev.code >= 4400 && ev.code < 4500) {
          setStatus("refused");
          refused.current?.(ev.code);
          return;
        }
        schedule();
      };
    };

    void connect();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      socket?.close();
      socket = null;
    };
  }, [resolveUrl]);

  return { status };
}
