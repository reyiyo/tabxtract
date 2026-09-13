import { useCallback, useEffect, useRef, useState } from "react";
import type { RegionOverride } from "../types";

interface Props {
  imageUrl: string;
  initialRegion: RegionOverride;
  onChange: (region: RegionOverride) => void;
}

type DragMode = "move" | "nw" | "ne" | "sw" | "se" | null;

const HANDLE_SIZE = 10;
const DISPLAY_WIDTH = 900;

export function RegionEditor({ imageUrl, initialRegion, onChange }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [scale, setScale] = useState(1);
  const [region, setRegion] = useState<RegionOverride>(initialRegion);
  const dragRef = useRef<{ mode: DragMode; startX: number; startY: number; start: RegionOverride } | null>(null);

  // The prop is mirrored into state during render instead of from an effect:
  // an effect would commit one render with the previous region still drawn.
  // This is the documented way to reset state when a prop changes.
  const [syncedRegion, setSyncedRegion] = useState(initialRegion);
  if (initialRegion !== syncedRegion) {
    setSyncedRegion(initialRegion);
    setRegion(initialRegion);
  }

  useEffect(() => {
    const img = new Image();
    img.crossOrigin = "anonymous";
    img.onload = () => {
      imgRef.current = img;
      setScale(DISPLAY_WIDTH / img.naturalWidth);
    };
    img.src = imageUrl;
  }, [imageUrl]);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img || !scale) return;
    canvas.width = img.naturalWidth * scale;
    canvas.height = img.naturalHeight * scale;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

    const x0 = region.x0 * scale, y0 = region.y0 * scale;
    const x1 = region.x1 * scale, y1 = region.y1 * scale;

    ctx.fillStyle = "rgba(0,0,0,0.35)";
    ctx.fillRect(0, 0, canvas.width, y0);
    ctx.fillRect(0, y1, canvas.width, canvas.height - y1);
    ctx.fillRect(0, y0, x0, y1 - y0);
    ctx.fillRect(x1, y0, canvas.width - x1, y1 - y0);

    ctx.strokeStyle = "#22c55e";
    ctx.lineWidth = 2;
    ctx.strokeRect(x0, y0, x1 - x0, y1 - y0);

    ctx.fillStyle = "#22c55e";
    for (const [hx, hy] of [[x0, y0], [x1, y0], [x0, y1], [x1, y1]]) {
      ctx.fillRect(hx - HANDLE_SIZE / 2, hy - HANDLE_SIZE / 2, HANDLE_SIZE, HANDLE_SIZE);
    }
  }, [region, scale]);

  // Declared after `draw` on purpose: reading it before its declaration is
  // what the react-hooks immutability rule flags.
  useEffect(() => {
    draw();
  }, [draw]);

  function hitTest(px: number, py: number): DragMode {
    const x0 = region.x0 * scale, y0 = region.y0 * scale;
    const x1 = region.x1 * scale, y1 = region.y1 * scale;
    const near = (ax: number, ay: number) => Math.abs(px - ax) < HANDLE_SIZE && Math.abs(py - ay) < HANDLE_SIZE;
    if (near(x0, y0)) return "nw";
    if (near(x1, y0)) return "ne";
    if (near(x0, y1)) return "sw";
    if (near(x1, y1)) return "se";
    if (px > x0 && px < x1 && py > y0 && py < y1) return "move";
    return null;
  }

  // The canvas can end up smaller on screen than its backing store
  // (maxWidth:100% shrinks it in narrow windows): without this correction,
  // clicks are read in the wrong coordinate system and the hit test on the
  // handles fails silently.
  function toCanvasCoords(e: React.MouseEvent<HTMLCanvasElement>): [number, number] {
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    const cssScale = canvas.width / rect.width;
    return [(e.clientX - rect.left) * cssScale, (e.clientY - rect.top) * cssScale];
  }

  function handleMouseDown(e: React.MouseEvent<HTMLCanvasElement>) {
    const [px, py] = toCanvasCoords(e);
    const mode = hitTest(px, py);
    if (!mode) return;
    dragRef.current = { mode, startX: px, startY: py, start: { ...region } };
  }

  function handleMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    const drag = dragRef.current;
    if (!drag) return;
    const [px, py] = toCanvasCoords(e);
    const dx = (px - drag.startX) / scale;
    const dy = (py - drag.startY) / scale;
    const s = drag.start;
    let next: RegionOverride = { ...s };

    if (drag.mode === "move") {
      next = { x0: s.x0 + dx, y0: s.y0 + dy, x1: s.x1 + dx, y1: s.y1 + dy };
    } else if (drag.mode === "nw") {
      next = { ...s, x0: s.x0 + dx, y0: s.y0 + dy };
    } else if (drag.mode === "ne") {
      next = { ...s, x1: s.x1 + dx, y0: s.y0 + dy };
    } else if (drag.mode === "sw") {
      next = { ...s, x0: s.x0 + dx, y1: s.y1 + dy };
    } else if (drag.mode === "se") {
      next = { ...s, x1: s.x1 + dx, y1: s.y1 + dy };
    }
    setRegion(normalize(next));
  }

  function handleMouseUp() {
    if (dragRef.current) onChange(region);
    dragRef.current = null;
  }

  return (
    <canvas
      ref={canvasRef}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
      style={{ cursor: "crosshair", maxWidth: "100%", border: "1px solid #333" }}
    />
  );
}

function normalize(r: RegionOverride): RegionOverride {
  return {
    x0: Math.round(Math.min(r.x0, r.x1)),
    y0: Math.round(Math.min(r.y0, r.y1)),
    x1: Math.round(Math.max(r.x0, r.x1)),
    y1: Math.round(Math.max(r.y0, r.y1)),
  };
}
