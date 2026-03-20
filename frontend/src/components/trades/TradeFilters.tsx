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

export type TabType = "orders" | "decisions";

interface TradeFiltersProps {
  tab: TabType;
  startDate: string;
  endDate: string;
  resultFilter: string;
  stockCode: string;
  onStartDateChange: (v: string) => void;
  onEndDateChange: (v: string) => void;
  onResultFilterChange: (v: string) => void;
  onStockCodeChange: (v: string) => void;
}

// base-ui Select의 onValueChange는 string | null을 받으므로 래퍼
function wrapHandler(fn: (v: string) => void) {
  return (value: string | null) => {
    if (value != null) fn(value);
  };
}

const ORDER_RESULT_OPTIONS = [
  { value: "all", label: "전체" },
  { value: "BUY", label: "BUY" },
  { value: "SELL", label: "SELL" },
];

const DECISION_RESULT_OPTIONS = [
  { value: "all", label: "전체" },
  { value: "BUY", label: "BUY" },
  { value: "SELL", label: "SELL" },
  { value: "HOLD", label: "HOLD" },
  { value: "errors_only", label: "에러만" },
];

export function getDefaultStartDate(): string {
  return format(subDays(new Date(), 7), "yyyy-MM-dd");
}

export function getDefaultEndDate(): string {
  return format(new Date(), "yyyy-MM-dd");
}

export default function TradeFilters({
  tab,
  startDate,
  endDate,
  resultFilter,
  stockCode,
  onStartDateChange,
  onEndDateChange,
  onResultFilterChange,
  onStockCodeChange,
}: TradeFiltersProps) {
  const { data: stocksData } = useTargetStocks();
  const resultOptions =
    tab === "orders" ? ORDER_RESULT_OPTIONS : DECISION_RESULT_OPTIONS;

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

      {/* 결과 필터 */}
      <div>
        <Label className="text-xs text-muted-foreground mb-1">결과</Label>
        <Select value={resultFilter} onValueChange={wrapHandler(onResultFilterChange)}>
          <SelectTrigger className="w-28">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {resultOptions.map((opt) => (
              <SelectItem key={opt.value} value={opt.value}>
                {opt.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
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
    </div>
  );
}
