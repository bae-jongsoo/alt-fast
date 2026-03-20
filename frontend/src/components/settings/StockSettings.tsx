import { useState } from "react";
import { toast } from "sonner";
import { useAuth } from "@/hooks/useAuth";
import {
  useTargetStocks,
  useAddStock,
  useDeleteStock,
  type TargetStockItem,
} from "@/hooks/useSettings";
import { formatDateTime } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { useNavigate } from "react-router-dom";

interface StockSettingsProps {
  isEditing: boolean;
  onEditToggle: (editing: boolean) => void;
  onDirtyChange: (dirty: boolean) => void;
}

export default function StockSettings({
  isEditing,
  onEditToggle,
  onDirtyChange,
}: StockSettingsProps) {
  const { isLoggedIn } = useAuth();
  const navigate = useNavigate();
  const { data, isLoading } = useTargetStocks();
  const addStock = useAddStock();
  const deleteStock = useDeleteStock();

  const [stockCode, setStockCode] = useState("");
  const [stockName, setStockName] = useState("");
  const [corpCode, setCorpCode] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [deleteTarget, setDeleteTarget] = useState<TargetStockItem | null>(
    null
  );

  const stocks = data?.items ?? [];

  function handleEditClick() {
    if (!isLoggedIn) {
      navigate(`/login?redirect=${encodeURIComponent("/settings")}`);
      return;
    }
    onEditToggle(true);
  }

  function handleCancelEdit() {
    onEditToggle(false);
    onDirtyChange(false);
    resetForm();
  }

  function resetForm() {
    setStockCode("");
    setStockName("");
    setCorpCode("");
    setErrors({});
  }

  function validate(): boolean {
    const newErrors: Record<string, string> = {};

    if (!stockCode.trim()) {
      newErrors.stockCode = "필수 항목입니다";
    } else if (!/^\d{6}$/.test(stockCode.trim())) {
      newErrors.stockCode = "종목코드는 6자리 숫자여야 합니다";
    } else if (stocks.some((s) => s.stock_code === stockCode.trim())) {
      newErrors.stockCode = "이미 등록된 종목입니다";
    }

    if (!stockName.trim()) {
      newErrors.stockName = "필수 항목입니다";
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }

  async function handleAdd() {
    if (!validate()) return;

    try {
      await addStock.mutateAsync({
        stock_code: stockCode.trim(),
        stock_name: stockName.trim(),
        dart_corp_code: corpCode.trim() || null,
      });
      toast.success("변경사항이 저장되었습니다. 다음 사이클부터 적용됩니다.");
      resetForm();
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } };
      const detail = error?.response?.data?.detail;
      if (detail?.includes("이미 등록된")) {
        setErrors({ stockCode: "이미 등록된 종목입니다" });
      } else {
        toast.error(detail ?? "종목 추가에 실패했습니다.");
      }
    }
  }

  async function confirmDelete() {
    if (!deleteTarget) return;

    try {
      await deleteStock.mutateAsync(deleteTarget.stock_code);
      toast.success(
        "종목이 삭제되었습니다. 기존 수집 데이터는 유지됩니다."
      );
      setDeleteTarget(null);
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } };
      toast.error(error?.response?.data?.detail ?? "종목 삭제에 실패했습니다.");
      setDeleteTarget(null);
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-medium">종목 설정</h3>
        {!isEditing && (
          <Button variant="outline" size="sm" onClick={handleEditClick}>
            편집
          </Button>
        )}
        {isEditing && (
          <Button variant="outline" size="sm" onClick={handleCancelEdit}>
            편집 완료
          </Button>
        )}
      </div>

      {isEditing && (
        <div className="rounded-lg border p-4 space-y-3">
          <p className="text-sm font-medium text-muted-foreground">
            종목 추가
          </p>
          <div className="flex items-start gap-3">
            <div className="flex-1 space-y-1">
              <Input
                placeholder="종목코드 (6자리)"
                value={stockCode}
                onChange={(e) => {
                  setStockCode(e.target.value);
                  onDirtyChange(true);
                  setErrors((prev) => ({ ...prev, stockCode: "" }));
                }}
                maxLength={6}
                aria-invalid={!!errors.stockCode}
              />
              {errors.stockCode && (
                <p className="text-xs text-destructive">{errors.stockCode}</p>
              )}
            </div>
            <div className="flex-1 space-y-1">
              <Input
                placeholder="종목명"
                value={stockName}
                onChange={(e) => {
                  setStockName(e.target.value);
                  onDirtyChange(true);
                  setErrors((prev) => ({ ...prev, stockName: "" }));
                }}
                aria-invalid={!!errors.stockName}
              />
              {errors.stockName && (
                <p className="text-xs text-destructive">{errors.stockName}</p>
              )}
            </div>
            <div className="flex-1">
              <Input
                placeholder="DART corp_code (선택)"
                value={corpCode}
                onChange={(e) => {
                  setCorpCode(e.target.value);
                  onDirtyChange(true);
                }}
              />
            </div>
            <Button
              onClick={handleAdd}
              disabled={addStock.isPending}
              size="sm"
            >
              추가
            </Button>
          </div>
        </div>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>종목코드</TableHead>
            <TableHead>종목명</TableHead>
            <TableHead>DART corp_code</TableHead>
            <TableHead>등록일</TableHead>
            {isEditing && <TableHead className="w-20" />}
          </TableRow>
        </TableHeader>
        <TableBody>
          {stocks.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={isEditing ? 5 : 4}
                className="text-center text-muted-foreground py-8"
              >
                등록된 종목이 없습니다.
              </TableCell>
            </TableRow>
          ) : (
            stocks.map((stock) => (
              <TableRow key={stock.id}>
                <TableCell className="font-mono">{stock.stock_code}</TableCell>
                <TableCell>{stock.stock_name}</TableCell>
                <TableCell className="font-mono text-muted-foreground">
                  {stock.dart_corp_code ?? "-"}
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDateTime(new Date(stock.created_at))}
                </TableCell>
                {isEditing && (
                  <TableCell>
                    <Button
                      variant="destructive"
                      size="xs"
                      onClick={() => setDeleteTarget(stock)}
                      disabled={deleteStock.isPending}
                    >
                      삭제
                    </Button>
                  </TableCell>
                )}
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>

      {/* 삭제 확인 다이얼로그 */}
      <Dialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>종목 삭제</DialogTitle>
            <DialogDescription>
              삭제하면 해당 종목의 수집이 중단됩니다. 기존 수집 데이터는
              유지됩니다. 삭제하시겠습니까?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteTarget(null)}>
              취소
            </Button>
            <Button
              variant="destructive"
              onClick={confirmDelete}
              disabled={deleteStock.isPending}
            >
              삭제
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
