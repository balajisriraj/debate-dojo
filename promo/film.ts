// DebateDojo's promo: why it exists, the product, then each feature given room on the real UI (DOM snapshots from
// capture.mjs): a title card that says what it does, then the app doing it. Fight-night broadcast like the app:
// charcoal, cream, signal red and gold. 120 bpm; shots are counted in beats, so two beats are a second.
import { big, chips, eyebrow, grad, makeFilm, sub } from "./kit/film";

// The app's mark, large: a red tile with a gold corner cut.
const mark = (size = 132) =>
  `<div style="width:${size}px;height:${size}px;margin:0 auto;background:#ee4434;clip-path:polygon(0 0,100% 0,100% 70%,70% 100%,0 100%);box-shadow:inset -${size * 0.27}px -${size * 0.27}px 0 #d9a441;filter:drop-shadow(0 26px 40px rgba(238,68,52,.4))"></div>`;
const logo = mark();
const INK = "#121214";
const CREAM = "#f3ead8";
const glow = (bg: string, a = "rgba(238,68,52,.22)", b = "rgba(217,164,65,.12)") =>
  `radial-gradient(1300px 620px at 50% -160px, ${a}, transparent 70%), radial-gradient(900px 500px at 100% 100%, ${b}, transparent 70%), ${bg}`;
const { word, ui, run, BEAT } = makeFilm({
  name: "debate-dojo",
  style: "arena",
  bpm: 120,
  bgs: {
    dark: [glow(INK), CREAM],
    light: [glow("#f3ead8", "rgba(238,68,52,.16)", "rgba(217,164,65,.22)"), INK],
    red: [glow("linear-gradient(120deg, #b82a1e, #ee4434)", "rgba(255,255,255,.12)", "rgba(0,0,0,.18)"), CREAM],
    gold: [glow("linear-gradient(120deg, #a8792a, #d9a441)", "rgba(255,255,255,.16)", "rgba(0,0,0,.12)"), INK],
    night: [glow("#0b0b0d", "rgba(217,164,65,.14)", "rgba(238,68,52,.12)"), CREAM],
  },
  grad: "linear-gradient(90deg, #ee4434, #f07a3c 50%, #d9a441)",
  font: `"Avenir Next Condensed", "DIN Condensed", "Helvetica Neue Condensed", "Roboto Condensed", "Arial Narrow", sans-serif`,
  stage: "radial-gradient(1100px 640px at 20% 10%, rgba(238,68,52,.22), transparent 70%), radial-gradient(900px 620px at 85% 90%, rgba(217,164,65,.16), transparent 70%), #0b0b0d",
  caption: { bg: "rgba(18, 18, 20, .9)", ink: CREAM, shadow: "0 22px 50px -18px rgba(0, 0, 0, .7), 0 0 0 1px rgba(217, 164, 65, .35)" },
  logo,
  css: `
    #type .w { font-weight: 800; text-transform: uppercase; letter-spacing: -.005em; line-height: .94; font-size: 168px; }
    #type .w.m { font-size: 128px; } #type .w.s { font-size: 104px; line-height: .98; }
    #type .sub { font-family: system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif; font-size: 40px; font-weight: 500; letter-spacing: -.01em; opacity: .78; max-width: 1400px; }
    #type .eyebrow { font-size: 30px; font-weight: 700; letter-spacing: .26em; opacity: 1; color: #d9a441; }
    #type[data-bg=gold] .eyebrow, #type[data-bg=light] .eyebrow { color: #b82a1e; }
    #type[data-bg=red] .eyebrow { color: #f3ead8; opacity: .8; }
    #type[data-bg=gold] .sub, #type[data-bg=red] .sub { opacity: .92; }
    #type .chips span { font-family: system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif; font-size: 30px; border-color: rgba(243,234,216,.3); background: rgba(255,255,255,.04); }
    #type .lines { display: grid; gap: 22px; }
    #caption .eyebrow { font-family: system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif; }
    #caption .title { font-family: system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif; }
    #camera.window { box-shadow: 0 60px 140px -40px rgba(0, 0, 0, .8), 0 0 0 1px rgba(217, 164, 65, .25); }
    #ring { box-shadow: 0 0 0 3px #d9a441, 0 0 0 9px rgba(217, 164, 65, .22), 0 18px 50px -12px rgba(0, 0, 0, .6); }
    #ripple { background: rgba(243, 234, 216, .45); }
  `,
});
const C = { x: 960, y: 540 };
const SNAPS = (window as unknown as { SNAPS: Record<string, string> }).SNAPS;
/** Every numbered snapshot of a sequence, one every `every` seconds from `from`, then its settled -done frame. */
const frames = (prefix: string, from = 0, every = 0.3, skip = 0): [number, string][] => {
  const names = Object.keys(SNAPS)
    .filter((n) => new RegExp(`^${prefix}-\\d+$`).test(n))
    .sort()
    .slice(skip);
  return [...names.map((n, k): [number, string] => [from + k * every, n]), [from + names.length * every, `${prefix}-done`]];
};

// The opening, typed: the frames before and after the clock starts.
const OPENING = [...Object.keys(SNAPS).filter((n) => /^opening-\d+$/.test(n)).sort(), "opening-done"];

// The hook: the moment that matters comes before the practice.
word(5, `${big("You have to argue well", "s")}${sub("at exactly the moment you've had no practice.")}`);
word(4, `${eyebrow("The debate round")}${big("The motion is set.", "m")}`, "night");
word(4, `${eyebrow("The meeting")}${big("Someone pushes back.", "m")}`, "night");
word(4, `${eyebrow("The sales call")}${big("“It’s too expensive.”", "m")}`, "night");
word(5, `${big(`And no one to ${grad("spar with")} first.`, "s")}`);
// The product.
word(6, `${logo}${big(`Debate<span style="color:#ee4434">Dojo</span>`)}${sub("Spar with an AI that argues back.")}`, "dark", { mark: "reveal", hit: true });
ui(8, { snap: "home", cam: [0.74, C, 0.82, C], caption: ["DebateDojo", "Argue it out, get scored, get better"] });

// 1. Three modes.
word(5, `${eyebrow("01 · Three modes")}${big("One ring. Three fights.", "m")}${sub("A formal debate, a meeting that pushes back, a buyer with objections.")}`, "red");
ui(9, { snap: "home-modes", cam: [1.16, { x: 960, y: 640 }, 1.2, { x: 960, y: 650 }], caption: ["Three modes", "Debate, Meeting and Sales"] });
ui(5, { snap: "meeting-done", cam: [1.5, { x: 1400, y: 260 }, 1.55, { x: 1420, y: 260 }], ring: [{ sel: ".corner-opp", from: 0.6 }], low: true, caption: ["Meeting", "A finance director who wants payback"] });
ui(6, { snap: "meeting-done", cam: [1.45, { x: 860, y: 690 }, 1.5, { x: 860, y: 690 }], low: true, caption: ["Meeting", "A finance director who wants payback"] });
ui(5, { snap: "sales-done", cam: [1.5, { x: 1400, y: 260 }, 1.55, { x: 1420, y: 260 }], ring: [{ sel: ".corner-opp", from: 0.6 }], low: true, caption: ["Sales", "A procurement manager pushing on price"] });
ui(6, { snap: "sales-done", cam: [1.45, { x: 860, y: 690 }, 1.5, { x: 860, y: 690 }], low: true, caption: ["Sales", "A procurement manager pushing on price"] });

// 2. Formats and the clock.
word(5, `${eyebrow("02 · Formats")}${big("Real formats. A real clock.", "m")}${sub("Oxford, Lincoln-Douglas and Rapid fire, each with timed phases.")}`, "gold");
ui(9, { snap: "setup-debate", cam: [1.45, { x: 1366, y: 600 }, 1.55, { x: 1366, y: 620 }], ring: [{ sel: ".setup-grid .panel:nth-child(2) .option:nth-child(1)", from: 1.0 }], caption: ["Formats", "Oxford-style, Lincoln-Douglas-style, Rapid fire"] });
ui(5, { snap: "arena-armed", cam: [1.5, { x: 960, y: 260 }, 1.6, { x: 960, y: 250 }], low: true, caption: ["The clock", "Timed phases, armed until your first word"] });
ui(8, { snap: OPENING.map((n, k): [number, string] => [k * 0.32, n]), cam: [0.86, C, 0.9, C], caption: ["The clock", "Running from the first word you type"] });
ui(9, { snap: "rapid-low", cam: [1.6, { x: 960, y: 300 }, 1.75, { x: 960, y: 280 }], low: true, caption: ["Rapid fire", "Thirty seconds a turn"] });

// 3. The opponent.
word(5, `${eyebrow("03 · The opponent")}${big("It answers what you said.", "m")}${sub("Your own words, quoted back and taken apart.")}`);
ui(13, { snap: frames("opp1", 0, 0.22), cam: [1.4, { x: 860, y: 640 }, 1.5, { x: 860, y: 660 }], caption: ["The opponent", "Quotes your claim, then argues back"] });

// 4. The fact-checker.
word(5, `${eyebrow("04 · The fact-checker")}${big("Shaky claims get flagged.", "m")}${sub("Inline, as you go, with the evidence that would fix them.")}`, "red");
ui(11, { snap: "flag", cam: [1.5, { x: 640, y: 560 }, 1.65, { x: 640, y: 560 }], ring: [{ sel: ".flag", from: 1.2 }], caption: ["Fact-checker", "An unnamed study, flagged as unsupported"] });

// 5. Voice.
word(5, `${eyebrow("05 · Voice")}${big("Say it out loud.", "m")}${sub("Speak your turns, hear the reply, and see how you sounded.")}`, "gold");
ui(12, { snap: frames("voice", 0, 0.5), cam: [1.38, { x: 750, y: 760 }, 1.42, { x: 750, y: 760 }], ring: [{ sel: ".mic", from: 0.4, to: 2.5 }], caption: ["Speech to text", "Your words land as you say them"] });
ui(9, { snap: "delivery", cam: [1.6, { x: 600, y: 480 }, 1.7, { x: 580, y: 500 }], ring: [{ sel: ".turn-meta:has(.src-voice)", from: 0.9 }], caption: ["Delivery", "Pace, fillers and pauses, from the spoken turn"] });
ui(9, { snap: "delivery", cam: [1.75, { x: 1600, y: 900 }, 1.85, { x: 1600, y: 920 }], ring: [{ sel: ".ringside .tiles", from: 0.8 }], caption: ["Delivery", "Talk time against the clock, every turn"] });

// 6. The hero: the judges' scorecard, on the drop.
word(4, big("Then the bell.", "m"), "night", { mark: "heroIn" });
word(5, `${eyebrow("06 · The judges")}${big(grad("Scored on your own words."), "s")}${sub("A rubric, a score per criterion, and a quote as evidence.")}`, "dark");
ui(12, { snap: "scorecard", cam: [1.22, { x: 960, y: 560 }, 1.32, { x: 960, y: 520 }], caption: ["Judges' scorecard", "A score out of 100, criterion by criterion"] }, { mark: "hero", hit: true });
ui(12, { snap: "criteria", cam: [1.3, { x: 960, y: 560 }, 1.36, { x: 960, y: 620 }], ring: [{ sel: ".criterion .evidence", from: 1.2 }], caption: ["Evidence", "Every score quotes what you said"] }, { mark: "heroEnd" });

// 7. The coach.
word(5, `${eyebrow("07 · The coach")}${big("Three fixes. One rewrite.", "m")}${sub("Your weakest turn, rewritten as the model answer.")}`, "red");
ui(10, { snap: "coach", cam: [1.28, { x: 960, y: 500 }, 1.34, { x: 960, y: 520 }], caption: ["The coach", "Three fixes, each with a drill"] });
ui(11, { snap: "rewrite", cam: [1.28, { x: 960, y: 560 }, 1.34, { x: 960, y: 580 }], ring: [{ sel: ".rewrite-after", from: 1.6 }], caption: ["The rewrite", "What you said, and how to say it better"] });

// 8. The record.
word(5, `${eyebrow("08 · The record")}${big("Is practice working?", "m")}${sub("Every bout logged. Every criterion charted.")}`, "gold");
ui(10, { snap: "record", cam: [1.15, { x: 960, y: 480 }, 1.25, { x: 960, y: 560 }], caption: ["Your record", "Progress across bouts"] });

// The angles: how it's built, and who it's for.
word(9, `${eyebrow("Under the hood")}${big("Four agents in one graph.", "s")}${chips("LangGraph", "Claude", "FastAPI + React", "Fact-checker and opponent in parallel", "Evals in CI")}`, "night");
word(7, `${eyebrow("Who it's for")}${big("Anyone who has to win the room.", "s")}${chips("Students and debaters", "A big meeting coming up", "Salespeople")}`);
word(7, `${logo}${big(grad("DebateDojo"))}${sub("by Balaji Sri Raj")}`, "dark", { mark: "outro" });

run((m) => ({ poster: [m.hero + 6 * BEAT, 0] }));
