import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import api, { setOnUnauthorized } from "@/lib/api";
import { getToken, setToken, removeToken } from "@/lib/auth";

interface AuthContextType {
  isLoggedIn: boolean;
  login: (loginId: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isLoggedIn, setIsLoggedIn] = useState(() => getToken() !== null);

  // 앱 시작 시 토큰 유효성 확인
  useEffect(() => {
    const token = getToken();
    if (!token) {
      setIsLoggedIn(false);
      return;
    }

    api
      .get("/auth/me")
      .then(() => {
        setIsLoggedIn(true);
      })
      .catch(() => {
        removeToken();
        setIsLoggedIn(false);
      });
  }, []);

  const logout = useCallback(() => {
    removeToken();
    setIsLoggedIn(false);
  }, []);

  // 401 인터셉터에 logout 콜백 등록
  useEffect(() => {
    setOnUnauthorized(logout);
    return () => {
      setOnUnauthorized(null);
    };
  }, [logout]);

  const login = useCallback(async (loginId: string, password: string) => {
    const response = await api.post("/auth/login", {
      login_id: loginId,
      password,
    });
    const { access_token } = response.data;
    setToken(access_token);
    setIsLoggedIn(true);
  }, []);

  return (
    <AuthContext.Provider value={{ isLoggedIn, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
