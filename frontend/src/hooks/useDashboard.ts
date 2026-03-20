import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";

export interface SummaryCard {
  total_asset_value: number;
  total_asset_change: number | null;
  total_asset_change_rate: number | null;
  cash_balance: number;
  today_realized_pnl: number;
  today_trade_count: number;
  today_buy_count: number;
  today_sell_count: number;
}

export interface HoldingStock {
  stock_code: string;
  stock_name: string;
  quantity: number;
  avg_buy_price: number;
  current_price: number;
  eval_pnl: number;
  profit_rate: number;
}

export interface SystemStatusItem {
  name: string;
  status: "normal" | "delayed" | "stopped";
  last_active_at: string | null;
  threshold_seconds: number;
}

export interface TradingCycleSummary {
  total_decisions: number;
  buy_count: number;
  sell_count: number;
  hold_count: number;
  error_count: number;
}

export interface RecentOrder {
  id: number;
  created_at: string;
  stock_name: string;
  order_type: "BUY" | "SELL";
  order_price: number;
  quantity: number;
  profit_loss: number | null;
}

export interface RecentError {
  id: number;
  created_at: string;
  error_message: string;
}

export interface DashboardResponse {
  summary: SummaryCard;
  holdings: HoldingStock[];
  system_status: SystemStatusItem[];
  trading_summary: TradingCycleSummary;
  recent_orders: RecentOrder[];
  recent_errors: RecentError[];
  last_updated_at: string;
}

export function useDashboard() {
  return useQuery<DashboardResponse>({
    queryKey: ["dashboard"],
    queryFn: () => api.get("/dashboard").then((res) => res.data),
    refetchInterval: 30000,
  });
}
