import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency, formatRelativeTime } from "@/lib/format";
import type { RecentOrder, RecentError } from "@/hooks/useDashboard";

interface RecentActivityProps {
  orders?: RecentOrder[];
  errors?: RecentError[];
  isLoading: boolean;
}

export default function RecentActivity({
  orders,
  errors,
  isLoading,
}: RecentActivityProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>최근 활동</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-6 w-full" />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="space-y-6 pt-4">
        {/* 최근 주문 */}
        <div>
          <h3 className="mb-3 text-sm font-medium">최근 주문</h3>
          {!orders || orders.length === 0 ? (
            <p className="py-4 text-center text-sm text-muted-foreground">
              오늘 거래 내역이 없습니다
            </p>
          ) : (
            <div className="space-y-3">
              {orders.map((order) => (
                <div
                  key={order.id}
                  className="flex items-center justify-between gap-2 text-sm"
                >
                  <div className="flex items-center gap-2">
                    <span className="text-muted-foreground">
                      {formatRelativeTime(new Date(order.created_at))}
                    </span>
                    <span className="font-medium">{order.stock_name}</span>
                    <Badge
                      variant={
                        order.order_type === "BUY" ? "default" : "destructive"
                      }
                      className={
                        order.order_type === "BUY"
                          ? "bg-loss text-white"
                          : "bg-profit text-white"
                      }
                    >
                      {order.order_type}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-3 text-right">
                    <span>{formatCurrency(order.order_price)}</span>
                    <span className="text-muted-foreground">
                      {order.quantity}주
                    </span>
                    {order.profit_loss != null && order.profit_loss !== 0 && (
                      <span
                        className={
                          order.profit_loss > 0 ? "text-profit" : "text-loss"
                        }
                      >
                        {order.profit_loss > 0 ? "+" : ""}
                        {formatCurrency(order.profit_loss)}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* 최근 에러 - 0건이면 숨김 */}
        {errors && errors.length > 0 && (
          <div className="border-t pt-4">
            <h3 className="mb-3 text-sm font-medium text-destructive">
              최근 에러
            </h3>
            <div className="space-y-2">
              {errors.map((error) => (
                <div
                  key={error.id}
                  className="flex items-start gap-2 text-sm"
                >
                  <span className="shrink-0 text-muted-foreground">
                    {formatRelativeTime(new Date(error.created_at))}
                  </span>
                  <span className="text-destructive">
                    {error.error_message}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
