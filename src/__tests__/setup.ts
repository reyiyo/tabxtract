// TabXtract - GPL-3.0-or-later. See LICENSE.
//
// Vitest runs without globals, and Testing Library only registers its
// automatic cleanup when a global `afterEach` exists. Without this, the DOM of
// one test leaks into the next.
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});
