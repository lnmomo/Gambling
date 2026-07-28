from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

try:
    from websockets.sync.client import connect
except ModuleNotFoundError:
    connect = None

# Candidate Chromium-family browsers, checked in priority order. Edge and Chrome
# both speak the CDP protocol used by this client, so either is acceptable.
BROWSER_CANDIDATES: tuple[str, ...] = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)


def _resolve_browser_path(explicit: str | None) -> Path:
    """Return the first existing Chromium-family browser, or raise a helpful error.

    Priority: explicit OFFICIAL_BROWSER_PATH > well-known Edge/Chrome install
    locations > msedge/chrome found on PATH. Raises a RuntimeError listing the
    attempted candidates so the operator knows exactly what to fix.
    """
    if explicit and explicit.strip():
        candidate = Path(explicit.strip())
        if candidate.exists():
            return candidate
        raise _browser_not_found_error([f"OFFICIAL_BROWSER_PATH={explicit}"] + list(BROWSER_CANDIDATES))

    tried: list[str] = list(BROWSER_CANDIDATES)
    for candidate in BROWSER_CANDIDATES:
        path = Path(candidate)
        if path.exists():
            return path
    for name in ("msedge", "chrome"):
        located = shutil.which(name)
        if located:
            return Path(located)
        tried.append(f"PATH:{name}")
    raise _browser_not_found_error(tried)


def _browser_not_found_error(tried: list[str]) -> RuntimeError:
    listing = "\n".join(f"  - {item}" for item in tried)
    return RuntimeError(
        "No Chromium-family browser (Edge/Chrome) found for the official data sync. "
        "Install Microsoft Edge or Google Chrome, or set OFFICIAL_BROWSER_PATH to an "
        f"existing executable. Tried:\n{listing}"
    )

EXTRACT_EXPRESSION = r"""
JSON.stringify({html: document.querySelector('.m-main')?.innerHTML || '', matches:
Array.from(document.querySelectorAll('.m-cardList')).map(el => {
  const root=el.querySelector('.m-cardListBat'), left=root?.querySelector('.m-cardListBat-lf');
  const center=root?.querySelector('.m-cardListBat-cen');
  const heading=el.closest('.m-card')?.querySelector('.m-cardTime')?.innerText || '';
  const dateParts=left ? Array.from(left.querySelectorAll('.u-match-date')).map(x=>x.textContent.trim()) : [];
  const year=(heading.match(/(\d{4})-/)||[])[1] || '';
  const oddsText=center?.querySelector('.btm')?.innerText || '', odds={};
  const h=oddsText.match(/胜\s*([0-9.]+)/), d=oddsText.match(/平\s*([0-9.]+)/), a=oddsText.match(/负\s*([0-9.]+)/);
  const scoreText=center?.innerText || '', score=scoreText.match(/(?:^|\s)(\d{1,2})\s*[:：]\s*(\d{1,2})(?:\s|$)/);
  if(h) odds.home=Number(h[1]); if(d) odds.draw=Number(d[1]); if(a) odds.away=Number(a[1]);
  return {source_match_id:(el.id||'').replace(/^#/,''),match_no:center?.querySelector('.top')?.textContent?.trim()||'',
    league:left?.querySelector('p')?.textContent?.trim()||'',match_date:(year && dateParts[0] ? year+'-'+dateParts[0] : (heading.match(/\d{4}-\d{2}-\d{2}/)||[''])[0]),
    match_time:dateParts[1]||'',home_team:center?.querySelector('.mid-ballLf span')?.textContent?.trim()||'',
    away_team:center?.querySelector('.mid-ballRt span')?.textContent?.trim()||'',sale_status:root?.querySelector('.m-cardListBat-rt')?.innerText?.trim()||'',
    home_score:score?Number(score[1]):null,away_score:score?Number(score[2]):null,odds};
})})
"""


def _restricted_access_error(page_text: str, request_id: str | None = None) -> RuntimeError | None:
    """Turn an upstream WAF page into an actionable sync failure.

    The public Sporttery page may return an EdgeOne 567 document instead of
    the schedule.  Treating that as an empty fixture list hides the real
    source state and leaves the dashboard showing stale data without context.
    """
    # The Chinese EdgeOne page's visible text contains just the 567 code and
    # request ID; its English wording lives in an inline translation script.
    is_restricted = (
        "Restricted Access" in page_text
        or "Access Restricted" in page_text
        or ("567" in page_text and bool(request_id))
    )
    if not is_restricted:
        return None
    suffix = f" (request ID: {request_id})" if request_id else ""
    return RuntimeError(f"Official source access restricted by upstream WAF (HTTP 567){suffix}")

class CdpConnection:
    def __init__(self, url: str) -> None:
        if connect is None:
            raise RuntimeError("websockets package is required for official browser sync")
        self.websocket=connect(url,open_timeout=5); self.sequence=0
    def command(self, method: str, params: dict[str,Any]|None=None, session_id: str|None=None) -> dict[str,Any]:
        self.sequence+=1; mid=self.sequence; message={"id":mid,"method":method,"params":params or {}}
        if session_id: message["sessionId"]=session_id
        self.websocket.send(json.dumps(message))
        while True:
            response=json.loads(self.websocket.recv(timeout=20))
            if response.get("id")==mid:
                if "error" in response: raise RuntimeError(response["error"])
                return response.get("result",{})
    def close(self) -> None: self.websocket.close()

class SportteryBrowserClient:
    """Render the public page in a normal off-screen Edge window, without bypassing access controls."""
    def __init__(self,browser_path:str,timeout_seconds:int=25)->None:
        self.browser_path=_resolve_browser_path(browser_path); self.timeout_seconds=timeout_seconds
    def fetch(self,url:str)->dict[str,Any]:
        if not self.browser_path.exists(): raise _browser_not_found_error([str(self.browser_path)] + list(BROWSER_CANDIDATES))
        profile=tempfile.mkdtemp(prefix="sporttery-browser-")
        process=subprocess.Popen([str(self.browser_path),"--no-first-run","--disable-extensions","--window-position=-32000,-32000","--window-size=800,600",f"--user-data-dir={profile}","--remote-debugging-port=0","about:blank"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        connection=None
        try:
            port_file=Path(profile)/"DevToolsActivePort"; deadline=time.monotonic()+10
            while not port_file.exists() and time.monotonic()<deadline: time.sleep(.1)
            if not port_file.exists(): raise TimeoutError("Browser debugging endpoint did not start")
            port,path=port_file.read_text(encoding="utf-8").splitlines()[:2]
            connection=CdpConnection(f"ws://127.0.0.1:{port}{path}")
            target=connection.command("Target.createTarget",{"url":"about:blank"})["targetId"]
            session=connection.command("Target.attachToTarget",{"targetId":target,"flatten":True})["sessionId"]
            connection.command("Page.enable",session_id=session); connection.command("Runtime.enable",session_id=session)
            connection.command("Page.navigate",{"url":url},session)
            deadline=time.monotonic()+self.timeout_seconds; count=0
            while time.monotonic()<deadline:
                time.sleep(.5)
                result=connection.command("Runtime.evaluate",{"expression":"document.querySelectorAll('.m-cardList').length","returnByValue":True},session)
                count=result["result"].get("value",0)
                if count:
                    # Vue renders cards incrementally. Allow the list to settle before extraction.
                    time.sleep(2)
                    result=connection.command("Runtime.evaluate",{"expression":"document.querySelectorAll('.m-cardList').length","returnByValue":True},session)
                    count=result["result"].get("value",count)
                    break
            if not count:
                diagnostic = connection.command("Runtime.evaluate", {"expression": (
                    "JSON.stringify({text:document.body.innerText||'',"
                    "requestId:document.querySelector('#requestId')?.textContent||''})"
                ), "returnByValue": True}, session)
                details = json.loads(diagnostic["result"].get("value") or "{}")
                restricted = _restricted_access_error(
                    str(details.get("text") or ""), str(details.get("requestId") or "") or None,
                )
                if restricted:
                    raise restricted
                raise RuntimeError("Official page returned no match cards")
            result=connection.command("Runtime.evaluate",{"expression":EXTRACT_EXPRESSION,"returnByValue":True},session)
            return json.loads(result["result"]["value"])
        finally:
            if connection: connection.close()
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill()
            time.sleep(.2); shutil.rmtree(profile,ignore_errors=True)

    def fetch_results(self, url: str, date_windows: list[tuple[str, str]]) -> dict[str, Any]:
        """Read the public result API from the official page's browser context.

        Direct scripted HTTP requests are rejected by the upstream WAF. The
        public page itself calls this API, so we use the same normal browser
        context and do not attempt to bypass the site's access controls.
        """
        if not self.browser_path.exists():
            raise _browser_not_found_error([str(self.browser_path)] + list(BROWSER_CANDIDATES))
        if not date_windows:
            return {"results": [], "windows": []}
        profile = tempfile.mkdtemp(prefix="sporttery-results-browser-")
        process = subprocess.Popen([
            str(self.browser_path), "--no-first-run", "--disable-extensions",
            "--window-position=-32000,-32000", "--window-size=800,600",
            f"--user-data-dir={profile}", "--remote-debugging-port=0", "about:blank",
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        connection = None
        try:
            port_file = Path(profile) / "DevToolsActivePort"
            deadline = time.monotonic() + 10
            while not port_file.exists() and time.monotonic() < deadline:
                time.sleep(.1)
            if not port_file.exists():
                raise TimeoutError("Browser debugging endpoint did not start")
            port, path = port_file.read_text(encoding="utf-8").splitlines()[:2]
            connection = CdpConnection(f"ws://127.0.0.1:{port}{path}")
            target = connection.command("Target.createTarget", {"url": "about:blank"})["targetId"]
            session = connection.command(
                "Target.attachToTarget", {"targetId": target, "flatten": True}
            )["sessionId"]
            connection.command("Page.enable", session_id=session)
            connection.command("Runtime.enable", session_id=session)
            connection.command("Page.navigate", {"url": url}, session)
            deadline = time.monotonic() + self.timeout_seconds
            ready = False
            while time.monotonic() < deadline:
                time.sleep(.25)
                state = connection.command("Runtime.evaluate", {
                    "expression": "document.readyState", "returnByValue": True,
                }, session)
                ready = state["result"].get("value") in {"interactive", "complete"}
                if ready:
                    break
            if not ready:
                raise TimeoutError("Official results page did not finish loading")

            expression = f"""
(async () => {{
  const windows = {json.dumps(date_windows)};
  const output = [];
  const metadata = [];
  for (const [startDate, endDate] of windows) {{
    let pageNo = 1;
    let pages = 1;
    do {{
      const params = new URLSearchParams({{
        matchBeginDate: startDate, matchEndDate: endDate, leagueId: '',
        pageSize: '100', pageNo: String(pageNo), isFix: '0', matchPage: '1', pcOrWap: '1'
      }});
      const endpoint = 'https://webapi.sporttery.cn/gateway/uniform/football/' +
        'getUniformMatchResultV1.qry?' + params.toString();
      const response = await fetch(endpoint);
      if (!response.ok) throw new Error('official result API HTTP ' + response.status);
      const body = await response.json();
      if (String(body.errorCode) !== '0') {{
        throw new Error('official result API error ' + body.errorCode + ': ' + body.errorMessage);
      }}
      const value = body.value || {{}};
      const rows = Array.isArray(value.matchResult) ? value.matchResult : [];
      output.push(...rows);
      pages = Math.max(1, Number(value.pages || 1));
      metadata.push({{startDate, endDate, pageNo, pages, rows: rows.length,
        lastUpdateTime: value.lastUpdateTime || null}});
      pageNo += 1;
    }} while (pageNo <= pages);
  }}
  return JSON.stringify({{results: output, windows: metadata}});
}})()
"""
            result = connection.command("Runtime.evaluate", {
                "expression": expression, "returnByValue": True, "awaitPromise": True,
            }, session)
            exception = result.get("exceptionDetails")
            if exception:
                raise RuntimeError(exception.get("text") or "Official result API evaluation failed")
            value = result["result"].get("value")
            if not isinstance(value, str):
                raise RuntimeError("Official result API returned no structured payload")
            return json.loads(value)
        finally:
            if connection:
                connection.close()
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            time.sleep(.2)
            shutil.rmtree(profile, ignore_errors=True)
