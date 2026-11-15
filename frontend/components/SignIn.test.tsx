import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { checkSession, retrySession, signOut, useSession } from "@/lib/session";
import { useStore } from "@/lib/store";
import Sidebar from "./Sidebar";
import SignIn from "./SignIn";

const ME = {
  id: "user-1",
  username: "user",
  name: { en: "Atefe Kalamati", fa: "عاطفه کلماتی" },
  initials: { en: "AK", fa: "عک" },
};

const fetchMock = vi.fn<typeof fetch>();
const reply = (status: number, body?: unknown) =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  useSession.setState({ status: "checking", user: null });
});

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

async function fillAndSubmit(username: string, password: string) {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Username"), username);
  await user.type(screen.getByLabelText("Password"), password);
  await user.click(screen.getByRole("button", { name: "Sign in" }));
}

describe("SignIn", () => {
  it("shows the logo, the form and its own language switcher", () => {
    render(<SignIn />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Tidy.");
    expect(screen.getByRole("heading", { level: 2, name: "Welcome back" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Language" })).toBeInTheDocument();
  });

  it("signs in with the entered credentials", async () => {
    fetchMock.mockResolvedValueOnce(reply(200, ME));
    render(<SignIn />);
    await fillAndSubmit("user", "password");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/login",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ username: "user", password: "password" }) }),
    );
    expect(useSession.getState()).toEqual({ status: "signed-in", user: ME });
  });

  it("shows one message for a wrong username or password and clears the password", async () => {
    fetchMock.mockResolvedValue(reply(401, { detail: "Invalid username or password" }));
    render(<SignIn />);
    await fillAndSubmit("user", "nope");
    expect(screen.getByRole("alert")).toHaveTextContent("Incorrect username or password.");
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByLabelText("Password")).toHaveFocus();
    expect(screen.getByLabelText("Username")).toHaveValue("user");
    expect(useSession.getState().status).toBe("checking");
  });

  it("says so when the server cannot be reached", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    render(<SignIn />);
    await fillAndSubmit("user", "password");
    expect(screen.getByRole("alert")).toHaveTextContent("Can't reach the server");
  });

  it("is fully translated and keeps the error when the language changes", async () => {
    fetchMock.mockResolvedValue(reply(401));
    render(<SignIn />);
    await fillAndSubmit("x", "y");
    await userEvent.click(screen.getByRole("button", { name: "فارسی" }));
    expect(useStore.getState().language).toBe("fa");
    expect(screen.getByRole("heading", { level: 2, name: "خوش آمدید" })).toBeInTheDocument();
    expect(screen.getByLabelText("نام کاربری")).toBeInTheDocument();
    expect(screen.getByLabelText("رمز عبور")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "ورود" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("نام کاربری یا رمز عبور نادرست است.");
  });
});

/** Like the page: the sidebar is only there while signed in. */
function SignedInShell() {
  const status = useSession((s) => s.status);
  return status === "signed-in" ? <Sidebar /> : null;
}

describe("account menu", () => {
  it("opens from ⋯ and signs out", async () => {
    useSession.setState({ status: "signed-in", user: ME });
    fetchMock.mockResolvedValueOnce(reply(204));
    render(<SignedInShell />);
    const toggle = within(screen.getByTestId("profile")).getByRole("button", { name: "Account menu" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    const item = screen.getByRole("menuitem", { name: "Sign out" });
    expect(item).toHaveFocus();
    await userEvent.click(item);
    expect(fetchMock).toHaveBeenCalledWith("/api/logout", expect.objectContaining({ method: "POST" }));
    expect(useSession.getState().status).toBe("signed-out");
  });

  it("closes with Escape and returns focus to ⋯", async () => {
    render(<Sidebar />);
    const toggle = screen.getByRole("button", { name: "Account menu" });
    await userEvent.click(toggle);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(toggle).toHaveFocus();
  });
});

describe("session", () => {
  it("is signed in when /api/me answers", async () => {
    fetchMock.mockResolvedValueOnce(reply(200, ME));
    await checkSession();
    expect(useSession.getState()).toEqual({ status: "signed-in", user: ME });
  });

  it("ends, and closes any dialog, when any API call returns 401", async () => {
    useSession.setState({ status: "signed-in", user: ME });
    act(() => useStore.getState().openDialog({ type: "help" }));
    fetchMock.mockResolvedValueOnce(reply(401));
    await api("/api/anything");
    expect(useSession.getState()).toEqual({ status: "signed-out", user: null });
    expect(useStore.getState().dialog).toBeNull();
  });

  it("stays signed in when the server is briefly unreachable", async () => {
    useSession.setState({ status: "signed-in", user: ME });
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await checkSession();
    expect(useSession.getState().status).toBe("signed-in");
  });

  it("says the server is unreachable, not signed out, when the first check cannot reach it", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await checkSession();
    expect(useSession.getState().status).toBe("unreachable");
  });

  it("treats a failing server on the first check as unreachable too", async () => {
    fetchMock.mockResolvedValueOnce(reply(500));
    await checkSession();
    expect(useSession.getState().status).toBe("unreachable");
  });

  it("tries again when asked, and signs in or out depending on the answer", async () => {
    useSession.setState({ status: "unreachable", user: null });
    fetchMock.mockResolvedValueOnce(reply(200, ME));
    retrySession();
    expect(useSession.getState().status).toBe("checking");
    await vi.waitFor(() => expect(useSession.getState().status).toBe("signed-in"));
    useSession.setState({ status: "unreachable", user: null });
    fetchMock.mockResolvedValueOnce(reply(401));
    retrySession();
    await vi.waitFor(() => expect(useSession.getState().status).toBe("signed-out"));
  });

  it("clears the board of the signed-out user", async () => {
    useSession.setState({ status: "signed-in", user: ME });
    fetchMock.mockResolvedValueOnce(reply(204));
    await signOut();
    expect(useStore.getState()).toMatchObject({ boardStatus: "idle", cards: {}, columns: [], currentUserId: "" });
  });

  it("signs out locally even if the server cannot be reached", async () => {
    useSession.setState({ status: "signed-in", user: ME });
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await signOut();
    expect(useSession.getState().status).toBe("signed-out");
  });
});
