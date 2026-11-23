"use client";

import { TriangleAlertIcon } from "lucide-react";

import { CopyButton } from "@/components/copy-button";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * A key or signing secret shown once, with a copy button. The API returns the plaintext
 * only in the creation response and never again, so the dashboard keeps it only in memory
 * until this dialog closes, and never fetches it again.
 */
export function SecretOnceDialog({
  value,
  title,
  description,
  label,
  onClose,
}: {
  value: string | null;
  title: string;
  description: string;
  label: string;
  onClose: () => void;
}) {
  return (
    <Dialog open={!!value} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogBody className="space-y-3">
          <div
            role="note"
            className="flex items-start gap-2 rounded-lg bg-warning-soft px-3 py-2.5 text-[12.5px] font-medium text-warning"
          >
            <TriangleAlertIcon className="mt-0.5 size-4 shrink-0" aria-hidden />
            Shown once, never again. Copy it into your secret manager now: LogMind stores only a
            hash and cannot show it later.
          </div>
          <div className="text-[11.5px] font-semibold tracking-wide text-subtle uppercase">
            {label}
          </div>
          <div className="flex items-center gap-2 rounded-lg bg-muted px-3 py-2.5">
            <code
              data-qa="one-time-secret"
              className="min-w-0 flex-1 font-mono text-[12.5px] break-all"
            >
              {value}
            </code>
            {value && <CopyButton value={value} label="Copy" />}
          </div>
        </DialogBody>
        <DialogFooter>
          <Button onClick={onClose}>I stored it</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
