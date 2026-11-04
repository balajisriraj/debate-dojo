import { describe, expect, it } from "vitest";
import cases from "../../fixtures/delivery-cases.json";
import { countFillers, longestPause, totalFillers, wordCount, wordsPerMinute } from "./delivery";

// The same fixture drives the server's implementation (backend/tests/test_metrics.py).
describe("filler words", () => {
  it.each(cases.fillers)("$text", ({ text, expect: want }) => {
    const got = Object.fromEntries(Object.entries(countFillers(text)).filter(([, n]) => n > 0));
    expect(got).toEqual(want);
  });

  it("totals across kinds", () => {
    expect(totalFillers(countFillers("um, like, you know, basically"))).toBe(4);
  });
});

describe("words and pace", () => {
  it.each(cases.words)("counts words in $text", ({ text, words }) => {
    expect(wordCount(text)).toBe(words);
  });

  it.each(cases.wpm)("$words words in $seconds s", ({ words, seconds, wpm }) => {
    expect(wordsPerMinute(words, seconds)).toBe(wpm);
  });
});

describe("longest pause", () => {
  it("is the widest gap between speech results, including the start and the end", () => {
    expect(longestPause(0, [500, 1200, 4800, 5000], 5600)).toBe(3.6);
    expect(longestPause(0, [3000], 3200)).toBe(3);
  });

  it("is unknown when nothing was heard", () => {
    expect(longestPause(0, [], 9000)).toBeNull();
  });
});
