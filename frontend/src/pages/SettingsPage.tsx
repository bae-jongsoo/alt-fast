import { useState, useCallback, useEffect } from "react";
import { usePageTitle } from "@/hooks/use-page-title";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui/tabs";
import StockSettings from "@/components/settings/StockSettings";
import PromptSettings from "@/components/settings/PromptSettings";
import ParameterSettings from "@/components/settings/ParameterSettings";

export default function SettingsPage() {
  usePageTitle("ALT | 설정");

  const [activeTab, setActiveTab] = useState("stocks");
  const [isDirty, setIsDirty] = useState(false);
  const [stockEditing, setStockEditing] = useState(false);
  const [paramEditing, setParamEditing] = useState(false);

  // 편집 모드 이탈 경고: 브라우저 탭 닫기/새로고침
  useEffect(() => {
    if (!isDirty) return;

    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };

    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [isDirty]);

  const handleTabChange = useCallback(
    (newTab: unknown) => {
      const tabValue = newTab as string;
      if (isDirty) {
        const confirmed = window.confirm(
          "저장하지 않은 변경사항이 있습니다. 이동하시겠습니까?"
        );
        if (!confirmed) return;
        setIsDirty(false);
        setStockEditing(false);
        setParamEditing(false);
      }
      setActiveTab(tabValue);
    },
    [isDirty]
  );

  const handleDirtyChange = useCallback((dirty: boolean) => {
    setIsDirty(dirty);
  }, []);

  const handleStockEditToggle = useCallback((editing: boolean) => {
    setStockEditing(editing);
  }, []);

  const handleParamEditToggle = useCallback((editing: boolean) => {
    setParamEditing(editing);
  }, []);

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-4 py-6">
      <h1 className="text-lg font-semibold">설정</h1>

      <Tabs value={activeTab} onValueChange={handleTabChange}>
        <TabsList>
          <TabsTrigger value="stocks">종목 설정</TabsTrigger>
          <TabsTrigger value="prompts">프롬프트 설정</TabsTrigger>
          <TabsTrigger value="parameters">시스템 파라미터</TabsTrigger>
        </TabsList>

        <TabsContent value="stocks">
          <StockSettings
            isEditing={stockEditing}
            onEditToggle={handleStockEditToggle}
            onDirtyChange={handleDirtyChange}
          />
        </TabsContent>

        <TabsContent value="prompts">
          <PromptSettings onDirtyChange={handleDirtyChange} />
        </TabsContent>

        <TabsContent value="parameters">
          <ParameterSettings
            isEditing={paramEditing}
            onEditToggle={handleParamEditToggle}
            onDirtyChange={handleDirtyChange}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
