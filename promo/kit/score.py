"""The promo's score: an original track, synthesised in plain Python and composed to the film's cut.

    python3 promo/kit/score.py out.wav <seconds> '<marks json>' <style>

Marks come from the film's timeline: reveal, heroIn, hero, heroEnd, outro, hits and bpm. The sections:

  intro   the hook: a pad, a soft pulse and a lead that hints at the theme
  groove  the features: the style's beat, bass and lead riff
  hush    before the hero feature: the beat drops out, a riser and a fill
  drop    the hero feature: the full beat with a bigger low end, the lead an octave up
  outro   the final chord rings out

Styles give each product its own sound (see STYLES). A style with crowd=True gets a crowd swell on the drop.
"""

import json
import math
import random
import struct
import sys
import wave

RATE = 44100
OUT, SECONDS, MARKS = sys.argv[1], float(sys.argv[2]), json.loads(sys.argv[3])
STYLE_NAME = sys.argv[4] if len(sys.argv) > 4 else "midnight"
BPM = float(MARKS.get("bpm", 112))
BEAT = 60 / BPM
BAR = 4 * BEAT
N = int((SECONDS + 4) * RATE)
L, R = [0.0] * N, [0.0] * N
PL, PR = [0.0] * N, [0.0] * N  # pads and bass, ducked by the kick
random.seed(11)
TABLE = 4096
SINE = [math.sin(2 * math.pi * i / TABLE) for i in range(TABLE)]

REVEAL = float(MARKS.get("reveal", 6.0))
HERO = float(MARKS.get("hero", SECONDS * 0.5))
HERO_IN = float(MARKS.get("heroIn", HERO - 2 * BAR))
HERO_END = float(MARKS.get("heroEnd", HERO + 8 * BAR))
OUTRO = float(MARKS.get("outro", SECONDS - 6))
HITS = [float(h) for h in MARKS.get("hits", [])]

# Each style: chords (bass, tones) per bar, a lead riff (eighth notes, None = rest), the beat, the lead's sound,
# the accent percussion, and touches.
STYLES = {
    # Ashariri: late-night, cinematic electronic in D minor. Glassy bells, trap hats, deep 808.
    "midnight": dict(
        chords=[(38, [62, 65, 69, 72]), (34, [62, 65, 70, 74]), (41, [60, 65, 69, 72]), (36, [60, 64, 67, 72])],
        riff=[74, None, 77, 74, 72, None, 69, None, 74, None, 72, 69, 65, None, 67, None],
        beat="trap", lead="bell", accent="sub", pad=0.05, swing=0.0,
    ),
    # PaperSensei: a warm study-desk groove. Rhodes chords, swung boom-bap, vinyl crackle, upright-ish bass.
    "study": dict(
        chords=[(41, [57, 60, 64, 67]), (38, [57, 60, 62, 65]), (43, [58, 62, 65, 69]), (36, [58, 60, 64, 67])],
        riff=[72, None, 69, None, 67, 69, None, 72, None, 74, 72, None, 69, None, 67, None],
        beat="boombap", lead="rhodes", accent="crackle", pad=0.035, swing=0.16,
    ),
    # VibeLens: loud and bold. Breakbeat drums, brassy stabs, a sliding bass.
    "punch": dict(
        chords=[(40, [64, 67, 71, 74]), (36, [64, 67, 72, 76]), (43, [62, 67, 71, 74]), (38, [62, 66, 69, 74])],
        riff=[76, 76, None, 74, None, 71, None, 74, 76, None, 79, None, 76, 74, None, None],
        beat="break", lead="brass", accent="stab", pad=0.03, swing=0.0,
    ),
    # SkillSmith: the forge. Stomps and claps, anvil strikes, a kalimba riff, low tom fills.
    "forge": dict(
        chords=[(33, [57, 60, 64, 69]), (41, [57, 60, 65, 69]), (36, [55, 60, 64, 67]), (43, [55, 59, 62, 67])],
        riff=[69, None, 72, 76, None, 72, 69, None, 67, None, 69, 72, None, 76, 74, None],
        beat="stomp", lead="kalimba", accent="anvil", pad=0.04, swing=0.0,
    ),
    # FlowMind: airy house. Four on the floor, offbeat hats, a marimba arpeggio, bright pads.
    "air": dict(
        chords=[(41, [65, 69, 72, 76]), (45, [64, 69, 72, 76]), (38, [62, 65, 69, 74]), (43, [62, 67, 71, 74])],
        riff=[77, 72, 69, 72, 76, 72, 69, 72, 74, 69, 65, 69, 72, 69, 65, 69],
        beat="house", lead="marimba", accent="shaker", pad=0.045, swing=0.0,
    ),
    # DebateDojo: fight night. A driving stadium beat with big snares and tom rolls, brass stabs in A minor, an
    # eighth-note bass, and a crowd that swells on the hero drop.
    "arena": dict(
        chords=[(45, [60, 64, 69, 72]), (41, [60, 65, 69, 72]), (36, [60, 64, 67, 72]), (43, [59, 62, 67, 71])],
        riff=[69, None, 69, 72, None, 74, 76, None, 76, None, 74, 72, None, 69, 71, None],
        beat="arena", lead="brass", accent="stadium", pad=0.035, swing=0.0, crowd=True,
    ),
}
S = STYLES[STYLE_NAME]


def hz(n):
    return 440.0 * 2 ** ((n - 69) / 12)


def section(t):
    if t < REVEAL:
        return "intro"
    if HERO_IN <= t < HERO:
        return "hush"
    if HERO <= t < HERO_END:
        return "drop"
    if t >= OUTRO:
        return "outro"
    return "groove"


def put(i, left, right, bus):
    if 0 <= i < N:
        if bus:
            PL[i] += left
            PR[i] += right
        else:
            L[i] += left
            R[i] += right


def tone(freq, start, dur, amp, pan=0.0, attack=0.005, release=0.2, harmonics=((1, 1.0),), decay=None, bend=0.0, bend_time=0.03, bus=False, vibrato=0.0):
    s0, n = int(start * RATE), int((dur + release) * RATE)
    gl, gr = amp * (1 - pan) * 0.7, amp * (1 + pan) * 0.7
    a_n, d_n, r_n = max(1, int(attack * RATE)), int(dur * RATE), max(1, int(release * RATE))
    ph = [0.0] * len(harmonics)
    k = 1 / (decay * RATE) if decay else 0
    b_n = max(1, int(bend_time * RATE))
    for j in range(n):
        env = j / a_n if j < a_n else 1.0
        if j >= d_n:
            env *= max(0.0, 1 - (j - d_n) / r_n)
        if k:
            env *= math.exp(-j * k)
        f = freq
        if bend:
            f *= 2 ** (bend * max(0.0, 1 - j / b_n) / 12)
        if vibrato:
            f *= 2 ** (vibrato * math.sin(2 * math.pi * 5.0 * j / RATE) / 1200)
        v = 0.0
        for idx, (h, w) in enumerate(harmonics):
            v += SINE[int(ph[idx]) & 4095] * w
            ph[idx] += TABLE * f * h / RATE
        v *= env
        put(s0 + j, v * gl, v * gr, bus)


def noise(start, dur, amp, decay=0.03, pan=0.0, bright=True, rise=False):
    s0, n = int(start * RATE), int(dur * RATE)
    last = 0.0
    for j in range(n):
        x = random.uniform(-1, 1)
        v = (x - last) if bright else (x + last) * 0.5
        last = x
        env = (j / n) ** 2.4 if rise else math.exp(-j / (decay * RATE))
        put(s0 + j, v * env * amp * (1 - pan), v * env * amp * (1 + pan), False)


def drum(start, base, amp, decay, drop=1.2, drop_rate=35.0, skin=0.25, pan=0.0):
    s0, n = int(start * RATE), int(decay * 6 * RATE)
    ph = ph2 = 0.0
    last = 0.0
    for j in range(n):
        t = j / RATE
        f = base * (1 + drop * math.exp(-t * drop_rate))
        ph += TABLE * f / RATE
        ph2 += TABLE * f * 1.58 / RATE
        body = SINE[int(ph) & 4095] * math.exp(-t / decay) + 0.3 * SINE[int(ph2) & 4095] * math.exp(-t / (decay * 0.4))
        x = random.uniform(-1, 1)
        sk = (x + last) * 0.5 * math.exp(-t * 90) * skin
        last = x
        v = (body + sk) * amp
        put(s0 + j, v * (1 - pan), v * (1 + pan), False)


def kick(at, amp=0.8):
    drum(at, 46, amp, 0.16, drop=2.4, drop_rate=42, skin=0.15)


def snare(at, amp=0.22):
    drum(at, 190, amp * 0.8, 0.06, drop=0.4, drop_rate=50, skin=0.2)
    noise(at, 0.22, amp, decay=0.07, bright=True, pan=0.05)


def clap(at, amp=0.2):
    for d in (0.0, 0.01, 0.021):
        noise(at + d, 0.12, amp, decay=0.035, bright=False)
    noise(at + 0.03, 0.4, amp * 0.16, decay=0.14, bright=False, pan=0.2)


def hat(at, amp=0.05, open_=False, pan=-0.2):
    noise(at, 0.22 if open_ else 0.04, amp, decay=0.09 if open_ else 0.014, pan=pan)


def tom(at, big=1.0, pan=0.0):
    drum(at, 70 / big ** 0.3, 0.6 * big, 0.26 * big, skin=0.4, pan=pan)


def anvil(at, amp=0.1, pan=0.3):
    """A struck metal bar: inharmonic partials that ring."""
    for ratio, w, dec in ((1.0, 1.0, 0.5), (2.76, 0.6, 0.3), (5.4, 0.35, 0.18), (8.93, 0.2, 0.1)):
        tone(1180 * ratio, at, 0.01, amp * w, pan=pan, attack=0.001, release=dec * 2, decay=dec)


def crowd(at, dur, amp=0.1):
    """A stadium crowd: dark noise in a few overlapping voices that roar up, then settle into a cheer."""
    s0, n = int(at * RATE), int(dur * RATE)
    lows = [0.0, 0.0, 0.0]
    rates = (0.05, 0.11, 0.2)
    for j in range(n):
        t = j / RATE
        env = min(1.0, t / 1.4) ** 2 * math.exp(-max(0.0, t - 1.4) / (dur * 0.45))
        swell = 0.75 + 0.25 * math.sin(2 * math.pi * 0.7 * t) * math.sin(2 * math.pi * 1.9 * t + 1)
        v = 0.0
        for k, a in enumerate(rates):
            lows[k] += a * (random.uniform(-1, 1) - lows[k])
            v += lows[k] * (1.6, 1.0, 0.6)[k]
        v *= env * swell * amp * 3
        put(s0 + j, v * (0.9 + 0.1 * math.sin(t * 3)), v * (0.9 - 0.1 * math.sin(t * 3)), False)
    # Scattered claps and whistles of a crowd on its feet.
    for _ in range(int(dur * 9)):
        c = at + 0.8 + random.uniform(0, dur * 0.8)
        noise(c, 0.05, amp * random.uniform(0.15, 0.4), decay=0.012, pan=random.uniform(-0.8, 0.8), bright=False)
    for _ in range(3):
        w = at + random.uniform(1.0, dur * 0.5)
        tone(random.uniform(1900, 2600), w, 0.5, amp * 0.12, pan=random.uniform(-0.7, 0.7), attack=0.05, release=0.25, bend=3, bend_time=0.2)


def shaker(at, amp=0.035, pan=0.35):
    noise(at, 0.07, amp, decay=0.03, pan=pan)


def bass(note, at, dur, amp=0.3, slide=0.0):
    s0, n = int(at * RATE), int((dur + 0.08) * RATE)
    f = hz(note)
    ph = 0.0
    for j in range(n):
        t = j / RATE
        env = min(1.0, j / 200) * (1 if j < dur * RATE else max(0.0, 1 - (j - dur * RATE) / (0.08 * RATE))) * (0.65 + 0.35 * math.exp(-t * 3))
        ph += TABLE * f * (2 ** (slide * max(0.0, 1 - t / 0.08) / 12)) / RATE
        v = math.tanh(1.8 * SINE[int(ph) & 4095]) * env * amp
        put(s0 + j, v, v, True)


def lead(note, at, amp=0.1, pan=0.0, length=None):
    kind = S["lead"]
    if kind == "bell":
        tone(hz(note), at, 0.04, amp, pan=pan, attack=0.002, release=1.6, harmonics=((1, 1.0), (2.76, 0.3), (5.4, 0.1)), decay=0.7)
    elif kind == "rhodes":
        tone(hz(note), at, length or 0.3, amp, pan=pan, attack=0.004, release=0.7, harmonics=((1, 1.0), (2, 0.35), (3, 0.12), (14, 0.03)), decay=0.8, vibrato=6)
    elif kind == "brass":
        tone(hz(note), at, length or 0.16, amp, pan=pan, attack=0.015, release=0.12, harmonics=((1, 1.0), (2, 0.7), (3, 0.5), (4, 0.35), (5, 0.25), (6, 0.15)), bend=-0.6, bend_time=0.05)
    elif kind == "kalimba":
        tone(hz(note), at, 0.03, amp, pan=pan, attack=0.001, release=1.0, harmonics=((1, 1.0), (5.9, 0.18), (3.0, 0.08)), decay=0.4)
    elif kind == "marimba":
        tone(hz(note), at, 0.03, amp, pan=pan, attack=0.001, release=0.6, harmonics=((1, 1.0), (4.0, 0.3), (10.0, 0.05)), decay=0.22)


def pad_chord(tones, at, dur, amp):
    for i, n_ in enumerate(tones):
        tone(hz(n_), at, dur, amp, pan=(i - 1.5) * 0.3, attack=0.5, release=0.8, harmonics=((1, 1.0), (1.004, 0.6), (2, 0.15)), bus=True)


def swing(k8):
    return S["swing"] * BEAT / 2 if k8 % 2 else 0.0


def beat_bar(t0, b, big):
    kind = S["beat"]
    amp = 1.0 if big else 0.85
    if kind == "trap":
        for k in (0.0, 1.75, 2.5):
            kick(t0 + k * BEAT, 0.8 * amp)
        for k in (1, 3):
            clap(t0 + k * BEAT, 0.2)
        for s16 in range(16):
            hat(t0 + s16 * BEAT / 4, 0.045 if s16 % 2 == 0 else 0.028)
        if b % 4 == 3:
            for k in range(8):
                hat(t0 + 3.5 * BEAT + k * BEAT / 16, 0.03 + 0.004 * k, pan=0.3)
    elif kind == "boombap":
        for k in (0.0, 1.5 + S["swing"] / 2, 2.5):
            kick(t0 + k * BEAT, 0.75 * amp)
        for k in (1, 3):
            snare(t0 + k * BEAT, 0.2)
        for k8 in range(8):
            hat(t0 + k8 * BEAT / 2 + swing(k8), 0.045 if k8 % 2 == 0 else 0.03)
    elif kind == "break":
        for k in (0.0, 1.5, 2.25, 2.75):
            kick(t0 + k * BEAT, 0.8 * amp if k == 0 else 0.6 * amp)
        for k in (1, 3):
            snare(t0 + k * BEAT, 0.26)
        snare(t0 + 3.75 * BEAT, 0.08)
        snare(t0 + 1.75 * BEAT, 0.06)
        for k8 in range(8):
            hat(t0 + k8 * BEAT / 2, 0.05 if k8 % 2 == 0 else 0.035, open_=(k8 == 7 and b % 2 == 1))
    elif kind == "stomp":
        for k in (0.0, 2.0):
            kick(t0 + k * BEAT, 0.85 * amp)
            tom(t0 + k * BEAT, 0.7)
        for k in (1, 3):
            clap(t0 + k * BEAT, 0.24)
        for k8 in range(8):
            hat(t0 + k8 * BEAT / 2, 0.035)
        if b % 4 == 3:
            for k, bg in ((3.0, 0.8), (3.25, 0.7), (3.5, 1.0), (3.75, 0.9)):
                tom(t0 + k * BEAT, bg, pan=0.25 if k % 0.5 else -0.25)
    elif kind == "arena":
        for k in (0.0, 2.0, 2.5):
            kick(t0 + k * BEAT, 0.85 * amp if k != 2.5 else 0.6 * amp)
        for k in (1, 3):
            snare(t0 + k * BEAT, 0.3 if big else 0.26)
            clap(t0 + k * BEAT, 0.14)
        for k8 in range(8):
            hat(t0 + k8 * BEAT / 2, 0.05 if k8 % 2 else 0.032, open_=(k8 == 7), pan=-0.25)
        tom(t0 + 3.5 * BEAT, 0.8, pan=0.2)
        if b % 4 == 3:
            for k, bg in ((3.0, 1.0), (3.25, 0.9), (3.5, 0.8), (3.75, 0.7)):
                tom(t0 + k * BEAT, bg, pan=-0.3 + 0.2 * (k - 3) * 4)
    elif kind == "house":
        for k in range(4):
            kick(t0 + k * BEAT, 0.8 * amp)
        for k in (1, 3):
            clap(t0 + k * BEAT, 0.17)
        for k in range(4):
            hat(t0 + (k + 0.5) * BEAT, 0.06, open_=True, pan=0.25)
        for s16 in range(16):
            if s16 % 4 != 2:
                hat(t0 + s16 * BEAT / 4, 0.018, pan=-0.3)


def accent_bar(t0, b, big):
    kind = S["accent"]
    if kind == "anvil":
        for k in (0.5, 2.5) if big else (2.5,):
            anvil(t0 + k * BEAT, 0.07, pan=0.35 if k < 1 else -0.25)
    elif kind == "shaker":
        for s16 in range(16):
            shaker(t0 + s16 * BEAT / 4, 0.03 if s16 % 2 else 0.018)
    elif kind == "stab" and b % 2 == 0:
        _, chord = S["chords"][b % 4]
        for n_ in chord:
            lead(n_, t0 + 3.5 * BEAT, 0.035, pan=0.2)
    elif kind == "stadium":
        _, chord = S["chords"][b % 4]
        for k in (0.0, 1.5, 3.5) if big else (0.0, 3.5):
            for n_ in chord[1:]:
                lead(n_, t0 + k * BEAT, 0.03, pan=0.25 if k else -0.25, length=0.12)
    elif kind == "sub" and big:
        tone(hz(26), t0, 0.5, 0.18, release=0.6, decay=0.5)


bars = int(SECONDS / BAR) + 1
for b in range(bars):
    t0 = b * BAR
    root, chord = S["chords"][b % 4]
    sec = section(t0 + 0.01)
    pad_chord(chord, t0, BAR, S["pad"] * (1.2 if sec in ("intro", "hush", "outro") else 1.0))
    if sec in ("groove", "drop"):
        big = sec == "drop"
        beat_bar(t0, b, big)
        accent_bar(t0, b, big)
        # Bass: on the kick pattern.
        hits = {"trap": ((0, 1.6), (1.75, 0.7), (2.5, 1.4)), "house": ((0.5, 0.4), (1.5, 0.4), (2.5, 0.4), (3.5, 0.4)), "boombap": ((0, 1.4), (1.5, 0.9), (2.5, 1.3)), "break": ((0, 1.2), (1.5, 0.6), (2.25, 0.4), (2.75, 1.0)), "stomp": ((0, 0.45), (0.5, 0.45), (1, 0.45), (1.5, 0.45), (2, 0.45), (2.5, 0.45), (3, 0.45), (3.5, 0.45))}
        hits["arena"] = hits["stomp"]
        hits = hits[S["beat"]]
        for k, d in hits:
            bass(root + 12 if root < 36 else root, t0 + k * BEAT, d * BEAT * 0.9, 0.3 if big else 0.26, slide=-2 if S["beat"] == "break" else 0)
        # The lead riff, every other bar in the groove, every bar in the drop (an octave up).
        if big or b % 2 == 0:
            up = 12 if big else 0
            for k, n_ in enumerate(S["riff"]):
                if n_ is not None:
                    lead(n_ + up, t0 + k * BEAT / 2 + swing(k), 0.085 if big else 0.08, pan=0.3 if k % 2 else -0.2)
        if S["lead"] == "rhodes":
            for n_ in chord:
                lead(n_, t0 + swing(1), 0.03, length=BAR * 0.45)
                lead(n_, t0 + 2.5 * BEAT, 0.022, length=BEAT)
    elif sec == "intro":
        # A soft pulse and the riff's first notes, building toward the reveal.
        kick(t0, 0.35)
        for k8 in range(8):
            hat(t0 + k8 * BEAT / 2, 0.012 + 0.02 * (t0 / max(REVEAL, 1)), pan=0.3)
        for k, n_ in enumerate(S["riff"][:8]):
            if n_ is not None:
                lead(n_, t0 + k * BEAT / 2, 0.05, pan=-0.2 + 0.08 * k)
    elif sec == "hush":
        lead(S["riff"][0], t0, 0.07)
        tone(hz(root), t0, BAR, 0.12, release=0.4, harmonics=((1, 1.0), (2, 0.2)), bus=True)
    if S["accent"] == "crackle":
        for _ in range(int(BAR * 14)):
            noise(t0 + random.uniform(0, BAR), 0.004, random.uniform(0.01, 0.05), decay=0.0015, pan=random.uniform(-0.6, 0.6))

# Into the reveal and the hero feature: risers, a fill, and impacts on the hits.
noise(REVEAL - 2.0, 2.0, 0.11, rise=True)
noise(HERO - 2.5, 2.5, 0.12, rise=True)
t = HERO - 2 * BEAT
gap = BEAT / 2
while t < HERO - 0.03:
    (tom if S["beat"] in ("stomp", "break", "arena") else snare)(t, 0.5 + 0.5 * (1 - (HERO - t) / (2 * BEAT)))
    t += gap
    gap = max(BEAT / 8, gap * 0.8)
if S.get("crowd"):
    crowd(HERO - 0.6, min(12.0, HERO_END - HERO + 2), 0.11)
for h in HITS:
    kick(h, 0.95)
    noise(h, 1.6, 0.12, decay=0.45)
    tone(hz(26), h, 0.4, 0.28, release=1.0, decay=0.55)
    if S["accent"] == "anvil":
        anvil(h, 0.1, pan=0)
root, chord = S["chords"][0]
for i, n_ in enumerate([root + 12] + chord + [chord[-1] + 12]):
    tone(hz(n_), OUTRO + 0.05, 5.0, 0.06, pan=(i - 2.5) * 0.2, attack=0.08, release=4.0, harmonics=((1, 1.0), (2, 0.2)))
for k, n_ in enumerate(chord + [chord[0] + 12, chord[1] + 12]):
    lead(n_, OUTRO + k * 0.11, 0.07, pan=-0.35 + k * 0.12)

# Mix: pads and bass duck under the kick in the busy sections; a short room; a soft limiter.
for i in range(min(N, int(SECONDS * RATE))):
    t = i / RATE
    g = 1.0
    if section(t) in ("groove", "drop"):
        g = 0.4 + 0.6 * min(1.0, ((t % BEAT) / BEAT) / 0.5)
    L[i] += PL[i] * g
    R[i] += PR[i] * g
for delay, gain in ((0.029, 0.18), (0.047, 0.15), (0.083, 0.12), (0.131, 0.09), (0.199, 0.06), (0.293, 0.04)):
    d = int(delay * RATE)
    for i in range(N - 1, d - 1, -1):
        L[i] += R[i - d] * gain
        R[i] += L[i - d] * gain
peak = max(max(abs(x) for x in L), max(abs(x) for x in R)) or 1.0
drive = 1.6
scale = 0.9 / math.tanh(drive)
frames = bytearray()
for i in range(int(SECONDS * RATE)):
    frames += struct.pack("<hh", int(math.tanh(drive * L[i] / peak) * scale * 32767), int(math.tanh(drive * R[i] / peak) * scale * 32767))
with wave.open(OUT, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(RATE)
    w.writeframes(bytes(frames))
print(f"  music: {SECONDS:.1f}s, style {STYLE_NAME}, {BPM:.0f} bpm, {len(HITS)} impacts")
