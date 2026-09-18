// TabXtract - GPL-3.0-or-later. See LICENSE.
import { describe, expect, it } from "vitest";

import { HANDSHAKE_PREFIX, parseHandshake } from "../handshake";

describe("parseHandshake", () => {
  it("reads the port and token from the line the sidecar emits", () => {
    const line = 'TABXTRACT_READY {"port": 51234, "token": "abc", "pid": 42}';
    expect(parseHandshake(line)).toEqual({ port: 51234, token: "abc" });
  });

  it("ignores any other line of stdout", () => {
    expect(parseHandshake("INFO: Uvicorn running")).toBeNull();
    expect(parseHandshake("TABXTRACT_READY no-es-json")).toBeNull();
  });

  it("rejects a handshake with no token: without it the API is wide open", () => {
    expect(parseHandshake('TABXTRACT_READY {"port": 51234}')).toBeNull();
  });

  it.each([
    ["lower-case prefix", 'tabxtract_ready {"port": 1, "token": "t"}'],
    ["leading whitespace", ' TABXTRACT_READY {"port": 1, "token": "t"}'],
    ["prefix without its trailing space", 'TABXTRACT_READY{"port": 1, "token": "t"}'],
    ["prefix in the middle of the line", 'log: TABXTRACT_READY {"port": 1, "token": "t"}'],
  ])("rejects a wrong prefix: %s", (_case, line) => {
    expect(parseHandshake(line)).toBeNull();
  });

  it.each([
    ["truncated JSON", '{"port": 51234, "token": "ab'],
    ["empty payload", ""],
    ["trailing garbage", '{"port": 1, "token": "t"} extra'],
  ])("rejects broken JSON: %s", (_case, payload) => {
    expect(parseHandshake(HANDSHAKE_PREFIX + payload)).toBeNull();
  });

  it.each([
    ["port as a string", '{"port": "51234", "token": "t"}'],
    ["token as a number", '{"port": 51234, "token": 42}'],
    ["missing port", '{"token": "t"}'],
    ["null port", '{"port": null, "token": "t"}'],
    ["JSON null", "null"],
    ["JSON array", "[51234, \"t\"]"],
    ["JSON number", "51234"],
  ])("rejects fields of the wrong type: %s", (_case, payload) => {
    expect(parseHandshake(HANDSHAKE_PREFIX + payload)).toBeNull();
  });

  it("drops fields other than port and token", () => {
    const parsed = parseHandshake(HANDSHAKE_PREFIX + '{"port": 1, "token": "t", "pid": 9, "x": true}');
    expect(parsed).toStrictEqual({ port: 1, token: "t" });
  });

  // Documents current behaviour rather than endorsing it: the parser only
  // checks types, so a port no socket can have still passes. backend.ts's
  // env fallback, by contrast, treats port 0 as absent.
  it("accepts any numeric port, including 0 and negatives", () => {
    expect(parseHandshake(HANDSHAKE_PREFIX + '{"port": 0, "token": "t"}')).toEqual({ port: 0, token: "t" });
    expect(parseHandshake(HANDSHAKE_PREFIX + '{"port": -1, "token": "t"}')).toEqual({ port: -1, token: "t" });
  });
});
