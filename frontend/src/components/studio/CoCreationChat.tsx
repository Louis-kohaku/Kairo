import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { ChangeProposal, ChatMessageT, QuickAction } from "../../types";

/**
 * AI Co-Creation (design doc sections 2/29-33/43).
 *
 * The panel's job is to make clear that a reply is not the result: an
 * instruction produces a *proposal*, the proposal shows what will change
 * and why, and only Apply touches the project. After applying, the same
 * card offers Undo, so an experiment is cheap.
 *
 * It can be collapsed and resized (section 41) because it must never be
 * the reason the user cannot see the preview or the timeline.
 */
export default function CoCreationChat({
  projectId,
  onApplied,
  onClose,
  disabled,
  disabledReason,
}: {
  projectId: string;
  onApplied: () => void;
  onClose?: () => void;
  disabled?: boolean;
  disabledReason?: string;
}) {
  const [messages, setMessages] = useState<ChatMessageT[]>([]);
  const [quickActions, setQuickActions] = useState<QuickAction[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [busyProposal, setBusyProposal] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.getChat(projectId).then(setMessages).catch(() => {});
    api.listQuickActions().then(setQuickActions).catch(() => {});
  }, [projectId]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, status]);

  const send = async (instruction: string) => {
    if (!instruction.trim() || sending) return;
    setSending(true);
    setError(null);
    setStatus("AIが現在の動画を分析しています…");
    // Shown immediately so the conversation doesn't appear to swallow the
    // instruction while the local model thinks (which can take a while).
    const optimistic: ChatMessageT = {
      id: `local-${Date.now()}`,
      role: "user",
      content: instruction,
      proposal: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimistic]);
    setInput("");
    try {
      await api.sendChat(projectId, instruction);
      setMessages(await api.getChat(projectId));
    } catch (e) {
      setError(String(e));
    } finally {
      setStatus(null);
      setSending(false);
    }
  };

  const act = async (
    proposal: ChangeProposal,
    action: "apply" | "cancel" | "undo",
  ) => {
    setBusyProposal(proposal.id);
    setError(null);
    setStatus(
      action === "apply"
        ? "変更を適用し、影響するシーンを作り直しています…"
        : action === "undo"
          ? "変更を元に戻しています…"
          : null,
    );
    try {
      if (action === "apply") {
        const res = await api.applyProposal(proposal.id);
        setStatus(
          `適用しました: ${res.result.applied.join(" / ") || "変更なし"}` +
            (res.result.skipped.length ? ` (見送り: ${res.result.skipped.length}件)` : ""),
        );
        onApplied();
      } else if (action === "undo") {
        await api.undoProposal(proposal.id);
        setStatus("元に戻しました。");
        onApplied();
      } else {
        await api.cancelProposal(proposal.id);
        setStatus(null);
      }
      setMessages(await api.getChat(projectId));
    } catch (e) {
      setError(String(e));
      setStatus(null);
    } finally {
      setBusyProposal(null);
    }
  };

  return (
    <div className="cochat">
      <div className="cochat-head">
        <span className="cochat-title">AI Co-Creation</span>
        <span style={{ flex: 1 }} />
        {onClose && (
          <button className="cochat-close" onClick={onClose} aria-label="チャットを閉じる">
            ✕
          </button>
        )}
      </div>

      <div className="cochat-log">
        {messages.length === 0 && (
          <div className="cochat-empty">
            動画について指示すると、AIが実際のプロジェクトを変更します。
            <br />
            例: 「もっとテンポよくして」「Scene 3をもっと面白くして」「字幕を大きくして」
          </div>
        )}

        {messages.map((m) => (
          <div key={m.id} className={`cochat-msg cochat-msg-${m.role}`}>
            <div className="cochat-bubble">{m.content}</div>
            {m.proposal && (
              <ProposalCard
                proposal={m.proposal}
                busy={busyProposal === m.proposal.id}
                onAct={(action) => act(m.proposal!, action)}
              />
            )}
          </div>
        ))}

        {status && <div className="cochat-status">{status}</div>}
        {error && <div className="cochat-error">{error}</div>}
        <div ref={endRef} />
      </div>

      {disabled && <div className="cochat-disabled">{disabledReason}</div>}

      <div className="cochat-quick">
        {quickActions.map((a) => (
          <button
            key={a.id}
            onClick={() => send(a.instruction)}
            disabled={sending || disabled}
            title={a.instruction}
          >
            {a.label}
          </button>
        ))}
      </div>

      <form
        className="cochat-input"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <textarea
          value={input}
          rows={2}
          placeholder="動画への指示を入力…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              send(input);
            }
          }}
          disabled={sending || disabled}
        />
        <button className="primary" type="submit" disabled={sending || disabled || !input.trim()}>
          {sending ? "…" : "送信"}
        </button>
      </form>
    </div>
  );
}

function ProposalCard({
  proposal,
  busy,
  onAct,
}: {
  proposal: ChangeProposal;
  busy: boolean;
  onAct: (action: "apply" | "cancel" | "undo") => void;
}) {
  return (
    <div className={`proposal proposal-${proposal.status}`}>
      <div className="proposal-title">
        {proposal.status === "applied"
          ? "適用済みの変更"
          : proposal.status === "undone"
            ? "元に戻した変更"
            : proposal.status === "cancelled"
              ? "取り消した変更"
              : "変更案"}
      </div>

      {proposal.reason && <div className="proposal-reason">{proposal.reason}</div>}

      <div className="proposal-changes">
        {proposal.preview.map((c, i) => (
          <div key={i} className="proposal-change">
            <span className="proposal-what">{c.what}</span>
            <span className="proposal-before">{c.before}</span>
            <span className="proposal-arrow">→</span>
            <span className="proposal-after">{c.after}</span>
            {c.reason && <span className="proposal-change-reason">{c.reason}</span>}
          </div>
        ))}
      </div>

      <div className="proposal-actions">
        {proposal.status === "pending" && (
          <>
            <button className="primary" onClick={() => onAct("apply")} disabled={busy}>
              {busy ? "適用中…" : "適用"}
            </button>
            <button onClick={() => onAct("cancel")} disabled={busy}>
              キャンセル
            </button>
          </>
        )}
        {proposal.status === "applied" && (
          <button onClick={() => onAct("undo")} disabled={busy}>
            {busy ? "戻しています…" : "元に戻す"}
          </button>
        )}
      </div>
    </div>
  );
}
