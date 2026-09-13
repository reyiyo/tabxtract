// TabXtract - GPL-3.0-or-later. See LICENSE.
//
// Client of the local backend. Every request carries the handshake token:
// without it, any page open in the user's browser could send jobs to this
// process.
import { authHeaders, backendUrl, withToken } from "./backend";
import type {
  Job,
  LayoutProfile,
  Overrides,
  Preferences,
  RegionOverride,
  RenderResult,
  SongInfo,
  VideoInfo,
  YtdlpStatus,
} from "./types";

/** A backend error already translated: yt-dlp's carry a cause and a hint. */
export class ApiError extends Error {
  kind: string;
  hint: string;

  constructor(message: string, kind = "error", hint = "") {
    super(message);
    this.name = "ApiError";
    this.kind = kind;
    this.hint = hint;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(backendUrl(path), { ...init, headers: authHeaders() });
  if (!res.ok) {
    const body = await res.text();
    try {
      const parsed = JSON.parse(body);
      const detail = parsed.detail ?? parsed;
      if (detail && typeof detail === "object") {
        throw new ApiError(detail.message ?? JSON.stringify(detail), detail.kind, detail.hint);
      }
      throw new ApiError(String(detail));
    } catch (err) {
      if (err instanceof ApiError) throw err;
      throw new ApiError(body || `error ${res.status}`);
    }
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

// ------------------------------------------------------------------ jobs

export const listJobs = () => request<Job[]>("/api/jobs");

export const getJob = (jobId: string) => request<Job>(`/api/jobs/${jobId}`);

/** A file already on disk: the path is sent, not the contents. */
export const createLocalJob = (path: string) => post<Job>("/api/jobs", { path });

export const deleteJob = (jobId: string) =>
  request<{ deleted: string }>(`/api/jobs/${jobId}`, { method: "DELETE" });

export const startAnalyze = (jobId: string) => post<Job>(`/api/jobs/${jobId}/analyze`);

export const cancelJob = (jobId: string) => post<{ cancelling: string }>(`/api/jobs/${jobId}/cancel`);

export const patchRegion = (jobId: string, overrides: Overrides) =>
  request<unknown>(`/api/jobs/${jobId}/region`, {
    method: "PATCH",
    body: JSON.stringify(overrides),
  });

export const startRender = (
  jobId: string,
  body: {
    region?: RegionOverride;
    songs?: SongInfo[];
    save_profile_name?: string | null;
    output_dir?: string | null;
  },
) => post<Job>(`/api/jobs/${jobId}/render`, body);

export const getReport = (jobId: string) => request<RenderResult>(`/api/jobs/${jobId}/report`);

/** <img> cannot send headers, so this one carries the token in the query. */
export const frameUrl = (jobId: string, index = 0) =>
  withToken(`/api/jobs/${jobId}/frame?index=${index}`);

export function progressSocketUrl(jobId: string): string {
  return withToken(`/api/jobs/${jobId}/progress`).replace(/^http/, "ws");
}

// ---------------------------------------------------------------- YouTube

export const probeVideo = (url: string) => post<VideoInfo>("/api/youtube/probe", { url });

export const createUrlJob = (url: string, formatId: string | null) =>
  post<Job>("/api/youtube/jobs", { url, format_id: formatId });

export const ytdlpStatus = () => request<YtdlpStatus>("/api/ytdlp");

export const updateYtdlp = () => post<YtdlpStatus & { method: string }>("/api/ytdlp/update");

// ----------------------------------------------------------- preferences

export const getPreferences = () => request<Preferences>("/api/preferences");

export const savePreferences = (patch: Partial<Preferences>) =>
  request<Preferences>("/api/preferences", { method: "PUT", body: JSON.stringify(patch) });

// --------------------------------------------------------------- profiles

export const listProfiles = () => request<LayoutProfile[]>("/api/profiles");

export const importProfiles = (profiles: LayoutProfile[]) =>
  post<{ imported: string[]; total: number }>("/api/profiles/import", { profiles });

export interface Health {
  ok: boolean;
  version: string;
  data_dir: string;
  log_path: string;
  missing_binaries: string[];
}

export const health = () => request<Health>("/api/health");
