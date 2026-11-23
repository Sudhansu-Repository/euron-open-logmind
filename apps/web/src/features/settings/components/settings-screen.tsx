"use client";

import {
  BuildingIcon,
  FolderKanbanIcon,
  KeyRoundIcon,
  ScrollTextIcon,
  SparklesIcon,
  UsersIcon,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";

import { PageHeader } from "@/components/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

import { AiPanel } from "./ai-panel";
import { AuditPanel } from "./audit-panel";
import { KeysPanel } from "./keys-panel";
import { OrgPanel } from "./org-panel";
import { PeoplePanel } from "./people-panel";
import { ProjectsPanel } from "./projects-panel";

const TABS = ["organization", "projects", "keys", "ai", "people", "audit"] as const;

export function SettingsScreen() {
  const params = useSearchParams();
  const router = useRouter();
  const raw = params.get("tab") ?? "organization";
  const tab = (TABS as readonly string[]).includes(raw) ? raw : "organization";
  return (
    <>
      <PageHeader
        title="Settings"
        description="Your organization, projects with their retention and redaction, API keys, AI providers, people and the audit log."
      />
      <Tabs
        value={tab}
        onValueChange={(v) => router.replace(`/settings?tab=${String(v)}`, { scroll: false })}
      >
        <TabsList className="max-w-full overflow-x-auto">
          <TabsTrigger value="organization">
            <BuildingIcon />
            Organization
          </TabsTrigger>
          <TabsTrigger value="projects">
            <FolderKanbanIcon />
            Projects
          </TabsTrigger>
          <TabsTrigger value="keys">
            <KeyRoundIcon />
            API keys
          </TabsTrigger>
          <TabsTrigger value="ai">
            <SparklesIcon />
            AI providers
          </TabsTrigger>
          <TabsTrigger value="people">
            <UsersIcon />
            People
          </TabsTrigger>
          <TabsTrigger value="audit">
            <ScrollTextIcon />
            Audit log
          </TabsTrigger>
        </TabsList>
        <TabsContent value="organization">
          <OrgPanel />
        </TabsContent>
        <TabsContent value="projects">
          <ProjectsPanel />
        </TabsContent>
        <TabsContent value="keys">
          <KeysPanel />
        </TabsContent>
        <TabsContent value="ai">
          <AiPanel />
        </TabsContent>
        <TabsContent value="people">
          <PeoplePanel />
        </TabsContent>
        <TabsContent value="audit">
          <AuditPanel />
        </TabsContent>
      </Tabs>
    </>
  );
}
