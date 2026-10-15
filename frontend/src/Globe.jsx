import React, { useEffect, useRef } from "react";
import MASK_B64 from "./globeMask.js";

/** Decorative dotted planet for the login screen: land-only dots from a land/sea mask, six lifted great-circle routes with
    travelling pulses, and a frosted pill on each city. It is purely illustrative (the routes carry no data), so it is
    aria-hidden and sits behind the form. Colours, speed and tilt come from the --g-* CSS variables in gate.css. */

const D2R = Math.PI / 180, TAU = Math.PI * 2;
const HUBS = {
  INR: { lat: 19.07, lon: 72.87 },   // Mumbai
  CNY: { lat: 31.23, lon: 121.47 },  // Shanghai
  EUR: { lat: 50.11, lon: 8.68 },    // Frankfurt
  USD: { lat: 40.71, lon: -74.0 },   // New York
};
const FLOWS = [["INR", "CNY"], ["INR", "USD"], ["INR", "EUR"], ["CNY", "USD"], ["CNY", "EUR"], ["EUR", "USD"]];

const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const smooth = (e0, e1, x) => { const t = clamp((x - e0) / (e1 - e0)); return t * t * (3 - 2 * t); };
const easeOut = (t) => 1 - Math.pow(1 - t, 3);
const easeInOut = (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);
const unit = (lat, lon) => {
  const la = lat * D2R, lo = lon * D2R;
  return [Math.cos(la) * Math.sin(lo), Math.sin(la), Math.cos(la) * Math.cos(lo)];
};

const Pin = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z" /><circle cx="12" cy="9.5" r="2.5" />
  </svg>
);

export default function Globe() {
  const root = useRef(null), canvas = useRef(null), par = useRef(null);

  useEffect(() => {
    const el = root.current, cv = canvas.current, pr = par.current;
    const ctx = cv.getContext("2d");
    const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const css = getComputedStyle(el);
    const num = (name, d) => { const v = parseFloat(css.getPropertyValue(name)); return Number.isFinite(v) ? v : d; };
    const rgb = (name) => {
      const h = css.getPropertyValue(name).trim().replace("#", "");
      const n = parseInt(h.length === 3 ? h.replace(/./g, "$&$&") : h, 16);
      return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    };
    const C = { dot: rgb("--g-dot"), arc: rgb("--g-arc"), pulse: rgb("--g-pulse"), bg: rgb("--g-bg") };
    const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
    const bodyFill = `rgb(${C.bg.map((v) => Math.round(v * 0.72)).join(",")})`;   // ocean: empty, a touch darker than the page

    const CFG = {
      turnSeconds: num("--g-turn", 75), tilt: num("--g-tilt", 22) * D2R, startLon: num("--g-start", 72.87),
      segments: 96, lift: 0.18, buckets: 8, dotRadius: [1.1, 1.6], labelGap: 14, labelFade: 0.4, parallax: 7,
    };

    /* land mask lookup (bilinear then threshold: smoother coasts than raw 1-degree cells) */
    const bytes = Uint8Array.from(atob(MASK_B64), (c) => c.charCodeAt(0));
    const cell = (r, c) => { r = clamp(r, 0, 179); c = ((c % 360) + 360) % 360; const n = r * 360 + c; return (bytes[n >> 3] >> (7 - (n & 7))) & 1; };
    const isLand = (lat, lon) => {
      const u = lon + 180 - 0.5, v = 90 - lat - 0.5, c0 = Math.floor(u), r0 = Math.floor(v), fu = u - c0, fv = v - r0;
      const top = cell(r0, c0) * (1 - fu) + cell(r0, c0 + 1) * fu, bot = cell(r0 + 1, c0) * (1 - fu) + cell(r0 + 1, c0 + 1) * fu;
      return top * (1 - fv) + bot * fv >= 0.5;
    };

    /* dots: evenly spaced rings, land only. Spacing is in screen px, so the grid is rebuilt when the size changes. */
    let DOT = new Float32Array(0), DN = 0, SX, SY, SB, builtFor = 0;
    const buildDots = (spacingPx, R) => {
      const step = spacingPx / R, rings = Math.round(Math.PI / step), out = [];
      for (let k = 0; k < rings; k++) {
        const lat = -90 + (k + 0.5) * (180 / rings);
        if (lat < -75) continue;                                  // with the tilt, nothing below about 68S ever faces the viewer
        const n = Math.max(1, Math.round(TAU * Math.cos(lat * D2R) / step));
        for (let j = 0; j < n; j++) {
          const lon = -180 + 360 * (j + 0.5 * (k & 1)) / n;
          if (isLand(lat, lon)) out.push(...unit(lat, lon));
        }
      }
      DOT = Float32Array.from(out); DN = DOT.length / 3;
      SX = new Float32Array(DN); SY = new Float32Array(DN); SB = new Int8Array(DN);
    };

    /* cities and routes: slerp between two cities, lifted by sin(PI t) * 0.18 * angular distance */
    const hubs = Object.entries(HUBS).map(([code, h]) => ({
      code, u: unit(h.lat, h.lon), el: el.querySelector(`.pill[data-code="${code}"]`), x: 0, y: 0, z: 0, face: 0, a: 0,
    }));
    const hub = Object.fromEntries(hubs.map((h) => [h.code, h]));
    const arcs = FLOWS.map(([a, b], i) => {
      const A = hub[a].u, B = hub[b].u;
      const ang = Math.acos(clamp(A[0] * B[0] + A[1] * B[1] + A[2] * B[2], -1, 1)), s = Math.sin(ang);
      const N = CFG.segments, pts = new Float32Array((N + 1) * 3);
      for (let k = 0; k <= N; k++) {
        const t = k / N, wa = Math.sin((1 - t) * ang) / s, wb = Math.sin(t * ang) / s;
        const h = 1 + Math.sin(Math.PI * t) * CFG.lift * ang;        // both ends sit exactly on the surface
        for (let q = 0; q < 3; q++) pts[k * 3 + q] = (A[q] * wa + B[q] * wb) * h;
      }
      return {
        from: hub[a], to: hub[b], pts, N, sx: new Float32Array(N + 1), sy: new Float32Array(N + 1), vis: new Float32Array(N + 1),
        period: 6.2 + (i % 3) * 0.9 + i * 0.17, offset: 2.6 + i * 0.9, travel: 0.4, drawDelay: 1.0 + i * 0.1,
      };
    });

    /* layout: a small, whole planet on the right of the screen (above the form on portrait screens).
       The CSS variables go on the .gate root so the login panel (left column) and the planet (right) share one layout. */
    const host = el.closest(".gate") || el;
    let W = 0, H = 0, dpr = 1, cx = 0, cy = 0, R = 0, spacing = 14;
    const layout = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = innerWidth; H = innerHeight;
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
      let px, py;                                                      // login panel centre: left column, or below the planet on portrait
      if (W / H >= 1) { R = Math.min(H * 0.4, W * 0.26); cx = clamp(W * 0.7, R + 24, W - R - 24); cy = H * 0.5; px = clamp(W * 0.26, 216, W - 216); py = H * 0.5; }
      else { R = Math.min(W * 0.36, H * 0.2); cx = W / 2; cy = H * 0.34; px = W / 2; py = Math.max(H * 0.74, 330); }
      host.style.setProperty("--cx", cx + "px"); host.style.setProperty("--cy", cy + "px"); host.style.setProperty("--R", R + "px");
      host.style.setProperty("--px", px + "px"); host.style.setProperty("--py", py + "px");
      spacing = clamp(R * 0.04, 10, 16);
      if (!builtFor || Math.abs(spacing - builtFor) > 0.4) { buildDots(spacing, R); builtFor = spacing; }
    };
    let rt = 0;
    const onResize = () => { clearTimeout(rt); rt = setTimeout(layout, 120); };
    addEventListener("resize", onResize);
    layout();

    const mouse = { tx: 0, ty: 0, x: 0, y: 0 };
    const onMove = (e) => { mouse.tx = (e.clientX / W - 0.5) * 2; mouse.ty = (e.clientY / H - 0.5) * 2; };
    if (!reduce) addEventListener("pointermove", onMove);

    const spin = (TAU / CFG.turnSeconds) * (reduce ? 0.12 : 1);      // west to east: the surface drifts left to right
    let rot = -CFG.startLon * D2R, last = performance.now(), raf = 0;
    const t0 = last, B = CFG.buckets, [rMin, rMax] = CFG.dotRadius;
    const dotFill = Array.from({ length: B }, (_, b) => rgba(C.dot, 0.14 + 0.82 * Math.pow((b + 0.5) / B, 0.8)));
    const ca = Math.cos(CFG.tilt), sa = Math.sin(CFG.tilt);

    const frame = (nowMs) => {
      const dt = Math.min(0.05, (nowMs - last) / 1000); last = nowMs;
      const now = (nowMs - t0) / 1000;
      if (innerWidth !== W || innerHeight !== H) layout();
      rot += spin * dt * (reduce ? 1 : easeOut(clamp(now / 2.5)));
      const k = 1 - Math.exp(-dt * 3);
      mouse.x += (mouse.tx - mouse.x) * k; mouse.y += (mouse.ty - mouse.y) * k;
      pr.style.transform = `translate3d(${(-mouse.x * CFG.parallax).toFixed(2)}px,${(-mouse.y * CFG.parallax * 0.6).toFixed(2)}px,0)`;
      const yaw = rot + mouse.x * 0.03, cr = Math.cos(yaw), sr = Math.sin(yaw);

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      ctx.fillStyle = bodyFill;                                       // ocean: empty
      ctx.beginPath(); ctx.arc(cx, cy, R, 0, TAU); ctx.fill();

      for (let i = 0; i < DN; i++) {                                  // land dots, batched by depth
        const x = DOT[i * 3], y = DOT[i * 3 + 1], z = DOT[i * 3 + 2];
        const xr = x * cr + z * sr, zr = z * cr - x * sr, zt = y * sa + zr * ca;
        if (zt <= 0) { SB[i] = -1; continue; }
        const px = cx + R * xr, py = cy - R * (y * ca - zr * sa);
        if (px < -6 || px > W + 6 || py < -6 || py > H + 6) { SB[i] = -1; continue; }
        SX[i] = px; SY[i] = py; SB[i] = Math.min(B - 1, (zt * B) | 0);
      }
      for (let b = 0; b < B; b++) {
        const r = rMin + (rMax - rMin) * (b + 0.5) / B;
        ctx.fillStyle = dotFill[b]; ctx.beginPath();
        for (let i = 0; i < DN; i++) { if (SB[i] === b) { ctx.moveTo(SX[i] + r, SY[i]); ctx.arc(SX[i], SY[i], r, 0, TAU); } }
        ctx.fill();
      }

      const labelsOn = reduce || now > 1.0;
      for (const h of hubs) {                                         // project each city every frame
        const x = h.u[0], y = h.u[1], z = h.u[2], xr = x * cr + z * sr, zr = z * cr - x * sr;
        h.x = cx + R * xr; h.y = cy - R * (y * ca - zr * sa); h.z = y * sa + zr * ca;
        h.face = smooth(-0.02, 0.18, h.z);
        const onScreen = h.x > -30 && h.x < W + 30 && h.y > -30 && h.y < H + 30;
        const target = labelsOn && h.z > 0.04 && onScreen ? 1 : 0;
        h.a += clamp(target - h.a, -dt / CFG.labelFade, dt / CFG.labelFade);
      }
      for (const a of arcs) {                                         // project route points; the globe hides what is behind its disc
        for (let j = 0; j <= a.N; j++) {
          const x = a.pts[j * 3], y = a.pts[j * 3 + 1], z = a.pts[j * 3 + 2];
          const xr = x * cr + z * sr, zr = z * cr - x * sr, yt = y * ca - zr * sa, zt = y * sa + zr * ca;
          a.sx[j] = cx + R * xr; a.sy[j] = cy - R * yt;
          a.vis[j] = zt >= 0 ? 1 : smooth(0.985, 1.0, Math.hypot(xr, yt));
        }
      }

      ctx.lineCap = "round"; ctx.lineWidth = 1;
      const heads = [];
      for (const a of arcs) {
        const fade = Math.min(a.from.face, a.to.face);                // a route fades only when one of its cities is on the back
        if (fade < 0.01) continue;
        const intro = reduce ? 1 : easeOut(clamp((now - a.drawDelay) / 0.9)), reach = intro * a.N;
        let head = -1;
        if (!reduce && intro >= 1 && now > a.offset) {
          const ph = (((now - a.offset) % a.period) + a.period) % a.period / a.period;
          if (ph < a.travel) head = easeInOut(ph / a.travel);
        }
        ctx.strokeStyle = rgba(C.arc, 1);
        for (let j = 0; j < reach && j < a.N; j++) {
          const v = Math.min(a.vis[j], a.vis[j + 1]) * fade;
          if (v < 0.01) continue;
          ctx.globalAlpha = 0.9 * v; ctx.beginPath(); ctx.moveTo(a.sx[j], a.sy[j]); ctx.lineTo(a.sx[j + 1], a.sy[j + 1]); ctx.stroke();
        }
        if (head >= 0) {
          const tail = 0.2;
          ctx.strokeStyle = rgba(C.pulse, 1);
          for (let j = 0; j < a.N; j++) {
            const d = head - (j + 0.5) / a.N;
            if (d < 0 || d > tail) continue;
            const v = Math.min(a.vis[j], a.vis[j + 1]) * fade;
            ctx.globalAlpha = 0.85 * v * Math.pow(1 - d / tail, 2);
            ctx.beginPath(); ctx.moveTo(a.sx[j], a.sy[j]); ctx.lineTo(a.sx[j + 1], a.sy[j + 1]); ctx.stroke();
          }
          const f = head * a.N, j = Math.min(a.N - 1, f | 0), u = f - j;
          heads.push({ x: a.sx[j] + (a.sx[j + 1] - a.sx[j]) * u, y: a.sy[j] + (a.sy[j + 1] - a.sy[j]) * u, v: (a.vis[j] + (a.vis[j + 1] - a.vis[j]) * u) * fade });
        }
      }
      ctx.fillStyle = rgba(C.pulse, 1);
      for (const h of heads) {                                        // pulse heads: soft halo and a small bright core
        ctx.globalAlpha = 0.10 * h.v; ctx.beginPath(); ctx.arc(h.x, h.y, 8, 0, TAU); ctx.fill();
        ctx.globalAlpha = 0.28 * h.v; ctx.beginPath(); ctx.arc(h.x, h.y, 3.6, 0, TAU); ctx.fill();
        ctx.globalAlpha = 0.95 * h.v; ctx.beginPath(); ctx.arc(h.x, h.y, 1.5, 0, TAU); ctx.fill();
      }
      for (const h of hubs) {                                         // marker dot, and its pill 14px directly above
        const on = h.a > 0.005;
        h.el.style.visibility = on ? "visible" : "hidden";
        if (!on) continue;
        h.el.style.opacity = h.a.toFixed(3);
        h.el.style.transform = `translate3d(${h.x.toFixed(1)}px,${(h.y - CFG.labelGap).toFixed(1)}px,0) translate(-50%,-100%)`;
        ctx.globalAlpha = 0.9 * h.a; ctx.beginPath(); ctx.arc(h.x, h.y, 2.2, 0, TAU); ctx.fill();
      }
      ctx.globalAlpha = 1;
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(raf); clearTimeout(rt);
      removeEventListener("resize", onResize); removeEventListener("pointermove", onMove);
    };
  }, []);

  return (
    <div className="globe" ref={root} aria-hidden="true">
      <div className="globe-wash" />
      <div className="globe-stage">
        <div className="globe-par" ref={par}>
          <canvas ref={canvas} />
          <div className="globe-atmo" />
          {Object.keys(HUBS).map((c) => <div key={c} className="pill" data-code={c}><Pin />{c}</div>)}
        </div>
      </div>
    </div>
  );
}
