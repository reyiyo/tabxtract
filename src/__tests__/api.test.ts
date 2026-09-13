// TabXtract - GPL-3.0-or-later. See LICENSE.
import { describe, expect, it } from "vitest";

import { parseHandshake } from "../handshake";

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
});
