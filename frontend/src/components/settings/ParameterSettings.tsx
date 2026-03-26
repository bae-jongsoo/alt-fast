import { useState, useEffect } from "react";
import { toast } from "sonner";
import { useAuth } from "@/hooks/useAuth";
import {
  useParameters,
  useUpdateParameters,
  useResetParameters,
} from "@/hooks/useSettings";
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

// 파라미터 메타데이터 (한글 레이블, 단위, 범위)
type ParameterMeta =
  | { label: string; unit: string; type: "int"; min: number; max: number }
  | { label: string; unit: string; type: "time"; min: string; max: string }
  | { label: string; unit: string; type: "select"; options: { value: string; label: string }[] };

const PARAMETER_META: Record<string, ParameterMeta> = {
  trading_interval: {
    label: "트레이딩 사이클 간격",
    unit: "초",
    type: "int",
    min: 10,
    max: 600,
  },
  market_start_time: {
    label: "장 시작 시각",
    unit: "-",
    type: "time",
    min: "08:00",
    max: "10:00",
  },
  market_end_time: {
    label: "장 종료 시각",
    unit: "-",
    type: "time",
    min: "14:00",
    max: "16:00",
  },
  news_interval: {
    label: "뉴스 수집 간격",
    unit: "초",
    type: "int",
    min: 60,
    max: 3600,
  },
  news_count: {
    label: "뉴스 수집 개수",
    unit: "건",
    type: "int",
    min: 1,
    max: 50,
  },
  dart_interval: {
    label: "DART 수집 간격",
    unit: "초",
    type: "int",
    min: 60,
    max: 7200,
  },
  market_snapshot_interval: {
    label: "시세 스냅샷 간격",
    unit: "초",
    type: "int",
    min: 10,
    max: 600,
  },
  llm_trading: {
    label: "트레이딩 판단 모델",
    unit: "-",
    type: "select",
    options: [
      { value: "normal", label: "normal (openclaw)" },
      { value: "high", label: "high (nanobot)" },
    ],
  },
  llm_review: {
    label: "회고 모델",
    unit: "-",
    type: "select",
    options: [
      { value: "normal", label: "normal (openclaw)" },
      { value: "high", label: "high (nanobot)" },
    ],
  },
  llm_news: {
    label: "뉴스 요약 모델",
    unit: "-",
    type: "select",
    options: [
      { value: "normal", label: "normal (openclaw)" },
      { value: "high", label: "high (nanobot)" },
    ],
  },
  llm_chatbot: {
    label: "챗봇 모델",
    unit: "-",
    type: "select",
    options: [
      { value: "normal", label: "normal (openclaw)" },
      { value: "high", label: "high (nanobot)" },
      { value: "gemini", label: "Gemini API" },
    ],
  },
};

interface ParameterSettingsProps {
  isEditing: boolean;
  onEditToggle: (editing: boolean) => void;
  onDirtyChange: (dirty: boolean) => void;
  filterKeys?: (key: string) => boolean;
  title?: string;
}

export default function ParameterSettings({
  isEditing,
  onEditToggle,
  onDirtyChange,
  filterKeys,
  title = "시스템 파라미터",
}: ParameterSettingsProps) {
  const { isLoggedIn } = useAuth();
  const navigate = useNavigate();
  const { data, isLoading } = useParameters();
  const updateParams = useUpdateParameters();
  const resetParams = useResetParameters();

  const [editValues, setEditValues] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [showSaveConfirm, setShowSaveConfirm] = useState(false);
  const [showResetConfirm, setShowResetConfirm] = useState(false);

  const allItems = data?.items ?? [];
  const items = filterKeys ? allItems.filter((item) => filterKeys(item.key)) : allItems;

  // 편집 모드 진입 시 현재 값으로 초기화 (isEditing이 true로 바뀔 때만)
  useEffect(() => {
    if (isEditing && items.length > 0) {
      const values: Record<string, string> = {};
      items.forEach((item) => {
        values[item.key] = item.value;
      });
      setEditValues(values);
      setErrors({});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isEditing]);

  function handleEditClick() {
    if (!isLoggedIn) {
      navigate(`/login?redirect=${encodeURIComponent("/settings")}`);
      return;
    }
    onEditToggle(true);
  }

  function handleCancel() {
    onEditToggle(false);
    onDirtyChange(false);
    setErrors({});
  }

  function handleValueChange(key: string, value: string) {
    setEditValues((prev) => ({ ...prev, [key]: value }));
    onDirtyChange(true);

    // 실시간 범위 검증
    const meta = PARAMETER_META[key];
    if (!meta) return;

    const newErrors = { ...errors };

    if (meta.type === "int") {
      const num = parseInt(value, 10);
      if (isNaN(num) || num < (meta.min as number) || num > (meta.max as number)) {
        newErrors[key] = `최소 ${meta.min}, 최대 ${meta.max} 사이의 값을 입력하세요`;
      } else {
        delete newErrors[key];
      }
    } else if (meta.type === "time") {
      if (!/^\d{2}:\d{2}$/.test(value)) {
        newErrors[key] = "HH:MM 형식으로 입력하세요";
      } else if (value < (meta.min as string) || value > (meta.max as string)) {
        newErrors[key] = `최소 ${meta.min}, 최대 ${meta.max} 사이의 값을 입력하세요`;
      } else {
        delete newErrors[key];
      }
    }

    setErrors(newErrors);
  }

  function handleSaveClick() {
    // 전체 검증
    const newErrors: Record<string, string> = {};
    for (const [key, value] of Object.entries(editValues)) {
      const meta = PARAMETER_META[key];
      if (!meta) continue;

      if (meta.type === "int") {
        const num = parseInt(value, 10);
        if (isNaN(num) || num < (meta.min as number) || num > (meta.max as number)) {
          newErrors[key] = `최소 ${meta.min}, 최대 ${meta.max} 사이의 값을 입력하세요`;
        }
      } else if (meta.type === "time") {
        if (!/^\d{2}:\d{2}$/.test(value)) {
          newErrors[key] = "HH:MM 형식으로 입력하세요";
        } else if (value < (meta.min as string) || value > (meta.max as string)) {
          newErrors[key] = `최소 ${meta.min}, 최대 ${meta.max} 사이의 값을 입력하세요`;
        }
      }
    }

    setErrors(newErrors);
    if (Object.keys(newErrors).length > 0) return;

    setShowSaveConfirm(true);
  }

  async function confirmSave() {
    try {
      await updateParams.mutateAsync(editValues);
      toast.success("변경사항이 저장되었습니다. 다음 사이클부터 적용됩니다.");
      setShowSaveConfirm(false);
      onEditToggle(false);
      onDirtyChange(false);
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } };
      toast.error(error?.response?.data?.detail ?? "파라미터 저장에 실패했습니다.");
      setShowSaveConfirm(false);
    }
  }

  async function confirmReset() {
    try {
      await resetParams.mutateAsync();
      toast.success("모든 파라미터가 기본값으로 초기화되었습니다.");
      setShowResetConfirm(false);
      onEditToggle(false);
      onDirtyChange(false);
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } };
      toast.error(
        error?.response?.data?.detail ?? "파라미터 초기화에 실패했습니다."
      );
      setShowResetConfirm(false);
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
        <h3 className="text-lg font-medium">{title}</h3>
        {!isEditing && (
          <Button variant="outline" size="sm" onClick={handleEditClick}>
            편집
          </Button>
        )}
        {isEditing && (
          <div className="flex gap-2">
            <Button
              variant="destructive"
              size="sm"
              onClick={() => setShowResetConfirm(true)}
            >
              기본값 초기화
            </Button>
            <Button variant="outline" size="sm" onClick={handleCancel}>
              취소
            </Button>
            <Button
              size="sm"
              onClick={handleSaveClick}
              disabled={updateParams.isPending}
            >
              저장
            </Button>
          </div>
        )}
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>파라미터</TableHead>
            <TableHead>현재값</TableHead>
            <TableHead>단위</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {items.length === 0 ? (
            <TableRow>
              <TableCell
                colSpan={3}
                className="text-center text-muted-foreground py-8"
              >
                파라미터가 설정되지 않았습니다.
              </TableCell>
            </TableRow>
          ) : (
            items.map((item) => {
              const meta = PARAMETER_META[item.key];
              return (
                <TableRow key={item.key}>
                  <TableCell>{meta?.label ?? item.key}</TableCell>
                  <TableCell>
                    {isEditing ? (
                      <div className="space-y-1">
                        {meta?.type === "select" ? (
                          <select
                            value={editValues[item.key] ?? item.value}
                            onChange={(e) =>
                              handleValueChange(item.key, e.target.value)
                            }
                            className="border-input bg-background ring-ring w-40 rounded-md border px-3 py-2 text-sm focus-visible:ring-1 focus-visible:outline-none"
                          >
                            {meta.options.map((opt) => (
                              <option key={opt.value} value={opt.value}>
                                {opt.label}
                              </option>
                            ))}
                          </select>
                        ) : meta?.type === "time" ? (
                          <Input
                            type="time"
                            value={editValues[item.key] ?? item.value}
                            onChange={(e) =>
                              handleValueChange(item.key, e.target.value)
                            }
                            className="w-32"
                            aria-invalid={!!errors[item.key]}
                          />
                        ) : (
                          <Input
                            type="number"
                            value={editValues[item.key] ?? item.value}
                            onChange={(e) =>
                              handleValueChange(item.key, e.target.value)
                            }
                            min={meta && "min" in meta ? (meta.min as number) : undefined}
                            max={meta && "max" in meta ? (meta.max as number) : undefined}
                            className="w-32"
                            aria-invalid={!!errors[item.key]}
                          />
                        )}
                        {errors[item.key] && (
                          <p className="text-xs text-destructive">
                            {errors[item.key]}
                          </p>
                        )}
                      </div>
                    ) : (
                      <span className="font-mono">
                        {meta?.type === "select"
                          ? meta.options.find((o) => o.value === item.value)?.label ?? item.value
                          : item.value}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {meta?.unit ?? "-"}
                  </TableCell>
                </TableRow>
              );
            })
          )}
        </TableBody>
      </Table>

      {/* 저장 확인 다이얼로그 */}
      <Dialog open={showSaveConfirm} onOpenChange={setShowSaveConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>파라미터 저장</DialogTitle>
            <DialogDescription>
              변경사항을 저장하시겠습니까?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowSaveConfirm(false)}
            >
              취소
            </Button>
            <Button onClick={confirmSave} disabled={updateParams.isPending}>
              저장
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* 기본값 초기화 확인 다이얼로그 */}
      <Dialog open={showResetConfirm} onOpenChange={setShowResetConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>기본값 초기화</DialogTitle>
            <DialogDescription>
              모든 파라미터를 기본값으로 초기화합니다. 계속하시겠습니까?
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowResetConfirm(false)}
            >
              취소
            </Button>
            <Button
              variant="destructive"
              onClick={confirmReset}
              disabled={resetParams.isPending}
            >
              초기화
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
