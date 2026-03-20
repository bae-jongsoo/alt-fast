import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";

// --- 타입 정의 ---

export interface NewsItem {
  id: number;
  published_at: string;
  stock_code: string;
  stock_name: string;
  title: string;
  summary: string | null;
  url: string;
  useful: boolean | null;
}

export interface NewsListResponse {
  items: NewsItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface DartItem {
  id: number;
  published_at: string;
  stock_code: string;
  stock_name: string;
  title: string;
  body: string | null;
  url: string;
}

export interface DartListResponse {
  items: DartItem[];
  total: number;
  page: number;
  page_size: number;
}

// --- 필터 타입 ---

export interface NewsFilters {
  page: number;
  page_size: number;
  start_date?: string;
  end_date?: string;
  stock_code?: string;
  useful?: boolean | null;
}

export interface DartFilters {
  page: number;
  page_size: number;
  start_date?: string;
  end_date?: string;
  stock_code?: string;
}

// --- API 훅 ---

export function useNewsList(filters: NewsFilters) {
  return useQuery<NewsListResponse>({
    queryKey: ["news", filters],
    queryFn: () => api.get("/news", { params: filters }).then((res) => res.data),
  });
}

export function useDartList(filters: DartFilters) {
  return useQuery<DartListResponse>({
    queryKey: ["dart", filters],
    queryFn: () => api.get("/dart", { params: filters }).then((res) => res.data),
  });
}
