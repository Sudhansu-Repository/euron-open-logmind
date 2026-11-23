"use client";

import { MenuIcon } from "lucide-react";
import Link from "next/link";
import * as React from "react";

import { BrandLogo } from "@/components/brand";
import { ProjectSelect } from "@/components/project-select";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";

import { SidebarNav } from "./sidebar";
import { UserMenu } from "./user-menu";

export function Topbar() {
  const [menuOpen, setMenuOpen] = React.useState(false);
  return (
    <header className="sticky top-0 z-30 bg-background/80 backdrop-blur-md supports-[backdrop-filter]:bg-background/70">
      <div className="flex h-14 items-center gap-2 px-4 sm:px-6 lg:px-8">
        <Button
          variant="subtle"
          size="icon"
          className="-ml-2 lg:hidden"
          aria-label="Open navigation"
          onClick={() => setMenuOpen(true)}
        >
          <MenuIcon />
        </Button>
        <Link href="/overview" className="rounded-lg lg:hidden" aria-label="LogMind overview">
          <BrandLogo collapsed className="sm:hidden" />
          <BrandLogo className="hidden sm:inline-flex" />
        </Link>
        <div className="ml-auto flex min-w-0 items-center gap-1.5">
          <ProjectSelect className="w-36 sm:w-48" label="Scope the dashboard to a project" />
          <ThemeToggle />
          <UserMenu />
        </div>
      </div>
      <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
        <SheetContent side="left" className="bg-sidebar">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <div className="flex h-14 items-center px-4">
            <BrandLogo />
          </div>
          <div className="overflow-y-auto px-3 pb-6">
            <SidebarNav onNavigate={() => setMenuOpen(false)} />
          </div>
        </SheetContent>
      </Sheet>
    </header>
  );
}
