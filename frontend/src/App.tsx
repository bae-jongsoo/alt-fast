import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider } from "@/hooks/useAuth";
import Layout from "@/components/layout/Layout";
import DashboardPage from "@/pages/DashboardPage";
import TradesPage from "@/pages/TradesPage";
import NewsPage from "@/pages/NewsPage";
import SettingsPage from "@/pages/SettingsPage";
import LoginPage from "@/pages/LoginPage";
import ChartPage from "@/pages/ChartPage";
import ChatPage from "@/pages/ChatPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30 * 1000, // 30초 (대시보드 폴링 주기와 맞춤)
      retry: 1,
    },
  },
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/trades" element={<TradesPage />} />
              <Route path="/news" element={<NewsPage />} />
              <Route path="/chart" element={<ChartPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/login" element={<LoginPage />} />
              <Route path="/chat" element={<ChatPage />} />
            </Route>
            {/* 존재하지 않는 경로 → 대시보드로 리다이렉트 */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          <Toaster position="top-right" />
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

export default App;
