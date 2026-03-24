import { useState } from "react";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { formatCurrency, formatDateTimeFull, formatPercent } from "@/lib/format";
import type { OrderHistoryItem } from "@/hooks/useTrades";
import DecisionDetail from "./DecisionDetail";
import { AlertCircle, ChevronLeft, ChevronRight } from "lucide-react";

interface OrderTableProps {
  items: OrderHistoryItem[];
  total: number;
  page: number;
  pageSize: number;
  isLoading: boolean;
  isError: boolean;
  onPageChange: (page: number) => void;
  onRetry: () => void;
}

export default function OrderTable({
  items,
  total,
  page,
  pageSize,
  isLoading,
  isError,
  onPageChange,
  onRetry,
}: OrderTableProps) {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const handleRowClick = (order: OrderHistoryItem) => {
    if (order.decision_history_id == null) return;
    setExpandedId((prev) =>
      prev === order.decision_history_id ? null : order.decision_history_id
    );
  };

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-12 gap-3 text-muted-foreground">
        <AlertCircle className="size-8 text-destructive" />
        <p>데이터를 불러오는 중 오류가 발생했습니다.</p>
        <Button variant="outline" size="sm" onClick={onRetry}>
          재시도
        </Button>
      </div>
    );
  }

  return (
    <div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>일시</TableHead>
            <TableHead>종목</TableHead>
            <TableHead>구분</TableHead>
            <TableHead className="text-right">주문가격</TableHead>
            <TableHead className="text-right">수량</TableHead>
            <TableHead className="text-right">총액</TableHead>
            <TableHead className="text-right">손익</TableHead>
            <TableHead className="text-right">수익률</TableHead>
            <TableHead className="text-right">수익률(세후)</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading
            ? Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i}>
                  {Array.from({ length: 9 }).map((_, j) => (
                    <TableCell key={j}>
                      <Skeleton className="h-4 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            : items.length === 0
              ? (
                <TableRow>
                  <TableCell colSpan={9} className="text-center py-12 text-muted-foreground">
                    조건에 맞는 이력이 없습니다. 필터를 조정해보세요.
                  </TableCell>
                </TableRow>
              )
              : items.map((order) => {
                  const hasDecision = order.decision_history_id != null;
                  const isExpanded = expandedId === order.decision_history_id;
                  return (
                    <>
                      <TableRow
                        key={order.id}
                        className={`${
                          hasDecision
                            ? "cursor-pointer hover:bg-muted/70"
                            : ""
                        } ${isExpanded ? "bg-muted/50" : ""}`}
                        onClick={() => handleRowClick(order)}
                      >
                        <TableCell className="text-xs">
                          {formatDateTimeFull(new Date(order.created_at))}
                        </TableCell>
                        <TableCell>
                          <span className="font-medium">{order.stock_name}</span>
                          <span className="text-xs text-muted-foreground ml-1">
                            ({order.stock_code})
                          </span>
                        </TableCell>
                        <TableCell>
                          <Badge
                            variant={order.order_type === "BUY" ? "default" : "destructive"}
                            className={
                              order.order_type === "BUY"
                                ? "bg-blue-500/15 text-blue-600 dark:text-blue-400"
                                : "bg-red-500/15 text-red-600 dark:text-red-400"
                            }
                          >
                            {order.order_type}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          {formatCurrency(order.order_price)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          {order.quantity.toLocaleString()}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          {formatCurrency(order.total_amount)}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          {order.order_type === "BUY" || order.profit_loss == null ? (
                            <span className="text-muted-foreground">-</span>
                          ) : (
                            <span
                              className={
                                order.profit_loss > 0
                                  ? "text-red-600 dark:text-red-400"
                                  : order.profit_loss < 0
                                    ? "text-blue-600 dark:text-blue-400"
                                    : "text-muted-foreground"
                              }
                            >
                              {order.profit_loss > 0 ? "+" : ""}
                              {formatCurrency(order.profit_loss)}
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          {order.order_type === "BUY" || order.profit_rate == null ? (
                            <span className="text-muted-foreground">-</span>
                          ) : (
                            <span
                              className={
                                order.profit_rate > 0
                                  ? "text-red-600 dark:text-red-400"
                                  : order.profit_rate < 0
                                    ? "text-blue-600 dark:text-blue-400"
                                    : "text-muted-foreground"
                              }
                            >
                              {formatPercent(order.profit_rate)}
                            </span>
                          )}
                        </TableCell>
                        <TableCell className="text-right font-mono text-xs">
                          {order.order_type === "BUY" || order.profit_rate_net == null ? (
                            <span className="text-muted-foreground">-</span>
                          ) : (
                            <span
                              className={
                                order.profit_rate_net > 0
                                  ? "text-red-600 dark:text-red-400"
                                  : order.profit_rate_net < 0
                                    ? "text-blue-600 dark:text-blue-400"
                                    : "text-muted-foreground"
                              }
                            >
                              {formatPercent(order.profit_rate_net)}
                            </span>
                          )}
                        </TableCell>
                      </TableRow>
                      {isExpanded && order.decision_history_id != null && (
                        <TableRow key={`detail-${order.id}`}>
                          <TableCell colSpan={9} className="p-0">
                            <DecisionDetail decisionId={order.decision_history_id} />
                          </TableCell>
                        </TableRow>
                      )}
                    </>
                  );
                })}
        </TableBody>
      </Table>

      {/* 페이지네이션 */}
      {!isLoading && items.length > 0 && (
        <div className="flex items-center justify-between px-2 py-3">
          <span className="text-xs text-muted-foreground">
            총 {total.toLocaleString()}건 중 {((page - 1) * pageSize + 1).toLocaleString()}–
            {Math.min(page * pageSize, total).toLocaleString()}
          </span>
          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => onPageChange(page - 1)}
            >
              <ChevronLeft className="size-4" />
            </Button>
            <span className="text-sm px-2">
              {page} / {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => onPageChange(page + 1)}
            >
              <ChevronRight className="size-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
