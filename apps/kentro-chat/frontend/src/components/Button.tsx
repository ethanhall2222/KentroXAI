import type { ButtonHTMLAttributes, PropsWithChildren } from "react";
import { cn } from "../lib/utils";

type Variant = "primary" | "ghost" | "subtle";

type ButtonProps = PropsWithChildren<
  ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: Variant;
    fullWidth?: boolean;
  }
>;

const variants: Record<Variant, string> = {
  primary:
    "bg-kentro-600 text-white hover:bg-kentro-700 focus-visible:ring-kentro-300 shadow-sm",
  ghost:
    "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 focus-visible:ring-slate-300",
  subtle:
    "border border-transparent bg-slate-100/80 text-slate-700 hover:bg-slate-200/80 focus-visible:ring-slate-300",
};

export function Button({ children, className, variant = "ghost", fullWidth = false, ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-2xl px-4 py-2.5 text-sm font-medium transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant],
        fullWidth && "w-full",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}
