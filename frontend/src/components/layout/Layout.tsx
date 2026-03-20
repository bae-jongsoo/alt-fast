import { useState } from "react";
import { Outlet } from "react-router-dom";
import Navbar from "./Navbar";
import ChatFAB from "@/components/chatbot/ChatFAB";
import ChatPanel from "@/components/chatbot/ChatPanel";

export default function Layout() {
  const [chatOpen, setChatOpen] = useState(false);

  return (
    <div className="flex min-h-screen flex-col">
      <Navbar />
      <main className="flex-1">
        <Outlet />
      </main>
      <ChatFAB open={chatOpen} onToggle={() => setChatOpen((v) => !v)} />
      <ChatPanel open={chatOpen} onClose={() => setChatOpen(false)} />
    </div>
  );
}
