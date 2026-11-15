"use client";

import { useEffect, useLayoutEffect, useSyncExternalStore } from "react";
import Board from "@/components/Board";
import BoardSkeleton from "@/components/BoardSkeleton";
import CardDialog from "@/components/CardDialog";
import Chat from "@/components/Chat";
import Header from "@/components/Header";
import HelpDialog from "@/components/HelpDialog";
import NoticeToast from "@/components/NoticeToast";
import Sidebar from "@/components/Sidebar";
import SignIn from "@/components/SignIn";
import UndoToast from "@/components/UndoToast";
import Unreachable from "@/components/Unreachable";
import { checkSession, retrySession, useSession } from "@/lib/session";
import { hasPendingChanges, useStore } from "@/lib/store";
import { useShortcuts } from "@/lib/useShortcuts";

const SESSION_CHECK_MS = 60_000;

const subscribe = () => () => {};

export default function Home() {
  // Render only on the client: what is shown depends on the browser's session, not on the server HTML.
  const mounted = useSyncExternalStore(subscribe, () => true, () => false);
  const session = useSession((s) => s.status);
  const boardStatus = useStore((s) => s.boardStatus);
  const loadBoard = useStore((s) => s.loadBoard);
  const language = useStore((s) => s.language);
  const view = useStore((s) => s.view);
  const dialog = useStore((s) => s.dialog);
  useShortcuts(session === "signed-in" && boardStatus === "ready");

  // The session can end while the board is open (expiry, sign-out in another tab), so check it
  // again when the tab comes back, when Back/Forward restores the page from cache, and every minute.
  useEffect(() => {
    void checkSession();
    const recheck = () => {
      if (document.visibilityState === "visible") void checkSession();
    };
    const onPageShow = (e: PageTransitionEvent) => {
      if (e.persisted) void checkSession();
    };
    window.addEventListener("focus", recheck);
    document.addEventListener("visibilitychange", recheck);
    window.addEventListener("pageshow", onPageShow);
    const timer = setInterval(recheck, SESSION_CHECK_MS);
    return () => {
      window.removeEventListener("focus", recheck);
      document.removeEventListener("visibilitychange", recheck);
      window.removeEventListener("pageshow", onPageShow);
      clearInterval(timer);
    };
  }, []);

  // Closing the tab while a change is still being sent would lose it: ask the browser to show its standard warning.
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (hasPendingChanges()) e.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);

  // Signed in: fetch the board. Nothing of it is shown (no sample data, no empty board) until it has arrived.
  useEffect(() => {
    if (session === "signed-in" && boardStatus === "idle") void loadBoard();
  }, [session, boardStatus, loadBoard]);

  useLayoutEffect(() => {
    document.documentElement.lang = language;
    document.documentElement.dir = language === "fa" ? "rtl" : "ltr";
  }, [language]);

  if (!mounted || session === "checking") return null;
  if (session === "unreachable") return <Unreachable onRetry={retrySession} />;
  if (session === "signed-out") return <SignIn />;
  if (boardStatus === "error") return <Unreachable onRetry={() => void loadBoard()} />;
  if (boardStatus !== "ready") return <BoardSkeleton />;

  return (
    <div className="flex h-dvh">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        {view === "board" ? <Board /> : <Chat />}
      </div>
      <UndoToast />
      <NoticeToast />
      {dialog?.type === "help" && <HelpDialog />}
      {dialog?.type === "card" && <CardDialog key={dialog.cardId ?? "new"} columnId={dialog.columnId} cardId={dialog.cardId} />}
    </div>
  );
}
