import { MessageCircle, X } from "lucide-react";
import { Button } from "@/components/ui/button";

interface ChatFABProps {
  open: boolean;
  onToggle: () => void;
}

export default function ChatFAB({ open, onToggle }: ChatFABProps) {
  return (
    <Button
      size="icon"
      onClick={onToggle}
      className="fixed bottom-6 right-6 z-50 size-12 rounded-full shadow-lg"
      aria-label={open ? "챗봇 닫기" : "챗봇 열기"}
    >
      {open ? <X className="size-5" /> : <MessageCircle className="size-5" />}
    </Button>
  );
}
