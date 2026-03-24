import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";

// --- 타입 정의 ---

export interface OrderHistoryItem {
  id: number;
  created_at: string;
  stock_code: string;
  stock_name: string;
  order_type: "BUY" | "SELL";
  order_price: number;
  quantity: number;
  total_amount: number;
  profit_loss: number | null;
  profit_rate: number | null;
  profit_rate_net: number | null;
  decision_history_id: number | null;
}

export interface OrderHistoryListResponse {
  items: OrderHistoryItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface SourceItem {
  type: string;
  weight: number;
  detail: string;
}

export interface DecisionHistoryItem {
  id: number;
  created_at: string;
  stock_code: string;
  stock_name: string;
  decision: string;
  is_error: boolean;
  error_message: string | null;
  sources: SourceItem[] | null;
}

export interface DecisionHistoryListResponse {
  items: DecisionHistoryItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface DecisionDetailResponse {
  id: number;
  created_at: string;
  stock_code: string;
  stock_name: string;
  decision: string;
  request_payload: string | null;
  response_payload: string | null;
  parsed_decision: Record<string, unknown> | null;
  is_error: boolean;
  error_message: string | null;
  linked_order: OrderHistoryItem | null;
}

export interface TargetStock {
  id: number;
  stock_code: string;
  stock_name: string;
  is_active: boolean;
}

// --- 필터 타입 ---

export interface OrderFilters {
  page: number;
  page_size: number;
  start_date?: string;
  end_date?: string;
  order_type?: string;
  stock_code?: string;
}

export interface DecisionFilters {
  page: number;
  page_size: number;
  start_date?: string;
  end_date?: string;
  decision?: string;
  stock_code?: string;
  errors_only?: boolean;
}

// --- API 훅 ---

export function useOrderHistory(filters: OrderFilters) {
  return useQuery<OrderHistoryListResponse>({
    queryKey: ["orders", filters],
    queryFn: () => api.get("/trades/orders", { params: filters }).then((res) => res.data),
  });
}

export function useDecisionHistory(filters: DecisionFilters) {
  return useQuery<DecisionHistoryListResponse>({
    queryKey: ["decisions", filters],
    queryFn: () => api.get("/trades/decisions", { params: filters }).then((res) => res.data),
  });
}

export function useDecisionDetail(id: number | null) {
  return useQuery<DecisionDetailResponse>({
    queryKey: ["decision", id],
    queryFn: () => api.get(`/trades/decisions/${id}`).then((res) => res.data),
    enabled: !!id,
  });
}

export function useTargetStocks() {
  return useQuery<{ items: TargetStock[] }>({
    queryKey: ["target-stocks"],
    queryFn: () => api.get("/settings/stocks").then((res) => res.data),
    staleTime: 60 * 1000,
  });
}
