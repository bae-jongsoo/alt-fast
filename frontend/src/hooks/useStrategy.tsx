import {
  createContext,
  useContext,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";

// --- 타입 ---

export interface Strategy {
  id: number;
  name: string;
  description: string | null;
  initial_capital: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface StrategyListResponse {
  items: Strategy[];
}

export interface StrategyCreate {
  name: string;
  description?: string | null;
  initial_capital: number;
}

export interface StrategyUpdate {
  description?: string | null;
  is_active?: boolean;
}

// --- API 훅 ---

export function useStrategies() {
  return useQuery<StrategyListResponse>({
    queryKey: ["strategies"],
    queryFn: () => api.get("/strategies").then((res) => res.data),
    staleTime: 60 * 1000,
  });
}

export function useCreateStrategy() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: StrategyCreate) =>
      api.post("/strategies", data).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["strategies"] });
    },
  });
}

export function useUpdateStrategy() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: StrategyUpdate }) =>
      api.patch(`/strategies/${id}`, data).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["strategies"] });
    },
  });
}

// --- 전역 전략 선택 컨텍스트 ---

interface StrategyContextType {
  /** null = "전체", number = 특정 전략 ID */
  selectedStrategyId: number | null;
  setSelectedStrategyId: (id: number | null) => void;
  /** 선택된 전략 객체 (전체 선택 시 null) */
  selectedStrategy: Strategy | null;
  /** 전략 목록 */
  strategies: Strategy[];
  isLoading: boolean;
}

const StrategyContext = createContext<StrategyContextType | null>(null);

export function StrategyProvider({ children }: { children: ReactNode }) {
  const [selectedStrategyId, setSelectedStrategyIdRaw] = useState<
    number | null
  >(() => {
    const stored = localStorage.getItem("selected_strategy_id");
    if (stored === null || stored === "null") return null;
    const parsed = parseInt(stored, 10);
    return isNaN(parsed) ? null : parsed;
  });

  const { data, isLoading } = useStrategies();
  const strategies = data?.items ?? [];

  const setSelectedStrategyId = useCallback((id: number | null) => {
    setSelectedStrategyIdRaw(id);
    localStorage.setItem(
      "selected_strategy_id",
      id === null ? "null" : String(id)
    );
  }, []);

  const selectedStrategy =
    strategies.find((s) => s.id === selectedStrategyId) ?? null;

  return (
    <StrategyContext.Provider
      value={{
        selectedStrategyId,
        setSelectedStrategyId,
        selectedStrategy,
        strategies,
        isLoading,
      }}
    >
      {children}
    </StrategyContext.Provider>
  );
}

export function useStrategyContext() {
  const ctx = useContext(StrategyContext);
  if (!ctx) {
    throw new Error("useStrategyContext must be used within StrategyProvider");
  }
  return ctx;
}
