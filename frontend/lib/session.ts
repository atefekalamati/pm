import { create } from "zustand";
import { api, json, onUnauthorized } from "./api";
import { useStore } from "./store";
import type { LocalizedText } from "./types";

export interface User {
  id: string;
  username: string;
  name: LocalizedText;
  initials: LocalizedText;
}

/** unreachable: the server could not be reached (or failed) when the page opened. */
type Status = "checking" | "signed-in" | "signed-out" | "unreachable";

/** Who is signed in. Kept in memory only: the session itself is an HttpOnly cookie set by the backend. */
export const useSession = create<{ status: Status; user: User | null }>(() => ({ status: "checking", user: null }));

/** Back to the sign-in page, with nothing of the last user left on the screen. */
function endSession() {
  // The page leaves the board first, then the data goes: nothing ever renders a board without its data.
  useSession.setState({ status: "signed-out", user: null });
  useStore.getState().reset();
}

// Any answer "not signed in" from the server, anywhere, ends the session here.
onUnauthorized(endSession);

/** Asks the backend whether the session is still valid. A brief network error keeps the current state. */
export async function checkSession() {
  const firstTime = () => useSession.getState().status === "checking";
  try {
    const response = await api("/api/me");
    if (response.ok) useSession.setState({ status: "signed-in", user: await response.json() });
    else if (response.status !== 401 && firstTime()) useSession.setState({ status: "unreachable" });
  } catch {
    if (firstTime()) useSession.setState({ status: "unreachable" });
  }
}

/** The "Try again" button of the unreachable page. */
export function retrySession() {
  useSession.setState({ status: "checking" });
  void checkSession();
}

export async function signIn(username: string, password: string): Promise<"ok" | "invalid" | "offline"> {
  try {
    const response = await api("/api/login", { method: "POST", body: json({ username, password }) });
    if (response.status === 401) return "invalid";
    if (!response.ok) return "offline";
    useSession.setState({ status: "signed-in", user: await response.json() });
    return "ok";
  } catch {
    return "offline";
  }
}

export async function signOut() {
  try {
    await api("/api/logout", { method: "POST" });
  } catch {
    // Signed out locally even if the server cannot be reached.
  }
  endSession();
}
