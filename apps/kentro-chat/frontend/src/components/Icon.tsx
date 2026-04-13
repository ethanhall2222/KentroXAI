import type { SVGProps } from "react";

type IconName =
  | "plus"
  | "spark"
  | "search"
  | "download"
  | "send"
  | "person"
  | "external"
  | "menu"
  | "panel"
  | "close"
  | "chevron";

export function Icon({ name, className = "" }: { name: IconName; className?: string }) {
  const props: SVGProps<SVGSVGElement> = {
    viewBox: "0 0 20 20",
    fill: "none",
    "aria-hidden": true,
    className,
  };

  switch (name) {
    case "plus":
      return (
        <svg {...props}>
          <path d="M10 4.167v11.666M4.167 10h11.666" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      );
    case "search":
      return (
        <svg {...props}>
          <circle cx="9.167" cy="9.167" r="4.583" stroke="currentColor" strokeWidth="1.5" />
          <path d="m12.5 12.5 3.333 3.333" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    case "download":
      return (
        <svg {...props}>
          <path d="M10 3.333v8.334m0 0 3.333-3.334M10 11.667 6.667 8.333M4.167 15.833h11.666" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "send":
      return (
        <svg {...props}>
          <path d="m16.667 3.333-7.5 13.334-1.667-5-5-1.667 13.334-7.5Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        </svg>
      );
    case "person":
      return (
        <svg {...props}>
          <path d="M10 10a3.333 3.333 0 1 0 0-6.667A3.333 3.333 0 0 0 10 10Zm-5 6.667c.689-2.153 2.809-3.75 5-3.75s4.311 1.597 5 3.75" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    case "external":
      return (
        <svg {...props}>
          <path d="M11.667 4.167h4.166v4.166M8.333 11.667l7.5-7.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          <path d="M15 10.833v3.334A.833.833 0 0 1 14.167 15H5.833A.833.833 0 0 1 5 14.167V5.833A.833.833 0 0 1 5.833 5H9.167" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "menu":
      return (
        <svg {...props}>
          <path d="M4.167 6.667h11.666M4.167 10h11.666M4.167 13.333h11.666" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    case "panel":
      return (
        <svg {...props}>
          <path d="M3.333 4.167h13.334v11.666H3.333z" stroke="currentColor" strokeWidth="1.5" />
          <path d="M12.5 4.167v11.666" stroke="currentColor" strokeWidth="1.5" />
        </svg>
      );
    case "close":
      return (
        <svg {...props}>
          <path d="m5 5 10 10M15 5 5 15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    case "chevron":
      return (
        <svg {...props}>
          <path d="m7.5 5 5 5-5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "spark":
    default:
      return (
        <svg {...props}>
          <path d="m10 2.5 1.817 4.85L16.667 9.167l-4.85 1.816L10 15.833l-1.817-4.85L3.333 9.167l4.85-1.817L10 2.5Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        </svg>
      );
  }
}
