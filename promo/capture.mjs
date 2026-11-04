// Pass 1 of the promo: run the real DebateDojo (the API on the scripted model, and the Vite UI), drive it like a
// person would, and save DOM snapshots of each moment to promo/out/snaps. Pass 2 (kit/render.mjs) films them.
//
//   cd promo && pnpm install && node capture.mjs
//
// Headless Chrome has no microphone, so for the spoken turn a stand-in for the Web Speech API reads a scripted
// turn at speaking pace, word by word. Everything downstream is the app's own: useVoice times the take, the live
// meter counts words and fillers, and the server computes the delivery metrics from those timings.
import { rmSync } from "node:fs";
import { resolve } from "node:path";
import { freePort, launch, serve, sleep, snapper, until } from "./kit/snap.mjs";

const ROOT = resolve(import.meta.dirname, "..");
const SNAPS = resolve(import.meta.dirname, "out/snaps");
rmSync(SNAPS, { recursive: true, force: true });
const data = resolve(import.meta.dirname, "out/data");
rmSync(data, { recursive: true, force: true });
// Set PNGS=dir to also save a screenshot of every snapshot, for checking the capture by eye.
const PNGS = process.env.PNGS;

// Never the real model: the scripted one, with no key in reach.
delete process.env.ANTHROPIC_API_KEY;
const api = await freePort();
const web = await freePort();
const stopApi = await serve("uv", ["run", "debatedojo", "serve", "--port", String(api)], {
  cwd: resolve(ROOT, "backend"),
  env: { DEBATEDOJO_LLM: "scripted", DEBATEDOJO_SCRIPTED_DELAY: "0.06", DEBATEDOJO_DB_PATH: resolve(data, "promo.db") },
  url: `http://127.0.0.1:${api}/api/health`,
});
const stopWeb = await serve("pnpm", ["exec", "vite", "--host", "127.0.0.1", "--port", String(web), "--strictPort"], {
  cwd: resolve(ROOT, "frontend"),
  env: { DEBATEDOJO_API: `http://127.0.0.1:${api}` },
  url: `http://127.0.0.1:${web}/`,
});
const API = `http://127.0.0.1:${api}/api`;

/** Play a whole bout through the API, as earlier practice sessions for the record. */
async function bout(start, turns) {
  const s = await (await fetch(`${API}/sessions`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(start) })).json();
  for (const t of turns) {
    const r = await fetch(`${API}/sessions/${s.id}/turns`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ duration_s: 40, ...t }) });
    await r.text();
  }
  const done = await (await fetch(`${API}/sessions/${s.id}`)).json();
  console.log(`  earlier bout: ${done.status} ${done.overall}`);
}

try {
  // Earlier practice: three debate bouts that get better, so the record has a story to tell.
  const debate = (topic, side) => ({ mode: "debate", format_id: "oxford", topic, side });
  await bout(debate("This house believes city centres should be car-free", "proposition"), [
    { text: "Cars make city centres loud and dirty. Removing them makes streets nicer." },
    { text: "Cities should be for people. Parks are nice and walking is healthy." },
    { text: "People like walking. That is why the motion should pass." },
  ]);
  await bout(debate("This house would make voting compulsory", "opposition"), [
    { text: "First, compulsion changes who votes but not how informed they are. A voter forced to the booth with no interest is likely to pick at random, which adds noise rather than a voice." },
    { text: "You said compulsory voting makes politicians listen to everyone. But they listen to people who are persuadable, which compulsion does not create." },
    { text: "To conclude, the other side treats a symptom, because trust is earned, not ordered." },
  ]);
  await bout(debate("This house believes remote work does more good than harm", "proposition"), [
    { text: "First, remote work gives people back the hours they spent commuting, because the office is no longer the only place work happens. Second, people spend that time on work and family." },
    { text: "You said teams lose touch. But teams that write things down stay in touch better." },
    { text: "In summary, they never answered the lost hours, and their point about isolation collapsed once you look at how written teams work." },
  ]);

  const { browser, page } = await launch();
  // The stand-in microphone: speaks window.SPEECH a word at a time at a natural pace, with a breath between sentences.
  await page.evaluateOnNewDocument(() => {
    class SpokenTurn {
      lang = "en-GB";
      interimResults = true;
      continuous = true;
      onresult = null;
      onend = null;
      onerror = null;
      start() {
        const sentences = (window.SPEECH ?? "").match(/[^.!?]+[.!?]/g) ?? [];
        let s = 0;
        let w = 0;
        const step = () => {
          if (s >= sentences.length) return;
          const words = sentences[s].trim().split(/\s+/);
          w++;
          const said = words.slice(0, w).join(" ");
          const isFinal = w >= words.length;
          const result = Object.assign([{ transcript: said }], { isFinal });
          this.onresult?.({ resultIndex: 0, results: [result] });
          if (isFinal) {
            s++;
            w = 0;
          }
          this.timer = setTimeout(step, isFinal ? 900 : 330 + ((s * 7 + w * 13) % 9) * 12);
        };
        this.timer = setTimeout(step, 700);
      }
      stop() {
        clearTimeout(this.timer);
        setTimeout(() => this.onend?.(), 50);
      }
      abort() {
        clearTimeout(this.timer);
      }
    }
    window.SpeechRecognition = window.webkitSpeechRecognition = SpokenTurn;
  });
  await page.goto(`http://127.0.0.1:${web}/`);
  await page.evaluate(() => localStorage.clear());
  await until(page, () => document.querySelector(".mode-cards") && document.querySelector(".bout-list"));
  await sleep(500);
  const raw = snapper(page, SNAPS);
  const shot = async (name) => {
    await raw(name);
    if (PNGS) await page.screenshot({ path: resolve(PNGS, `${name}.png`) });
  };
  const go = async (hash, ready) => {
    await page.evaluate((h) => (location.hash = h), hash);
    await until(page, ready);
    await sleep(500);
  };
  const idle = () => !document.querySelector(".composer-input:disabled") && !document.querySelector(".turn.is-streaming");

  /** Snapshot every `every` ms until done() is true in the page, then once more when it settles. */
  async function seq(prefix, done, { every = 250, max = 120, settle = 700 } = {}) {
    let i = 0;
    for (; i < max; i++) {
      await shot(`${prefix}-${String(i).padStart(2, "0")}`);
      if (await page.evaluate(done)) break;
      await sleep(every);
    }
    await sleep(settle);
    await shot(`${prefix}-done`);
    console.log(`${prefix}: ${i + 1} frames`);
  }

  /** Type a turn like a person, snapshotting the clock as it runs. */
  async function typeTurn(prefix, text, { delay = 38, every = 6 } = {}) {
    await page.click(".composer-input");
    const words = text.split(" ");
    for (let k = 0; k < words.length; k++) {
      await page.keyboard.type((k ? " " : "") + words[k], { delay });
      if (prefix && k % every === every - 1) await shot(`${prefix}-${String(Math.floor(k / every)).padStart(2, "0")}`);
    }
    if (prefix) await shot(`${prefix}-done`);
  }
  const sendTurn = async () => {
    await page.click(".composer .send");
    await until(page, () => document.querySelector(".composer-input:disabled"));
  };

  // 1. The card: home, and the three modes.
  await shot("home");
  await page.evaluate(() => document.querySelector(".cards-section").scrollIntoView({ block: "center" }));
  await sleep(300);
  await shot("home-modes");
  await page.evaluate(() => scrollTo(0, 0));

  // 2. Meeting and sales: each set-up with its persona, then the first exchange.
  await go("#/new/meeting", () => document.querySelector(".setup.mode-meeting"));
  await page.click(".chip");
  await page.evaluate(() => [...document.querySelectorAll(".option")].find((o) => o.textContent.includes("Finance Director")).click());
  await sleep(300);
  await shot("setup-meeting");
  await page.click(".setup .btn-primary");
  await until(page, () => document.querySelector(".arena .composer-input"));
  await sleep(500);
  await typeTurn(null, "I propose we move the support team to a four-day week for a three-month trial, because burnout is driving people out. We would measure response times and satisfaction every week, and stop the trial if either slips.", { delay: 8 });
  await sendTurn();
  await seq("meeting", idle, { every: 400 });

  await go("#/new/sales", () => document.querySelector(".setup.mode-sales"));
  await page.click(".chip");
  await page.evaluate(() => [...document.querySelectorAll(".option")].find((o) => o.textContent.includes("Procurement Manager")).click());
  await sleep(300);
  await shot("setup-sales");
  await page.click(".setup .btn-primary");
  await until(page, () => document.querySelector(".arena .composer-input"));
  await sleep(500);
  await typeTurn(null, "Thanks for making the time. Clinics like yours lose hours every week to missed appointments and phone tag. Our tool books patients online and sends reminders, so the front desk spends that time on the people in the room.", { delay: 8 });
  await sendTurn();
  await seq("sales", idle, { every: 400 });

  // 3. Rapid fire: thirty seconds a turn, and the clock running low.
  await go("#/new/debate", () => document.querySelector(".setup.mode-debate"));
  await page.evaluate(() => [...document.querySelectorAll(".option")].find((o) => o.textContent.includes("Rapid fire")).click());
  await page.click(".chip");
  await sleep(300);
  await shot("setup-rapid");
  await page.click(".setup .btn-primary");
  await until(page, () => document.querySelector(".arena .composer-input"));
  await sleep(500);
  await page.click(".composer-input");
  await page.keyboard.type("Phones in class", { delay: 60 });
  await until(page, () => document.querySelector(".board-clock.is-low"), null, 40000);
  await page.keyboard.type(" split attention,", { delay: 60 });
  await sleep(1200);
  await shot("rapid-low");

  // 4. The main bout: Oxford-style, on the motion, from the proposition.
  await go("#/new/debate", () => document.querySelector(".setup.mode-debate"));
  await page.click(".chip");
  await sleep(300);
  await shot("setup-debate");
  await page.click(".setup .btn-primary");
  await until(page, () => document.querySelector(".arena .composer-input"));
  await sleep(600);
  await shot("arena-armed");

  // The opening, typed at a human pace: the clock starts on the first word.
  const OPENING =
    "Phones are wrecking concentration in the classroom. Studies show that 73% of teachers say phones are the biggest distraction in class. First, attention is what school is for, because every buzz costs minutes of focus. Second, a ban applies to every pupil equally, which makes it fair.";
  await typeTurn("opening", OPENING, { delay: 42, every: 4 });
  await sendTurn();
  await seq("opp1", idle, { every: 250 });
  // Back up the transcript to the opening, where the fact-checker's flag sits inline.
  await page.evaluate(() => {
    const t = document.querySelector(".transcript");
    t.scrollTop = document.querySelector(".turn-you").offsetTop - t.offsetTop - 16;
  });
  await sleep(300);
  await shot("flag");
  await page.evaluate(() => {
    const t = document.querySelector(".transcript");
    t.scrollTop = t.scrollHeight;
  });

  // The rebuttal, spoken: the mic opens, the words land as they are said, the meter keeps pace.
  await page.evaluate(() => {
    window.SPEECH =
      "You called the ban a blunt instrument. But treating every pupil the same is the point, because a rule that applies to everyone cannot be gamed. You say it moves the behaviour somewhere less visible. Um during lessons there is nowhere less visible to move it to. So the displacement argument fails inside the classroom.";
  });
  await page.click(".mic");
  await sleep(200);
  await seq("voice", () => document.querySelector(".composer-input").value.includes("inside the classroom."), { every: 900, settle: 600 });
  await page.click(".mic");
  await sleep(500);
  await shot("voice-stopped");
  await sendTurn();
  await seq("opp2", idle, { every: 250 });
  await shot("delivery");

  // The closing, then the bell: the judge scores, the coach finds the fixes.
  await typeTurn(null, "In summary, they never answered fairness, and their displacement point collapsed once you look at school hours. Take a pupil who checks one message mid-lesson: they lose the thread, which means the whole class waits. Attention is what school is for, and this motion protects it.", { delay: 10 });
  await sendTurn();
  await seq("verdict", () => !!document.querySelector(".coach .improvements"), { every: 300, settle: 1200 });
  const at = async (name, sel, block = "start", nudge = 0) => {
    await page.evaluate((s, b, n) => {
      document.querySelector(s).scrollIntoView({ block: b });
      scrollBy(0, n);
    }, sel, block, nudge);
    await sleep(400);
    await shot(name);
  };
  // Each part of the report a little below the caption's band.
  await at("scorecard", ".scorecard", "start", -150);
  await at("criteria", ".criteria", "start", -170);
  await at("coach", ".coach", "start", -150);
  await at("rewrite", ".rewrite", "start", -260);

  // 5. The record: every bout, criterion by criterion.
  await go("#/record/debate", () => document.querySelector(".spark-big"));
  await shot("record");
  await at("record-criteria", ".multiples", "center");

  await browser.close();
  console.log(`${raw.names.length} snapshots in promo/out/snaps`);
} finally {
  stopWeb();
  stopApi();
}
process.exit(0);
