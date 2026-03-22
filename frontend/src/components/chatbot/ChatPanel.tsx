import { useNavigate } from "react-router-dom";
import { X, RotateCcw, Maximize2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import MessageList from "./MessageList";
import ChatInput from "./ChatInput";
import ExampleChips from "./ExampleChips";
import { useChatbot } from "./useChatbot";

interface ChatPanelProps {
  open: boolean;
  onClose: () => void;
}

export default function ChatPanel({ open, onClose }: ChatPanelProps) {
  const navigate = useNavigate();
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
    <>
      {/* Mobile overlay backdrop */}
      {open && (
        <div
          className="bg-background/80 fixed inset-0 z-40 backdrop-blur-sm md:hidden"
          onClick={onClose}
        />
      )}

      {/* Panel */}
      <div
        className={`fixed top-0 right-0 z-50 flex h-full w-full flex-col border-l shadow-lg transition-transform duration-300 ease-in-out md:w-[380px] ${
          open ? "translate-x-0" : "translate-x-full"
        } bg-background`}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b px-4 py-3">
          <h2 className="text-sm font-semibold">AI 어시스턴트</h2>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              onClick={() => {
                onClose();
                navigate("/chat");
              }}
              className="size-8"
              aria-label="전체 화면으로 열기"
              title="전체 화면으로 열기"
            >
              <Maximize2 className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={resetChat}
              className="size-8"
              aria-label="대화 초기화"
              title="대화 초기화"
            >
              <RotateCcw className="size-4" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              onClick={onClose}
              className="size-8"
              aria-label="닫기"
            >
              <X className="size-4" />
            </Button>
          </div>
        </div>

        {/* Body */}
        {isEmpty ? (
          <ExampleChips questions={exampleQuestions} onSelect={sendMessage} />
        ) : (
          <MessageList
            messages={messages}
            isStreaming={isStreaming}
            error={error}
            onRetry={retry}
          />
        )}

        {/* Input */}
        <ChatInput onSend={sendMessage} disabled={isStreaming} />
      </div>
    </>
  );
}
