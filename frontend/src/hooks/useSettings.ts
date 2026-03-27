import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";

// ── 종목 설정 타입 ──

export interface TargetStockItem {
  id: number;
  stock_code: string;
  stock_name: string;
  dart_corp_code: string | null;
  is_active: boolean;
  created_at: string;
}

export interface TargetStockListResponse {
  items: TargetStockItem[];
}

export interface TargetStockCreate {
  strategy_id: number;
  stock_code: string;
  stock_name: string;
  dart_corp_code?: string | null;
}

// ── 프롬프트 설정 타입 ──

export interface PromptTemplateItem {
  id: number;
  prompt_type: string;
  content: string;
  version: number;
  is_active: boolean;
  created_at: string;
}

export interface PromptTemplateListResponse {
  buy_prompt: PromptTemplateItem | null;
  sell_prompt: PromptTemplateItem | null;
  buy_versions: PromptTemplateItem[];
  sell_versions: PromptTemplateItem[];
}

// ── 시스템 파라미터 타입 ──

export interface SystemParameterItem {
  key: string;
  value: string;
  updated_at: string;
}

export interface SystemParameterListResponse {
  items: SystemParameterItem[];
}

// ── 종목 설정 훅 ──

export function useTargetStocks(strategyId?: number | null) {
  const params: Record<string, unknown> = {};
  if (strategyId != null) params.strategy_id = strategyId;

  return useQuery<TargetStockListResponse>({
    queryKey: ["settings", "stocks", strategyId ?? "all"],
    queryFn: () => api.get("/settings/stocks", { params }).then((res) => res.data),
  });
}

export function useAddStock() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: TargetStockCreate) =>
      api.post("/settings/stocks", data).then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings", "stocks"] });
    },
  });
}

export function useDeleteStock() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (stockCode: string) =>
      api.delete(`/settings/stocks/${stockCode}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings", "stocks"] });
    },
  });
}

// ── 프롬프트 설정 훅 ──

export function usePrompts(strategyId?: number | null) {
  const params: Record<string, unknown> = {};
  if (strategyId != null) params.strategy_id = strategyId;

  return useQuery<PromptTemplateListResponse>({
    queryKey: ["settings", "prompts", strategyId ?? "all"],
    queryFn: () => api.get("/settings/prompts", { params }).then((res) => res.data),
  });
}

export function usePromptVariables() {
  return useQuery<Record<string, string[]>>({
    queryKey: ["settings", "prompts", "variables"],
    queryFn: () =>
      api.get("/settings/prompts/variables").then((res) => res.data),
  });
}

export function useUpdatePrompt() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      promptType,
      content,
      strategyId,
    }: {
      promptType: string;
      content: string;
      strategyId?: number;
    }) =>
      api
        .put(`/settings/prompts/${promptType}`, { content }, {
          params: strategyId != null ? { strategy_id: strategyId } : undefined,
        })
        .then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings", "prompts"] });
    },
  });
}

// ── 시스템 파라미터 훅 ──

export function useParameters() {
  return useQuery<SystemParameterListResponse>({
    queryKey: ["settings", "parameters"],
    queryFn: () => api.get("/settings/parameters").then((res) => res.data),
  });
}

export function useUpdateParameters() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (parameters: Record<string, string>) =>
      api
        .put("/settings/parameters", { parameters })
        .then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings", "parameters"] });
    },
  });
}

export function useResetParameters() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.post("/settings/parameters/reset").then((res) => res.data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings", "parameters"] });
    },
  });
}
