import React from "react";

/** App background for the logged-in pages: an inverted horizon glow. The top of the screen is pure black; a violet-indigo glow
    rises from the bottom edge and curves up the lower corners, so the black core reads as a wide bowl. One fixed radial gradient
    (no images), plus a faint noise layer so the long dark ramp does not band. Decorative, behind the content, no pointer events. */
export function DarkPattern() {
  return (
    <div className="dp" aria-hidden="true">
      <div className="dp-noise" />
    </div>
  );
}
