import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "./types";

interface MessageListProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  error: string | null;
  onRetry: () => void;
  wide?: boolean;
}

function TypingIndicator() {
  return (
    <div className="flex items-start gap-2">
      <div className="bg-muted max-w-[85%] rounded-lg px-3 py-2">
        <div className="flex items-center gap-1">
          <span className="bg-muted-foreground/50 inline-block size-1.5 animate-bounce rounded-full [animation-delay:0ms]" />
          <span className="bg-muted-foreground/50 inline-block size-1.5 animate-bounce rounded-full [animation-delay:150ms]" />
          <span className="bg-muted-foreground/50 inline-block size-1.5 animate-bounce rounded-full [animation-delay:300ms]" />
        </div>
      </div>
    </div>
  );
}

function AssistantMessage({ content, wide }: { content: string; wide?: boolean }) {
  return (
    <div className="flex items-start gap-2">
      <div className={`bg-muted rounded-lg px-3 py-2 ${wide ? "max-w-full" : "max-w-[85%]"}`}>
        <div className="prose prose-sm dark:prose-invert max-w-none [&_table]:block [&_table]:overflow-x-auto [&_table]:whitespace-nowrap">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}

function UserMessage({ content }: { content: string }) {
  return (
    <div className="flex items-start justify-end gap-2">
      <div className="bg-primary text-primary-foreground max-w-[85%] rounded-lg px-3 py-2">
        <p className="whitespace-pre-wrap text-sm">{content}</p>
      </div>
    </div>
  );
}

export default function MessageList({
  messages,
  isStreaming,
  error,
  onRetry,
  wide,
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isStreaming]);

  return (
    <div className="flex flex-1 flex-col gap-3 overflow-y-auto p-4">
      {messages.map((msg, i) => {
        if (msg.role === "user") {
          return <UserMessage key={i} content={msg.content} />;
        }
        // Streaming assistant message (last message, empty content)
        if (isStreaming && i === messages.length - 1 && msg.content === "") {
          return <TypingIndicator key={i} />;
        }
        return <AssistantMessage key={i} content={msg.content} wide={wide} />;
      })}

      {error && (
        <div className="flex items-start gap-2">
          <div className="bg-destructive/10 text-destructive max-w-[85%] rounded-lg px-3 py-2">
            <p className="text-sm">{error}</p>
            <button
              onClick={onRetry}
              className="text-destructive mt-1 text-xs font-medium underline"
            >
              재시도
            </button>
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
