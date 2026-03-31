import { useState, useRef, useCallback } from "react";
import { toast } from "sonner";
import { useAuth } from "@/hooks/useAuth";
import { useStrategyContext } from "@/hooks/useStrategy";
import {
  usePrompts,
  usePromptVariables,
  useUpdatePrompt,
  type PromptGroup,
  type PromptTemplateItem,
} from "@/hooks/useSettings";
import { formatDateTime } from "@/lib/format";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { useNavigate } from "react-router-dom";

/** prompt_type → 전략 이름 매핑 (전체 모드에서 뱃지 표시용) */
const PROMPT_STRATEGY_MAP: Record<string, string> = {
  buy: "default",
  sell: "default",
  event_buy: "event_trader",
  event_sell: "event_trader",
};

interface PromptSettingsProps {
  onDirtyChange: (dirty: boolean) => void;
}

export default function PromptSettings({ onDirtyChange }: PromptSettingsProps) {
  const { isLoggedIn } = useAuth();
  const navigate = useNavigate();
  const { selectedStrategyId } = useStrategyContext();
  const { data, isLoading } = usePrompts(selectedStrategyId);
  const { data: variables } = usePromptVariables();
  const updatePrompt = useUpdatePrompt();

  const [editingGroup, setEditingGroup] = useState<PromptGroup | null>(null);
  const [editContent, setEditContent] = useState("");
  const [showVersionConfirm, setShowVersionConfirm] = useState(false);
  const [pendingVersion, setPendingVersion] = useState<PromptTemplateItem | null>(null);
  const [showSaveConfirm, setShowSaveConfirm] = useState(false);
  const [missingVars, setMissingVars] = useState<string[]>([]);
  const [showMissingVarsWarning, setShowMissingVarsWarning] = useState(false);
  const editorRef = useRef<HTMLTextAreaElement>(null);

  const groups = data?.groups ?? [];

  const currentVariables = editingGroup
    ? variables?.[editingGroup.prompt_type] ?? []
    : [];

  function handleEditClick(group: PromptGroup) {
    if (!isLoggedIn) {
      navigate(`/login?redirect=${encodeURIComponent("/settings")}`);
      return;
    }
    setEditContent(group.active?.content ?? "");
    setEditingGroup(group);
    onDirtyChange(false);
  }

  function handleCloseEditor() {
    setEditingGroup(null);
    setEditContent("");
    onDirtyChange(false);
  }

  function handleInsertVariable(variable: string) {
    const editor = editorRef.current;
    if (!editor) return;

    const tag = `{${variable}}`;
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    const newContent =
      editContent.substring(0, start) + tag + editContent.substring(end);
    setEditContent(newContent);
    onDirtyChange(true);

    requestAnimationFrame(() => {
      editor.focus();
      editor.selectionStart = start + tag.length;
      editor.selectionEnd = start + tag.length;
    });
  }

  function handleVersionClick(version: PromptTemplateItem) {
    setPendingVersion(version);
    setShowVersionConfirm(true);
  }

  function confirmLoadVersion() {
    if (pendingVersion) {
      setEditContent(pendingVersion.content);
      onDirtyChange(true);
    }
    setShowVersionConfirm(false);
    setPendingVersion(null);
  }

  const checkMissingVariables = useCallback((): string[] => {
    if (!editingGroup || !currentVariables.length) return [];
    return currentVariables.filter(
      (v) => !editContent.includes(`{${v}}`)
    );
  }, [editingGroup, currentVariables, editContent]);

  function handleSaveClick() {
    const missing = checkMissingVariables();
    if (missing.length > 0) {
      setMissingVars(missing);
      setShowMissingVarsWarning(true);
    } else {
      setShowSaveConfirm(true);
    }
  }

  function handleMissingVarsConfirm() {
    setShowMissingVarsWarning(false);
    setShowSaveConfirm(true);
  }

  async function confirmSave() {
    if (!editingGroup) return;

    try {
      await updatePrompt.mutateAsync({
        promptType: editingGroup.prompt_type,
        content: editContent,
        strategyId: selectedStrategyId ?? undefined,
      });
      toast.success("변경사항이 저장되었습니다. 다음 사이클부터 적용됩니다.");
      setShowSaveConfirm(false);
      handleCloseEditor();
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } } };
      toast.error(error?.response?.data?.detail ?? "프롬프트 저장에 실패했습니다.");
      setShowSaveConfirm(false);
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

  // 편집 모드
  if (editingGroup) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-medium">
            {editingGroup.label} 편집
          </h3>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={handleCloseEditor}>
              취소
            </Button>
            <Button
              size="sm"
              onClick={handleSaveClick}
              disabled={updatePrompt.isPending}
            >
              저장
            </Button>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* 좌측: 텍스트 에디터 */}
          <div className="lg:col-span-2">
            <textarea
              ref={editorRef}
              value={editContent}
              onChange={(e) => {
                setEditContent(e.target.value);
                onDirtyChange(true);
              }}
              className="w-full min-h-[400px] rounded-lg border border-input bg-transparent p-4 font-mono text-sm leading-relaxed outline-none focus:border-ring focus:ring-3 focus:ring-ring/50 resize-y dark:bg-input/30"
              placeholder="프롬프트 내용을 입력하세요..."
            />
          </div>

          {/* 우측: 변수 목록 + 버전 이력 */}
          <div className="space-y-4">
            {/* 필수 변수 목록 */}
            <div className="rounded-lg border p-4 space-y-3">
              <p className="text-sm font-medium">필수 변수</p>
              <div className="flex flex-wrap gap-2">
                {currentVariables.map((v) => (
                  <Badge
                    key={v}
                    className="cursor-pointer hover:bg-primary/80"
                    onClick={() => handleInsertVariable(v)}
                  >
                    {`{${v}}`}
                  </Badge>
                ))}
              </div>
              <p className="text-xs text-muted-foreground">
                클릭하면 에디터 커서 위치에 삽입됩니다.
              </p>
            </div>

            {/* 이전 버전 목록 */}
            <div className="rounded-lg border p-4 space-y-3">
              <p className="text-sm font-medium">이전 버전</p>
              {editingGroup.versions.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  이전 버전이 없습니다.
                </p>
              ) : (
                <div className="space-y-1 max-h-[300px] overflow-y-auto">
                  {editingGroup.versions.map((ver) => (
                    <button
                      key={ver.id}
                      className="w-full text-left rounded-md px-3 py-2 text-sm hover:bg-muted transition-colors"
                      onClick={() => handleVersionClick(ver)}
                    >
                      <span className="text-muted-foreground">
                        v{ver.version}
                      </span>
                      <span className="ml-2 text-xs text-muted-foreground">
                        {formatDateTime(new Date(ver.created_at))}
                      </span>
                      {ver.is_active && (
                        <Badge variant="outline" className="ml-2 text-xs">
                          현재
                        </Badge>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* 버전 로드 확인 다이얼로그 */}
        <Dialog open={showVersionConfirm} onOpenChange={setShowVersionConfirm}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>이전 버전 로드</DialogTitle>
              <DialogDescription>
                현재 편집 중인 내용이 사라집니다. 이전 버전을 로드하시겠습니까?
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setShowVersionConfirm(false)}
              >
                취소
              </Button>
              <Button onClick={confirmLoadVersion}>로드</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* 누락 변수 경고 다이얼로그 */}
        <Dialog
          open={showMissingVarsWarning}
          onOpenChange={setShowMissingVarsWarning}
        >
          <DialogContent>
            <DialogHeader>
              <DialogTitle>필수 변수 누락</DialogTitle>
              <DialogDescription>
                다음 변수가 누락되었습니다:{" "}
                {missingVars.map((v) => `{${v}}`).join(", ")}. 이대로
                저장하시겠습니까?
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setShowMissingVarsWarning(false)}
              >
                취소
              </Button>
              <Button onClick={handleMissingVarsConfirm}>계속 저장</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* 저장 확인 다이얼로그 */}
        <Dialog open={showSaveConfirm} onOpenChange={setShowSaveConfirm}>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>프롬프트 저장</DialogTitle>
              <DialogDescription>
                프롬프트 변경은 트레이딩 결과에 직접 영향을 미칩니다. 변경사항을
                저장하시겠습니까?
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => setShowSaveConfirm(false)}
              >
                취소
              </Button>
              <Button onClick={confirmSave} disabled={updatePrompt.isPending}>
                저장
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    );
  }

  // 읽기 모드
  const isAllMode = selectedStrategyId === null;

  return (
    <div className="space-y-6">
      <h3 className="text-lg font-medium">프롬프트 설정</h3>

      {groups.map((group) => (
        <div key={group.prompt_type} className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="font-medium">{group.label}</span>
              {isAllMode && (
                <Badge variant="secondary" className="text-xs">
                  {PROMPT_STRATEGY_MAP[group.prompt_type] ?? "unknown"}
                </Badge>
              )}
              {group.active && (
                <span className="text-xs text-muted-foreground">
                  v{group.active.version} /{" "}
                  {formatDateTime(new Date(group.active.created_at))}
                </span>
              )}
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleEditClick(group)}
              disabled={isAllMode}
            >
              수정
            </Button>
          </div>
          <pre className="rounded-lg border bg-muted/30 p-4 text-sm font-mono whitespace-pre-wrap max-h-[300px] overflow-y-auto">
            {group.active?.content ?? "프롬프트가 설정되지 않았습니다."}
          </pre>
        </div>
      ))}
    </div>
  );
}
