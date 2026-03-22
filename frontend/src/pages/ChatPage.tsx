import { RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import MessageList from "@/components/chatbot/MessageList";
import ChatInput from "@/components/chatbot/ChatInput";
import ExampleChips from "@/components/chatbot/ExampleChips";
import { useChatbot } from "@/components/chatbot/useChatbot";

export default function ChatPage() {
  const {
    messages,
    isStreaming,
    error,
    sendMessage,
    retry,
    resetChat,
    exampleQuestions,
  } = useChatbot();

  const isEmpty = messages.length === 0;

  return (
    <div className="mx-auto flex h-[calc(100vh-3.5rem)] max-w-7xl flex-col px-4 py-6 pb-0">
      {/* 헤더: 대시보드와 동일 패턴 */}
      <div className="flex items-center justify-between pb-4">
        <h1 className="text-lg font-semibold">AI 어시스턴트</h1>
        <Button
          variant="outline"
          size="icon"
          onClick={resetChat}
          aria-label="대화 초기화"
          title="대화 초기화"
        >
          <RotateCcw className="size-4" />
        </Button>
      </div>

      {/* 채팅 영역 */}
      <div className="flex flex-1 flex-col overflow-hidden rounded-t-lg border border-b-0">
        {isEmpty ? (
          <ExampleChips questions={exampleQuestions} onSelect={sendMessage} />
        ) : (
          <MessageList
            messages={messages}
            isStreaming={isStreaming}
            error={error}
            onRetry={retry}
            wide
          />
        )}
        <ChatInput onSend={sendMessage} disabled={isStreaming} />
      </div>
    </div>
  );
}
