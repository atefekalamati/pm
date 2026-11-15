import { create } from "zustand";
import { useStore } from "./store";
import type { LocalizedText } from "./types";

export interface User {
  username: string;
  name: LocalizedText;
  initials: LocalizedText;
}

type Status = "checking" | "signed-in" | "signed-out";

/** Who is signed in. Kept in memory only: the session itself is an HttpOnly cookie set by the backend. */
export const useSession = create<{ status: Status; user: User | null }>(() => ({ status: "checking", user: null }));

function endSession() {
  useStore.getState().closeDialog();
  useSession.setState({ status: "signed-out", user: null });
}

/** Every call to the backend goes through here, so an expired session anywhere returns the user to sign-in. */
export async function api(path: string, init: RequestInit = {}) {
  const response = await fetch(path, {
    ...init,
    cache: "no-store",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  if (response.status === 401 && path !== "/api/login") endSession();
  return response;
}

/** Asks the backend whether the session is still valid. Network errors keep the current state. */
export async function checkSession() {
  try {
    const response = await api("/api/me");
    if (response.ok) useSession.setState({ status: "signed-in", user: await response.json() });
  } catch {
    // The server cannot be reached. On first load show the sign-in page rather than nothing.
    if (useSession.getState().status === "checking") useSession.setState({ status: "signed-out" });
  }
}

export async function signIn(username: string, password: string): Promise<"ok" | "invalid" | "offline"> {
  try {
    const response = await api("/api/login", { method: "POST", body: JSON.stringify({ username, password }) });
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
