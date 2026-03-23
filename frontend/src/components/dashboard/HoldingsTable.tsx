import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatPercent } from "@/lib/format";
import type { HoldingStock } from "@/hooks/useDashboard";

interface HoldingsTableProps {
  data?: HoldingStock[];
  isLoading: boolean;
}

function pnlColor(value: number): string {
  if (value > 0) return "text-profit";
  if (value < 0) return "text-loss";
  return "";
}

export default function HoldingsTable({ data, isLoading }: HoldingsTableProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>보유종목</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-8 w-full" />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>보유종목</CardTitle>
      </CardHeader>
      <CardContent>
        {!data || data.length === 0 ? (
          <p className="py-8 text-center text-muted-foreground">
            현재 보유 종목 없음
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>종목명</TableHead>
                <TableHead>종목코드</TableHead>
                <TableHead className="text-right">수량</TableHead>
                <TableHead className="text-right">매수단가</TableHead>
                <TableHead className="text-right">현재가</TableHead>
                <TableHead className="text-right">평가손익</TableHead>
                <TableHead className="text-right">수익률</TableHead>
                <TableHead className="text-right">수익률(세후)</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.map((h) => (
                <TableRow key={h.stock_code}>
                  <TableCell className="font-medium">{h.stock_name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {h.stock_code}
                  </TableCell>
                  <TableCell className="text-right">
                    {h.quantity.toLocaleString()}
                  </TableCell>
                  <TableCell className="text-right">
                    {formatCurrency(h.avg_buy_price)}
                  </TableCell>
                  <TableCell className="text-right">
                    {formatCurrency(h.current_price)}
                  </TableCell>
                  <TableCell className={`text-right ${pnlColor(h.eval_pnl)}`}>
                    {h.eval_pnl > 0 ? "+" : ""}
                    {formatCurrency(h.eval_pnl)}
                  </TableCell>
                  <TableCell
                    className={`text-right ${pnlColor(h.profit_rate)}`}
                  >
                    {formatPercent(h.profit_rate)}
                  </TableCell>
                  <TableCell
                    className={`text-right ${pnlColor(h.profit_rate_net)}`}
                  >
                    {formatPercent(h.profit_rate_net)}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
