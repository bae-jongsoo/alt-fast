import { useState, useCallback } from "react";
import { useSearchParams } from "react-router-dom";
import { usePageTitle } from "@/hooks/use-page-title";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import TradeFilters, {
  getDefaultStartDate,
  getDefaultEndDate,
  type TabType,
} from "@/components/trades/TradeFilters";
import OrderTable from "@/components/trades/OrderTable";
import DecisionTable from "@/components/trades/DecisionTable";
import {
  useOrderHistory,
  useDecisionHistory,
  type OrderFilters,
  type DecisionFilters,
} from "@/hooks/useTrades";

export default function TradesPage() {
  usePageTitle("ALT | 매매이력");

  // 탭 상태 (URL 파라미터로 유지)
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = (searchParams.get("tab") as TabType) || "orders";

  // 공통 필터 상태
  const [startDate, setStartDate] = useState(getDefaultStartDate);
  const [endDate, setEndDate] = useState(getDefaultEndDate);
  const [resultFilter, setResultFilter] = useState("all");
  const [stockCode, setStockCode] = useState("all");

  // 페이지 상태
  const [orderPage, setOrderPage] = useState(1);
  const [decisionPage, setDecisionPage] = useState(1);

  // 판단 이력 하이라이트 (주문 이력에서 클릭 시)
  const [highlightDecisionId, setHighlightDecisionId] = useState<number | null>(null);

  // 주문 이력 필터 구성
  const orderFilters: OrderFilters = {
    page: orderPage,
    page_size: 20,
    start_date: startDate || undefined,
    end_date: endDate || undefined,
    order_type: resultFilter !== "all" ? resultFilter : undefined,
    stock_code: stockCode !== "all" ? stockCode : undefined,
  };

  // 판단 이력 필터 구성
  const decisionFilters: DecisionFilters = {
    page: decisionPage,
    page_size: 20,
    start_date: startDate || undefined,
    end_date: endDate || undefined,
    decision:
      resultFilter !== "all" && resultFilter !== "errors_only"
        ? resultFilter
        : undefined,
    stock_code: stockCode !== "all" ? stockCode : undefined,
    errors_only: resultFilter === "errors_only" ? true : undefined,
  };

  // API 호출
  const ordersQuery = useOrderHistory(orderFilters);
  const decisionsQuery = useDecisionHistory(decisionFilters);

  // 필터 변경 시 페이지 리셋
  const handleStartDateChange = useCallback((v: string) => {
    setStartDate(v);
    setOrderPage(1);
    setDecisionPage(1);
  }, []);
  const handleEndDateChange = useCallback((v: string) => {
    setEndDate(v);
    setOrderPage(1);
    setDecisionPage(1);
  }, []);
  const handleResultFilterChange = useCallback((v: string) => {
    setResultFilter(v);
    setOrderPage(1);
    setDecisionPage(1);
  }, []);
  const handleStockCodeChange = useCallback((v: string) => {
    setStockCode(v);
    setOrderPage(1);
    setDecisionPage(1);
  }, []);

  // 탭 전환 시 결과 필터 리셋 (탭별 옵션이 다르므로)
  const handleTabChange = useCallback(
    (value: unknown) => {
      const tab = value as TabType;
      setSearchParams({ tab }, { replace: true });
      // 탭 전환 시 결과 필터를 "전체"로 리셋
      setResultFilter("all");
      setHighlightDecisionId(null);
    },
    [setSearchParams]
  );

  // 주문 이력 행 클릭 → 판단 이력 탭으로 이동 + 하이라이트
  const handleOrderClick = useCallback((decisionHistoryId: number) => {
    setHighlightDecisionId(decisionHistoryId);
    setSearchParams({ tab: "decisions" }, { replace: true });
    setResultFilter("all");
    setDecisionPage(1);
  }, []);

  return (
    <div className="mx-auto max-w-7xl space-y-4 px-4 py-6">
      <h1 className="text-lg font-semibold">매매이력</h1>

      <Tabs value={activeTab} onValueChange={handleTabChange}>
        <TabsList>
          <TabsTrigger value="orders">주문 이력</TabsTrigger>
          <TabsTrigger value="decisions">판단 이력</TabsTrigger>
        </TabsList>

        <TabsContent value="orders">
          <TradeFilters
            tab="orders"
            startDate={startDate}
            endDate={endDate}
            resultFilter={resultFilter}
            stockCode={stockCode}
            onStartDateChange={handleStartDateChange}
            onEndDateChange={handleEndDateChange}
            onResultFilterChange={handleResultFilterChange}
            onStockCodeChange={handleStockCodeChange}
          />
          <OrderTable
            items={ordersQuery.data?.items ?? []}
            total={ordersQuery.data?.total ?? 0}
            page={orderPage}
            pageSize={20}
            isLoading={ordersQuery.isLoading}
            isError={ordersQuery.isError}
            onPageChange={setOrderPage}
            onOrderClick={handleOrderClick}
            onRetry={() => ordersQuery.refetch()}
          />
        </TabsContent>

        <TabsContent value="decisions">
          <TradeFilters
            tab="decisions"
            startDate={startDate}
            endDate={endDate}
            resultFilter={resultFilter}
            stockCode={stockCode}
            onStartDateChange={handleStartDateChange}
            onEndDateChange={handleEndDateChange}
            onResultFilterChange={handleResultFilterChange}
            onStockCodeChange={handleStockCodeChange}
          />
          <DecisionTable
            items={decisionsQuery.data?.items ?? []}
            total={decisionsQuery.data?.total ?? 0}
            page={decisionPage}
            pageSize={20}
            isLoading={decisionsQuery.isLoading}
            isError={decisionsQuery.isError}
            highlightId={highlightDecisionId}
            onPageChange={setDecisionPage}
            onRetry={() => decisionsQuery.refetch()}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
