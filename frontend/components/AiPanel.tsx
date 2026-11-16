"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useAssistant, type AiChange, type AiErrorKind, type AiMessage } from "@/lib/assistant";
import { useT } from "@/lib/i18n";
import { columnOf, useStore } from "@/lib/store";
import { ArrowIcon, CloseIcon, SparkleIcon, cx } from "./ui";

const chipStyle = {
  create_card: "border-due-done-bg bg-due-done-bg text-due-done",
  update_card: "border-segment-border bg-segment text-heading",
  move_card: "border-column-border bg-column text-heading",
};

/** One change as a small button; clicking it opens that card. */
function Chip({ change }: { change: AiChange }) {
  const { t, L, columnName } = useT();
  const card = useStore((s) => s.cards[change.cardId]);
  const columns = useStore((s) => s.columns);
  const openDialog = useStore((s) => s.openDialog);
  const title = card ? L(card.title) : (change.title ?? t.ai.chip.gone);
  const target = columns.find((c) => c.id === change.column);
  const label =
    change.type === "create_card"
      ? t.ai.chip.created(title)
      : change.type === "move_card"
        ? t.ai.chip.moved(title, target ? columnName(target) : (change.column ?? ""))
        : t.ai.chip.updated(title);

  return (
    <button
      type="button"
      data-testid="ai-chip"
      dir="auto"
      disabled={!card}
      title={t.ai.chip.open(label)}
      onClick={() => card && openDialog({ type: "card", columnId: columnOf(columns, card.id).id, cardId: card.id })}
      className={cx(
        "max-w-full truncate rounded-full border px-2.5 py-1 text-[12px] font-medium transition-colors enabled:hover:brightness-95 disabled:cursor-default disabled:opacity-60",
        chipStyle[change.type],
      )}
    >
      {label}
    </button>
  );
}

function Bubble({ message }: { message: AiMessage }) {
  const own = message.role === "user";
  return (
    <div data-testid={own ? "ai-user-message" : "ai-answer"} className={cx("flex max-w-[92%] flex-col gap-2", own ? "items-end self-end" : "items-start self-start")}>
      <p
        dir="auto"
        className={cx(
          "whitespace-pre-wrap break-words rounded-xl px-3.5 py-2.5 text-[13.5px]/[22px]",
          own ? "bg-primary text-white" : "border border-surface-border bg-surface text-ink shadow-card",
        )}
      >
        {message.content}
      </p>
      {message.changes.length > 0 && (
        <div data-testid="ai-changes" className="flex flex-wrap gap-1.5">
          {message.changes.map((change, i) => (
            <Chip key={`${change.cardId}-${i}`} change={change} />
          ))}
        </div>
      )}
    </div>
  );
}

function Guide({ onPick }: { onPick: (text: string) => void }) {
  const { t } = useT();
  return (
    <div data-testid="ai-guide" className="m-auto flex w-full flex-col gap-3 py-6">
      <span className="grid size-10 place-items-center self-start rounded-[10px] bg-column text-primary">
        <SparkleIcon size={20} />
      </span>
      <h3 className="text-[15px] font-semibold text-heading">{t.ai.guideTitle}</h3>
      <p className="text-[13px]/5 text-secondary">{t.ai.guideText}</p>
      <div className="flex flex-col gap-2">
        {t.ai.examples.map((example) => (
          <button
            key={example}
            type="button"
            data-testid="ai-example"
            dir="auto"
            onClick={() => onPick(example)}
            className="rounded-[10px] border border-surface-border bg-surface px-3.5 py-2.5 text-start text-[13px]/5 text-ink shadow-card transition-colors hover:border-surface-hover-border hover:bg-surface-hover"
          >
            {example}
          </button>
        ))}
      </div>
    </div>
  );
}

const errorText = (t: ReturnType<typeof useT>["t"], kind: AiErrorKind) =>
  ({ "not-configured": t.ai.errors.notConfigured, busy: t.ai.errors.busy, failed: t.ai.errors.failed, timeout: t.ai.errors.timeout, offline: t.ai.errors.offline })[kind];

/** The assistant: a panel at the inline-end side beside the board (full screen on a phone). */
export default function AiPanel() {
  const { t } = useT();
  const open = useAssistant((s) => s.open);
  const history = useAssistant((s) => s.history);
  const messages = useAssistant((s) => s.messages);
  const waiting = useAssistant((s) => s.waiting);
  const error = useAssistant((s) => s.error);
  const { hide, loadHistory, send, retry } = useAssistant.getState();
  const [draft, setDraft] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const log = useRef<HTMLDivElement>(null);
  const blocked = error?.kind === "not-configured";

  // Every time the panel opens, the conversation is loaded from the server.
  useEffect(() => {
    if (open) {
      void loadHistory();
      input.current?.focus();
    }
  }, [open, loadHistory]);

  // New messages, the thinking indicator and errors scroll into view; when an answer arrives the input gets focus back.
  useEffect(() => {
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [messages.length, waiting, error, history]);
  useEffect(() => {
    if (open && !waiting && !blocked) input.current?.focus();
  }, [open, waiting, blocked]);

  if (!open) return null;

  function submit(text: string) {
    const value = text.trim();
    if (!value || waiting || blocked) return;
    setDraft("");
    void send(value);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit(draft);
    }
  }

  const empty = history === "ready" && messages.length === 0 && !waiting;

  return (
    <aside
      id="ai-panel"
      data-testid="ai-panel"
      aria-label={t.ai.title}
      onKeyDown={(e) => {
        if (e.key === "Escape" && !document.querySelector("dialog[open]")) {
          hide();
          document.querySelector<HTMLElement>("[data-ai-toggle]")?.focus();
        }
      }}
      className="fixed inset-0 z-40 flex min-h-0 flex-col bg-chrome md:static md:inset-auto md:z-auto md:w-[400px] md:flex-none md:border-s md:border-hairline"
    >
      <div className="flex items-center gap-2.5 border-b border-hairline px-4 py-3.5">
        <span aria-hidden className="grid size-8 flex-none place-items-center rounded-[9px] bg-primary text-white">
          <SparkleIcon size={17} />
        </span>
        <h2 className="min-w-0 flex-1 truncate text-[16px]/6 font-semibold text-heading">{t.ai.title}</h2>
        <button
          type="button"
          aria-label={t.close}
          title={t.close}
          onClick={() => {
            hide();
            document.querySelector<HTMLElement>("[data-ai-toggle]")?.focus();
          }}
          className="grid size-9 flex-none place-items-center rounded-lg text-muted transition-colors hover:bg-ghost-hover hover:text-ink"
        >
          <CloseIcon size={18} />
        </button>
      </div>

      <div ref={log} role="log" aria-live="polite" aria-busy={waiting} className="tidy-scroll flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto bg-page px-4 py-4">
        {history === "loading" && messages.length === 0 && <p className="text-[12.5px] text-muted">{t.ai.loading}</p>}
        {empty && <Guide onPick={submit} />}
        {messages.map((message) => (
          <Bubble key={message.id} message={message} />
        ))}
        {waiting && (
          <div role="status" data-testid="ai-thinking" className="inline-flex items-center gap-2 self-start rounded-xl border border-surface-border bg-surface px-3.5 py-2.5 text-[13px] text-secondary shadow-card">
            <span aria-hidden className="flex gap-1">
              {[0, 1, 2].map((i) => (
                <span key={i} className="size-1.5 rounded-full bg-primary motion-safe:animate-pulse" style={{ animationDelay: `${i * 160}ms` }} />
              ))}
            </span>
            {t.ai.thinking}
          </div>
        )}
        {error && (
          <div role="alert" data-testid="ai-error" data-kind={error.kind} className="flex flex-col items-start gap-2 rounded-xl bg-due-overdue-bg px-3.5 py-3 text-[13px]/5 text-due-overdue">
            <span dir="auto">{errorText(t, error.kind)}</span>
            <button
              type="button"
              onClick={() => void retry()}
              className="h-8 rounded-lg border border-due-overdue/40 bg-surface px-3 text-[12.5px] font-semibold text-heading transition-colors hover:bg-surface-hover"
            >
              {t.ai.tryAgain}
            </button>
          </div>
        )}
      </div>

      <div className="border-t border-hairline bg-chrome p-3">
        <div className="flex items-end gap-2 rounded-xl border border-surface-border bg-surface p-1.5 shadow-card">
          <textarea
            ref={input}
            dir="auto"
            rows={2}
            value={draft}
            disabled={waiting || blocked}
            aria-label={t.ai.placeholder}
            placeholder={t.ai.placeholder}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            className="max-h-32 min-h-[44px] min-w-0 flex-1 resize-none bg-transparent px-2 py-1.5 text-[14px]/5 text-ink placeholder:text-muted disabled:opacity-60"
          />
          <button
            type="button"
            disabled={waiting || blocked || !draft.trim()}
            onClick={() => submit(draft)}
            className="flex h-[38px] flex-none items-center gap-1.5 rounded-[9px] bg-primary px-3.5 text-[13px] font-semibold text-white transition-colors hover:bg-primary-hover disabled:opacity-55 disabled:hover:bg-primary"
          >
            {t.ai.send}
            <ArrowIcon size={15} />
          </button>
        </div>
      </div>
    </aside>
  );
}
