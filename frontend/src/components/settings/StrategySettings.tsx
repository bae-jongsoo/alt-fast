import { useState } from "react";
import {
  useStrategies,
  useCreateStrategy,
  useUpdateStrategy,
  type Strategy,
  type StrategyCreate,
} from "@/hooks/useStrategy";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Plus, X } from "lucide-react";
import { toast } from "sonner";
import { formatCurrency } from "@/lib/format";

export default function StrategySettings() {
  const { data, isLoading } = useStrategies();
  const createMutation = useCreateStrategy();
  const updateMutation = useUpdateStrategy();

  const [showForm, setShowForm] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [initialCapital, setInitialCapital] = useState("10000000");

  const strategies = data?.items ?? [];

  const handleCreate = async () => {
    if (!name.trim()) {
      toast.error("전략 이름을 입력해주세요.");
      return;
    }
    const capital = parseInt(initialCapital, 10);
    if (isNaN(capital) || capital <= 0) {
      toast.error("초기 자금은 양수여야 합니다.");
      return;
    }

    try {
      const payload: StrategyCreate = {
        name: name.trim(),
        description: description.trim() || null,
        initial_capital: capital,
      };
      await createMutation.mutateAsync(payload);
      toast.success(`전략 "${name}" 생성 완료`);
      setName("");
      setDescription("");
      setInitialCapital("10000000");
      setShowForm(false);
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : "전략 생성에 실패했습니다.";
      toast.error(msg);
    }
  };

  const handleToggleActive = async (strategy: Strategy) => {
    try {
      await updateMutation.mutateAsync({
        id: strategy.id,
        data: { is_active: !strategy.is_active },
      });
      toast.success(
        `전략 "${strategy.name}" ${strategy.is_active ? "비활성화" : "활성화"} 완료`
      );
    } catch {
      toast.error("전략 상태 변경에 실패했습니다.");
    }
  };

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>전략 관리</CardTitle>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowForm((v) => !v)}
          >
            {showForm ? (
              <>
                <X className="size-4 mr-1" /> 취소
              </>
            ) : (
              <>
                <Plus className="size-4 mr-1" /> 전략 추가
              </>
            )}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* 생성 폼 */}
        {showForm && (
          <div className="rounded-lg border p-4 space-y-3">
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <Label htmlFor="strategy-name">이름</Label>
                <Input
                  id="strategy-name"
                  placeholder="예: aggressive"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
              <div>
                <Label htmlFor="strategy-desc">설명</Label>
                <Input
                  id="strategy-desc"
                  placeholder="예: 공격적 단타 전략"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>
              <div>
                <Label htmlFor="strategy-capital">초기 자금</Label>
                <Input
                  id="strategy-capital"
                  type="number"
                  placeholder="10000000"
                  value={initialCapital}
                  onChange={(e) => setInitialCapital(e.target.value)}
                />
              </div>
            </div>
            <Button
              onClick={handleCreate}
              disabled={createMutation.isPending}
              size="sm"
            >
              {createMutation.isPending ? "생성 중..." : "생성"}
            </Button>
          </div>
        )}

        {/* 전략 목록 */}
        {isLoading ? (
          <p className="text-sm text-muted-foreground">로딩 중...</p>
        ) : strategies.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">
            등록된 전략이 없습니다.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>이름</TableHead>
                <TableHead>설명</TableHead>
                <TableHead className="text-right">초기 자금</TableHead>
                <TableHead>상태</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {strategies.map((s) => (
                <TableRow key={s.id}>
                  <TableCell className="font-medium">{s.name}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {s.description || "-"}
                  </TableCell>
                  <TableCell className="text-right">
                    {formatCurrency(s.initial_capital)}
                  </TableCell>
                  <TableCell>
                    <Badge variant={s.is_active ? "default" : "secondary"}>
                      {s.is_active ? "활성" : "비활성"}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleToggleActive(s)}
                      disabled={updateMutation.isPending}
                    >
                      {s.is_active ? "비활성화" : "활성화"}
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
