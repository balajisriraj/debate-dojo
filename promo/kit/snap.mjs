// Capture helpers for the promo: run the real app, drive it with puppeteer, and save DOM snapshots of it.
//
// A snapshot is the page's live DOM, serialised with its CSS, images, form values and scroll positions inlined, so
// the film can replay it as vector-crisp HTML: zooms stay sharp, and nothing is a screenshot.
import { spawn } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { resolve } from "node:path";
import puppeteer from "puppeteer-core";

export const CHROME = process.env.CHROME_PATH ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** A free TCP port. */
export function freePort() {
  return new Promise((ok) => {
    const s = createServer().listen(0, () => {
      const { port } = s.address();
      s.close(() => ok(port));
    });
  });
}

/** Start a process and wait until url answers. Returns a stop function. */
export async function serve(cmd, args, { cwd, env = {}, url, timeout = 90000 }) {
  const child = spawn(cmd, args, { cwd, env: { ...process.env, ...env }, stdio: ["ignore", "pipe", "pipe"], detached: true });
  let log = "";
  child.stdout.on("data", (d) => (log += d));
  child.stderr.on("data", (d) => (log += d));
  const stop = () => {
    try {
      process.kill(-child.pid, "SIGTERM");
    } catch {}
  };
  process.on("exit", stop);
  const until = Date.now() + timeout;
  while (Date.now() < until) {
    if (child.exitCode !== null) throw new Error(`${cmd} exited:\n${log}`);
    try {
      const r = await fetch(url);
      if (r.status < 500) return stop;
    } catch {}
    await sleep(300);
  }
  stop();
  throw new Error(`${url} did not come up:\n${log}`);
}

export async function launch({ width = 1920, height = 1080 } = {}) {
  const browser = await puppeteer.launch({ executablePath: CHROME, headless: true, args: ["--hide-scrollbars", "--force-color-profile=srgb"], defaultViewport: { width, height, deviceScaleFactor: 1 } });
  const page = await browser.newPage();
  page.on("pageerror", (e) => console.error("page error:", e.message));
  return { browser, page };
}

/** Wait until fn() (run in the page) is truthy. */
export const until = (page, fn, arg, timeout = 60000) => page.waitForFunction(fn, { timeout, polling: 100 }, arg);

/** Type like a person into a selector. */
export async function typeInto(page, sel, text, delay = 18) {
  await page.click(sel);
  await page.keyboard.type(text, { delay });
}

/** Serialise the page's DOM into a self-contained HTML document. */
export function snapshot(page) {
  return page.evaluate(async () => {
    const toData = async (url) => {
      try {
        const blob = await (await fetch(url)).blob();
        return await new Promise((ok) => {
          const fr = new FileReader();
          fr.onload = () => ok(fr.result);
          fr.readAsDataURL(blob);
        });
      } catch {
        return url;
      }
    };
    // Mark what cloning loses: scroll offsets, form values, canvases.
    const marks = [];
    for (const el of document.querySelectorAll("*")) {
      if (el.scrollTop || el.scrollLeft) {
        el.setAttribute("data-snap-scroll", `${el.scrollTop},${el.scrollLeft}`);
        marks.push(el);
      }
    }
    for (const el of document.querySelectorAll("input, textarea, select")) {
      el.setAttribute("data-snap-value", el.type === "checkbox" || el.type === "radio" ? (el.checked ? "1" : "") : el.value);
      marks.push(el);
    }
    for (const c of document.querySelectorAll("canvas")) {
      try {
        c.setAttribute("data-snap-img", c.toDataURL());
        marks.push(c);
      } catch {}
    }
    let css = "";
    for (const sheet of document.styleSheets) {
      // A <style> element's own text, where there is one: the CSSOM loses a font shorthand that uses var() when
      // a font longhand follows it in the same rule.
      if (sheet.ownerNode?.tagName === "STYLE" && sheet.ownerNode.textContent.trim()) {
        css += sheet.ownerNode.textContent + "\n";
        continue;
      }
      try {
        css += [...sheet.cssRules].map((r) => r.cssText).join("\n") + "\n";
      } catch {
        if (sheet.href) css += await (await fetch(sheet.href)).text().catch(() => "");
      }
    }
    // Inline url(...) references in the CSS.
    const urls = [...new Set([...css.matchAll(/url\(["']?([^"')]+)["']?\)/g)].map((m) => m[1]).filter((u) => !u.startsWith("data:") && !u.startsWith("#")))];
    for (const u of urls) css = css.split(u).join(await toData(new URL(u, location.href).href));
    const root = document.documentElement.cloneNode(true);
    marks.forEach((el) => {
      el.removeAttribute("data-snap-scroll");
      el.removeAttribute("data-snap-value");
      el.removeAttribute("data-snap-img");
    });
    root.querySelectorAll("script, link[rel=stylesheet], link[rel=modulepreload], style, noscript").forEach((n) => n.remove());
    for (const el of root.querySelectorAll("[data-snap-value]")) {
      const v = el.getAttribute("data-snap-value");
      if (el.tagName === "TEXTAREA") el.textContent = v;
      else if (el.type === "checkbox" || el.type === "radio") v ? el.setAttribute("checked", "") : el.removeAttribute("checked");
      else if (el.tagName === "SELECT") [...el.options].forEach((o) => (o.value === v ? o.setAttribute("selected", "") : o.removeAttribute("selected")));
      else el.setAttribute("value", v);
    }
    for (const c of root.querySelectorAll("canvas[data-snap-img]")) {
      const img = document.createElement("img");
      img.src = c.getAttribute("data-snap-img");
      img.className = c.className;
      img.setAttribute("style", (c.getAttribute("style") ?? "") + `;width:${c.clientWidth || c.width}px;height:${c.clientHeight || c.height}px`);
      c.replaceWith(img);
    }
    for (const img of root.querySelectorAll("img[src]")) {
      const src = img.getAttribute("src");
      if (!src.startsWith("data:")) img.setAttribute("src", await toData(new URL(src, location.href).href));
      img.removeAttribute("srcset");
      img.removeAttribute("loading");
    }
    for (const el of root.querySelectorAll("[style*='url(']")) {
      let st = el.getAttribute("style");
      for (const m of st.matchAll(/url\(["']?([^"')]+)["']?\)/g)) if (!m[1].startsWith("data:")) st = st.split(m[1]).join(await toData(new URL(m[1], location.href).href));
      el.setAttribute("style", st);
    }
    for (const svgUse of root.querySelectorAll("use[href^='/'], use[href^='http']")) svgUse.removeAttribute("href");
    const head = root.querySelector("head");
    const style = document.createElement("style");
    // Freeze motion: animations sit at their end state, nothing transitions, no caret.
    style.textContent = `${css}\n*,*::before,*::after{animation-delay:-60s!important;animation-play-state:paused!important;transition:none!important;caret-color:transparent!important}`;
    head.appendChild(style);
    const body = root.querySelector("body");
    body.setAttribute("data-snap-window", `${scrollY},${scrollX}`);
    return `<!doctype html>${root.outerHTML}`;
  });
}

/** A snapshot writer bound to a directory: await shot("name"). */
export function snapper(page, dir) {
  mkdirSync(dir, { recursive: true });
  const names = [];
  const shot = async (name) => {
    writeFileSync(resolve(dir, `${name}.html`), await snapshot(page));
    names.push(name);
    process.stdout.write(`  snap ${name}\n`);
  };
  shot.names = names;
  return shot;
}

/** Snapshot a streaming region as it fills: every `every` ms until done() is truthy (or `max` frames). */
export async function film(page, shot, prefix, done, { every = 220, max = 40, arg } = {}) {
  for (let i = 0; i < max; i++) {
    await shot(`${prefix}-${String(i).padStart(2, "0")}`);
    if (await page.evaluate(done, arg)) return i + 1;
    await sleep(every);
  }
  return max;
}
