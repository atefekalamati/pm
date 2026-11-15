"use client";

import { useT } from "@/lib/i18n";

const pulse = "motion-safe:animate-pulse";

/** What the screen shows until the board arrives from the server: the shape of the page, no data. */
export default function BoardSkeleton() {
  const { t } = useT();
  return (
    <div role="status" aria-busy="true" aria-label={t.loadingBoard} data-testid="board-skeleton" className="flex h-dvh">
      <aside className="hidden h-full w-64 flex-none flex-col gap-4 border-e border-hairline bg-chrome p-5 md:flex">
        <div className={`h-[34px] w-32 rounded-lg bg-segment ${pulse}`} />
        <div className={`h-14 rounded-xl bg-segment ${pulse}`} />
        <div className="flex flex-col gap-2 pt-2">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className={`h-9 rounded-[10px] bg-segment ${pulse}`} />
          ))}
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-[68px] flex-none items-center border-b border-hairline bg-chrome px-6">
          <div className={`h-5 w-48 rounded-md bg-segment ${pulse}`} />
        </div>
        <div className="flex min-h-0 flex-1 gap-4 overflow-hidden bg-page p-6">
          {[3, 2, 3, 2, 2].map((cards, column) => (
            <div key={column} className="flex w-[280px] flex-none flex-col gap-3 rounded-xl border border-column-border bg-column p-3">
              <div className={`h-4 w-24 rounded bg-column-border ${pulse}`} />
              {Array.from({ length: cards }, (_, i) => (
                <div key={i} className={`h-[88px] rounded-[10px] border border-surface-border bg-surface ${pulse}`} />
              ))}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
