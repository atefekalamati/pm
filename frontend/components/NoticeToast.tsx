"use client";

import { useEffect } from "react";
import { useT } from "@/lib/i18n";
import { useStore } from "@/lib/store";

export const NOTICE_MS = 8000;

/** "That change could not be saved, so it was undone." Appears after a change was refused or lost. */
export default function NoticeToast() {
  const { t } = useT();
  const notice = useStore((s) => s.notice);
  const dismissNotice = useStore((s) => s.dismissNotice);

  // Each failure is a new object, so the time restarts with it.
  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(dismissNotice, NOTICE_MS);
    return () => clearTimeout(timer);
  }, [notice, dismissNotice]);

  if (!notice) return null;

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-[76px] z-50 flex justify-center px-4">
      <div
        role="alert"
        data-testid="notice-toast"
        className="pointer-events-auto flex max-w-[520px] items-center gap-2 rounded-xl bg-heading py-1 pe-1.5 ps-4 text-[13px] font-medium text-white shadow-dialog"
      >
        <span className="py-2">{t.saveFailed}</span>
        <button
          type="button"
          onClick={dismissNotice}
          className="h-9 flex-none rounded-lg px-2.5 font-semibold text-white underline underline-offset-2 transition-colors hover:bg-primary-hover"
        >
          {t.close}
        </button>
      </div>
    </div>
  );
}
