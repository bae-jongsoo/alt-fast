import { useState, useRef, useCallback } from "react";
import { toast } from "sonner";
import { useAuth } from "@/hooks/useAuth";
import {
  usePrompts,
  usePromptVariables,
  useUpdatePrompt,
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

interface PromptSettingsProps {
  onDirtyChange: (dirty: boolean) => void;
}

export default function PromptSettings({ onDirtyChange }: PromptSettingsProps) {
  const { isLoggedIn } = useAuth();
  const navigate = useNavigate();
  const { data, isLoading } = usePrompts();
  const { data: variables } = usePromptVariables();
  const updatePrompt = useUpdatePrompt();

  const [editingType, setEditingType] = useState<"buy" | "sell" | null>(null);
  const [editContent, setEditContent] = useState("");
  const [showVersionConfirm, setShowVersionConfirm] = useState(false);
  const [pendingVersion, setPendingVersion] = useState<PromptTemplateItem | null>(null);
  const [showSaveConfirm, setShowSaveConfirm] = useState(false);
  const [missingVars, setMissingVars] = useState<string[]>([]);
  const [showMissingVarsWarning, setShowMissingVarsWarning] = useState(false);
  const editorRef = useRef<HTMLTextAreaElement>(null);

  const buyPrompt = data?.buy_prompt;
  const sellPrompt = data?.sell_prompt;
  const buyVersions = data?.buy_versions ?? [];
  const sellVersions = data?.sell_versions ?? [];

  const currentVersions = editingType === "buy" ? buyVersions : sellVersions;
  const currentVariables = editingType
    ? variables?.[editingType] ?? []
    : [];

  function handleEditClick(type: "buy" | "sell") {
    if (!isLoggedIn) {
      navigate(`/login?redirect=${encodeURIComponent("/settings")}`);
      return;
    }
    const prompt = type === "buy" ? buyPrompt : sellPrompt;
    setEditContent(prompt?.content ?? "");
    setEditingType(type);
    onDirtyChange(false);
  }

  function handleCloseEditor() {
    setEditingType(null);
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

    // 커서 위치 복원
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
    if (!editingType || !currentVariables.length) return [];
    return currentVariables.filter(
      (v) => !editContent.includes(`{${v}}`)
    );
  }, [editingType, currentVariables, editContent]);

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
    if (!editingType) return;

    try {
      await updatePrompt.mutateAsync({
        promptType: editingType,
        content: editContent,
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

  // 슬라이드 패널(편집 모드)
  if (editingType) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-medium">
            {editingType === "buy" ? "매수" : "매도"} 프롬프트 편집
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
              {currentVersions.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  이전 버전이 없습니다.
                </p>
              ) : (
                <div className="space-y-1 max-h-[300px] overflow-y-auto">
                  {currentVersions.map((ver) => (
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
  return (
    <div className="space-y-6">
      <h3 className="text-lg font-medium">프롬프트 설정</h3>

      {/* 매수 프롬프트 */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div>
            <span className="font-medium">매수 프롬프트</span>
            {buyPrompt && (
              <span className="ml-2 text-xs text-muted-foreground">
                v{buyPrompt.version} /{" "}
                {formatDateTime(new Date(buyPrompt.created_at))}
              </span>
            )}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleEditClick("buy")}
          >
            수정
          </Button>
        </div>
        <pre className="rounded-lg border bg-muted/30 p-4 text-sm font-mono whitespace-pre-wrap max-h-[300px] overflow-y-auto">
          {buyPrompt?.content ?? "프롬프트가 설정되지 않았습니다."}
        </pre>
      </div>

      {/* 매도 프롬프트 */}
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div>
            <span className="font-medium">매도 프롬프트</span>
            {sellPrompt && (
              <span className="ml-2 text-xs text-muted-foreground">
                v{sellPrompt.version} /{" "}
                {formatDateTime(new Date(sellPrompt.created_at))}
              </span>
            )}
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={() => handleEditClick("sell")}
          >
            수정
          </Button>
        </div>
        <pre className="rounded-lg border bg-muted/30 p-4 text-sm font-mono whitespace-pre-wrap max-h-[300px] overflow-y-auto">
          {sellPrompt?.content ?? "프롬프트가 설정되지 않았습니다."}
        </pre>
      </div>
    </div>
  );
}
