"use client";

import { dictionaries } from "@/lib/i18n";

/** Shown when the server cannot be reached. The user's language is not known yet, so both are shown. */
export default function Unreachable({ onRetry }: { onRetry: () => void }) {
  const { en, fa } = dictionaries;
  return (
    <main className="flex h-dvh items-center justify-center bg-page p-6">
      <section
        role="alert"
        data-testid="unreachable"
        className="flex w-full max-w-xl flex-col gap-4 rounded-xl border border-surface-border bg-surface p-6 shadow-card"
      >
        <div lang="en" dir="ltr" className="flex flex-col gap-1.5">
          <h1 className="text-lg font-semibold text-heading">{en.unreachable.title}</h1>
          <p className="text-sm leading-6 text-secondary">{en.unreachable.text}</p>
        </div>
        <div lang="fa" dir="rtl" className="flex flex-col gap-1.5">
          <h2 className="text-lg font-semibold text-heading">{fa.unreachable.title}</h2>
          <p className="text-sm leading-6 text-secondary">{fa.unreachable.text}</p>
        </div>
        <div>
          <button
            type="button"
            onClick={onRetry}
            className="h-10 rounded-lg bg-primary px-4 text-sm font-semibold text-white hover:bg-primary-hover"
          >
            {en.unreachable.retry} · {fa.unreachable.retry}
          </button>
        </div>
      </section>
    </main>
  );
}
