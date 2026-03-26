import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";

export interface CandleItem {
  minute_at: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface CandleListResponse {
  items: CandleItem[];
}

export interface CandleFilters {
  stock_code: string;
  start?: string;
  end?: string;
}

export function useCandles(filters: CandleFilters, enabled = true) {
  return useQuery<CandleListResponse>({
    queryKey: ["candles", filters],
    queryFn: () =>
      api.get("/chart/candles", { params: filters }).then((res) => res.data),
    enabled: enabled && !!filters.stock_code,
  });
}
