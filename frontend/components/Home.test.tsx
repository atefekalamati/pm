import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Home from "@/app/page";
import { createSeed } from "@/data/fixtures";
import { useSession } from "@/lib/session";
import { useStore } from "@/lib/store";
import { fetchMock } from "../vitest.server";
import NoticeToast, { NOTICE_MS } from "./NoticeToast";

const ME = { id: "user-1", username: "user", name: { en: "Atefe Kalamati", fa: "عاطفه کلماتی" }, initials: { en: "AK", fa: "عک" } };

function boardAnswer(language = "en") {
  const seed = createSeed();
  return Response.json({
    currentUserId: "sara",
    language,
    density: "comfortable",
    ...seed,
    columns: seed.columns.map((c) => ({ ...c, name: null })),
    messages: {},
  });
}

/** Answers /api/me and /api/board like a server would; the board answer can be held back. */
function serve({ me = 200, board = () => boardAnswer() }: { me?: number; board?: () => Response | Promise<Response> } = {}) {
  fetchMock.mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/me") return me === 200 ? Response.json(ME) : new Response(null, { status: me });
    if (url === "/api/board") return board();
    return new Response(null, { status: 204 });
  });
}

beforeEach(() => {
  useSession.setState({ status: "checking", user: null });
  useStore.getState().reset(); // a page that has just opened: nothing loaded
});

afterEach(() => {
  vi.useRealTimers();
});

describe("opening the page", () => {
  it("shows the sign-in page when nobody is signed in, and no board", async () => {
    serve({ me: 401 });
    render(<Home />);
    expect(await screen.findByRole("heading", { level: 2, name: "Welcome back" })).toBeInTheDocument();
    expect(screen.queryByTestId("card")).not.toBeInTheDocument();
    expect(screen.queryByTestId("board-skeleton")).not.toBeInTheDocument();
  });

  it("shows a skeleton until the board arrives: never sample data or an empty board", async () => {
    let arrive: (response: Response) => void = () => {};
    serve({ board: () => new Promise<Response>((resolve) => (arrive = resolve)) });
    render(<Home />);

    const skeleton = await screen.findByRole("status", { name: "Loading your board" });
    expect(skeleton).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByTestId("card")).not.toBeInTheDocument();
    expect(screen.queryByTestId("column-todo")).not.toBeInTheDocument(); // not even empty columns
    expect(screen.queryByText("Fix mixed text direction")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();

    arrive(boardAnswer());
    expect(await screen.findAllByTestId("card")).toHaveLength(10);
    expect(screen.queryByTestId("board-skeleton")).not.toBeInTheDocument();
  });

  it("opens in the language and direction the server has saved", async () => {
    serve({ board: () => boardAnswer("fa") });
    render(<Home />);
    expect((await screen.findAllByText("اصلاح جهت متن ترکیبی")).length).toBeGreaterThan(0);
    expect(document.documentElement).toHaveAttribute("lang", "fa");
    expect(document.documentElement).toHaveAttribute("dir", "rtl");
  });
});

describe("when the server cannot be reached", () => {
  it("says so in both languages and offers Try again, when the first check fails", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    render(<Home />);
    const message = await screen.findByTestId("unreachable");
    expect(message).toHaveTextContent("Can't reach the server");
    expect(message).toHaveTextContent("ارتباط با سرور برقرار نشد");
    expect(screen.queryByRole("heading", { name: "Welcome back" })).not.toBeInTheDocument(); // not mistaken for "signed out"

    serve();
    await userEvent.click(screen.getByRole("button", { name: /Try again/ }));
    expect(await screen.findAllByTestId("card")).toHaveLength(10);
  });

  it("offers Try again when the board cannot be loaded after sign-in, and loads it on retry", async () => {
    serve({ board: () => new Response(null, { status: 500 }) });
    render(<Home />);
    expect(await screen.findByTestId("unreachable")).toBeInTheDocument();
    expect(screen.queryByTestId("card")).not.toBeInTheDocument();

    serve();
    await userEvent.click(screen.getByRole("button", { name: /Try again/ }));
    expect(await screen.findAllByTestId("card")).toHaveLength(10);
    expect(screen.queryByTestId("unreachable")).not.toBeInTheDocument();
  });

  it("treats a failing server on the first check like an unreachable one", async () => {
    serve({ me: 500 });
    render(<Home />);
    expect(await screen.findByTestId("unreachable")).toBeInTheDocument();
  });
});

describe("a session that ends while the board is open", () => {
  it("returns to sign-in at once, with nothing of the board left in the store", async () => {
    serve();
    render(<Home />);
    await screen.findAllByTestId("card");

    fetchMock.mockImplementation(async () => new Response(null, { status: 401 }));
    act(() => useStore.getState().updateCard("c1", { title: "x", details: "", priority: "low", dueDate: null, labelIds: [], memberIds: [] }));
    expect(await screen.findByRole("heading", { level: 2, name: "Welcome back" })).toBeInTheDocument();
    expect(screen.queryByTestId("card")).not.toBeInTheDocument();
    expect(useStore.getState()).toMatchObject({ boardStatus: "idle", cards: {}, notice: null });
  });
});

describe("the toast for a change that was undone", () => {
  it("is shown in the current language, can be closed, and goes away by itself", () => {
    vi.useFakeTimers();
    useStore.setState({ notice: { id: 1 } });
    render(<NoticeToast />);
    expect(screen.getByRole("alert")).toHaveTextContent("That change could not be saved, so it was undone.");
    act(() => vi.advanceTimersByTime(NOTICE_MS));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    act(() => useStore.setState({ notice: { id: 2 } }));
    expect(screen.getByRole("alert")).toBeInTheDocument(); // a new failure shows it again
    act(() => screen.getByRole("button", { name: "Close" }).click());
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("speaks Persian when the language is Persian", () => {
    useStore.setState({ notice: { id: 1 }, language: "fa" });
    render(<NoticeToast />);
    expect(screen.getByRole("alert")).toHaveTextContent("این تغییر ذخیره نشد و برگردانده شد.");
  });

  it("appears on the board when a change is refused", async () => {
    serve();
    render(<Home />);
    await screen.findAllByTestId("card");
    fetchMock.mockImplementation(async (input) =>
      String(input).includes("/move") ? new Response(null, { status: 500 }) : String(input) === "/api/board" ? boardAnswer() : new Response(null, { status: 204 }),
    );
    act(() => useStore.getState().moveCard("c1", "done", 0));
    expect(await screen.findByTestId("notice-toast")).toBeInTheDocument();
    await waitFor(() => expect(useStore.getState().columns.find((c) => c.id === "done")!.cardIds).not.toContain("c1"));
  });
});
