import { format, formatDistanceToNow } from "date-fns";
import { ko } from "date-fns/locale";

// 금액 포맷: 1,234,567원
export function formatCurrency(value: number): string {
  return `${value.toLocaleString("ko-KR")}원`;
}

// 수익률 포맷: +2.34%, -1.05%
export function formatPercent(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

// 상대 시각: "2분 전", "1시간 전"
export function formatRelativeTime(date: Date): string {
  return formatDistanceToNow(date, { addSuffix: true, locale: ko });
}

// 절대 시각: 2024-03-20 14:23
export function formatDateTime(date: Date): string {
  return format(date, "yyyy-MM-dd HH:mm");
}

// 절대 시각 (초 포함): 2024-03-20 14:23:15
export function formatDateTimeFull(date: Date): string {
  return format(date, "yyyy-MM-dd HH:mm:ss");
}
