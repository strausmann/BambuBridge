import darkLockup from "../../../docs/brand/logos/drehscheibe-dark-lockup.svg";
import darkMark from "../../../docs/brand/logos/drehscheibe-dark-mark.svg";
import lightLockup from "../../../docs/brand/logos/drehscheibe-light-lockup.svg";
import lightMark from "../../../docs/brand/logos/drehscheibe-light-mark.svg";

/**
 * The brand logo from `docs/brand/logos` (never redrawn or set in type here): the mark alone or
 * the lockup with the wordmark, each in its light and dark drawing. Both drawings are in the
 * page and the theme shows one (`.logo-light` / `.logo-dark` in index.css); the first carries
 * the name, the second is hidden from assistive technology.
 */
export function Logo({ variant = "lockup", className }: { variant?: "lockup" | "mark"; className?: string }) {
  const [light, dark, width, height] = variant === "lockup" ? [lightLockup, darkLockup, 407, 64] : [lightMark, darkMark, 64, 64];
  return (
    <span className={className} data-logo={variant}>
      <img src={light} alt="BambuBridge" width={width} height={height} className="logo-light h-full w-auto" />
      <img src={dark} alt="" aria-hidden="true" width={width} height={height} className="logo-dark h-full w-auto" />
    </span>
  );
}
