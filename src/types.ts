// TabXtract - GPL-3.0-or-later. See LICENSE.
export type AdvanceMode = "scroll_vertical" | "scroll_horizontal" | "paginated";

export interface RegionInfo {
  bbox: [number, number, number, number];
  confidence: number;
  instrument: string;
  n_lines: number;
  low_res_warning: boolean;
}

export interface SongInfo {
  index: number;
  start_frame: number;
  end_frame: number;
  title?: string;
}

export interface AnalysisResult {
  region: RegionInfo;
  advance_mode: AdvanceMode;
  frame_count: number;
  songs: SongInfo[];
  matched_profile: string | null;
}

export interface MeasureIssue {
  system_index: number;
  kind: "gap" | "backwards";
  from_measure: number;
  to_measure: number;
}

export interface SongReport {
  score: number;
  measure_continuity: string;
  measure_issues: MeasureIssue[];
  low_confidence_systems: number[];
  overlap_ok: boolean | null;
  cuts_on_ink: number[];
  discarded_ink_flag: "ok" | "warn" | "error";
  notes: string[];
}

export interface RenderedSong {
  index: number;
  title: string;
  pages: number;
  /** Absolute path on the user's disk: no download, the PDF is already there. */
  path: string;
  report: SongReport;
}

export interface RenderResult {
  songs: RenderedSong[];
  combined_path: string | null;
  output_dir: string;
}

export interface RegionOverride {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface Overrides {
  region?: RegionOverride;
  songs?: SongInfo[];
}

export type JobStatus =
  | "new"
  | "ready"
  | "downloading"
  | "queued"
  | "analyzing"
  | "analyzed"
  | "queued_render"
  | "rendering"
  | "rendered"
  | "cancelled"
  | "failed";

export interface Job {
  id: string;
  source: string;
  source_kind: "file" | "url";
  title: string;
  status: JobStatus;
  created_at: number;
  updated_at: number;
  error: string | null;
  analysis: AnalysisResult | null;
  render: RenderResult | null;
  overrides?: Overrides;
  output_dir: string | null;
  local_path: string | null;
}

export interface ProgressMessage {
  stage: string;
  pct: number;
  message: string;
  ts: number;
  kind?: string;
}

export interface Preferences {
  output_dir: string | null;
  updates_enabled: boolean;
  legal_notice_acknowledged: boolean;
  youtube_max_height: number;
}

export interface VideoFormat {
  format_id: string;
  height: number | null;
  fps: number | null;
  ext: string;
  filesize: number | null;
  note: string;
}

export interface VideoInfo {
  url: string;
  title: string;
  duration: number | null;
  uploader: string | null;
  thumbnail: string | null;
  formats: VideoFormat[];
}

export interface YtdlpStatus {
  available: boolean;
  version: string | null;
  path: string | null;
  updatable: boolean;
}

export interface LayoutProfile {
  name: string;
  video_width: number;
  video_height: number;
  region: [number, number, number, number];
  mode: string;
  created_at: number;
}
