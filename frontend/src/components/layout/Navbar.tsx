import { useState } from "react";
import { NavLink, Link } from "react-router-dom";
import { Moon, Sun, Menu, X, User, LogOut, ChevronDown } from "lucide-react";
import { useTheme } from "@/hooks/use-theme";
import { useAuth } from "@/hooks/useAuth";
import { useStrategyContext } from "@/hooks/useStrategy";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "@/components/ui/dropdown-menu";

/** 전략 셀렉터에 연동되는 메뉴 */
const strategyNavItems = [
  { to: "/", label: "대시보드" },
  { to: "/trades", label: "매매이력" },
  { to: "/settings", label: "설정" },
] as const;

/** 전략과 무관한 공통 메뉴 */
const commonNavItems = [
  { to: "/news", label: "뉴스·공시" },
  { to: "/chart", label: "차트" },
] as const;

function NavLinkItem({
  to,
  label,
  onClick,
}: {
  to: string;
  label: string;
  onClick?: () => void;
}) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      onClick={onClick}
      className={({ isActive }) =>
        `px-3 py-2 rounded-md text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring ${
          isActive
            ? "bg-accent text-accent-foreground"
            : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
        }`
      }
    >
      {label}
    </NavLink>
  );
}

function StrategySelector() {
  const { selectedStrategyId, setSelectedStrategyId, strategies, selectedStrategy } =
    useStrategyContext();

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-sm font-medium hover:bg-accent transition-colors cursor-pointer">
        {selectedStrategy ? selectedStrategy.name : "전체"}
        <ChevronDown className="size-3.5 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" sideOffset={8}>
        <DropdownMenuItem
          onClick={() => setSelectedStrategyId(null)}
          className={selectedStrategyId === null ? "bg-accent" : ""}
        >
          전체
        </DropdownMenuItem>
        {strategies
          .filter((s) => s.is_active)
          .map((s) => (
            <DropdownMenuItem
              key={s.id}
              onClick={() => setSelectedStrategyId(s.id)}
              className={selectedStrategyId === s.id ? "bg-accent" : ""}
            >
              {s.name}
            </DropdownMenuItem>
          ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export default function Navbar() {
  const { theme, toggleTheme } = useTheme();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const { isLoggedIn, logout } = useAuth();

  const handleLogout = () => {
    logout();
    setMobileMenuOpen(false);
  };

  return (
    <nav
      className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60"
      role="navigation"
      aria-label="메인 네비게이션"
    >
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
        {/* 좌측: 로고 */}
        <div className="flex items-center">
          <Link
            to="/"
            className="text-lg font-bold tracking-tight focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            aria-label="ALT 홈으로 이동"
          >
            ALT
          </Link>
        </div>

        {/* 중앙: 데스크톱 네비게이션 (전략별 | 공통) */}
        <div className="hidden md:flex items-center gap-1" role="menubar">
          <StrategySelector />
          {strategyNavItems.map((item) => (
            <NavLinkItem key={item.to} to={item.to} label={item.label} />
          ))}
          <div className="mx-2 h-5 w-px bg-border" role="separator" aria-hidden />
          {commonNavItems.map((item) => (
            <NavLinkItem key={item.to} to={item.to} label={item.label} />
          ))}
        </div>

        {/* 우측: 테마 토글 + 로그인 상태 (데스크톱) */}
        <div className="hidden md:flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleTheme}
            aria-label={
              theme === "dark" ? "라이트 모드로 전환" : "다크 모드로 전환"
            }
          >
            {theme === "dark" ? (
              <Moon className="size-5" />
            ) : (
              <Sun className="size-5" />
            )}
          </Button>

          {isLoggedIn ? (
            <DropdownMenu>
              <DropdownMenuTrigger
                className="flex items-center justify-center rounded-full size-8 bg-muted hover:bg-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring cursor-pointer"
                aria-label="사용자 메뉴"
              >
                <User className="size-4" />
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" sideOffset={8}>
                <DropdownMenuItem onClick={handleLogout}>
                  <LogOut className="size-4" />
                  로그아웃
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <Link
              to="/login"
              className="text-sm text-muted-foreground hover:text-foreground transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
            >
              로그인
            </Link>
          )}
        </div>

        {/* 우측: 햄버거 메뉴 (모바일) */}
        <Button
          variant="ghost"
          size="icon"
          className="md:hidden"
          onClick={() => setMobileMenuOpen((prev) => !prev)}
          aria-label={mobileMenuOpen ? "메뉴 닫기" : "메뉴 열기"}
          aria-expanded={mobileMenuOpen}
        >
          {mobileMenuOpen ? (
            <X className="size-5" />
          ) : (
            <Menu className="size-5" />
          )}
        </Button>
      </div>

      {/* 모바일 사이드 메뉴 */}
      {mobileMenuOpen && (
        <div
          className="md:hidden border-t animate-in slide-in-from-top-2 duration-200"
          role="menu"
        >
          <div className="flex flex-col gap-1 p-4">
            <div className="px-3 py-2">
              <StrategySelector />
            </div>
            {strategyNavItems.map((item) => (
              <NavLinkItem
                key={item.to}
                to={item.to}
                label={item.label}
                onClick={() => setMobileMenuOpen(false)}
              />
            ))}
            <div className="my-2 h-px bg-border" role="separator" />
            {commonNavItems.map((item) => (
              <NavLinkItem
                key={item.to}
                to={item.to}
                label={item.label}
                onClick={() => setMobileMenuOpen(false)}
              />
            ))}
            <div className="my-2 h-px bg-border" role="separator" />
            <div className="flex items-center justify-between px-3 py-2">
              <span className="text-sm text-muted-foreground">테마</span>
              <Button
                variant="ghost"
                size="icon"
                onClick={toggleTheme}
                aria-label={
                  theme === "dark"
                    ? "라이트 모드로 전환"
                    : "다크 모드로 전환"
                }
              >
                {theme === "dark" ? (
                  <Moon className="size-5" />
                ) : (
                  <Sun className="size-5" />
                )}
              </Button>
            </div>
            {isLoggedIn ? (
              <button
                onClick={handleLogout}
                className="flex items-center gap-2 px-3 py-2 rounded-md text-sm text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              >
                <LogOut className="size-4" />
                로그아웃
              </button>
            ) : (
              <Link
                to="/login"
                onClick={() => setMobileMenuOpen(false)}
                className="px-3 py-2 rounded-md text-sm text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
              >
                로그인
              </Link>
            )}
          </div>
        </div>
      )}
    </nav>
  );
}
