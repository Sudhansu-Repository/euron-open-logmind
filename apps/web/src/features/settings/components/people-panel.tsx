"use client";

import { UserPlusIcon, UsersIcon } from "lucide-react";
import * as React from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { GatedButton } from "@/components/gated";
import { QueryState } from "@/components/query-state";
import { Surface, SurfaceHeader } from "@/components/surface";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Field, FieldError } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { usePermissions } from "@/features/auth/api";
import { useCan } from "@/hooks/use-can";
import type { User } from "@/lib/api/types";
import { errorMessage } from "@/lib/api/errors";
import { formatRelative } from "@/lib/format";
import { passwordMessage } from "@/lib/password";
import { ROLES, roleDescription, roleLabel, type Role } from "@/lib/roles";

import { useCreateUser, useUpdateUser, useUsers } from "../api";

const ROLE_OPTIONS = ROLES.map((r) => ({ value: r, label: roleLabel(r) }));

function InviteDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const create = useCreateUser();
  const [name, setName] = React.useState("");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [role, setRole] = React.useState<Role>("viewer");
  const [error, setError] = React.useState<string | null>(null);
  React.useEffect(() => {
    if (open) {
      setName("");
      setEmail("");
      setPassword("");
      setRole("viewer");
      setError(null);
    }
  }, [open]);
  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !email.trim()) return setError("Enter their name and email.");
    const weak = passwordMessage(password);
    if (weak) return setError(weak);
    setError(null);
    create.mutate(
      { name: name.trim(), email: email.trim(), password, role },
      {
        onSuccess: (u) => {
          toast.success(`${u.name} can now sign in as ${roleLabel(u.role).toLowerCase()}.`);
          onOpenChange(false);
        },
        onError: (err) => setError(errorMessage(err)),
      }
    );
  }
  return (
    <Dialog open={open} onOpenChange={(o) => !create.isPending && onOpenChange(o)}>
      <DialogContent>
        <form onSubmit={submit} className="flex min-h-0 flex-col" noValidate>
          <DialogHeader>
            <DialogTitle>Add a person</DialogTitle>
            <DialogDescription>
              They sign in with this email and the starting password you set; share it with them
              privately.
            </DialogDescription>
          </DialogHeader>
          <DialogBody className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Name" htmlFor="inv-name">
                <Input
                  id="inv-name"
                  autoFocus
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </Field>
              <Field label="Email" htmlFor="inv-email">
                <Input
                  id="inv-email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </Field>
            </div>
            <Field
              label="Starting password"
              htmlFor="inv-pw"
              hint="At least 10 characters, with upper and lower case letters and a digit."
            >
              <Input
                id="inv-pw"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
            <Field label="Role" htmlFor="inv-role" hint={roleDescription(role)}>
              <SimpleSelect
                id="inv-role"
                value={role}
                onValueChange={(v) => setRole(v as Role)}
                options={ROLE_OPTIONS}
              />
            </Field>
            {error && <FieldError>{error}</FieldError>}
          </DialogBody>
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => onOpenChange(false)}
              disabled={create.isPending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending ? "Adding..." : "Add person"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function UserRow({ u, self }: { u: User; self: boolean }) {
  const update = useUpdateUser();
  const save = (body: { role?: string; disabled?: boolean }, msg: string) =>
    update.mutate(
      { id: u.id, body },
      { onSuccess: () => toast.success(msg), onError: (e) => toast.error(errorMessage(e)) }
    );
  return (
    <TableRow>
      <TableCell>
        <span className="block font-medium">
          {u.name}
          {self && <span className="ml-1.5 text-[11.5px] font-normal text-subtle">(you)</span>}
        </span>
        <span className="block text-[11.5px] text-subtle">{u.email}</span>
      </TableCell>
      <TableCell className="w-40">
        <SimpleSelect
          size="sm"
          aria-label={`Role for ${u.name}`}
          value={u.role}
          disabled={update.isPending || self}
          onValueChange={(v) =>
            v !== u.role && save({ role: v }, `${u.name} is now ${roleLabel(v).toLowerCase()}.`)
          }
          options={ROLE_OPTIONS}
        />
        {self && (
          <span className="mt-1 block text-[11px] text-subtle">
            Another owner must change your role.
          </span>
        )}
      </TableCell>
      <TableCell className="hidden text-muted-foreground md:table-cell">
        {formatRelative(u.last_login_at)}
      </TableCell>
      <TableCell className="text-right">
        <span className="inline-flex items-center gap-2">
          {u.disabled ? <Chip tone="warning">Disabled</Chip> : <Chip tone="success">Active</Chip>}
          <Switch
            aria-label={u.disabled ? `Enable ${u.name}` : `Disable ${u.name}`}
            checked={!u.disabled}
            disabled={update.isPending || self}
            onCheckedChange={(on) =>
              save(
                { disabled: !on },
                on
                  ? `${u.name} can sign in again.`
                  : `${u.name} is disabled and signed out everywhere.`
              )
            }
          />
        </span>
      </TableCell>
    </TableRow>
  );
}

/** People: Owner only on the API. Other roles see the panel with the reason, never a hidden tab. */
export function PeoplePanel() {
  const users = useUsers();
  const { allowed, reason } = useCan("manageUsers");
  const { user } = usePermissions();
  const [open, setOpen] = React.useState(false);
  return (
    <Surface>
      <SurfaceHeader
        title="People"
        description="Who can sign in to this organization, and with which role."
        action={
          <GatedButton need="manageUsers" size="sm" onClick={() => setOpen(true)}>
            <UserPlusIcon />
            Add person
          </GatedButton>
        }
      />
      {!allowed ? (
        <EmptyState
          compact
          icon={UsersIcon}
          title="Only owners manage people"
          description={`${reason} Ask an owner of your organization to add someone or change a role.`}
        />
      ) : (
        <QueryState
          query={users}
          errorTitle="Could not load people"
          empty={(d) => d.length === 0}
          emptyState={
            <EmptyState
              compact
              icon={UsersIcon}
              title="Nobody else yet"
              description="Add teammates so they can search logs, triage errors and read investigations."
            />
          }
        >
          {(list) => (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Person</TableHead>
                  <TableHead>Role</TableHead>
                  <TableHead className="hidden md:table-cell">Last sign in</TableHead>
                  <TableHead className="text-right">Access</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {list.map((u) => (
                  <UserRow key={u.id} u={u} self={u.id === user?.id} />
                ))}
              </TableBody>
            </Table>
          )}
        </QueryState>
      )}
      <InviteDialog open={open} onOpenChange={setOpen} />
    </Surface>
  );
}
