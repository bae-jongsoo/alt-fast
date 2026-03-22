import { useState, useCallback } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import NewsFilterBar, {
  getDefaultStartDate,
  getDefaultEndDate,
  type NewsTabType,
} from "@/components/news/NewsFilters";
import NewsTable from "@/components/news/NewsTable";
import DartTable from "@/components/news/DartTable";
import {
  useNewsList,
  useDartList,
  type NewsFilters,
  type DartFilters,
} from "@/hooks/useNews";

export default function NewsPage() {
  usePageTitle("ALT | 뉴스·공시");

  // 탭 상태
  const [activeTab, setActiveTab] = useState<NewsTabType>("news");

  // 공통 필터 상태 (탭 전환 시 유지)
  const [startDate, setStartDate] = useState(getDefaultStartDate);
  const [endDate, setEndDate] = useState(getDefaultEndDate);
  const [stockCode, setStockCode] = useState("all");

  // 뉴스 탭 전용 필터
  const [usefulFilter, setUsefulFilter] = useState("all");

  // 페이지 상태
  const [newsPage, setNewsPage] = useState(1);
  const [dartPage, setDartPage] = useState(1);

  // 뉴스 필터 구성
  const newsFilters: NewsFilters = {
    page: newsPage,
    page_size: 20,
    start_date: startDate || undefined,
    end_date: endDate || undefined,
    stock_code: stockCode !== "all" ? stockCode : undefined,
    useful:
      usefulFilter === "useful"
        ? true
        : usefulFilter === "not_useful"
          ? false
          : usefulFilter === "unknown"
            ? null
            : undefined,
  };

  // 공시 필터 구성
  const dartFilters: DartFilters = {
    page: dartPage,
    page_size: 20,
    start_date: startDate || undefined,
    end_date: endDate || undefined,
    stock_code: stockCode !== "all" ? stockCode : undefined,
  };

  // API 호출
  const newsQuery = useNewsList(newsFilters);
  const dartQuery = useDartList(dartFilters);

  // 필터 변경 시 페이지 리셋
  const handleStartDateChange = useCallback((v: string) => {
    setStartDate(v);
    setNewsPage(1);
    setDartPage(1);
  }, []);

  const handleEndDateChange = useCallback((v: string) => {
    setEndDate(v);
    setNewsPage(1);
    setDartPage(1);
  }, []);

  const handleStockCodeChange = useCallback((v: string) => {
    setStockCode(v);
    setNewsPage(1);
    setDartPage(1);
  }, []);

  const handleUsefulFilterChange = useCallback((v: string) => {
    setUsefulFilter(v);
    setNewsPage(1);
  }, []);

  // 탭 전환 시 필터 상태(종목, 날짜 범위) 유지
  const handleTabChange = useCallback((value: unknown) => {
    setActiveTab(value as NewsTabType);
  }, []);

  return (
    <div className="mx-auto max-w-7xl space-y-4 px-4 py-6">
      <h1 className="text-lg font-semibold">뉴스·공시</h1>

      <Tabs value={activeTab} onValueChange={handleTabChange}>
        <TabsList>
          <TabsTrigger value="news">뉴스</TabsTrigger>
          <TabsTrigger value="dart">공시</TabsTrigger>
        </TabsList>

        <TabsContent value="news">
          <NewsFilterBar
            tab="news"
            startDate={startDate}
            endDate={endDate}
            usefulFilter={usefulFilter}
            stockCode={stockCode}
            onStartDateChange={handleStartDateChange}
            onEndDateChange={handleEndDateChange}
            onUsefulFilterChange={handleUsefulFilterChange}
            onStockCodeChange={handleStockCodeChange}
          />
          <NewsTable
            items={newsQuery.data?.items ?? []}
            total={newsQuery.data?.total ?? 0}
            page={newsPage}
            pageSize={20}
            isLoading={newsQuery.isLoading}
            isError={newsQuery.isError}
            onPageChange={setNewsPage}
            onRetry={() => newsQuery.refetch()}
          />
        </TabsContent>

        <TabsContent value="dart">
          <NewsFilterBar
            tab="dart"
            startDate={startDate}
            endDate={endDate}
            usefulFilter={usefulFilter}
            stockCode={stockCode}
            onStartDateChange={handleStartDateChange}
            onEndDateChange={handleEndDateChange}
            onUsefulFilterChange={handleUsefulFilterChange}
            onStockCodeChange={handleStockCodeChange}
          />
          <DartTable
            items={dartQuery.data?.items ?? []}
            total={dartQuery.data?.total ?? 0}
            page={dartPage}
            pageSize={20}
            isLoading={dartQuery.isLoading}
            isError={dartQuery.isError}
            onPageChange={setDartPage}
            onRetry={() => dartQuery.refetch()}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
