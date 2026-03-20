import { useState } from "react";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ExternalLink } from "lucide-react";
import { formatDateTime } from "@/lib/format";
import type { DartItem } from "@/hooks/useNews";

interface DartTableProps {
  items: DartItem[];
  total: number;
  page: number;
  pageSize: number;
  isLoading: boolean;
  isError: boolean;
  onPageChange: (page: number) => void;
  onRetry: () => void;
}

function BodyPreviewCell({ text }: { text: string | null }) {
  const [expanded, setExpanded] = useState(false);

  if (!text) return <span className="text-muted-foreground">-</span>;

  return (
    <div className="max-w-md">
      <p className={expanded ? "" : "line-clamp-2"}>
        {text}
      </p>
      {text.length > 80 && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-primary hover:underline mt-0.5"
        >
          {expanded ? "접기" : "더보기"}
        </button>
      )}
    </div>
  );
}

export default function DartTable({
  items,
  total,
  page,
  pageSize,
  isLoading,
  isError,
  onPageChange,
  onRetry,
}: DartTableProps) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground gap-2">
        <p>공시 데이터를 불러오는 중 오류가 발생했습니다.</p>
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
            <TableHead className="w-36">일시</TableHead>
            <TableHead className="w-24">종목명</TableHead>
            <TableHead>제목</TableHead>
            <TableHead className="w-64">본문 미리보기</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {isLoading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <TableRow key={i}>
                <TableCell><Skeleton className="h-4 w-28" /></TableCell>
                <TableCell><Skeleton className="h-4 w-16" /></TableCell>
                <TableCell><Skeleton className="h-4 w-48" /></TableCell>
                <TableCell><Skeleton className="h-4 w-40" /></TableCell>
              </TableRow>
            ))
          ) : items.length === 0 ? (
            <TableRow>
              <TableCell colSpan={4} className="text-center py-12 text-muted-foreground">
                해당 조건의 공시가 없습니다.
              </TableCell>
            </TableRow>
          ) : (
            items.map((item) => (
              <TableRow key={item.id}>
                <TableCell className="text-muted-foreground text-xs">
                  {formatDateTime(new Date(item.published_at))}
                </TableCell>
                <TableCell className="font-medium">{item.stock_name}</TableCell>
                <TableCell>
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:underline text-primary inline-flex items-center gap-1"
                  >
                    {item.title}
                    <ExternalLink className="size-3 shrink-0" />
                  </a>
                </TableCell>
                <TableCell className="whitespace-normal">
                  <BodyPreviewCell text={item.body} />
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>

      {/* 페이지네이션 */}
      {!isLoading && total > 0 && (
        <div className="flex items-center justify-between mt-4">
          <span className="text-sm text-muted-foreground">
            총 {total}건 중 {(page - 1) * pageSize + 1}-
            {Math.min(page * pageSize, total)}건
          </span>
          <div className="flex gap-1">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => onPageChange(page - 1)}
            >
              이전
            </Button>
            <span className="flex items-center px-3 text-sm">
              {page} / {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => onPageChange(page + 1)}
            >
              다음
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
