import { useDashboard, type DashboardResponse } from "@/hooks/useDashboard";
import {
  useStrategyContext,
  type Strategy,
} from "@/hooks/useStrategy";
import { formatCurrency } from "@/lib/format";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { TrendingUp, TrendingDown, Minus, ArrowRight } from "lucide-react";

function StrategyCard({
  strategy,
  data,
  isLoading,
  onClick,
}: {
  strategy: Strategy;
  data?: DashboardResponse;
  isLoading: boolean;
  onClick: () => void;
}) {
  const summary = data?.summary;
  const holdings = data?.holdings ?? [];
  const tradingSummary = data?.trading_summary;

  const pnl = summary?.today_realized_pnl ?? 0;
  const pnlColor =
    pnl > 0 ? "text-red-500" : pnl < 0 ? "text-blue-500" : "text-muted-foreground";
  const PnlIcon = pnl > 0 ? TrendingUp : pnl < 0 ? TrendingDown : Minus;

  return (
    <Card
      className="cursor-pointer transition-shadow hover:shadow-md"
      onClick={onClick}
    >
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base font-semibold">
            {strategy.name}
          </CardTitle>
          <ArrowRight className="size-4 text-muted-foreground" />
        </div>
        {strategy.description && (
          <p className="text-xs text-muted-foreground">{strategy.description}</p>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <div className="space-y-2">
            <Skeleton className="h-6 w-32" />
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-4 w-20" />
          </div>
        ) : (
          <>
            {/* 총 자산 */}
            <div>
              <p className="text-xs text-muted-foreground">총 자산</p>
              <p className="text-lg font-bold">
                {summary ? formatCurrency(summary.total_asset_value) : "-"}
              </p>
            </div>

            {/* 오늘 실현손익 */}
            <div className="flex items-center gap-1.5">
              <PnlIcon className={`size-3.5 ${pnlColor}`} />
              <span className={`text-sm font-medium ${pnlColor}`}>
                {pnl > 0 ? "+" : ""}
                {formatCurrency(pnl)}
              </span>
              <span className="text-xs text-muted-foreground">오늘</span>
            </div>

            {/* 보유 종목 */}
            <div>
              <p className="text-xs text-muted-foreground">
                보유: {holdings.length > 0 ? holdings.map((h) => h.stock_name).join(", ") : "없음"}
              </p>
            </div>

            {/* 오늘 거래 */}
            {tradingSummary && (
              <div className="flex gap-3 text-xs text-muted-foreground">
                <span>매수 {tradingSummary.buy_count}</span>
                <span>매도 {tradingSummary.sell_count}</span>
                <span>관망 {tradingSummary.hold_count}</span>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function useStrategyDashboard(strategyId: number) {
  return useDashboard(strategyId);
}

function StrategyCardWrapper({
  strategy,
  onClick,
}: {
  strategy: Strategy;
  onClick: () => void;
}) {
  const { data, isLoading } = useStrategyDashboard(strategy.id);
  return (
    <StrategyCard
      strategy={strategy}
      data={data}
      isLoading={isLoading}
      onClick={onClick}
    />
  );
}

export default function StrategyOverview() {
  const { strategies, isLoading, setSelectedStrategyId } = useStrategyContext();

  const activeStrategies = strategies.filter((s) => s.is_active);

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-4 py-6">
      <h1 className="text-lg font-semibold">전략 오버뷰</h1>

      {isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => (
            <Card key={i}>
              <CardHeader>
                <Skeleton className="h-5 w-24" />
              </CardHeader>
              <CardContent className="space-y-2">
                <Skeleton className="h-6 w-32" />
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-4 w-20" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : activeStrategies.length === 0 ? (
        <p className="text-muted-foreground py-10 text-center">
          활성 전략이 없습니다. 설정에서 전략을 추가해주세요.
        </p>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {activeStrategies.map((strategy) => (
            <StrategyCardWrapper
              key={strategy.id}
              strategy={strategy}
              onClick={() => setSelectedStrategyId(strategy.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
