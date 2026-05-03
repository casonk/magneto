(() => {
  const list = document.querySelector("[data-torrent-list]");
  if (!list) {
    return;
  }

  const refreshUrl = list.dataset.refreshUrl;
  const visibleInterval = Number(list.dataset.visibleInterval || 4000);
  const hiddenInterval = Number(list.dataset.hiddenInterval || 60000);
  let timer = 0;
  let inFlight = false;

  const schedule = () => {
    window.clearTimeout(timer);
    const interval = document.hidden ? hiddenInterval : visibleInterval;
    timer = window.setTimeout(refresh, interval);
  };

  const refresh = async () => {
    if (inFlight || !refreshUrl) {
      schedule();
      return;
    }

    inFlight = true;
    try {
      const response = await fetch(refreshUrl, {
        cache: "no-store",
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
      });
      if (!response.ok) {
        throw new Error(`refresh failed: ${response.status}`);
      }
      list.innerHTML = await response.text();
      list.classList.remove("is-stale");
    } catch (_error) {
      list.classList.add("is-stale");
    } finally {
      inFlight = false;
      schedule();
    }
  };

  document.addEventListener("visibilitychange", () => {
    window.clearTimeout(timer);
    if (document.hidden) {
      schedule();
    } else {
      refresh();
    }
  });

  window.addEventListener("pageshow", () => {
    if (!document.hidden) {
      refresh();
    }
  });

  schedule();
})();
