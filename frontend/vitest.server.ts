import { vi } from "vitest";

/** Every request the app makes in a unit test lands here. Tests read it, or make a request fail. */
export const fetchMock = vi.fn<typeof fetch>();

export interface Sent {
  method: string;
  url: string;
  body: unknown;
  contentType: string | null;
}

/** The requests sent so far, oldest first. A binary body is returned as the Blob itself. */
export const sent = (): Sent[] =>
  fetchMock.mock.calls.map(([input, init]) => {
    const raw = init?.body;
    const headers = new Headers(init?.headers);
    return {
      method: init?.method ?? "GET",
      url: String(input),
      body: typeof raw === "string" ? JSON.parse(raw) : raw,
      contentType: headers.get("Content-Type"),
    };
  });

/** A minimal stand-in for the backend: success for everything, with the few answers the store reads. */
export function installFakeServer() {
  let counter = 0;
  const uploads = new Map<string, string>(); // image id -> the file name it was uploaded with
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (input, init) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    if (method === "POST" && /^\/api\/spaces\/[^/]+\/messages$/.test(url)) {
      const body = JSON.parse(String(init!.body));
      return Response.json(
        {
          id: `server-${++counter}`,
          type: "message",
          authorId: "sara",
          createdAt: new Date().toISOString(),
          ...(body.text !== undefined && { text: body.text }),
          ...(body.imageId && { image: { file: uploads.get(body.imageId), src: `/api/images/${body.imageId}` } }),
        },
        { status: 201 },
      );
    }
    if (method === "POST" && url.startsWith("/api/images")) {
      const id = `image-${++counter}`;
      uploads.set(id, decodeURIComponent(new URL(url, "http://x").searchParams.get("fileName") ?? ""));
      return Response.json({ id }, { status: 201 });
    }
    if (url === "/api/board") return new Response(null, { status: 503 }); // tests that need a board set their own answer
    return new Response(null, { status: 204 });
  });
  vi.stubGlobal("fetch", fetchMock);
}

/** Makes the requests whose URL contains `part` (and use `method`, when given) fail the way a refusing server or a dropped connection does. */
export function failRequests(part: string, how: number | "network" = 500, method?: string) {
  const normal = fetchMock.getMockImplementation()!;
  fetchMock.mockImplementation(async (input, init) => {
    if (String(input).includes(part) && (!method || (init?.method ?? "GET") === method)) {
      if (how === "network") throw new TypeError("Failed to fetch");
      return new Response(null, { status: how });
    }
    return normal(input, init);
  });
}
