import { useState, useCallback } from "react";
import type { ChatMessage } from "./types";

const EXAMPLE_QUESTIONS = ["오늘 거래 요약", "포트폴리오 분석", "최근 뉴스 요약"];

export function useChatbot() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastFailedMessage, setLastFailedMessage] = useState<string | null>(
    null
  );

  const sendMessage = useCallback(
    async (message: string) => {
      const trimmed = message.trim();
      if (!trimmed || isStreaming) return;

      setError(null);
      setLastFailedMessage(null);

      const userMsg: ChatMessage = { role: "user", content: trimmed };
      const currentMessages = [...messages, userMsg];
      setMessages(currentMessages);
      setIsStreaming(true);

      // Add empty assistant message for streaming
      setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

      try {
        const response = await fetch("/api/chatbot/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: trimmed,
            history: currentMessages.slice(0, -1), // exclude the just-added user message from history
          }),
        });

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const reader = response.body?.getReader();
        if (!reader) throw new Error("No reader available");

        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const jsonStr = line.slice(6).trim();
            if (!jsonStr) continue;

            try {
              const event = JSON.parse(jsonStr);

              if (event.type === "token") {
                setMessages((prev) => {
                  const updated = [...prev];
                  const last = updated[updated.length - 1];
                  if (last?.role === "assistant") {
                    updated[updated.length - 1] = {
                      ...last,
                      content: last.content + event.content,
                    };
                  }
                  return updated;
                });
              } else if (event.type === "done") {
                // Streaming complete
              } else if (event.type === "error") {
                throw new Error(
                  event.message || "답변을 생성하지 못했습니다."
                );
              }
            } catch (parseErr) {
              if (
                parseErr instanceof Error &&
                parseErr.message !== "답변을 생성하지 못했습니다."
              ) {
                // Ignore JSON parse errors for incomplete chunks
                continue;
              }
              throw parseErr;
            }
          }
        }
      } catch (err) {
        setError("답변을 생성하지 못했습니다. 다시 시도해주세요.");
        setLastFailedMessage(trimmed);
        // Remove the empty assistant message on error
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.role === "assistant" && last.content === "") {
            return updated.slice(0, -1);
          }
          return updated;
        });
      } finally {
        setIsStreaming(false);
      }
    },
    [messages, isStreaming]
  );

  const retry = useCallback(() => {
    if (lastFailedMessage) {
      // Remove the last user message (the failed one) before resending
      setMessages((prev) => {
        const updated = [...prev];
        if (
          updated.length > 0 &&
          updated[updated.length - 1].role === "user"
        ) {
          return updated.slice(0, -1);
        }
        return updated;
      });
      const msg = lastFailedMessage;
      setError(null);
      setLastFailedMessage(null);
      // Use setTimeout to ensure state is updated before sending
      setTimeout(() => sendMessage(msg), 0);
    }
  }, [lastFailedMessage, sendMessage]);

  const resetChat = useCallback(() => {
    setMessages([]);
    setIsStreaming(false);
    setError(null);
    setLastFailedMessage(null);
  }, []);

  return {
    messages,
    isStreaming,
    error,
    lastFailedMessage,
    sendMessage,
    retry,
    resetChat,
    exampleQuestions: EXAMPLE_QUESTIONS,
  };
}
