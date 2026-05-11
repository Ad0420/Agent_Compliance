"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState, type CSSProperties } from "react";
import { Wordmark } from "./brand";

const NAV_ITEMS: Array<[string, string]> = [
  ["Product", "/"],
  ["Regulations", "/regulations"],
];

const linkStyle = (hot: boolean): CSSProperties => ({
  fontSize: 14,
  color: hot ? "var(--ink)" : "var(--ink-2)",
  textDecoration: "none",
  fontWeight: 500,
  letterSpacing: "-0.005em",
});

const ctaStyle: CSSProperties = {
  background: "var(--ink)",
  color: "var(--paper)",
  border: "1px solid var(--ink)",
  padding: "9px 16px",
  fontSize: 13.5,
  fontWeight: 600,
  fontFamily: "var(--sans)",
  cursor: "pointer",
  borderRadius: 6,
  boxShadow: "var(--shadow-1)",
  textDecoration: "none",
  display: "inline-block",
};

export function V4Nav() {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  return (
    <nav
      style={{
        position: "sticky",
        top: 0,
        zIndex: 10,
        backdropFilter: "blur(14px)",
        WebkitBackdropFilter: "blur(14px)",
        background: "rgba(243,239,231,.78)",
        borderBottom: "1px solid var(--ink-4)",
        padding: "16px var(--gutter)",
        display: "flex",
        alignItems: "center",
        gap: 16,
      }}
    >
      <Wordmark size={17} />
      <span style={{ flex: 1 }} />

      <div className="v4-nav-desktop">
        {NAV_ITEMS.map(([label, href]) => (
          <Link key={label} href={href} style={linkStyle(pathname === href)}>
            {label}
          </Link>
        ))}
        <span style={{ width: 6 }} />
        <Link
          href="/login"
          style={{
            fontSize: 14,
            color: "var(--ink-2)",
            textDecoration: "none",
            fontWeight: 500,
          }}
        >
          Sign in
        </Link>
        <Link href="/register" style={ctaStyle}>
          Get started →
        </Link>
      </div>

      <Link
        href="/register"
        className="v4-nav-cta-mobile"
        style={{
          background: "var(--ink)",
          color: "var(--paper)",
          border: "1px solid var(--ink)",
          padding: "8px 14px",
          fontSize: 13,
          fontWeight: 600,
          fontFamily: "var(--sans)",
          cursor: "pointer",
          borderRadius: 6,
          boxShadow: "var(--shadow-1)",
          textDecoration: "none",
        }}
      >
        Get started →
      </Link>

      <button
        type="button"
        className="v4-nav-trigger"
        aria-label={open ? "Close menu" : "Open menu"}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
      >
        <svg width="18" height="14" viewBox="0 0 18 14" fill="none" aria-hidden>
          {open ? (
            <>
              <line x1="2" y1="2" x2="16" y2="12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              <line x1="16" y1="2" x2="2" y2="12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </>
          ) : (
            <>
              <line x1="1" y1="2" x2="17" y2="2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              <line x1="1" y1="7" x2="17" y2="7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              <line x1="1" y1="12" x2="17" y2="12" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </>
          )}
        </svg>
      </button>

      {open && (
        <div className="v4-nav-drawer">
          {NAV_ITEMS.map(([label, href]) => (
            <Link
              key={label}
              href={href}
              style={{ ...linkStyle(pathname === href), fontSize: 16, padding: "8px 0" }}
              onClick={() => setOpen(false)}
            >
              {label}
            </Link>
          ))}
          <Link
            href="/login"
            style={{
              fontSize: 16,
              color: "var(--ink-2)",
              textDecoration: "none",
              fontWeight: 500,
              padding: "8px 0",
              borderTop: "1px solid var(--ink-4)",
              paddingTop: 16,
              marginTop: 4,
            }}
            onClick={() => setOpen(false)}
          >
            Sign in
          </Link>
        </div>
      )}
    </nav>
  );
}
