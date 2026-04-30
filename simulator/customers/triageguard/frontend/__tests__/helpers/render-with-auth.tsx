/**
 * Test helper for rendering a hook (or component) inside `<AuthProvider />`.
 *
 * `renderHookWithAuth(useFoo)` returns the same surface as
 * `@testing-library/react`'s `renderHook` plus the underlying provider —
 * tests that need the AuthContext to be populated import this instead of
 * doing the wrapping inline every time.
 */

import * as React from "react";
import { renderHook, type RenderHookOptions } from "@testing-library/react";

import { AuthProvider } from "@/hooks/use-auth";

export function authWrapper({
  children,
}: {
  children: React.ReactNode;
}): React.JSX.Element {
  return <AuthProvider>{children}</AuthProvider>;
}

export function renderHookWithAuth<TResult, TProps>(
  callback: (props: TProps) => TResult,
  options: Omit<RenderHookOptions<TProps>, "wrapper"> = {} as Omit<
    RenderHookOptions<TProps>,
    "wrapper"
  >,
) {
  return renderHook<TResult, TProps>(callback, {
    ...options,
    wrapper: authWrapper,
  });
}
