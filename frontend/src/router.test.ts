import { describe, expect, it } from "vitest";
import { href, parse } from "./router";

describe("router", () => {
  it("round-trips every page", () => {
    for (const route of [
      { page: "home" },
      { page: "setup", mode: "sales" },
      { page: "bout", id: "0123456789abcdef" },
      { page: "record", mode: "meeting" },
    ] as const) {
      expect(parse(href(route))).toEqual(route);
    }
  });

  it("falls back safely on anything unknown", () => {
    expect(parse("#/new/chess")).toEqual({ page: "home" });
    expect(parse("#/bout/not-an-id")).toEqual({ page: "home" });
    expect(parse("#/record")).toEqual({ page: "record", mode: "debate" });
    expect(parse("")).toEqual({ page: "home" });
  });
});
