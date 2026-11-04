import { useCallback, useEffect, useRef, useState } from "react";
import { longestPause } from "./delivery";

// Web Speech API: recognition is still prefixed in Chromium and Safari, and absent in Firefox,
// so it is feature-detected and typing always works as well.
type Result = ArrayLike<{ transcript: string }> & { isFinal: boolean };
type Recognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((e: { resultIndex: number; results: ArrayLike<Result> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error?: string }) => void) | null;
};

const Ctor = (globalThis as unknown as { SpeechRecognition?: new () => Recognition }).SpeechRecognition ??
  (globalThis as unknown as { webkitSpeechRecognition?: new () => Recognition }).webkitSpeechRecognition;

const MUTE_KEY = "debatedojo.muted";

export type SpokenTake = { talkSeconds: number; longestPause: number | null };

/**
 * Speech-to-text for the user's turn, with the timings the delivery metrics need, and
 * text-to-speech for the opponent with a remembered mute.
 */
export function useVoice(onFinal: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [muted, setMuted] = useState(() => localStorage.getItem(MUTE_KEY) === "1");
  const [speaking, setSpeaking] = useState(false);
  const rec = useRef<Recognition | null>(null);
  const take = useRef({ talkMs: 0, openedAt: 0, results: [] as number[], longest: null as number | null });
  const finalRef = useRef(onFinal);
  finalRef.current = onFinal;

  const canListen = Boolean(Ctor);
  const canSpeak = typeof window !== "undefined" && "speechSynthesis" in window;

  const close = useCallback(() => {
    const t = take.current;
    if (t.openedAt) {
      const now = performance.now();
      t.talkMs += now - t.openedAt;
      const pause = longestPause(t.openedAt, t.results, now);
      if (pause !== null) t.longest = Math.max(t.longest ?? 0, pause);
      t.openedAt = 0;
      t.results = [];
    }
    setListening(false);
    setInterim("");
  }, []);

  const start = useCallback(() => {
    if (!Ctor || rec.current) return;
    if (canSpeak) speechSynthesis.cancel();
    setError(null);
    const r = new Ctor();
    r.lang = "en-GB";
    r.interimResults = true;
    r.continuous = true;
    r.onresult = (e) => {
      take.current.results.push(performance.now());
      let partial = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const result = e.results[i];
        if (result.isFinal) finalRef.current(result[0].transcript.trim());
        else partial += result[0].transcript;
      }
      setInterim(partial.trim());
    };
    r.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") setError("Microphone access was blocked. You can still type.");
      else if (e.error && e.error !== "no-speech" && e.error !== "aborted") setError("Speech recognition stopped. You can keep typing.");
    };
    r.onend = () => {
      rec.current = null;
      close();
    };
    rec.current = r;
    take.current.openedAt = performance.now();
    take.current.results = [];
    setListening(true);
    try {
      r.start();
    } catch {
      rec.current = null;
      close();
      setError("The microphone could not start. You can still type.");
    }
  }, [canSpeak, close]);

  const stop = useCallback(() => rec.current?.stop(), []);

  /** What was said into the mic this turn, then reset for the next one. */
  const collect = useCallback((): SpokenTake | null => {
    rec.current?.abort();
    rec.current = null;
    close();
    const t = take.current;
    const out = t.talkMs > 0 ? { talkSeconds: Math.round(t.talkMs / 100) / 10, longestPause: t.longest } : null;
    take.current = { talkMs: 0, openedAt: 0, results: [], longest: null };
    return out;
  }, [close]);

  const speak = useCallback(
    (text: string) => {
      if (!canSpeak || muted || !text.trim()) return;
      speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "en-GB";
      u.rate = 1.04;
      u.onstart = () => setSpeaking(true);
      u.onend = u.onerror = () => setSpeaking(false);
      speechSynthesis.speak(u);
    },
    [canSpeak, muted],
  );

  const toggleMute = useCallback(() => {
    setMuted((m) => {
      const next = !m;
      localStorage.setItem(MUTE_KEY, next ? "1" : "0");
      if (next && canSpeak) speechSynthesis.cancel();
      return next;
    });
  }, [canSpeak]);

  useEffect(
    () => () => {
      rec.current?.abort();
      if (canSpeak) speechSynthesis.cancel();
    },
    [canSpeak],
  );

  return { canListen, canSpeak, listening, interim, error, muted, speaking, start, stop, collect, speak, toggleMute };
}
