import type { Label } from "@/lib/types";

export const GENERAL_SPACE = "general";
export const MAX_IMAGE_BYTES = 2 * 1024 * 1024;

/** The board's labels. The backend creates the same five for every board; the id is the slug the colours use. */
export const labels: Label[] = [
  { id: "design", name: { en: "Design", fa: "طراحی" } },
  { id: "frontend", name: { en: "Frontend", fa: "فرانت‌اند" } },
  { id: "bug", name: { en: "Bug", fa: "باگ" } },
  { id: "docs", name: { en: "Docs", fa: "مستندات" } },
  { id: "testing", name: { en: "Testing", fa: "تست" } },
];
