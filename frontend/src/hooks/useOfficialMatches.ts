import {useCallback, useEffect, useRef, useState} from "react";
import {fetchOfficialMatches} from "../api/officialMatches";
import {apiGet} from "../api/system";
import type {OfficialMatch} from "../types";

export default function useOfficialMatches() {
  const [matches, setMatches] = useState<OfficialMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const requestRunning = useRef(false);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (requestRunning.current) return;
    requestRunning.current = true;
    try {
      setMatches(await fetchOfficialMatches(signal));
      setError("");
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      setError(e instanceof Error ? e.message : "官方比赛加载失败");
    } finally {
      requestRunning.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    let timer: number | undefined;
    let warmupTimer: number | undefined;
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") void load(controller.signal);
    };

    void load(controller.signal);
    // The backend starts the official-data agent immediately; re-read once after its first browser sync.
    warmupTimer = window.setTimeout(refreshWhenVisible, 10_000);
    apiGet<{refresh_seconds: number}>("/api/settings", controller.signal)
      .then(settings => {
        timer = window.setInterval(refreshWhenVisible, Math.max(30, settings.refresh_seconds || 60) * 1000);
      })
      .catch(() => { timer = window.setInterval(refreshWhenVisible, 60000); });
    document.addEventListener("visibilitychange", refreshWhenVisible);
    window.addEventListener("focus", refreshWhenVisible);

    return () => {
      controller.abort();
      if (timer) window.clearInterval(timer);
      if (warmupTimer) window.clearTimeout(warmupTimer);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
      window.removeEventListener("focus", refreshWhenVisible);
    };
  }, [load]);

  return {matches, loading, error, reload: load};
}
