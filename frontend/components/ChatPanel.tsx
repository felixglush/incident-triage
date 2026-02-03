"use client";

import { useEffect, useRef, useState } from "react";

const seedMessages = [
  {
    id: "msg-1",
    role: "assistant",
    content: "Standing by. Ask me to summarize, compare, or generate next steps.",
  },
];

type ReferenceLink = { label: string; href: string };
type Message = { id: string; role: string; content: string };

export default function ChatPanel({
  endpoint = "/api/chat/stream",
  references = [],
}: {
  endpoint?: string;
  references?: ReferenceLink[];
}) {
  const [messages, setMessages] = useState<Message[]>(seedMessages);
  const [toolEvents, setToolEvents] = useState<string[]>([]);
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const eventRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const source = new EventSource(endpoint);
    eventRef.current = source;

    source.addEventListener("assistant", (event) => {
      const data = JSON.parse((event as MessageEvent).data);
      setMessages((prev) => [...prev, data]);
    });

    source.addEventListener("tool", (event) => {
      const data = JSON.parse((event as MessageEvent).data);
      setToolEvents((prev) => [...prev, `${data.tool}: ${data.status}`]);
    });

    source.addEventListener("done", () => {
      source.close();
    });

    return () => source.close();
  }, [endpoint]);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, toolEvents]);

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
            {msg.content}
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
      <form onSubmit={handleSubmit} className="flex-shrink-0 p-4 border-t border-mist/10">
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
            className="flex items-center justify-center w-10 h-10 rounded-xl bg-info/20 text-info hover:bg-info/30 transition-colors"
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
