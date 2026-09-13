// TabXtract - GPL-3.0-or-later. See LICENSE.
import { useEffect, useState } from "react";

import { progressSocketUrl } from "../api";
import type { ProgressMessage } from "../types";

/**
 * Job progress over a WebSocket. No reconnection and no state recovery: this
 * is a local process, and if the socket drops the screen finds out anyway
 * from the job state, which is polled in parallel.
 */
export function useProgress(jobId: string | null, active: boolean) {
  const [latest, setLatest] = useState<ProgressMessage | null>(null);
  const [log, setLog] = useState<ProgressMessage[]>([]);

  useEffect(() => {
    if (!jobId || !active) return;
    let socket: WebSocket;
    try {
      socket = new WebSocket(progressSocketUrl(jobId));
    } catch {
      return;
    }
    socket.onmessage = (event) => {
      const msg: ProgressMessage = JSON.parse(event.data);
      setLatest(msg);
      setLog((prev) => [...prev.slice(-200), msg]);
    };
    return () => socket.close();
  }, [jobId, active]);

  return { latest, log };
}
