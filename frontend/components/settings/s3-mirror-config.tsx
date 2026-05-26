"use client";

/**
 * S3MirrorConfig — Settings → Off-Vera evidence mirror panel.
 *
 * Phase 3 Wave 3D.3. The customer's off-Vera S3 mirror is the durable,
 * customer-controlled copy of every sealed checkpoint plus the
 * underlying action records — the authoritative evidence trail if Vera
 * ever became unreachable.
 *
 * Surfaces:
 *   - Current ARN (masked for display), last successful export, recent
 *     failure summary, counts of success/failure/skipped exports.
 *   - Configuration form: ARN input with server-side syntax validation
 *     on blur (UX nicety only — the PUT also validates authoritatively).
 *   - "Test connection" button gated behind ACTIONLEDGER_S3_TRUST_PROBE_ENABLED.
 *   - Last 10 export rows from checkpoint_exports.
 *
 * RBAC: viewing the panel is admin + developer; editing the ARN and
 * running the probe is admin-only. Non-admins see a read-only view.
 */

import * as React from "react";
import { Check, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Loading } from "@/components/ui/loading";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { StatusDot, type StatusVariant } from "@/components/ui/status-indicator";
import { useAuth } from "@/hooks/use-auth";
import {
  useClearS3MirrorArn,
  useProbeS3MirrorArn,
  useS3MirrorConfig,
  useUpdateS3MirrorArn,
  useValidateS3MirrorArn,
} from "@/hooks/use-s3-mirror";
import { ApiError } from "@/lib/api-client";
import type {
  S3ExportStatus,
  S3MirrorErrorDetail,
  S3MirrorRecentExport,
} from "@/lib/api-types";
import { cn, formatDate, truncateHash } from "@/lib/utils";

// ── Helpers ──────────────────────────────────────────────────────


/**
 * Mask the middle of an ARN for display. Keeps the prefix
 * ``arn:aws:s3:::`` and the last few chars of the bucket/prefix so the
 * operator can recognise which mirror is configured at a glance,
 * without surfacing the full path next to a shoulder-surfer.
 */
export function maskArn(arn: string | null | undefined): string {
  if (!arn) return "";
  // Show the canonical prefix + last 8 chars; replace the middle with
  // a thin ellipsis so a long path doesn't visually swamp the panel.
  const prefix = "arn:aws:s3:::";
  if (!arn.startsWith(prefix)) {
    // Non-canonical ARN — fall back to a generic mask.
    return truncateHash(arn, 6);
  }
  const rest = arn.slice(prefix.length);
  if (rest.length <= 14) return arn;
  return `${prefix}${rest.slice(0, 6)}…${rest.slice(-6)}`;
}


/**
 * Map a flat-error envelope into the kind of message the UI should
 * render. Returns the structured shape when present, otherwise null
 * so the caller can fall back to a generic Error.message.
 */
function readFlatError(err: unknown): S3MirrorErrorDetail | null {
  if (!(err instanceof ApiError)) return null;
  const detail = err.detail;
  if (!detail || typeof detail !== "object") return null;
  const code = (detail as Record<string, unknown>).code;
  const message = (detail as Record<string, unknown>).message;
  if (typeof code !== "string" || typeof message !== "string") return null;
  const hint = (detail as Record<string, unknown>).hint;
  return {
    code,
    message,
    hint: typeof hint === "string" ? hint : undefined,
  };
}


const STATUS_VARIANT_BY_EXPORT: Record<S3ExportStatus, StatusVariant> = {
  success: "ok",
  failure: "error",
  pending: "muted",
  skipped: "warn",
};


function statusLabel(s: S3ExportStatus): string {
  // Match dashboard-design-system.md voice — title-case nouns, no
  // imperatives. "Skipped" surfaces when the org has no ARN configured
  // (forensic row), so the operator sees that we considered exporting
  // and chose not to rather than a silent gap.
  switch (s) {
    case "success":
      return "Success";
    case "failure":
      return "Failure";
    case "pending":
      return "Pending";
    case "skipped":
      return "Skipped";
  }
}


// ── Recent exports table ─────────────────────────────────────────


function RecentExportsTable({
  rows,
}: {
  rows: S3MirrorRecentExport[];
}) {
  if (rows.length === 0) {
    return (
      <p className="text-sm text-[color:var(--ink-2)]">
        No exports yet. The next sealed checkpoint will appear here.
      </p>
    );
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead className="text-xs uppercase tracking-wider text-[color:var(--ink-2)]">
            Checkpoint
          </TableHead>
          <TableHead className="text-xs uppercase tracking-wider text-[color:var(--ink-2)]">
            Status
          </TableHead>
          <TableHead className="text-xs uppercase tracking-wider text-[color:var(--ink-2)]">
            Exported
          </TableHead>
          <TableHead className="text-xs uppercase tracking-wider text-[color:var(--ink-2)] tabular-nums">
            Duration
          </TableHead>
          <TableHead className="text-xs uppercase tracking-wider text-[color:var(--ink-2)] tabular-nums">
            Records
          </TableHead>
          <TableHead className="text-xs uppercase tracking-wider text-[color:var(--ink-2)]">
            Reason
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.id}>
            <TableCell className="font-mono text-xs">
              {truncateHash(row.checkpoint_id, 6)}
            </TableCell>
            <TableCell>
              <StatusDot
                variant={STATUS_VARIANT_BY_EXPORT[row.status]}
                label={statusLabel(row.status)}
              />
            </TableCell>
            <TableCell className="text-xs tabular-nums">
              {row.exported_at ? formatDate(row.exported_at) : "—"}
            </TableCell>
            <TableCell className="text-xs tabular-nums">
              {row.duration_ms != null ? `${row.duration_ms}ms` : "—"}
            </TableCell>
            <TableCell className="text-xs tabular-nums">
              {/* copy-allow: numeric value rendered with tabular-nums on the cell */}
              {row.record_count != null
                ? row.record_count.toLocaleString("en-US")
                : "—"}
            </TableCell>
            <TableCell className="text-xs text-[color:var(--ink-2)]">
              {row.reason ?? "—"}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}


// ── Main panel ───────────────────────────────────────────────────


export function S3MirrorConfigPanel() {
  const { isAdmin } = useAuth();
  const { data, isLoading, isError, error } = useS3MirrorConfig();

  if (isLoading) {
    return (
      <Card>
        <CardContent
          className="flex items-center gap-2 text-sm text-[color:var(--ink-2)]"
          aria-busy="true"
        >
          <Loading.Spinner label="Loading mirror configuration" />
          <span>Loading mirror configuration…</span>
        </CardContent>
      </Card>
    );
  }

  if (isError || !data) {
    return (
      <Card>
        <CardContent>
          <p className="text-sm text-[color:var(--ink-2)]" role="alert">
            Couldn&apos;t load mirror configuration
            {error instanceof Error ? ` — ${error.message}` : ""}.
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <CurrentStateCard config={data} />
      {isAdmin ? <ConfigureCard config={data} /> : <ReadOnlyNotice />}
      <RecentExportsCard rows={data.recent_exports} />
    </div>
  );
}


function ReadOnlyNotice() {
  return (
    <Card>
      <CardContent>
        <p className="text-sm text-[color:var(--ink-2)]">
          Mirror configuration is admin-only. Ask an admin in your
          organization to set the bucket ARN.
        </p>
      </CardContent>
    </Card>
  );
}


function CurrentStateCard({
  config,
}: {
  config: ReturnType<typeof useS3MirrorConfig>["data"] & object;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Current state</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {config.arn ? (
          <>
            <div className="space-y-1">
              <div className="text-xs uppercase tracking-wider text-[color:var(--ink-2)]">
                Configured bucket
              </div>
              <div
                className="font-mono text-sm text-[color:var(--ink)] break-all"
                title={config.arn}
              >
                {maskArn(config.arn)}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
              <Metric
                label="Successful exports"
                value={config.success_total.toLocaleString("en-US")}
              />
              <Metric
                label="Failures"
                value={config.failure_total.toLocaleString("en-US")}
              />
              <Metric
                label="Skipped"
                value={config.skipped_total.toLocaleString("en-US")}
              />
              <Metric
                label="Pending"
                value={config.pending_total.toLocaleString("en-US")}
              />
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 text-xs">
              <div>
                <div className="uppercase tracking-wider text-[color:var(--ink-2)]">
                  Last successful sync
                </div>
                <div className="tabular-nums text-[color:var(--ink)]">
                  {config.last_success_at
                    ? formatDate(config.last_success_at)
                    : "—"}
                </div>
              </div>
              <div>
                <div className="uppercase tracking-wider text-[color:var(--ink-2)]">
                  Last failure
                </div>
                <div className="tabular-nums text-[color:var(--ink)]">
                  {config.last_failure_at ? (
                    <>
                      {formatDate(config.last_failure_at)}
                      {config.last_failure_reason ? (
                        <span className="block text-[color:var(--ink-2)]">
                          {config.last_failure_reason}
                        </span>
                      ) : null}
                    </>
                  ) : (
                    "—"
                  )}
                </div>
              </div>
            </div>
          </>
        ) : (
          <p className="text-sm text-[color:var(--ink-2)]">
            No mirror is configured yet. Vera is still sealing
            checkpoints in its own evidence store; configure a bucket
            below to start mirroring to a location your auditor controls.
          </p>
        )}
      </CardContent>
    </Card>
  );
}


function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wider text-[color:var(--ink-2)]">
        {label}
      </div>
      <div className="text-lg tabular-nums text-[color:var(--ink)]">
        {value}
      </div>
    </div>
  );
}


function ConfigureCard({
  config,
}: {
  config: ReturnType<typeof useS3MirrorConfig>["data"] & object;
}) {
  const [arnInput, setArnInput] = React.useState<string>(config.arn ?? "");
  const [roleArnInput, setRoleArnInput] = React.useState<string>("");
  const [inlineError, setInlineError] = React.useState<
    S3MirrorErrorDetail | null
  >(null);
  const [probeResult, setProbeResult] = React.useState<
    { ok: true; stub: boolean } | { ok: false; error: S3MirrorErrorDetail } | null
  >(null);
  const [saved, setSaved] = React.useState(false);

  // Keep the local input in sync if the upstream config changes (e.g.
  // another admin in the same org saved a value in another tab).
  React.useEffect(() => {
    setArnInput(config.arn ?? "");
  }, [config.arn]);

  const update = useUpdateS3MirrorArn();
  const clear = useClearS3MirrorArn();
  const validate = useValidateS3MirrorArn();
  const probe = useProbeS3MirrorArn();

  const onBlurValidate = async () => {
    const candidate = arnInput.trim();
    if (!candidate) {
      setInlineError(null);
      return;
    }
    try {
      await validate.mutateAsync({ arn: candidate });
      setInlineError(null);
    } catch (err) {
      const flat = readFlatError(err);
      setInlineError(
        flat ?? {
          code: "validation_failed",
          message:
            err instanceof Error
              ? err.message
              : "We couldn't validate the ARN. Try again.",
        },
      );
    }
  };

  const onSave = async () => {
    const candidate = arnInput.trim();
    setInlineError(null);
    setProbeResult(null);
    try {
      await update.mutateAsync(candidate);
      setSaved(true);
      // copy-allow: setTimeout duration in ms, not a user-facing quantity
      setTimeout(() => setSaved(false), 2500);
    } catch (err) {
      const flat = readFlatError(err);
      setInlineError(
        flat ?? {
          code: "save_failed",
          message:
            err instanceof Error
              ? err.message
              : "We couldn't save the ARN. Try again.",
        },
      );
    }
  };

  const onClear = async () => {
    setInlineError(null);
    setProbeResult(null);
    try {
      await clear.mutateAsync();
      setArnInput("");
    } catch (err) {
      setInlineError({
        code: "clear_failed",
        message:
          err instanceof Error
            ? err.message
            : "We couldn't clear the configuration. Try again.",
      });
    }
  };

  const onProbe = async () => {
    setInlineError(null);
    setProbeResult(null);
    try {
      const result = await probe.mutateAsync({
        arn: arnInput.trim(),
        role_arn: roleArnInput.trim() || undefined,
      });
      setProbeResult({ ok: true, stub: result.stub });
    } catch (err) {
      const flat = readFlatError(err);
      setProbeResult({
        ok: false,
        error: flat ?? {
          code: "probe_failed",
          message:
            err instanceof Error
              ? err.message
              : "The connection test couldn't complete.",
        },
      });
    }
  };

  const probeDisabled =
    !config.probe_enabled ||
    !arnInput.trim() ||
    probe.isPending ||
    update.isPending;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Configure mirror</CardTitle>
        <p className="text-xs text-[color:var(--ink-2)]">
          Paste the S3 bucket ARN from your AWS console. Vera writes
          one JSON document per sealed checkpoint with Object Lock in
          COMPLIANCE mode and a 7-year retention window.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <label
            htmlFor="s3-mirror-arn"
            className="text-xs uppercase tracking-wider text-[color:var(--ink-2)]"
          >
            Bucket ARN
          </label>
          <Input
            id="s3-mirror-arn"
            value={arnInput}
            onChange={(e) => {
              setArnInput(e.target.value);
              setInlineError(null);
              setProbeResult(null);
            }}
            onBlur={onBlurValidate}
            placeholder="arn:aws:s3:::your-vera-mirror"
            className={cn(
              "font-mono text-sm",
              inlineError ? "border-[color:var(--brick)]" : undefined,
            )}
            aria-invalid={inlineError ? true : undefined}
            aria-describedby={
              inlineError ? "s3-mirror-arn-error" : "s3-mirror-arn-hint"
            }
          />
          {inlineError ? (
            <p
              id="s3-mirror-arn-error"
              className="text-xs text-[color:var(--brick)]"
              role="alert"
            >
              {inlineError.message}
              {inlineError.hint ? (
                <span className="block text-[color:var(--ink-2)]">
                  {inlineError.hint}
                </span>
              ) : null}
            </p>
          ) : (
            <p
              id="s3-mirror-arn-hint"
              className="text-xs text-[color:var(--ink-2)]"
            >
              Format: arn:aws:s3:::bucket-name/optional-prefix/
            </p>
          )}
        </div>

        <div className="space-y-2">
          <label
            htmlFor="s3-mirror-role"
            className="text-xs uppercase tracking-wider text-[color:var(--ink-2)]"
          >
            IAM role ARN (optional)
          </label>
          <Input
            id="s3-mirror-role"
            value={roleArnInput}
            onChange={(e) => setRoleArnInput(e.target.value)}
            // copy-allow: AWS IAM placeholder uses canonical 12-digit account-id format
            placeholder="arn:aws:iam::123456789012:role/VeraExportRole"
            className="font-mono text-sm"
            disabled={!config.iam_role_supported}
          />
          {!config.iam_role_supported ? (
            <p className="text-xs text-[color:var(--ink-2)]">
              Cross-account role assumption is coming in a follow-up
              release. For now, Vera uses its service credentials and
              your bucket policy controls access.
            </p>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            onClick={onSave}
            disabled={!arnInput.trim() || update.isPending}
          >
            {update.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : saved ? (
              <>
                <Check className="mr-1 h-4 w-4 text-emerald-400" /> Saved
              </>
            ) : config.arn ? (
              "Update"
            ) : (
              "Save"
            )}
          </Button>
          {config.arn ? (
            <Button
              size="sm"
              variant="outline"
              onClick={onClear}
              disabled={clear.isPending}
              className="text-[color:var(--ink-2)]"
            >
              {clear.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                "Clear"
              )}
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="outline"
            onClick={onProbe}
            disabled={probeDisabled}
            title={
              config.probe_enabled
                ? "Run a write probe against the bucket"
                : "Connection test is disabled in this deployment — contact ops to enable."
            }
          >
            {probe.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              "Test connection"
            )}
          </Button>
        </div>

        {!config.probe_enabled ? (
          <p className="text-xs text-[color:var(--ink-2)]">
            Connection test is disabled in this deployment. Vera will
            exercise write access on the next sealed checkpoint.
          </p>
        ) : null}

        {probeResult ? <ProbeResultLine result={probeResult} /> : null}
      </CardContent>
    </Card>
  );
}


function ProbeResultLine({
  result,
}: {
  result:
    | { ok: true; stub: boolean }
    | { ok: false; error: S3MirrorErrorDetail };
}) {
  if (result.ok) {
    return (
      <div className="rounded-md border border-[color:var(--olive)] bg-[color:var(--olive-bg)] px-3 py-2 text-sm">
        <StatusDot
          variant="ok"
          label={
            result.stub
              ? "Syntax validated. Vera will exercise write access on the next sealed checkpoint."
              : "Connection verified. Vera can write to the bucket."
          }
        />
      </div>
    );
  }
  return (
    <div
      className="rounded-md border border-[color:var(--brick)] bg-[color:var(--brick-bg)] px-3 py-2 text-sm"
      role="alert"
    >
      <div className="text-[color:var(--brick)]">{result.error.message}</div>
      {result.error.hint ? (
        <div className="mt-1 text-xs text-[color:var(--ink-2)]">
          {result.error.hint}
        </div>
      ) : null}
    </div>
  );
}


function RecentExportsCard({ rows }: { rows: S3MirrorRecentExport[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Recent exports</CardTitle>
        <p className="text-xs text-[color:var(--ink-2)]">
          Last 10 checkpoint export attempts. Forensic record of every
          mirror write Vera has attempted on your behalf.
        </p>
      </CardHeader>
      <CardContent>
        <RecentExportsTable rows={rows} />
      </CardContent>
    </Card>
  );
}
