import { useCallback, useEffect, useRef, useState } from "react";

/**
 * A turn clock. It is armed at the turn's limit and starts on the user's first word, typed or
 * spoken, so reading the opponent's reply costs nothing. At zero it calls `onExpire` once.
 */
export function useCountdown(limit: number, onExpire: () => void) {
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => performance.now());
  const fired = useRef(false);
  const expire = useRef(onExpire);
  expire.current = onExpire;

  const remaining = startedAt === null ? limit : Math.max(0, limit - (now - startedAt) / 1000);

  useEffect(() => {
    if (startedAt === null) return;
    const id = setInterval(() => setNow(performance.now()), 200);
    return () => clearInterval(id);
  }, [startedAt]);

  useEffect(() => {
    if (startedAt !== null && remaining <= 0 && !fired.current) {
      fired.current = true;
      expire.current();
    }
  }, [remaining, startedAt]);

  const start = useCallback(() => {
    setStartedAt((s) => s ?? performance.now());
    setNow(performance.now());
  }, []);

  const reset = useCallback(() => {
    fired.current = false;
    setStartedAt(null);
  }, []);

  /** Seconds since the clock started, for the turn's duration. */
  const elapsed = useCallback(() => (startedAt === null ? 0 : (performance.now() - startedAt) / 1000), [startedAt]);

  return { remaining, running: startedAt !== null && remaining > 0, started: startedAt !== null, start, reset, elapsed };
}
