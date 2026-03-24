"use client";

import { useEffect, useRef, useState } from "react";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8080";

export interface SSEEvent {
  type: "connected" | "run_started" | "run_completed" | "trust_changed" | "violation_detected" | "agent_created" | "agent_paused" | "agent_resumed";
  data: Record<string, unknown>;
  timestamp: string;
}

type EventHandler = (event: SSEEvent) => void;

/**
 * Hook that subscribes to the norma.ai SSE stream.
 * Returns the last event and a boolean indicating connection status.
 *
 * Usage:
 *   const { lastEvent, connected } = useEventStream();
 *   useEffect(() => {
 *     if (lastEvent?.type === "run_completed") refreshData();
 *   }, [lastEvent]);
 */
export function useEventStream(onEvent?: EventHandler) {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<SSEEvent | null>(null);
  const onEventRef = useRef<EventHandler | undefined>(undefined);

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    let es: EventSource | null = null;
    let retryTimeout: ReturnType<typeof setTimeout>;

    function connect() {
      es = new EventSource(`${BASE_URL}/api/events/stream`);

      es.onmessage = (e) => {
        try {
          const event: SSEEvent = JSON.parse(e.data);
          setLastEvent(event);
          if (event.type === "connected") {
            setConnected(true);
          }
          onEventRef.current?.(event);
        } catch {
          // ignore malformed events
        }
      };

      es.onerror = () => {
        setConnected(false);
        es?.close();
        // Retry after 5s
        retryTimeout = setTimeout(connect, 5000);
      };
    }

    connect();

    return () => {
      es?.close();
      clearTimeout(retryTimeout);
    };
  }, []);

  return { lastEvent, connected };
}
