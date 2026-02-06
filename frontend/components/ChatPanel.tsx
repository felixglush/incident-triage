"use client";

import { useEffect, useRef, useState } from "react";

type ReferenceLink = { label: string; href: string };
type Citation = {
  type?: string;
  id?: number;
  title?: string;
  score?: number;
  source_document?: string;
  chunk_index?: number;
};
type Message = {
  id: string;
  role: string;
  content: string;
  citations?: Citation[];
};
type RetryTurn = {
  incidentId: string;
  message: string;
};

function citationHref(citation: Citation): string | null {
  if (citation.type === "incident" && citation.id) {
    return `/incidents/${citation.id}`;
  }
  if (citation.type === "alert" && citation.id) {
    return `/alerts?alert_id=${citation.id}`;
  }
  if (citation.type === "runbook" && citation.source_document) {
    const doc = encodeURIComponent(citation.source_document);
    const anchor = citation.chunk_index != null ? `#chunk-${citation.chunk_index}` : "";
    return `/runbooks?doc=${doc}${anchor}`;
  }
  return null;
}

function citationLabel(citation: Citation, index: number): string {
  if (citation.type === "incident" && citation.id) {
    return `[${index + 1}] Incident #${citation.id}${citation.title ? ` - ${citation.title}` : ""}`;
  }
  if (citation.type === "alert" && citation.id) {
    return `[${index + 1}] Alert #${citation.id}${citation.title ? ` - ${citation.title}` : ""}`;
  }
  if (citation.type === "runbook") {
    const chunk = citation.chunk_index != null ? ` (chunk ${citation.chunk_index})` : "";
    return `[${index + 1}] ${citation.source_document ?? "Runbook"}${chunk}`;
  }
  return `[${index + 1}] Source`;
}

function normalizeAssistantText(content: string): string {
  const normalized = content.replace(/\r\n/g, "\n");
  const transformedLines = normalized.split("\n").flatMap((line) => {
    const numberedMatches = line.match(/\d+\.\s/g);
    if (numberedMatches && numberedMatches.length >= 2) {
      const firstIdx = line.search(/\d+\.\s/);
      const head = line.slice(0, firstIdx).trimEnd();
      const listPart = line.slice(firstIdx).trim();
      const items = listPart.split(/\s+(?=\d+\.\s)/g);
      return head ? [head, ...items] : items;
    }
    return [line];
  });
  return transformedLines.join("\n");
}

function renderAssistantContent(content: string) {
  const lines = normalizeAssistantText(content).split("\n").map((line) => line.trimRight());
  const nodes: JSX.Element[] = [];

  let i = 0;
  while (i < lines.length) {
    const line = lines[i].trim();
    if (!line) {
      i += 1;
      continue;
    }

    if (line.startsWith(">")) {
      const quoteLines: string[] = [];
      let j = i;
      while (j < lines.length && lines[j].trim().startsWith(">")) {
        quoteLines.push(lines[j].trim().replace(/^>\s?/, ""));
        j += 1;
      }
      nodes.push(
        <blockquote
          key={`quote-${i}`}
          className="my-2 border-l-2 border-info/40 pl-3 italic text-mist/85"
        >
          {quoteLines.map((quoteLine, lineIdx) => (
            <p key={`quote-line-${lineIdx}`}>{quoteLine}</p>
          ))}
        </blockquote>
      );
      i = j;
      continue;
    }

    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      let j = i;
      while (j < lines.length && /^\d+\.\s+/.test(lines[j].trim())) {
        items.push(lines[j].trim().replace(/^\d+\.\s+/, ""));
        j += 1;
      }
      nodes.push(
        <ol key={`list-number-${i}`} className="my-2 list-decimal space-y-1 pl-5">
          {items.map((item, itemIdx) => (
            <li key={`item-${itemIdx}`}>{item}</li>
          ))}
        </ol>
      );
      i = j;
      continue;
    }

    if (line.startsWith("- ")) {
      const items: string[] = [];
      let j = i;
      while (j < lines.length && lines[j].trim().startsWith("- ")) {
        items.push(lines[j].trim().replace(/^- /, ""));
        j += 1;
      }
      nodes.push(
        <ul key={`list-bullet-${i}`} className="my-2 list-disc space-y-1 pl-5">
          {items.map((item, itemIdx) => (
            <li key={`item-${itemIdx}`}>{item}</li>
          ))}
        </ul>
      );
      i = j;
      continue;
    }

    if (line.endsWith(":")) {
      nodes.push(
        <p key={`heading-${i}`} className="my-2 text-sm font-semibold tracking-wide text-mist/90">
          {line}
        </p>
      );
      i += 1;
      continue;
    }

    const paragraphLines: string[] = [];
    let j = i;
    while (j < lines.length) {
      const current = lines[j].trim();
      if (
        !current ||
        current.startsWith(">") ||
        current.startsWith("- ") ||
        /^\d+\.\s+/.test(current) ||
        current.endsWith(":")
      ) {
        break;
      }
      paragraphLines.push(current);
      j += 1;
    }
    nodes.push(
      <p key={`p-${i}`} className="my-2 leading-relaxed whitespace-pre-line text-mist/95">
        {paragraphLines.join("\n")}
      </p>
    );
    i = j;
  }

  return nodes;
}

export default function ChatPanel({
  endpoint = "/api/opsrelay/chat/stream",
  references = [],
  incidentId,
}: {
  endpoint?: string;
  references?: ReferenceLink[];
  incidentId?: string;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [toolEvents, setToolEvents] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [retryTurn, setRetryTurn] = useState<RetryTurn | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const eventRef = useRef<EventSource | null>(null);
  const deltaBufferRef = useRef<Record<string, string>>({});
  const flushTimerRef = useRef<number | null>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: submitting ? "auto" : "smooth" });
  }, [messages, toolEvents, submitting]);

  useEffect(() => {
    return () => {
      eventRef.current?.close();
      eventRef.current = null;
      if (flushTimerRef.current !== null) {
        window.clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
    };
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim()) return;

    const userMessage: Message = {
      id: `msg-${Date.now()}`,
      role: "user",
      content: input.trim(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setStreamError(null);
    setRetryTurn(null);
    if (incidentId) {
      submitChat(incidentId, userMessage.content);
    }
  };

  const handleRetry = () => {
    if (!retryTurn || submitting) return;
    setStreamError(null);
    submitChat(retryTurn.incidentId, retryTurn.message);
  };

  const submitChat = async (id: string, message: string) => {
    setSubmitting(true);
    if (flushTimerRef.current !== null) {
      window.clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }
    deltaBufferRef.current = {};
    eventRef.current?.close();
    try {
      const streamUrl = `${endpoint}?incident_id=${encodeURIComponent(id)}&message=${encodeURIComponent(message)}`;
      const source = new EventSource(streamUrl);
      eventRef.current = source;
      let receivedAssistant = false;
      let streamCompleted = false;
      const flushBufferedDeltas = () => {
        const pending = deltaBufferRef.current;
        deltaBufferRef.current = {};
        flushTimerRef.current = null;
        const pendingIds = Object.keys(pending);
        if (pendingIds.length === 0) return;
        setMessages((prev) => {
          let next = prev;
          for (const messageId of pendingIds) {
            const delta = pending[messageId];
            const existingIndex = next.findIndex((msg) => msg.id === messageId);
            if (existingIndex === -1) {
              next = [...next, { id: messageId, role: "assistant", content: delta }];
              continue;
            }
            const updated = [...next];
            updated[existingIndex] = {
              ...updated[existingIndex],
              content: `${updated[existingIndex].content}${delta}`,
            };
            next = updated;
          }
          return next;
        });
      };
      source.addEventListener("assistant_delta", (event) => {
        receivedAssistant = true;
        const data = JSON.parse((event as MessageEvent).data);
        const messageId = data.id ?? `msg-${Date.now()}`;
        const delta = data.delta ?? "";
        deltaBufferRef.current[messageId] = `${deltaBufferRef.current[messageId] ?? ""}${delta}`;
        if (flushTimerRef.current === null) {
          flushTimerRef.current = window.setTimeout(flushBufferedDeltas, 40);
        }
      });

      source.addEventListener("assistant", (event) => {
        receivedAssistant = true;
        flushBufferedDeltas();
        const data = JSON.parse((event as MessageEvent).data);
        const messageId = data.id ?? `msg-${Date.now()}`;
        setMessages((prev) => {
          const existingIndex = prev.findIndex((msg) => msg.id === messageId);
          if (existingIndex === -1) {
            return [
              ...prev,
              {
                id: messageId,
                role: "assistant",
                content: data.content ?? "",
                citations: Array.isArray(data.citations) ? data.citations : [],
              },
            ];
          }
          const updated = [...prev];
          updated[existingIndex] = {
            ...updated[existingIndex],
            content: data.content ?? updated[existingIndex].content,
            citations: Array.isArray(data.citations) ? data.citations : updated[existingIndex].citations,
          };
          return updated;
        });
      });

      source.addEventListener("tool", (event) => {
        const data = JSON.parse((event as MessageEvent).data);
        setToolEvents((prev) => [...prev, `${data.tool}: ${data.status}`]);
      });

      source.addEventListener("done", () => {
        flushBufferedDeltas();
        streamCompleted = true;
        source.close();
        setStreamError(null);
        setRetryTurn(null);
        setSubmitting(false);
      });

      source.addEventListener("error", () => {
        flushBufferedDeltas();
        source.close();
        if (!streamCompleted) {
          setRetryTurn({ incidentId: id, message });
          setStreamError(
            receivedAssistant
              ? "Stream interrupted before completion. Continue to retry this turn."
              : "Unable to start streaming response. Continue to retry."
          );
        }
        setSubmitting(false);
      });
    } catch {
      setRetryTurn({ incidentId: id, message });
      setStreamError("Failed to open streaming connection. Continue to retry.");
      setSubmitting(false);
    }
  };

  return (
    <div className="h-full flex flex-col bg-graphite/50 border-l border-mist/10">
      {/* Header */}
      <div className="flex-shrink-0 p-4 border-b border-mist/10">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-info opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-info"></span>
          </span>
          <span className="text-xs font-mono uppercase tracking-wider text-mist/60">
            AI Copilot
          </span>
        </div>
        {references.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {references.map((ref) => (
              <a
                key={ref.label}
                href={ref.href}
                className="rounded-full border border-info/30 bg-info/5 px-2.5 py-1 text-xs text-info/80 hover:bg-info/10 hover:text-info transition-colors"
              >
                {ref.label}
              </a>
            ))}
          </div>
        )}
      </div>

      {/* Messages - scrollable area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.length === 0 && (
          <div className="text-xs text-mist/50">No messages yet.</div>
        )}
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`rounded-xl p-3 text-sm ${
              msg.role === "user"
                ? "bg-info/15 text-info ml-8"
                : "bg-slate/60 text-white mr-4"
            }`}
          >
            {msg.role === "assistant" && (
              <p className="text-[10px] uppercase tracking-wider text-mist/40 mb-1">
                Assistant
              </p>
            )}
            {msg.role === "assistant" ? renderAssistantContent(msg.content) : msg.content}
            {msg.role === "assistant" && (msg.citations?.length ?? 0) > 0 && (
              <div className="mt-3 border-t border-mist/10 pt-2">
                <p className="mb-1 text-[10px] uppercase tracking-wider text-mist/45">Citations</p>
                <div className="space-y-1">
                  {msg.citations?.map((citation, index) => {
                    const href = citationHref(citation);
                    const label = citationLabel(citation, index);
                    if (!href) {
                      return (
                        <p key={`citation-${index}`} className="text-xs text-mist/70">
                          {label}
                        </p>
                      );
                    }
                    return (
                      <a
                        key={`citation-${index}`}
                        href={href}
                        className="block text-xs text-info/85 underline decoration-info/40 underline-offset-2 hover:text-info"
                      >
                        {label}
                      </a>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        ))}

        {toolEvents.length > 0 && (
          <div className="rounded-xl border border-info/20 bg-info/5 px-3 py-2 text-xs text-info/70">
            <p className="text-[10px] uppercase tracking-wider text-info/50 mb-1">
              Tool Activity
            </p>
            {toolEvents.map((item, i) => (
              <p key={i} className="text-info/80">{item}</p>
            ))}
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <form
        onSubmit={handleSubmit}
        className="flex-shrink-0 p-4 bg-graphite/40 shadow-[inset_0_12px_24px_-20px_rgba(0,0,0,0.7)]"
      >
        {streamError && (
          <div className="mb-3 rounded-xl border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning">
            <p>{streamError}</p>
            <button
              type="button"
              onClick={handleRetry}
              disabled={submitting || !retryTurn}
              className="mt-2 rounded-lg border border-warning/50 px-2 py-1 text-xs text-warning hover:bg-warning/15 disabled:opacity-50"
            >
              Continue / Retry
            </button>
          </div>
        )}
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about this incident..."
            className="flex-1 rounded-xl border border-mist/20 bg-slate/40 px-4 py-2.5 text-sm text-mist placeholder:text-mist/40 focus:outline-none focus:border-info/50 focus:bg-slate/60 transition-colors"
          />
          <button
            type="submit"
            className="flex items-center justify-center w-10 h-10 rounded-xl bg-info/20 text-info hover:bg-info/30 transition-colors disabled:opacity-40"
            disabled={submitting}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
        </div>
      </form>
    </div>
  );
}
