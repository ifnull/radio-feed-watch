(() => {
  const state = {
    meta: null,
    transcripts: [],
    incidents: [],
    markers: new Map(),
    map: null,
    sourceFilter: "",
  };

  const el = {
    brand: document.getElementById("brand"),
    subtitle: document.getElementById("subtitle"),
    mode: document.getElementById("mode-badge"),
    status: document.getElementById("status-badge"),
    incidents: document.getElementById("incidents"),
    transcripts: document.getElementById("transcripts"),
    filterSource: document.getElementById("filter-source"),
  };

  function fmtTime(ts) {
    try {
      return new Date(ts).toLocaleTimeString();
    } catch {
      return ts || "";
    }
  }

  function tsMs(ts) {
    const n = Date.parse(ts);
    return Number.isFinite(n) ? n : 0;
  }

  function typeClass(t) {
    return `type type-${t || "unknown"}`;
  }

  function burstGapMs() {
    const s = state.meta?.transcript_burst_gap_s;
    return (typeof s === "number" && s >= 0 ? s : 3) * 1000;
  }

  /** Group newest-first transcripts into same-source time bursts. */
  function groupBursts(rows) {
    const gap = burstGapMs();
    const bursts = [];
    for (const t of rows) {
      const prev = bursts[bursts.length - 1];
      const sameSource = prev && prev.source_id === (t.source_id || "");
      // Compare to oldest line already in the burst (list is newest-first)
      const close =
        prev &&
        Math.abs(tsMs(prev.oldest_ts) - tsMs(t.ts)) <= gap;
      if (sameSource && close) {
        prev.items.push(t);
        prev.oldest_ts = t.ts;
      } else {
        bursts.push({
          source_id: t.source_id || "",
          source_label: t.source_label || t.source_id || "",
          newest_ts: t.ts,
          oldest_ts: t.ts,
          items: [t],
        });
      }
    }
    return bursts;
  }

  function lineTags(t) {
    const tags = [];
    if (t.raw?.phonetic_hits?.length) tags.push(`<span class="tail-tag">phonetic</span>`);
    if (t.raw?.radio_code_hits?.length) tags.push(`<span class="tail-tag">codes</span>`);
    return tags.join("");
  }

  function initMap(center) {
    const lat = center.lat ?? 30.27;
    const lon = center.lon ?? -97.74;
    const zoom = center.zoom ?? 11;
    state.map = L.map("map", { zoomControl: true }).setView([lat, lon], zoom);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      attribution: "&copy; OpenStreetMap &copy; CARTO",
      maxZoom: 19,
    }).addTo(state.map);
  }

  function upsertMarker(incident) {
    if (incident.lat == null || incident.lon == null || !state.map) return;
    const key = incident.event_id || incident.clip_id || `${incident.lat},${incident.lon},${incident.ts}`;
    const html = `<strong>${incident.incident_type || "unknown"}</strong><br/>${incident.address || ""}<br/><em>${incident.text || ""}</em>`;
    if (state.markers.has(key)) {
      state.markers.get(key).setLatLng([incident.lat, incident.lon]).setPopupContent(html);
      return;
    }
    const m = L.circleMarker([incident.lat, incident.lon], {
      radius: 7,
      color: "#3d9cf0",
      fillColor: "#3d9cf0",
      fillOpacity: 0.8,
      weight: 1,
    }).addTo(state.map).bindPopup(html);
    state.markers.set(key, m);
  }

  function renderIncidents() {
    const rows = state.incidents.filter((i) => !state.sourceFilter || i.source_id === state.sourceFilter);
    const ops = state.meta?.ops;
    const body = rows.slice(0, 100).map((i) => {
      const play = i.clip_id
        ? `<button class="btn" data-play="${i.clip_id}">play</button>`
        : "";
      const save = ops && i.clip_id
        ? `<button class="btn" data-save="${i.clip_id}">save</button>`
        : "";
      return `<tr>
        <td class="mono">${fmtTime(i.ts)}</td>
        <td>${i.source_label || i.source_id || ""}</td>
        <td><span class="${typeClass(i.incident_type)}">${i.incident_type || "unknown"}</span></td>
        <td>${i.address || "—"}</td>
        <td class="mono">${i.lat != null ? Number(i.lat).toFixed(4) : "—"}, ${i.lon != null ? Number(i.lon).toFixed(4) : "—"}</td>
        <td>${play} ${save}</td>
      </tr>`;
    }).join("");
    el.incidents.innerHTML = `<table>
      <thead><tr><th>Time</th><th>Source</th><th>Type</th><th>Address</th><th>Coords</th><th></th></tr></thead>
      <tbody>${body || `<tr><td colspan="6" class="muted">Waiting for incidents…</td></tr>`}</tbody>
    </table>`;
  }

  function renderTranscripts() {
    const rows = state.transcripts
      .filter((t) => !state.sourceFilter || t.source_id === state.sourceFilter)
      .slice(0, 150);
    const bursts = groupBursts(rows);
    const html = bursts
      .map((b) => {
        const multi = b.items.length > 1;
        const timeLabel =
          multi && b.oldest_ts !== b.newest_ts
            ? `${fmtTime(b.oldest_ts)} – ${fmtTime(b.newest_ts)}`
            : fmtTime(b.newest_ts);
        const count = multi ? `<span class="burst-count">${b.items.length}</span>` : "";
        // Show chronological order inside the burst (oldest → newest)
        const lines = [...b.items]
          .reverse()
          .map((t) => {
            const play = t.clip_id
              ? `<button class="btn" data-play="${t.clip_id}">play</button>`
              : "";
            const when = multi
              ? `<span class="line-time">${fmtTime(t.ts)}</span>`
              : "";
            return `<div class="burst-line">${when}${lineTags(t)}<span class="line-text">${t.text || ""}</span> ${play}</div>`;
          })
          .join("");
        return `<div class="burst${multi ? " burst-multi" : ""}">
          <div class="burst-head"><span class="tail-meta">${timeLabel} · ${b.source_id}</span>${count}</div>
          <div class="burst-body">${lines}</div>
        </div>`;
      })
      .join("");
    el.transcripts.innerHTML = html || `<div class="muted">Waiting for transcripts…</div>`;
  }

  function applySnapshot(snap) {
    state.transcripts = snap.transcripts || [];
    state.incidents = snap.incidents || [];
    state.incidents.forEach(upsertMarker);
    renderIncidents();
    renderTranscripts();
  }

  function onEvent(evt) {
    if (evt.kind === "snapshot") {
      applySnapshot(evt);
      return;
    }
    if (evt.kind === "transcript") {
      state.transcripts.unshift(evt);
      state.transcripts = state.transcripts.slice(0, 200);
      renderTranscripts();
    } else if (evt.kind === "incident") {
      state.incidents.unshift(evt);
      state.incidents = state.incidents.slice(0, 200);
      upsertMarker(evt);
      renderIncidents();
    }
  }

  async function loadMeta() {
    const res = await fetch("/api/meta");
    state.meta = await res.json();
    el.brand.textContent = state.meta.brand_name || "radio-feed-watch";
    el.subtitle.textContent = state.meta.demo_title || state.meta.locale?.label || "";
    el.mode.textContent = state.meta.mode || "ops";
    initMap(state.meta.map_center || {});
    const sources = (state.meta.sources || []).filter((s) => s.enabled);
    for (const s of sources) {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.textContent = s.label || s.id;
      el.filterSource.appendChild(opt);
    }
  }

  function connectSSE() {
    const es = new EventSource("/api/events");
    es.onopen = () => {
      el.status.textContent = "live";
      el.status.classList.add("badge-live");
    };
    es.onerror = () => {
      el.status.textContent = "reconnecting…";
      el.status.classList.remove("badge-live");
    };
    es.onmessage = (msg) => {
      try {
        onEvent(JSON.parse(msg.data));
      } catch (err) {
        console.warn(err);
      }
    };
  }

  document.body.addEventListener("click", async (e) => {
    const play = e.target.closest("[data-play]");
    if (play) {
      const id = play.getAttribute("data-play");
      const audio = new Audio(`/api/clips/${id}`);
      audio.play();
      return;
    }
    const save = e.target.closest("[data-save]");
    if (save) {
      const id = save.getAttribute("data-save");
      await fetch(`/api/clips/${id}/save`, { method: "POST" });
      save.textContent = "saved";
    }
  });

  el.filterSource.addEventListener("change", () => {
    state.sourceFilter = el.filterSource.value;
    renderIncidents();
    renderTranscripts();
  });

  loadMeta().then(connectSSE).catch((err) => {
    el.status.textContent = "error";
    console.error(err);
  });
})();
