import { V4Nav } from "@/components/landing/v4-nav";
import { V4Hero } from "@/components/landing/v4-hero";
import { V4Customers } from "@/components/landing/v4-customers";
import { V4Problem } from "@/components/landing/v4-problem";
import { V4Deadline } from "@/components/landing/v4-deadline";
import { V4Compare } from "@/components/landing/v4-compare";
import { V4Code } from "@/components/landing/v4-code";
import { V4Artifact } from "@/components/landing/v4-artifact";
import { V4DarkCTA } from "@/components/landing/v4-dark-cta";
import { V4Footer } from "@/components/landing/v4-footer";

export default function LandingPage() {
  return (
    <div
      style={{
        background: "var(--paper)",
        color: "var(--ink)",
        fontFamily: "var(--sans)",
        overflow: "hidden",
      }}
    >
      <V4Nav />
      <V4Hero />
      <V4Customers />
      <V4Problem />
      <V4Deadline />
      <V4Compare />
      <V4Code />
      <V4Artifact />
      <V4DarkCTA />
      <V4Footer />
    </div>
  );
}
