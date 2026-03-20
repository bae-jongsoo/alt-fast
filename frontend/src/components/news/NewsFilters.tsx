import { format, subDays } from "date-fns";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useTargetStocks } from "@/hooks/useTrades";

export type NewsTabType = "news" | "dart";

interface NewsFiltersProps {
  tab: NewsTabType;
  startDate: string;
  endDate: string;
  usefulFilter: string;
  stockCode: string;
  onStartDateChange: (v: string) => void;
  onEndDateChange: (v: string) => void;
  onUsefulFilterChange: (v: string) => void;
  onStockCodeChange: (v: string) => void;
}

// base-ui Select의 onValueChange는 string | null을 받으므로 래퍼
function wrapHandler(fn: (v: string) => void) {
  return (value: string | null) => {
    if (value != null) fn(value);
  };
}

const USEFUL_OPTIONS = [
  { value: "all", label: "전체" },
  { value: "useful", label: "유용" },
  { value: "not_useful", label: "비유용" },
  { value: "unknown", label: "미판단" },
];

export function getDefaultStartDate(): string {
  return format(subDays(new Date(), 7), "yyyy-MM-dd");
}

export function getDefaultEndDate(): string {
  return format(new Date(), "yyyy-MM-dd");
}

export default function NewsFilterBar({
  tab,
  startDate,
  endDate,
  usefulFilter,
  stockCode,
  onStartDateChange,
  onEndDateChange,
  onUsefulFilterChange,
  onStockCodeChange,
}: NewsFiltersProps) {
  const { data: stocksData } = useTargetStocks();

  return (
    <div className="flex flex-wrap items-end gap-4 mb-4">
      {/* 날짜 범위 */}
      <div className="flex items-end gap-2">
        <div>
          <Label className="text-xs text-muted-foreground mb-1">시작일</Label>
          <Input
            type="date"
            value={startDate}
            onChange={(e) => onStartDateChange(e.target.value)}
            className="h-8 w-36"
          />
        </div>
        <span className="pb-1.5 text-muted-foreground">~</span>
        <div>
          <Label className="text-xs text-muted-foreground mb-1">종료일</Label>
          <Input
            type="date"
            value={endDate}
            onChange={(e) => onEndDateChange(e.target.value)}
            className="h-8 w-36"
          />
        </div>
      </div>

      {/* 종목코드 필터 */}
      <div>
        <Label className="text-xs text-muted-foreground mb-1">종목</Label>
        <Select value={stockCode} onValueChange={wrapHandler(onStockCodeChange)}>
          <SelectTrigger className="w-36">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">전체</SelectItem>
            {stocksData?.items?.map((s) => (
              <SelectItem key={s.stock_code} value={s.stock_code}>
                {s.stock_name} ({s.stock_code})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* 유용성 필터 (뉴스 탭에서만 표시) */}
      {tab === "news" && (
        <div>
          <Label className="text-xs text-muted-foreground mb-1">유용성</Label>
          <Select value={usefulFilter} onValueChange={wrapHandler(onUsefulFilterChange)}>
            <SelectTrigger className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {USEFUL_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={opt.value}>
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
    </div>
  );
}
