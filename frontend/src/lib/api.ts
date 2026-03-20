import axios from "axios";
import { toast } from "sonner";

const api = axios.create({
  baseURL: "/api",
});

// AuthContext의 logout을 인터셉터에서 호출하기 위한 콜백 레지스트리
let onUnauthorized: (() => void) | null = null;

export function setOnUnauthorized(callback: (() => void) | null) {
  onUnauthorized = callback;
}

// JWT 토큰 자동 첨부 인터셉터
api.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 401 응답 시 자동 로그아웃 + 리다이렉트 인터셉터
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // 로그인 요청 자체의 401은 인터셉터에서 처리하지 않음
      const url = error.config?.url ?? "";
      if (!url.includes("/auth/login")) {
        if (onUnauthorized) {
          onUnauthorized();
        } else {
          localStorage.removeItem("access_token");
        }

        toast.error("세션이 만료되었습니다. 다시 로그인해주세요.");

        // 현재 경로를 query param으로 전달하여 로그인 후 복귀
        const currentPath = window.location.pathname;
        if (currentPath !== "/login") {
          window.location.href = `/login?redirect=${encodeURIComponent(currentPath)}`;
        }
      }
    }
    return Promise.reject(error);
  }
);

export default api;
