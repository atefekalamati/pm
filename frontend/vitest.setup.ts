import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";
import { GENERAL_SPACE } from "@/data/constants";
import { CURRENT_USER_ID, createSeed } from "@/data/fixtures";
import { useStore, whenIdle } from "@/lib/store";
import { installFakeServer } from "./vitest.server";

// jsdom does not implement the native modal dialog.
HTMLDialogElement.prototype.showModal = function () {
  this.setAttribute("open", "");
};
HTMLDialogElement.prototype.close = function () {
  this.removeAttribute("open");
  this.dispatchEvent(new Event("close"));
};

beforeEach(() => {
  localStorage.clear();
  installFakeServer();
  // Start every test with the sample board loaded, as if the server had just sent it.
  useStore.getState().reset();
  useStore.setState({
    ...createSeed(),
    currentUserId: CURRENT_USER_ID,
    language: "en",
    density: "comfortable",
    view: "board",
    activeSpace: GENERAL_SPACE,
    boardStatus: "ready",
  });
});

afterEach(async () => {
  cleanup();
  await whenIdle(); // no request of this test may reach into the next one
});
