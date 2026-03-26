import { useState, useMemo } from "react";
import { format } from "date-fns";
import {
  ComposedChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  Customized,
  ReferenceLine,
} from "recharts";
import { usePageTitle } from "@/hooks/use-page-title";
import { useCandles, type CandleItem } from "@/hooks/useChart";
import {
  useTargetStocks,
  useOrderHistory,
  type TargetStock,
} from "@/hooks/useTrades";
import { formatCurrency } from "@/lib/format";

function getToday() {
  return format(new Date(), "yyyy-MM-dd");
}

interface CandleRow {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  base: number;
  body: number;
  isUp: boolean;
}

function toCandleRows(items: CandleItem[]): CandleRow[] {
  return items.map((c) => {
    const isUp = c.close >= c.open;
    return {
      time: format(new Date(c.minute_at), "HH:mm"),
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
      volume: c.volume,
      base: Math.min(c.open, c.close),
      body: Math.abs(c.close - c.open) || 1,
      isUp,
    };
  });
}

function CandleWicks(props: Record<string, unknown>) {
  const { formattedGraphicalItems } = props as {
    formattedGraphicalItems?: Array<{
      props?: {
        data?: Array<{
          x: number;
          y: number;
          width: number;
          height: number;
          payload: CandleRow;
        }>;
      };
    }>;
  };

  const bodyBar = formattedGraphicalItems?.[1];
  if (!bodyBar?.props?.data) return null;
  const items = bodyBar.props.data;

  const baseBar = formattedGraphicalItems?.[0];
  if (!baseBar?.props?.data) return null;
  const baseItems = baseBar.props.data;

  return (
    <g>
      {items.map((item, i) => {
        const { payload, x, width } = item;
        if (!payload) return null;
        const baseItem = baseItems[i];
        if (!baseItem) return null;

        const bodyTop = item.y;
        const bodyBottom = item.y + item.height;
        const bodyPrice = payload.body;
        const pxPerPrice = bodyPrice > 0 ? item.height / bodyPrice : 0;
        const candleTop = Math.max(payload.open, payload.close);
        const candleBottom = Math.min(payload.open, payload.close);
        const wickTopY =
          pxPerPrice > 0
            ? bodyTop - (payload.high - candleTop) * pxPerPrice
            : bodyTop;
        const wickBottomY =
          pxPerPrice > 0
            ? bodyBottom + (candleBottom - payload.low) * pxPerPrice
            : bodyBottom;
        const cx = x + width / 2;
        const color = payload.isUp ? "#ef4444" : "#3b82f6";

        return (
          <line
            key={i}
            x1={cx}
            y1={wickTopY}
            x2={cx}
            y2={wickBottomY}
            stroke={color}
            strokeWidth={1}
          />
        );
      })}
    </g>
  );
}

function CandleTooltip({ active, payload }: Record<string, unknown>) {
  if (!active || !payload) return null;
  const items = payload as { payload: CandleRow }[];
  if (!items.length) return null;
  const d = items[0].payload;
  return (
    <div className="rounded-md border bg-popover p-2 text-xs shadow-md">
      <div className="font-medium">{d.time}</div>
      <div className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5">
        <span className="text-muted-foreground">시가</span>
        <span className="text-right">{formatCurrency(d.open)}</span>
        <span className="text-muted-foreground">고가</span>
        <span className="text-right text-red-500">
          {formatCurrency(d.high)}
        </span>
        <span className="text-muted-foreground">저가</span>
        <span className="text-right text-blue-500">
          {formatCurrency(d.low)}
        </span>
        <span className="text-muted-foreground">종가</span>
        <span className="text-right">{formatCurrency(d.close)}</span>
        <span className="text-muted-foreground">거래량</span>
        <span className="text-right">{d.volume.toLocaleString()}</span>
      </div>
    </div>
  );
}

// --- 개별 종목 차트 ---
function StockChart({
  stock,
  selectedDate,
}: {
  stock: TargetStock;
  selectedDate: string;
}) {
  const { data, isLoading } = useCandles(
    { stock_code: stock.stock_code, start: selectedDate, end: selectedDate },
    true,
  );

  const { data: ordersData } = useOrderHistory({
    page: 1,
    page_size: 100,
    stock_code: stock.stock_code,
    start_date: selectedDate,
    end_date: selectedDate,
  });

  const rows = useMemo(() => toCandleRows(data?.items ?? []), [data]);

  const tradeLines = useMemo(() => {
    if (!ordersData?.items) return [];
    return ordersData.items
      .filter((o) => o.result_executed_at)
      .map((o) => ({
        time: format(new Date(o.result_executed_at!), "HH:mm"),
        type: o.order_type as "BUY" | "SELL",
      }));
  }, [ordersData]);

  const { minPrice, maxPrice } = useMemo(() => {
    if (!rows.length) return { minPrice: 0, maxPrice: 0 };
    const min = Math.min(...rows.map((r) => r.low));
    const max = Math.max(...rows.map((r) => r.high));
    const padding = Math.max(Math.round((max - min) * 0.05), 10);
    return { minPrice: min - padding, maxPrice: max + padding };
  }, [rows]);

  if (isLoading) {
    return (
      <div className="rounded-lg border bg-card p-3">
        <div className="mb-1 text-sm font-medium">{stock.stock_name}</div>
        <div className="flex h-48 items-center justify-center text-xs text-muted-foreground">
          로딩 중...
        </div>
      </div>
    );
  }

  if (!rows.length) {
    return (
      <div className="rounded-lg border bg-card p-3">
        <div className="mb-1 text-sm font-medium">{stock.stock_name}</div>
        <div className="flex h-48 items-center justify-center text-xs text-muted-foreground">
          데이터 없음
        </div>
      </div>
    );
  }

  const last = rows[rows.length - 1];
  const first = rows[0];
  const diff = last.close - first.open;
  const rate = first.open > 0 ? (diff / first.open) * 100 : 0;
  const sign = diff > 0 ? "+" : "";
  const color =
    diff > 0
      ? "text-red-500"
      : diff < 0
        ? "text-blue-500"
        : "text-muted-foreground";

  return (
    <div className="rounded-lg border bg-card p-3">
      {/* 헤더 */}
      <div className="mb-1 flex items-baseline gap-2">
        <span className="text-sm font-medium">{stock.stock_name}</span>
        <span className="text-base font-bold">
          {formatCurrency(last.close)}
        </span>
        <span className={`text-xs ${color}`}>
          {sign}
          {rate.toFixed(2)}%
        </span>
      </div>

      {/* 캔들스틱 */}
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart
          data={rows}
          margin={{ top: 5, right: 5, bottom: 0, left: 5 }}
        >
          <XAxis
            dataKey="time"
            tick={{ fontSize: 9 }}
            tickLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[minPrice, maxPrice]}
            allowDataOverflow
            tick={{ fontSize: 9 }}
            tickLine={false}
            tickFormatter={(v: number) => v.toLocaleString()}
            width={55}
          />
          <Tooltip
            content={<CandleTooltip />}
            cursor={{ fill: "hsl(var(--accent))", opacity: 0.3 }}
          />
          {tradeLines.map((t, i) => (
            <ReferenceLine
              key={`trade-${i}`}
              x={t.time}
              stroke={t.type === "BUY" ? "#ef4444" : "#3b82f6"}
              strokeDasharray={t.type === "BUY" ? "none" : "4 2"}
              strokeWidth={1.5}
              label={{
                value: t.type === "BUY" ? "매수" : "매도",
                position: "top",
                fill: t.type === "BUY" ? "#ef4444" : "#3b82f6",
                fontSize: 9,
              }}
            />
          ))}
          <Bar
            dataKey="base"
            stackId="candle"
            fill="transparent"
            isAnimationActive={false}
          />
          <Bar dataKey="body" stackId="candle" isAnimationActive={false}>
            {rows.map((row, i) => (
              <Cell key={i} fill={row.isUp ? "#ef4444" : "#3b82f6"} />
            ))}
          </Bar>
          <Customized component={CandleWicks} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

// --- 메인 페이지 ---
export default function ChartPage() {
  usePageTitle("ALT | 차트");

  const [selectedDate, setSelectedDate] = useState(getToday);
  const [selectedCodes, setSelectedCodes] = useState<Set<string> | null>(null);

  const { data: stocksData } = useTargetStocks();
  const stocks = stocksData?.items ?? [];

  // 기본: 전체 선택
  const activeCodes = useMemo(
    () => selectedCodes ?? new Set(stocks.map((s) => s.stock_code)),
    [selectedCodes, stocks],
  );

  const toggleStock = (code: string) => {
    const next = new Set(activeCodes);
    if (next.has(code)) {
      next.delete(code);
    } else {
      next.add(code);
    }
    setSelectedCodes(next);
  };

  const toggleAll = () => {
    if (activeCodes.size === stocks.length) {
      setSelectedCodes(new Set());
    } else {
      setSelectedCodes(new Set(stocks.map((s) => s.stock_code)));
    }
  };

  const visibleStocks = stocks.filter((s) => activeCodes.has(s.stock_code));

  // 장중 자동 갱신
  const isMarketHours = useMemo(() => {
    const now = new Date();
    const minutes = now.getHours() * 60 + now.getMinutes();
    return minutes >= 540 && minutes <= 930 && selectedDate === getToday();
  }, [selectedDate]);

  return (
    <div className="mx-auto max-w-7xl space-y-4 px-4 py-6">
      <h1 className="text-lg font-semibold">분봉 차트</h1>

      {/* 필터 */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="date"
          value={selectedDate}
          onChange={(e) => setSelectedDate(e.target.value)}
          className="h-9 rounded-md border border-input bg-background px-3 text-sm"
        />

        {isMarketHours && (
          <span className="text-xs font-medium text-green-600">
            장중 자동갱신
          </span>
        )}
      </div>

      {/* 종목 체크박스 */}
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1.5 text-sm">
          <input
            type="checkbox"
            checked={activeCodes.size === stocks.length}
            onChange={toggleAll}
            className="rounded"
          />
          <span className="font-medium">전체</span>
        </label>
        <span className="text-border">|</span>
        {stocks.map((s) => (
          <label
            key={s.stock_code}
            className="flex items-center gap-1.5 text-sm"
          >
            <input
              type="checkbox"
              checked={activeCodes.has(s.stock_code)}
              onChange={() => toggleStock(s.stock_code)}
              className="rounded"
            />
            {s.stock_name}
          </label>
        ))}
      </div>

      {/* 차트 그리드 */}
      {visibleStocks.length === 0 ? (
        <div className="flex h-48 items-center justify-center text-muted-foreground">
          종목을 선택해주세요
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {visibleStocks.map((s) => (
            <StockChart
              key={s.stock_code}
              stock={s}
              selectedDate={selectedDate}
            />
          ))}
        </div>
      )}
    </div>
  );
}
