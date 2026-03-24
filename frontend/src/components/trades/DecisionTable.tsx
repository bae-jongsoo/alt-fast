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
import { formatDateTimeFull } from "@/lib/format";
import type { DecisionHistoryItem } from "@/hooks/useTrades";
import DecisionDetail from "./DecisionDetail";
import { AlertCircle, ChevronLeft, ChevronRight } from "lucide-react";

interface DecisionTableProps {
  items: DecisionHistoryItem[];
  total: number;
  page: number;
  pageSize: number;
  isLoading: boolean;
  isError: boolean;
  highlightId: number | null;
  onPageChange: (page: number) => void;
  onRetry: () => void;
}

function DecisionBadge({ decision }: { decision: string }) {
  switch (decision) {
    case "BUY":
      return (
        <Badge className="bg-blue-500/15 text-blue-600 dark:text-blue-400">
          BUY
        </Badge>
      );
    case "SELL":
      return (
        <Badge className="bg-red-500/15 text-red-600 dark:text-red-400">
          SELL
        </Badge>
      );
    case "HOLD":
      return (
        <Badge variant="secondary">HOLD</Badge>
      );
    default:
      return <Badge variant="outline">{decision}</Badge>;
  }
}

export default function DecisionTable({
  items,
  total,
  page,
  pageSize,
  isLoading,
  isError,
  highlightId,
  onPageChange,
  onRetry,
}: DecisionTableProps) {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  const handleRowClick = (id: number) => {
    setExpandedId((prev) => (prev === id ? null : id));
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
            <TableHead>결과</TableHead>
            <TableHead>소스</TableHead>
            <TableHead>에러</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading
            ? Array.from({ length: 5 }).map((_, i) => (
                <TableRow key={i}>
                  {Array.from({ length: 5 }).map((_, j) => (
                    <TableCell key={j}>
                      <Skeleton className="h-4 w-full" />
                    </TableCell>
                  ))}
                </TableRow>
              ))
            : items.length === 0
              ? (
                <TableRow>
                  <TableCell colSpan={5} className="text-center py-12 text-muted-foreground">
                    조건에 맞는 이력이 없습니다. 필터를 조정해보세요.
                  </TableCell>
                </TableRow>
              )
              : items.map((item) => (
                  <>
                    <TableRow
                      key={item.id}
                      className={`cursor-pointer hover:bg-muted/70 ${
                        highlightId === item.id
                          ? "bg-yellow-100/50 dark:bg-yellow-900/20"
                          : ""
                      } ${expandedId === item.id ? "bg-muted/50" : ""}`}
                      onClick={() => handleRowClick(item.id)}
                    >
                      <TableCell className="text-xs">
                        {formatDateTimeFull(new Date(item.created_at))}
                      </TableCell>
                      <TableCell>
                        <span className="font-medium">{item.stock_name}</span>
                        <span className="text-xs text-muted-foreground ml-1">
                          ({item.stock_code})
                        </span>
                      </TableCell>
                      <TableCell>
                        <DecisionBadge decision={item.decision} />
                      </TableCell>
                      <TableCell>
                        {item.sources && item.sources.length > 0 ? (
                          <div className="flex flex-wrap gap-1">
                            {item.sources.map((s, i) => (
                              <span
                                key={i}
                                className="inline-flex items-center text-xs rounded bg-muted px-1.5 py-0.5"
                                title={s.detail}
                              >
                                <span className="font-medium">{s.type}</span>
                                <span className="text-muted-foreground ml-1">
                                  {Math.round(s.weight * 100)}%
                                </span>
                              </span>
                            ))}
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground">-</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {item.is_error ? (
                          <div className="flex items-center gap-1.5">
                            <AlertCircle className="size-4 text-destructive" />
                            <span className="text-xs text-destructive truncate max-w-[200px]">
                              {item.error_message || "에러"}
                            </span>
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground">-</span>
                        )}
                      </TableCell>
                    </TableRow>
                    {expandedId === item.id && (
                      <TableRow key={`detail-${item.id}`}>
                        <TableCell colSpan={5} className="p-0">
                          <DecisionDetail decisionId={item.id} />
                        </TableCell>
                      </TableRow>
                    )}
                  </>
                ))}
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
