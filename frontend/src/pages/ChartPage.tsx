import { useState, useMemo, useEffect, useRef } from "react";
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
} from "recharts";
import { usePageTitle } from "@/hooks/use-page-title";
import { useCandles, type CandleItem } from "@/hooks/useChart";
import { useTargetStocks } from "@/hooks/useTrades";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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
  // stacked bar용: 투명 하단 + 캔들 바디
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

// 커스텀 위크(wick) 렌더링 - Customized 컴포넌트로 SVG 직접 그리기
function CandleWicks(props: Record<string, unknown>) {
  const { formattedGraphicalItems } = props as {
    formattedGraphicalItems?: Array<{
      props?: { data?: Array<{ x: number; y: number; width: number; height: number; payload: CandleRow }> };
    }>;
  };

  // body bar의 그래픽 아이템 찾기 (두 번째 bar = body)
  const bodyBar = formattedGraphicalItems?.[1];
  if (!bodyBar?.props?.data) return null;

  const items = bodyBar.props.data;

  // base bar에서 y축 스케일 추출 (첫 번째 bar)
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

        // base bar의 y + height = 차트 바닥의 y 좌표(가격 0에 해당하지 않고, y축 최소값)
        // body bar의 y = 캔들 바디 상단
        // body bar의 y + height = 캔들 바디 하단
        const bodyTop = item.y;
        const bodyBottom = item.y + item.height;

        // 1px당 가격 계산
        const bodyPrice = payload.body;
        const pxPerPrice = bodyPrice > 0 ? item.height / bodyPrice : 0;

        const high = payload.high;
        const low = payload.low;
        const candleTop = Math.max(payload.open, payload.close);
        const candleBottom = Math.min(payload.open, payload.close);

        const wickTopY = pxPerPrice > 0 ? bodyTop - (high - candleTop) * pxPerPrice : bodyTop;
        const wickBottomY = pxPerPrice > 0 ? bodyBottom + (candleBottom - low) * pxPerPrice : bodyBottom;

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

// 커스텀 툴팁
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
        <span className="text-right text-red-500">{formatCurrency(d.high)}</span>
        <span className="text-muted-foreground">저가</span>
        <span className="text-right text-blue-500">{formatCurrency(d.low)}</span>
        <span className="text-muted-foreground">종가</span>
        <span className="text-right">{formatCurrency(d.close)}</span>
        <span className="text-muted-foreground">거래량</span>
        <span className="text-right">{d.volume.toLocaleString()}</span>
      </div>
    </div>
  );
}

export default function ChartPage() {
  usePageTitle("ALT | 차트");

  const [stockCode, setStockCode] = useState("");
  const [selectedDate, setSelectedDate] = useState(getToday);

  const { data: stocksData } = useTargetStocks();
  const stocks = stocksData?.items ?? [];

  const effectiveStockCode = stockCode || (stocks.length > 0 ? stocks[0].stock_code : "");

  const { data, isLoading, isError, refetch } = useCandles(
    { stock_code: effectiveStockCode, start: selectedDate, end: selectedDate },
    !!effectiveStockCode,
  );

  const rows = useMemo(() => toCandleRows(data?.items ?? []), [data]);

  // 가격 범위 계산
  const { minPrice, maxPrice } = useMemo(() => {
    if (!rows.length) return { minPrice: 0, maxPrice: 0 };
    const min = Math.min(...rows.map((r) => r.low));
    const max = Math.max(...rows.map((r) => r.high));
    const padding = Math.max(Math.round((max - min) * 0.05), 10);
    return { minPrice: min - padding, maxPrice: max + padding };
  }, [rows]);

  const maxVolume = useMemo(
    () => (rows.length ? Math.max(...rows.map((r) => r.volume)) : 0),
    [rows],
  );

  const selectedStock = stocks.find((s) => s.stock_code === effectiveStockCode);

  // 장중 자동 갱신 (30초 폴링)
  const isMarketHours = useMemo(() => {
    const now = new Date();
    const minutes = now.getHours() * 60 + now.getMinutes();
    return minutes >= 540 && minutes <= 930 && selectedDate === getToday();
  }, [selectedDate]);

  const intervalRef = useRef<ReturnType<typeof setInterval>>(null);

  useEffect(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    if (isMarketHours) {
      intervalRef.current = setInterval(() => refetch(), 30_000);
    }
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [isMarketHours, refetch]);

  return (
    <div className="mx-auto max-w-7xl space-y-4 px-4 py-6">
      <h1 className="text-lg font-semibold">분봉 차트</h1>

      {/* 필터 */}
      <div className="flex flex-wrap items-center gap-3">
        <Select
          value={effectiveStockCode}
          onValueChange={(v) => setStockCode(v)}
        >
          <SelectTrigger className="w-48">
            <SelectValue placeholder="종목 선택" />
          </SelectTrigger>
          <SelectContent>
            {stocks.map((s) => (
              <SelectItem key={s.stock_code} value={s.stock_code}>
                {s.stock_name} ({s.stock_code})
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <input
          type="date"
          value={selectedDate}
          onChange={(e) => setSelectedDate(e.target.value)}
          className="h-9 rounded-md border border-input bg-background px-3 text-sm"
        />

        {isMarketHours && (
          <span className="text-xs text-green-600 font-medium">
            장중 자동갱신
          </span>
        )}
      </div>

      {/* 차트 영역 */}
      {isLoading ? (
        <div className="flex h-96 items-center justify-center text-muted-foreground">
          로딩 중...
        </div>
      ) : isError ? (
        <div className="flex h-96 flex-col items-center justify-center gap-2 text-muted-foreground">
          <span>데이터를 불러올 수 없습니다</span>
          <button
            onClick={() => refetch()}
            className="text-sm underline hover:text-foreground"
          >
            다시 시도
          </button>
        </div>
      ) : rows.length === 0 ? (
        <div className="flex h-96 items-center justify-center text-muted-foreground">
          {effectiveStockCode
            ? "해당 날짜의 분봉 데이터가 없습니다"
            : "종목을 선택해주세요"}
        </div>
      ) : (
        <>
          {/* 종목 정보 헤더 */}
          {selectedStock && rows.length > 0 && (
            <div className="flex items-baseline gap-3">
              <span className="text-base font-medium">
                {selectedStock.stock_name}
              </span>
              <span className="text-2xl font-bold">
                {formatCurrency(rows[rows.length - 1].close)}
              </span>
              {(() => {
                const first = rows[0].open;
                const last = rows[rows.length - 1].close;
                const diff = last - first;
                const rate = first > 0 ? (diff / first) * 100 : 0;
                const sign = diff > 0 ? "+" : "";
                const color =
                  diff > 0
                    ? "text-red-500"
                    : diff < 0
                      ? "text-blue-500"
                      : "text-muted-foreground";
                return (
                  <span className={`text-sm ${color}`}>
                    {sign}
                    {diff.toLocaleString()} ({sign}
                    {rate.toFixed(2)}%)
                  </span>
                );
              })()}
            </div>
          )}

          {/* 캔들스틱 차트 */}
          <div className="rounded-lg border bg-card p-2">
            <ResponsiveContainer width="100%" height={400}>
              <ComposedChart
                data={rows}
                margin={{ top: 10, right: 10, bottom: 0, left: 10 }}
              >
                <XAxis
                  dataKey="time"
                  tick={{ fontSize: 11 }}
                  tickLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis
                  domain={[minPrice, maxPrice]}
                  tick={{ fontSize: 11 }}
                  tickLine={false}
                  tickFormatter={(v: number) => v.toLocaleString()}
                  width={70}
                />
                <Tooltip
                  content={<CandleTooltip />}
                  cursor={{ fill: "hsl(var(--accent))", opacity: 0.3 }}
                />
                {/* 투명 하단 (base) */}
                <Bar
                  dataKey="base"
                  stackId="candle"
                  fill="transparent"
                  isAnimationActive={false}
                />
                {/* 캔들 바디 */}
                <Bar dataKey="body" stackId="candle" isAnimationActive={false}>
                  {rows.map((row, i) => (
                    <Cell
                      key={i}
                      fill={row.isUp ? "#ef4444" : "#3b82f6"}
                    />
                  ))}
                </Bar>
                {/* 위크(wick) 오버레이 */}
                <Customized component={CandleWicks} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          {/* 거래량 차트 */}
          <div className="rounded-lg border bg-card p-2">
            <ResponsiveContainer width="100%" height={120}>
              <ComposedChart
                data={rows}
                margin={{ top: 5, right: 10, bottom: 0, left: 10 }}
              >
                <XAxis
                  dataKey="time"
                  tick={{ fontSize: 11 }}
                  tickLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis
                  tick={{ fontSize: 11 }}
                  tickLine={false}
                  tickFormatter={(v: number) =>
                    v >= 10000
                      ? `${(v / 10000).toFixed(0)}만`
                      : v.toLocaleString()
                  }
                  width={70}
                  domain={[0, Math.ceil(maxVolume * 1.1)]}
                />
                <Tooltip
                  formatter={(value: number) => [
                    value.toLocaleString(),
                    "거래량",
                  ]}
                  labelFormatter={(label: string) => label}
                  contentStyle={{
                    fontSize: "12px",
                    borderRadius: "6px",
                  }}
                />
                <Bar dataKey="volume" isAnimationActive={false}>
                  {rows.map((row, i) => (
                    <Cell
                      key={i}
                      fill={row.isUp ? "#ef444480" : "#3b82f680"}
                    />
                  ))}
                </Bar>
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </>
      )}
    </div>
  );
}
