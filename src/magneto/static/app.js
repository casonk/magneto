(() => {
  const hostSelect = document.querySelector("[data-torrent-host]");
  if (hostSelect) {
    hostSelect.addEventListener("change", () => {
      const target = hostSelect.value;
      if (target && target !== window.location.href) {
        window.location.assign(target);
      }
    });
  }

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

  // The list is replaced wholesale, which would discard a half-made choice or typed
  // number in a per-torrent control. Hold the refresh while one is focused or changed.
  const isEditing = () => {
    const active = document.activeElement;
    if (
      active &&
      list.contains(active) &&
      active.matches("input, select, textarea")
    ) {
      return true;
    }
    for (const control of list.querySelectorAll("input[name], select[name], textarea[name]")) {
      if (control.type === "hidden" || control.type === "submit") {
        continue;
      }
      if (control.tagName === "SELECT") {
        if (Array.from(control.options).some((o) => o.selected !== o.defaultSelected)) {
          return true;
        }
      } else if (control.type === "checkbox" || control.type === "radio") {
        if (control.checked !== control.defaultChecked) {
          return true;
        }
      } else if (control.value !== control.defaultValue) {
        return true;
      }
    }
    return false;
  };

  const refresh = async () => {
    if (inFlight || !refreshUrl) {
      schedule();
      return;
    }
    if (isEditing()) {
      list.classList.add("is-editing");
      schedule();
      return;
    }
    list.classList.remove("is-editing");

    inFlight = true;
    try {
      const response = await fetch(refreshUrl, {
        cache: "no-store",
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
      });
      list.innerHTML = await response.text();
      list.classList.toggle("is-stale", !response.ok);
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
