import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams, Navigate } from "react-router-dom";
import { toast } from "sonner";
import { Loader2 } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { usePageTitle } from "@/hooks/use-page-title";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import axios from "axios";

export default function LoginPage() {
  usePageTitle("ALT | 로그인");

  const { isLoggedIn, login } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [loginId, setLoginId] = useState("");
  const [password, setPassword] = useState("");
  const [errors, setErrors] = useState<{ loginId?: string; password?: string; form?: string }>({});
  const [loading, setLoading] = useState(false);

  // 이미 로그인 상태이면 대시보드로 리다이렉트
  if (isLoggedIn) {
    return <Navigate to="/" replace />;
  }

  const validate = (): boolean => {
    const newErrors: typeof errors = {};
    if (!loginId.trim()) {
      newErrors.loginId = "필수 항목입니다";
    }
    if (!password) {
      newErrors.password = "필수 항목입니다";
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setErrors({});

    if (!validate()) return;

    setLoading(true);
    try {
      await login(loginId, password);
      toast.success("로그인되었습니다.");

      // 이전 페이지로 리다이렉트 (기본: 설정 페이지)
      const redirect = searchParams.get("redirect") || "/settings";
      navigate(redirect, { replace: true });
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const status = err.response?.status;
        if (status === 401) {
          setErrors({ form: "아이디 또는 비밀번호가 올바르지 않습니다" });
        } else if (status === 429) {
          setErrors({ form: "잠시 후 다시 시도해주세요." });
        } else {
          setErrors({ form: "로그인 중 오류가 발생했습니다." });
        }
      } else {
        setErrors({ form: "로그인 중 오류가 발생했습니다." });
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-[calc(100vh-3.5rem)] items-center justify-center px-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="text-center">
          <CardTitle className="text-2xl font-bold tracking-tight">
            ALT
          </CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            {/* 폼 에러 메시지 */}
            {errors.form && (
              <p className="text-sm text-destructive text-center" role="alert">
                {errors.form}
              </p>
            )}

            {/* 아이디 필드 */}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="loginId">아이디</Label>
              <Input
                id="loginId"
                placeholder="아이디"
                value={loginId}
                onChange={(e) => {
                  setLoginId(e.target.value);
                  if (errors.loginId) setErrors((prev) => ({ ...prev, loginId: undefined }));
                }}
                aria-invalid={!!errors.loginId}
                autoComplete="username"
                autoFocus
              />
              {errors.loginId && (
                <p className="text-xs text-destructive" role="alert">
                  {errors.loginId}
                </p>
              )}
            </div>

            {/* 비밀번호 필드 */}
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="password">비밀번호</Label>
              <Input
                id="password"
                type="password"
                placeholder="비밀번호"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (errors.password) setErrors((prev) => ({ ...prev, password: undefined }));
                }}
                aria-invalid={!!errors.password}
                autoComplete="current-password"
              />
              {errors.password && (
                <p className="text-xs text-destructive" role="alert">
                  {errors.password}
                </p>
              )}
            </div>

            {/* 로그인 버튼 */}
            <Button
              type="submit"
              size="lg"
              className="w-full"
              disabled={loading}
            >
              {loading ? (
                <>
                  <Loader2 className="size-4 animate-spin" />
                  로그인 중...
                </>
              ) : (
                "로그인"
              )}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
