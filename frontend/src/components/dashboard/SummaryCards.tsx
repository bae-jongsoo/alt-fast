import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatPercent } from "@/lib/format";
import type { SummaryCard } from "@/hooks/useDashboard";
import {
  Wallet,
  Banknote,
  TrendingUp,
  ArrowLeftRight,
} from "lucide-react";

interface SummaryCardsProps {
  data?: SummaryCard;
  isLoading: boolean;
}

function pnlColor(value: number): string {
  if (value > 0) return "text-profit";
  if (value < 0) return "text-loss";
  return "";
}

export default function SummaryCards({ data, isLoading }: SummaryCardsProps) {
  if (isLoading || !data) {
    return (
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <Card key={i}>
            <CardHeader>
              <Skeleton className="h-4 w-24" />
            </CardHeader>
            <CardContent>
              <Skeleton className="h-8 w-32" />
              <Skeleton className="mt-2 h-3 w-20" />
            </CardContent>
          </Card>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      {/* 총 자산가치 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm text-muted-foreground">
            <Wallet className="size-4" />
            총 자산가치
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">
            {formatCurrency(data.total_asset_value)}
          </p>
          {data.total_asset_change != null &&
            data.total_asset_change_rate != null &&
            data.total_asset_change !== 0 && (
              <p
                className={`mt-1 text-sm ${pnlColor(data.total_asset_change)}`}
              >
                {data.total_asset_change > 0 ? "+" : ""}
                {formatCurrency(data.total_asset_change)} (
                {formatPercent(data.total_asset_change_rate)})
              </p>
            )}
        </CardContent>
      </Card>

      {/* 현금 잔고 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm text-muted-foreground">
            <Banknote className="size-4" />
            현금 잔고
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">
            {formatCurrency(data.cash_balance)}
          </p>
        </CardContent>
      </Card>

      {/* 오늘 실현손익 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm text-muted-foreground">
            <TrendingUp className="size-4" />
            오늘 실현손익
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className={`text-2xl font-bold ${pnlColor(data.today_realized_pnl)}`}>
            {data.today_realized_pnl > 0 ? "+" : ""}
            {formatCurrency(data.today_realized_pnl)}
          </p>
        </CardContent>
      </Card>

      {/* 오늘 거래 횟수 */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm text-muted-foreground">
            <ArrowLeftRight className="size-4" />
            오늘 거래 횟수
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-2xl font-bold">{data.today_trade_count}건</p>
          <p className="mt-1 text-sm text-muted-foreground">
            BUY {data.today_buy_count} / SELL {data.today_sell_count}
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
