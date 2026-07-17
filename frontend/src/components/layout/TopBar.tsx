import { LogOut, Moon, Sun } from "lucide-react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Logo } from "@/components/layout/Logo";
import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";

export function TopBar() {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const toggleTheme = () => setTheme(theme === "dark" ? "light" : "dark");

  return (
    <header className="flex h-14 shrink-0 items-center justify-between gap-4 border-b border-border bg-card/60 px-4 backdrop-blur-sm sm:px-6">
      <div className="flex items-center gap-3 sm:hidden">
        <Logo />
      </div>

      <div className="flex flex-1 items-center justify-end gap-2">
        <Button variant="ghost" size="icon" className="rounded-full" onClick={toggleTheme} aria-label="Toggle theme">
          {theme === "dark" ? <Sun className="size-[18px]" /> : <Moon className="size-[18px]" />}
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button type="button" className="rounded-full ring-offset-2 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none">
              <Avatar className="ring-2 ring-border">
                <AvatarFallback className="bg-gradient-to-br from-primary/20 to-device/20 font-semibold text-primary">
                  {(user?.username ?? "?").slice(0, 2).toUpperCase()}
                </AvatarFallback>
              </Avatar>
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>{user?.username}</DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => void logout()}>
              <LogOut className="size-4" />
              Log out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
