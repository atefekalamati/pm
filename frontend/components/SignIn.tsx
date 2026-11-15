"use client";

import { useState, type FormEvent } from "react";
import { useT } from "@/lib/i18n";
import { signIn } from "@/lib/session";
import { useStore } from "@/lib/store";
import { Logo, Segmented, SegmentButton } from "./ui";

const field = "flex flex-col gap-1.5 text-[13px] font-semibold text-heading";
const input =
  "h-10 rounded-lg border border-surface-border bg-surface-hover px-3 text-[14px] font-normal text-ink hover:border-surface-hover-border";

export default function SignIn() {
  const { t, language } = useT();
  const setLanguage = useStore((s) => s.setLanguage);
  const [error, setError] = useState<"invalid" | "offline" | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    setBusy(true);
    setError(null);
    const result = await signIn(String(data.get("username")), String(data.get("password")));
    if (result === "ok") return;
    setBusy(false);
    setError(result);
    const password = form.elements.namedItem("password") as HTMLInputElement;
    password.value = "";
    password.focus();
  }

  return (
    <main className="flex min-h-dvh items-center justify-center bg-page p-6">
      <section
        aria-labelledby="sign-in-title"
        className="flex w-full max-w-[400px] flex-col gap-6 rounded-xl border border-surface-border bg-surface p-7 shadow-card"
      >
        <div className="flex items-center gap-2.5">
          <Logo />
          <div className="ms-auto w-[156px]">
            <Segmented label={t.langLabel}>
              <SegmentButton active={language === "en"} onClick={() => setLanguage("en")} className="flex-1 font-brand">
                English
              </SegmentButton>
              <SegmentButton active={language === "fa"} onClick={() => setLanguage("fa")} className="flex-1 [font-family:var(--font-vazirmatn)]">
                فارسی
              </SegmentButton>
            </Segmented>
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <h2 id="sign-in-title" className="text-[20px]/7 font-semibold text-heading">
            {t.signIn.title}
          </h2>
          <p className="text-[13px] text-secondary">{t.signIn.lead}</p>
        </div>

        <form onSubmit={submit} className="flex flex-col gap-4">
          <label className={field}>
            {t.signIn.username}
            <input name="username" required autoFocus autoComplete="username" dir="auto" className={input} />
          </label>
          <label className={field}>
            {t.signIn.password}
            <input name="password" type="password" required autoComplete="current-password" dir="ltr" className={input} />
          </label>
          {error && (
            <p role="alert" className="rounded-lg bg-due-overdue-bg px-3 py-2 text-[13px] text-due-overdue">
              {t.signIn[error]}
            </p>
          )}
          <button
            type="submit"
            disabled={busy}
            className="h-10 rounded-lg bg-primary px-4 text-[14px] font-semibold text-white transition-colors hover:bg-primary-hover disabled:opacity-70"
          >
            {busy ? t.signIn.busy : t.signIn.submit}
          </button>
        </form>
      </section>
    </main>
  );
}
