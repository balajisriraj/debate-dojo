// The film runtime: a list of shots, each so many beats long. Kinetic type cards, and shots of the real app,
// replayed from DOM snapshots (capture.mjs) with a moving camera, a cursor, typing and captions.
// renderAt(t) draws the shot under t, so render.mjs can step through frames deterministically.

export type Point = { x: number; y: number };
/** A point in app pixels (1920×1080), or a CSS selector inside the snapshot (its centre). */
export type Aim = Point | string;
export type View = {
  /** A snapshot name, or a timeline of [seconds into the shot, name] (for streaming and clicks). */
  snap: string | [number, string][];
  /** Scale and aim at the start, then at the end. Scale below 1 shows the app as a floating window. */
  cam: [number, Aim, number, Aim];
  caption?: [string, string];
  /** Put the caption at the bottom, for shots whose story is at the top of the page. */
  low?: boolean;
  /** The pointer: keyframes [seconds, aim]; clicks ripple at the given seconds. */
  cursor?: { path: [number, Aim][]; click?: number[] };
  /** Type text into an input or textarea in the snapshot between two times. */
  type?: { sel: string; text: string; from: number; to: number; until?: number };
  /** A soft ring around an element from a time on. */
  ring?: { sel: string; from?: number; to?: number }[];
  /** Scroll an element inside the snapshot: [from, to] pixels over [start, end] seconds. */
  scroll?: { sel: string; px: [number, number]; at: [number, number] };
};
export type Theme = {
  /** Output name (docs/<name>-promo.mp4) and the score's style (score.py STYLES). */
  name: string;
  style: string;
  bpm: number;
  /** Kinetic-type backgrounds: name → [background, ink]. Must include "dark" and "light". */
  bgs: Record<string, [string, string]>;
  /** Gradient for .grad text and the caption eyebrow. */
  grad: string;
  font: string;
  /** Behind the floating app window. */
  stage: string;
  caption: { bg: string; ink: string; shadow: string };
  /** HTML for the product mark on title cards. */
  logo: string;
  /** Extra CSS for the type layer. */
  css?: string;
};
type Shot = { beats: number; type?: { html: string; bg: string }; view?: View; mark?: string; hit?: boolean };

const W = 1920;
const H = 1080;
const clamp = (x: number) => Math.max(0, Math.min(1, x));
const out = (x: number) => 1 - (1 - x) ** 3;
const inOut = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2);
const $ = <T extends HTMLElement>(sel: string) => document.querySelector<T>(sel)!;

export const big = (text: string, cls = "") => `<div class="w ${cls}">${text}</div>`;
export const sub = (text: string) => `<div class="sub">${text}</div>`;
export const grad = (text: string) => `<span class="grad">${text}</span>`;
export const eyebrow = (text: string) => `<div class="eyebrow">${text}</div>`;
/** A row of small "chips" under a headline. */
export const chips = (...items: string[]) => `<div class="chips">${items.map((x) => `<span>${x}</span>`).join("")}</div>`;

/** A streamed reply as a snapshot timeline: prefix-00, prefix-01, … then prefix-done, one every `every` seconds. */
export function stream(prefix: string, from = 0, every = 0.3): [number, string][] {
  const names = Object.keys((window as unknown as { SNAPS: Record<string, string> }).SNAPS)
    .filter((n) => n.startsWith(`${prefix}-`) && /-\d+$/.test(n))
    .sort();
  const seq: [number, string][] = names.map((n, i) => [from + i * every, n]);
  seq.push([from + names.length * every, `${prefix}-done`]);
  return seq;
}

export function makeFilm(theme: Theme) {
  const BEAT = 60 / theme.bpm;
  const shots: Shot[] = [];
  const word = (beats: number, html: string, bg = "dark", extra: Partial<Shot> = {}) => shots.push({ beats, type: { html, bg }, ...extra });
  const ui = (beats: number, view: View, extra: Partial<Shot> = {}) => shots.push({ beats, view, ...extra });

  function run(scenes: (marks: Record<string, number>, beat: number) => Record<string, [number, number]>) {
    const SNAPS = (window as unknown as { SNAPS: Record<string, string> }).SNAPS;
    document.documentElement.style.setProperty("--grad", theme.grad);
    document.documentElement.style.setProperty("--font", theme.font);
    document.documentElement.style.setProperty("--stage", theme.stage);
    document.documentElement.style.setProperty("--cap-bg", theme.caption.bg);
    document.documentElement.style.setProperty("--cap-ink", theme.caption.ink);
    document.documentElement.style.setProperty("--cap-shadow", theme.caption.shadow);
    if (theme.css) document.head.insertAdjacentHTML("beforeend", `<style>${theme.css}</style>`);
    const camera = $("#camera");
    const stage = $("#stage");
    const typeLayer = $("#type");
    const captionEl = $("#caption");
    const cursor = $("#cursor");
    const ripple = $("#ripple");
    const ringEl = $("#ring");

    // One iframe per snapshot used, loaded up front.
    const used = new Set<string>();
    for (const s of shots) if (s.view) (typeof s.view.snap === "string" ? [s.view.snap] : s.view.snap.map((x) => x[1])).forEach((n) => used.add(n));
    const frames = new Map<string, HTMLIFrameElement>();
    const loads: Promise<void>[] = [];
    for (const name of used) {
      if (!SNAPS[name]) throw new Error(`missing snapshot ${name}`);
      const f = document.createElement("iframe");
      f.style.visibility = "hidden";
      loads.push(
        new Promise((ok) => {
          f.onload = () => {
            const d = f.contentDocument!;
            const [sy, sx] = (d.body.getAttribute("data-snap-window") ?? "0,0").split(",").map(Number);
            f.contentWindow!.scrollTo(sx, sy);
            d.querySelectorAll<HTMLElement>("[data-snap-scroll]").forEach((el) => {
              const [top, left] = el.getAttribute("data-snap-scroll")!.split(",").map(Number);
              el.scrollTop = top;
              el.scrollLeft = left;
            });
            ok();
          };
        }),
      );
      f.srcdoc = SNAPS[name];
      stage.appendChild(f);
      frames.set(name, f);
    }

    const starts: number[] = [];
    let total = 0;
    for (const s of shots) {
      starts.push(total);
      total += s.beats * BEAT;
    }
    const DURATION = total + 0.6;
    const marks: Record<string, number> = {};
    const hits: number[] = [];
    shots.forEach((s, i) => {
      if (s.mark) marks[s.mark] = starts[i];
      if (s.hit) hits.push(starts[i]);
    });

    let current: HTMLIFrameElement | null = null;
    /** Inputs a shot has typed into, with the value their snapshot had. */
    const typed = new Map<HTMLInputElement, string>();
    const snapAt = (v: View, u: number) => {
      if (typeof v.snap === "string") return v.snap;
      let name = v.snap[0][1];
      for (const [at, n] of v.snap) if (u >= at) name = n;
      return name;
    };
    const doc = () => current!.contentDocument!;
    const rectOf = (sel: string) => doc().querySelector(sel)?.getBoundingClientRect() ?? null;
    const aim = (a: Aim): Point => {
      if (typeof a !== "string") return a;
      const r = rectOf(a);
      return r ? { x: r.left + r.width / 2, y: r.top + r.height / 2 } : { x: W / 2, y: H / 2 };
    };
    const along = (path: [number, Aim][], u: number): Point => {
      if (u <= path[0][0]) return aim(path[0][1]);
      for (let k = 1; k < path.length; k++) {
        if (u <= path[k][0]) {
          const p = inOut(clamp((u - path[k - 1][0]) / (path[k][0] - path[k - 1][0])));
          const a = aim(path[k - 1][1]);
          const b = aim(path[k][1]);
          return { x: a.x + (b.x - a.x) * p, y: a.y + (b.y - a.y) * p };
        }
      }
      return aim(path[path.length - 1][1]);
    };

    function renderCaption(c: [string, string] | undefined, fresh: boolean, u: number) {
      if (!c) {
        captionEl.style.opacity = "0";
        return;
      }
      const sig = c.join("|");
      if (captionEl.dataset.sig !== sig) {
        captionEl.dataset.sig = sig;
        captionEl.innerHTML = `<div class="eyebrow">${c[0]}</div><div class="title">${c[1]}</div>`;
      }
      const p = fresh ? out(clamp(u / 0.35)) : 1;
      captionEl.style.opacity = String(p);
      captionEl.style.transform = `translate(-50%, ${(1 - p) * -16}px)`;
    }

    function renderType(s: Shot, u: number, dur: number) {
      renderCaption(undefined, false, u);
      const { html, bg } = s.type!;
      typeLayer.style.display = "grid";
      camera.style.display = "none";
      if (typeLayer.dataset.sig !== html + bg) {
        typeLayer.dataset.sig = html + bg;
        typeLayer.innerHTML = html;
      }
      const [background, color] = theme.bgs[bg] ?? theme.bgs.dark;
      typeLayer.style.background = background;
      typeLayer.style.color = color;
      typeLayer.dataset.bg = bg;
      // Each line rises in, a little after the one before; the whole card drifts slowly closer.
      const push = 1 + 0.03 * (u / dur);
      typeLayer.querySelectorAll<HTMLElement>(":scope > *").forEach((el, k) => {
        const p = 0.35 + 0.65 * out(clamp((u - k * 0.16) / 0.4));
        el.style.opacity = String(p);
        el.style.transform = `scale(${push}) translateY(${(1 - p) * 26}px)`;
      });
    }

    function renderView(s: Shot, u: number, dur: number, fresh: boolean) {
      const v = s.view!;
      typeLayer.style.display = "none";
      camera.style.display = "";
      const name = snapAt(v, u);
      const next = frames.get(name)!;
      if (current !== next) {
        if (current) current.style.visibility = "hidden";
        next.style.visibility = "visible";
        current = next;
      }
      const d = doc();
      let typing: HTMLInputElement | null = null;
      if (v.type && u < (v.type.until ?? 1e9)) {
        const el = d.querySelector<HTMLInputElement>(v.type.sel);
        if (el) {
          if (!typed.has(el)) typed.set(el, el.value);
          typing = el;
          const n = Math.floor(clamp((u - v.type.from) / (v.type.to - v.type.from)) * v.type.text.length);
          el.value = v.type.text.slice(0, n);
          if (el.tagName === "TEXTAREA") el.textContent = el.value;
        }
      }
      // Typing must not leak into later shots of the same snapshot: put back what the snapshot had.
      for (const [el, orig] of typed) {
        if (el === typing || el.value === orig) continue;
        el.value = orig;
        if (el.tagName === "TEXTAREA") el.textContent = orig;
      }
      if (v.scroll) {
        const el = d.querySelector<HTMLElement>(v.scroll.sel);
        const p = inOut(clamp((u - v.scroll.at[0]) / (v.scroll.at[1] - v.scroll.at[0])));
        if (el) el.scrollTop = v.scroll.px[0] + (v.scroll.px[1] - v.scroll.px[0]) * p;
      }
      captionEl.classList.toggle("low", !!v.low);
      renderCaption(v.caption, fresh, u);
      // The camera: ease from the first framing to the second.
      const [s0, a0, s1, a1] = v.cam;
      const p0 = aim(a0);
      const p1 = aim(a1);
      const p = inOut(clamp(u / dur));
      const sc = s0 + (s1 - s0) * p;
      let cx = p0.x + (p1.x - p0.x) * p;
      let cy = p0.y + (p1.y - p0.y) * p;
      if (sc > 1) {
        cx = Math.min(Math.max(cx, W / (2 * sc)), W - W / (2 * sc));
        cy = Math.min(Math.max(cy, H / (2 * sc)), H - H / (2 * sc));
      } else {
        cx = W / 2;
        cy = H / 2;
      }
      camera.style.transform = `translate(${W / 2 - cx * sc}px, ${H / 2 - cy * sc}px) scale(${sc})`;
      camera.classList.toggle("window", sc < 0.999);
      // Pointer and click ripple.
      if (v.cursor) {
        const pt = along(v.cursor.path, u);
        cursor.style.display = "";
        cursor.style.transform = `translate(${pt.x - 4}px, ${pt.y - 3}px)`;
        const c = (v.cursor.click ?? []).find((t) => u >= t && u < t + 0.5);
        if (c !== undefined) {
          const q = (u - c) / 0.5;
          ripple.style.opacity = String(0.9 * (1 - q));
          ripple.style.transform = `translate(${pt.x - 22}px, ${pt.y - 22}px) scale(${0.4 + q * 1.2})`;
          cursor.style.transform += ` scale(${0.86 + 0.14 * q})`;
        } else ripple.style.opacity = "0";
      } else {
        cursor.style.display = "none";
        ripple.style.opacity = "0";
      }
      const ring = (v.ring ?? []).find((r) => u >= (r.from ?? 0) && u < (r.to ?? 1e9));
      const rr = ring && rectOf(ring.sel);
      if (ring && rr) {
        const q = out(clamp((u - (ring.from ?? 0)) / 0.35));
        Object.assign(ringEl.style, { display: "", left: `${rr.left - 8}px`, top: `${rr.top - 8}px`, width: `${rr.width + 16}px`, height: `${rr.height + 16}px`, opacity: String(q), transform: `scale(${1.06 - 0.06 * q})` });
      } else ringEl.style.display = "none";
    }

    function renderAt(t: number) {
      let i = starts.length - 1;
      while (i > 0 && starts[i] > t) i--;
      const s = shots[i];
      const u = t - starts[i];
      const dur = s.beats * BEAT;
      const fresh = !!s.view?.caption && s.view.caption.join("|") !== shots[i - 1]?.view?.caption?.join("|");
      if (s.type) renderType(s, u, dur);
      else renderView(s, u, dur, fresh);
      document.body.style.opacity = String(1 - clamp((t - total) / 0.5));
    }

    Object.assign(window, {
      renderAt,
      READY: Promise.all(loads),
      DURATION,
      META: { name: theme.name, style: theme.style },
      MARKS: { ...marks, hits, bpm: theme.bpm },
      SCENES: scenes(marks, BEAT),
    });
  }

  return { word, ui, run, BEAT };
}
