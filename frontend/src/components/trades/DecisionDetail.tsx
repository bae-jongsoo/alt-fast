import { useDecisionDetail } from "@/hooks/useTrades";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { formatCurrency } from "@/lib/format";

interface DecisionDetailProps {
  decisionId: number;
}

function SourceBadge({ type }: { type: string }) {
  const colors: Record<string, string> = {
    price: "bg-green-500/15 text-green-600 dark:text-green-400",
    news: "bg-purple-500/15 text-purple-600 dark:text-purple-400",
    financial: "bg-orange-500/15 text-orange-600 dark:text-orange-400",
    technical: "bg-cyan-500/15 text-cyan-600 dark:text-cyan-400",
  };
  return (
    <Badge className={colors[type] || "bg-muted text-muted-foreground"}>
      {type}
    </Badge>
  );
}

export default function DecisionDetail({ decisionId }: DecisionDetailProps) {
  const { data, isLoading, isError } = useDecisionDetail(decisionId);

  if (isLoading) {
    return (
      <div className="p-4 space-y-3">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="p-4 text-sm text-destructive">
        상세 정보를 불러오는 중 오류가 발생했습니다.
      </div>
    );
  }

  const parsedDecision = data.parsed_decision;
  const sources = parsedDecision?.sources as
    | Array<{ type: string; detail: string }>
    | undefined;

  return (
    <div className="p-4 space-y-4 bg-muted/30 border-t">
      {/* LLM 요청 프롬프트 */}
      <div>
        <h4 className="text-xs font-semibold text-muted-foreground mb-1">
          LLM 요청 프롬프트
        </h4>
        <pre className="bg-background border rounded-md p-3 text-xs font-mono max-h-[400px] overflow-auto whitespace-pre-wrap break-words">
          {data.request_payload || "(없음)"}
        </pre>
      </div>

      {/* LLM 응답 */}
      <div>
        <h4 className="text-xs font-semibold text-muted-foreground mb-1">
          LLM 응답
        </h4>
        <pre className="bg-background border rounded-md p-3 text-xs font-mono max-h-[400px] overflow-auto whitespace-pre-wrap break-words">
          {data.response_payload || "(없음)"}
        </pre>
      </div>

      {/* 파싱된 판단 결과 */}
      {parsedDecision && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground mb-1">
            파싱된 판단 결과
          </h4>
          <pre className="bg-background border rounded-md p-3 text-xs font-mono max-h-[400px] overflow-auto whitespace-pre-wrap break-words">
            {JSON.stringify(parsedDecision, null, 2)}
          </pre>

          {/* sources 필드 표시 */}
          {sources && sources.length > 0 && (
            <div className="mt-2 space-y-1">
              <span className="text-xs font-semibold text-muted-foreground">
                Sources
              </span>
              <div className="space-y-1">
                {sources.map((src, idx) => (
                  <div key={idx} className="flex items-start gap-2 text-xs">
                    <SourceBadge type={src.type} />
                    <span className="text-muted-foreground">{src.detail}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* 연결된 주문 정보 */}
      {data.linked_order && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground mb-1">
            연결된 주문
          </h4>
          <div className="bg-background border rounded-md p-3 text-sm space-y-1">
            <div className="flex gap-4">
              <span className="text-muted-foreground">주문가격:</span>
              <span className="font-mono">
                {formatCurrency(data.linked_order.order_price)}
              </span>
            </div>
            <div className="flex gap-4">
              <span className="text-muted-foreground">수량:</span>
              <span className="font-mono">
                {data.linked_order.quantity.toLocaleString()}
              </span>
            </div>
            {data.linked_order.profit_loss != null && (
              <div className="flex gap-4">
                <span className="text-muted-foreground">손익:</span>
                <span
                  className={`font-mono ${
                    data.linked_order.profit_loss > 0
                      ? "text-red-600 dark:text-red-400"
                      : data.linked_order.profit_loss < 0
                        ? "text-blue-600 dark:text-blue-400"
                        : ""
                  }`}
                >
                  {data.linked_order.profit_loss > 0 ? "+" : ""}
                  {formatCurrency(data.linked_order.profit_loss)}
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
