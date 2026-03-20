import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatRelativeTime, formatDateTimeFull } from "@/lib/format";
import type { SystemStatusItem, TradingCycleSummary } from "@/hooks/useDashboard";

interface SystemStatusProps {
  statusData?: SystemStatusItem[];
  tradingSummary?: TradingCycleSummary;
  isLoading: boolean;
}

const STATUS_CONFIG: Record<
  string,
  { color: string; label: string }
> = {
  normal: { color: "bg-green-500", label: "정상" },
  delayed: { color: "bg-yellow-500", label: "지연" },
  stopped: { color: "bg-red-500", label: "중단" },
};

const COLLECTOR_NAMES: Record<string, string> = {
  trader: "트레이더",
  market: "시장 데이터",
  news: "뉴스 수집",
  dart: "DART 공시",
  ws: "웹소켓",
};

export default function SystemStatus({
  statusData,
  tradingSummary,
  isLoading,
}: SystemStatusProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>시스템 상태</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-6 w-full" />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>시스템 상태</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* 수집기 상태 */}
        <div className="space-y-2">
          {statusData?.map((item) => {
            const config = STATUS_CONFIG[item.status] ?? STATUS_CONFIG.stopped;
            const lastAt = item.last_active_at
              ? new Date(item.last_active_at)
              : null;
            const relativeText = lastAt
              ? formatRelativeTime(lastAt)
              : null;
            const absoluteText = lastAt
              ? `마지막 동작: ${formatDateTimeFull(lastAt)}`
              : "데이터 없음";

            let statusText = config.label;
            if (item.status === "normal" && relativeText) {
              statusText = relativeText;
            } else if (item.status !== "normal" && relativeText) {
              statusText = `${config.label} (${relativeText})`;
            }

            return (
              <div
                key={item.name}
                className="flex items-center justify-between"
                title={absoluteText}
              >
                <span className="text-sm">
                  {COLLECTOR_NAMES[item.name] ?? item.name}
                </span>
                <span className="flex items-center gap-2 text-sm">
                  <span
                    className={`inline-block size-2 rounded-full ${config.color}`}
                  />
                  {statusText}
                </span>
              </div>
            );
          })}
        </div>

        {/* 트레이딩 사이클 요약 */}
        {tradingSummary && (
          <div className="border-t pt-3">
            <p className="mb-2 text-sm font-medium">트레이딩 사이클</p>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <span className="text-muted-foreground">총 판단</span>
              <span className="text-right">{tradingSummary.total_decisions}회</span>
              <span className="text-muted-foreground">BUY</span>
              <span className="text-right">{tradingSummary.buy_count}회</span>
              <span className="text-muted-foreground">SELL</span>
              <span className="text-right">{tradingSummary.sell_count}회</span>
              <span className="text-muted-foreground">HOLD</span>
              <span className="text-right">{tradingSummary.hold_count}회</span>
              <span className="text-muted-foreground">에러</span>
              <span className="text-right text-destructive">
                {tradingSummary.error_count}회
              </span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
