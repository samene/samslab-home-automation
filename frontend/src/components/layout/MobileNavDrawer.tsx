import { Menu } from "lucide-react";
import { useState } from "react";
import { NavList } from "@/components/layout/Sidebar";
import { Logo } from "@/components/layout/Logo";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";

/**
 * Mobile navigation (below `md`, where neither Sidebar variant renders): a
 * hamburger button that opens a left-edge drawer holding the exact same
 * `NavList` the desktop sidebar uses — every route the sidebar can reach is
 * reachable here too, unlike the bottom tab bar this replaced (which only
 * ever surfaced 3 of the app's 6 routes).
 */
export function MobileNavDrawer() {
  const [open, setOpen] = useState(false);

  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="rounded-full"
          aria-label="Open navigation menu"
        >
          <Menu className="size-5" />
        </Button>
      </SheetTrigger>
      <SheetContent
        side="left"
        className="max-w-[85vw] gap-0 p-0 pt-[max(1rem,env(safe-area-inset-top))] pb-[max(1rem,env(safe-area-inset-bottom))] pl-[env(safe-area-inset-left)]"
      >
        <SheetHeader className="px-5 py-4">
          <SheetTitle className="font-normal">
            <Logo />
          </SheetTitle>
        </SheetHeader>
        <NavList onNavigate={() => setOpen(false)} />
      </SheetContent>
    </Sheet>
  );
}
