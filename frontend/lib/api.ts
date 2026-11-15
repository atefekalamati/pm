import type { Card, Column, ColumnId, Density, Language, Member, Message } from "./types";
import { currentTime } from "./utils";

export class ApiError extends Error {
  constructor(readonly status: number) {
    super(`The server answered ${status}`);
  }
}

let unauthorized: () => void = () => {};

/** Set once by lib/session: what to do when the server says the session is gone. */
export const onUnauthorized = (handler: () => void) => {
  unauthorized = handler;
};

/** Every call to the backend goes through here, so an ended session anywhere returns the user to sign-in. */
export async function api(path: string, init: RequestInit = {}) {
  const response = await fetch(path, {
    ...init,
    cache: "no-store",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...init.headers },
  });
  if (response.status === 401 && path !== "/api/login") unauthorized();
  return response;
}

/** Like api(), but an answer that is not a success throws, so the caller can undo what it showed. */
export async function request(path: string, init: RequestInit = {}) {
  const response = await api(path, init);
  if (!response.ok) throw new ApiError(response.status);
  return response;
}

export const json = (body: unknown) => JSON.stringify(body);

// ---- the board as the server sends it -> the shape of the store --------------------------------------

export interface RawMessage {
  id: string;
  type: string;
  authorId: string;
  createdAt: string;
  [field: string]: unknown;
}

export interface RawBoard {
  currentUserId: string;
  language: Language;
  density: Density;
  columns: { id: string; name: string | null; cardIds: string[]; wipLimit: number | null; collapsed: boolean }[];
  cards: Record<string, Card>;
  members: Record<string, Member>;
  messages: Record<string, RawMessage[]>;
  unread: Record<string, number>;
}

/** The server stamps messages with a UTC time; the screens show the local HH:mm. */
export function parseMessage(raw: RawMessage): Message {
  const { createdAt, byAi: _byAi, ...rest } = raw;
  return { ...rest, time: currentTime(new Date(createdAt)) } as Message;
}

export function parseBoard(raw: RawBoard) {
  return {
    currentUserId: raw.currentUserId,
    language: raw.language,
    density: raw.density,
    columns: raw.columns.map((c): Column => ({ id: c.id as ColumnId, name: c.name ?? undefined, cardIds: c.cardIds, wipLimit: c.wipLimit, collapsed: c.collapsed })),
    cards: raw.cards,
    members: raw.members,
    messages: Object.fromEntries(Object.entries(raw.messages).map(([space, list]) => [space, list.map(parseMessage)])),
    unread: raw.unread,
  };
}
