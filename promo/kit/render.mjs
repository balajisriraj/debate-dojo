// Pass 2 of the promo: render the film frame by frame, score it, and cut the web film and the README GIF.
//
//   node promo/kit/render.mjs [--fps 30] [--preview 12.5] [--music track.wav]
//
// Reads promo/film.ts (the timeline) and promo/out/snaps/*.html (from promo/capture.mjs). Writes
// promo/out/<name>-promo.mp4 (1080p), promo/out/<name>-poster.jpg and
// promo/out/<name>-promo-web.mp4 (web size: upload it to the README on github.com).
import { execFileSync, spawn } from "node:child_process";
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import * as esbuild from "esbuild";
import puppeteer from "puppeteer-core";

const PROMO = resolve(import.meta.dirname, "..");
const OUT = resolve(PROMO, "out");
const arg = (name) => {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 ? process.argv[i + 1] : undefined;
};
const FPS = Number(arg("fps") ?? 30);
const PREVIEW = arg("preview");
const CHROME = process.env.CHROME_PATH ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
mkdirSync(OUT, { recursive: true });

await esbuild.build({ entryPoints: [resolve(PROMO, "film.ts")], outfile: resolve(OUT, "film.js"), bundle: true, format: "iife", target: "chrome120", logLevel: "error" });
const snaps = {};
for (const f of readdirSync(resolve(OUT, "snaps"))) if (f.endsWith(".html")) snaps[f.slice(0, -5)] = readFileSync(resolve(OUT, "snaps", f), "utf8");
// Keep "</script>" inside the JSON from closing the script tag.
const json = JSON.stringify(snaps).replace(/<\/(script)/gi, "<\\/$1");
writeFileSync(resolve(OUT, "film.html"), readFileSync(resolve(PROMO, "kit/film.html"), "utf8").replace("/*SNAPS*/", () => json));

const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, protocolTimeout: 600000, args: ["--hide-scrollbars", "--force-color-profile=srgb", "--font-render-hinting=none"], defaultViewport: { width: 1920, height: 1080, deviceScaleFactor: 1 } });
const page = await browser.newPage();
page.on("pageerror", (e) => console.error("film error:", e.message));
page.on("console", (m) => m.type() === "error" && console.error("film:", m.text()));
await page.goto(`file://${resolve(OUT, "film.html")}`);
await page.evaluate(() => window.READY);
await page.evaluate(() => document.fonts.ready);
const { duration, marks, scenes, meta } = await page.evaluate(() => ({ duration: window.DURATION, marks: window.MARKS, scenes: window.SCENES, meta: window.META }));

if (PREVIEW) {
  for (const t of PREVIEW.split(",")) {
    await page.evaluate((t) => window.renderAt(t), Number(t));
    await new Promise((r) => setTimeout(r, 120));
    await page.screenshot({ path: resolve(OUT, `preview-${t}.png`) });
  }
  await browser.close();
  console.log(`preview at ${PREVIEW}s of ${duration.toFixed(1)}s`);
  process.exit(0);
}

const silent = resolve(OUT, "silent.mp4");
const ff = spawn("ffmpeg", ["-y", "-v", "error", "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart", silent], { stdio: ["pipe", "inherit", "inherit"] });
const frames = Math.ceil(duration * FPS);
const started = Date.now();
for (let f = 0; f < frames; f++) {
  await page.evaluate((t) => window.renderAt(t), f / FPS);
  const jpg = await page.screenshot({ type: "jpeg", quality: 94, optimizeForSpeed: true });
  if (!ff.stdin.write(jpg)) await new Promise((r) => ff.stdin.once("drain", r));
  if (f % (FPS * 5) === 0) process.stdout.write(`\r  rendering ${Math.round((f / frames) * 100)}% (${((Date.now() - started) / 1000).toFixed(0)}s)`);
}
ff.stdin.end();
await new Promise((r) => ff.on("close", r));
await browser.close();
console.log(`\n  ${frames} frames, ${duration.toFixed(1)}s`);
writeFileSync(resolve(OUT, "timeline.json"), JSON.stringify({ duration, marks, scenes }, null, 2));

// The score: an original track composed to the cut (kit/score.py), unless you bring your own.
const track = arg("music") ?? resolve(OUT, "music.wav");
if (!arg("music")) execFileSync("python3", [resolve(PROMO, "kit/score.py"), track, String(duration), JSON.stringify(marks), meta.style], { stdio: "inherit" });
const film = resolve(OUT, `${meta.name}-promo.mp4`);
execFileSync("ffmpeg", ["-y", "-v", "error", "-i", silent, "-i", track, "-filter_complex", `[1:a]atrim=0:${duration.toFixed(2)},loudnorm=I=-14:TP=-1.2:LRA=11,afade=t=in:d=0.4,afade=t=out:st=${(duration - 2.4).toFixed(2)}:d=2.4[a]`, "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", film]);

// For the README and the portfolio: a web-sized film, and a poster.
execFileSync("ffmpeg", ["-y", "-v", "error", "-i", film, "-vf", "scale=1280:-2:flags=lanczos", "-c:v", "libx264", "-crf", "30", "-preset", "slow", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", resolve(OUT, `${meta.name}-promo-web.mp4`)]);
execFileSync("ffmpeg", ["-y", "-v", "error", "-ss", String(scenes.poster?.[0] ?? marks.reveal ?? 2), "-i", silent, "-frames:v", "1", "-vf", "scale=1280:-2:flags=lanczos", "-q:v", "3", resolve(OUT, `${meta.name}-poster.jpg`)]);
console.log(JSON.stringify({ name: meta.name, duration: +duration.toFixed(1), marks, scenes }));
