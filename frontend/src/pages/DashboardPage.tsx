import { usePageTitle } from "@/hooks/use-page-title";
import { useDashboard } from "@/hooks/useDashboard";
import { format } from "date-fns";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import SummaryCards from "@/components/dashboard/SummaryCards";
import HoldingsTable from "@/components/dashboard/HoldingsTable";
import SystemStatus from "@/components/dashboard/SystemStatus";
import RecentActivity from "@/components/dashboard/RecentActivity";

export default function DashboardPage() {
  usePageTitle("ALT | 대시보드");

  const { data, isLoading, isError, refetch, isFetching, dataUpdatedAt } =
    useDashboard();

  // 에러 상태
  if (isError && !data) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-20">
        <p className="text-muted-foreground">
          데이터를 불러올 수 없습니다. 다시 시도해주세요.
        </p>
        <Button variant="outline" onClick={() => refetch()}>
          다시 시도
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-4 py-6">
      {/* 헤더: 제목 + 새로고침 버튼 */}
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">대시보드</h1>
        <div className="flex items-center gap-3">
          {dataUpdatedAt > 0 && (
            <span className="text-sm text-muted-foreground">
              마지막 갱신: {format(new Date(dataUpdatedAt), "HH:mm:ss")}
            </span>
          )}
          <Button
            variant="outline"
            size="icon"
            onClick={() => refetch()}
            disabled={isFetching}
          >
            <RefreshCw
              className={`size-4 ${isFetching ? "animate-spin" : ""}`}
            />
          </Button>
        </div>
      </div>

      {/* 요약 카드 */}
      <SummaryCards data={data?.summary} isLoading={isLoading} />

      {/* 중단 영역: 보유종목(좌) + 시스템상태(우) */}
      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
        <HoldingsTable data={data?.holdings} isLoading={isLoading} />
        <SystemStatus
          statusData={data?.system_status}
          tradingSummary={data?.trading_summary}
          isLoading={isLoading}
        />
      </div>

      {/* 최근 활동 */}
      <RecentActivity
        orders={data?.recent_orders}
        errors={data?.recent_errors}
        isLoading={isLoading}
      />
    </div>
  );
}
