/**
 * Blackjack Pilot - In-Browser Content Script
 * 1. Maintains always-visible 3-zone overlays (Feed, Dealer, Player) on the webpage.
 * 2. In-page Options Panel that never disappears when clicking outside.
 * 3. Bridges frame streaming to local Python AI engine via background service worker.
 */

(() => {
  if (window.__bjp_active) return;
  window.__bjp_active = true;

  const BUILD_VERSION = "v1.4.4";
  const BUILD_DATE = "2026-10-08";
  const BUILD_TIMESTAMP = "2026-10-08 (Feed Area Restored, Spatial Card Counter & Cards Readout)";
  console.log(
    `%c[Blackjack Pilot] Loaded ${BUILD_VERSION} (${BUILD_TIMESTAMP})`,
    "color: #58a6ff; font-weight: bold; font-size: 13px;"
  );

  // Background port bridge
  let bgPort = null;
  let serverConnected = false;

  // Capture State & Flow Control
  let isCapturing = false;
  let captureStream = null;
  let captureVideo = null;
  let captureCanvas = null;
  let captureTimer = null;
  let isFrameInFlight = false;
  let lastFrameSentAt = 0;
  let lastResultReceivedAt = 0;

  // Calibrated Regions (Viewport coordinates)
  let feedRect = null; // { x, y, width, height, pageX, pageY }
  let feedTargetEl = null;
  let feedTargetOffset = null; // { relX, relY, width, height }

  // Relative coordinates sent to Python engine (normalized 0.0 to 1.0)
  let dealerZoneRel = null; // [dx1, dy1, dx2, dy2]
  let playerZoneRel = null; // [px1, py1, px2, py2]

  // Settings
  let showHud = true;
  let showZones = true;
  let drawBoxes = true; // Minimalist corner reticles on cards (0 text)
  let confThresh = 0.35;
  let iouThresh = 0.50;
  let decksCount = 6;

  // DOM elements & Root Container
  let bjpRootEl = null;
  let hudEl = null;
  let zoneOverlaysEl = null;
  let feedBoxEl = null;
  let dealerBoxEl = null;
  let playerBoxEl = null;
  let bboxCanvasEl = null;
  let rafTrackingId = null;

  function getBjpRoot() {
    if (!bjpRootEl || !document.contains(bjpRootEl)) {
      bjpRootEl = document.getElementById("bjp-root-container");
      if (!bjpRootEl) {
        bjpRootEl = document.createElement("div");
        bjpRootEl.id = "bjp-root-container";
      }
      const mount = document.body || document.documentElement;
      if (mount && !document.contains(bjpRootEl)) {
        mount.appendChild(bjpRootEl);
      }
    }
    return bjpRootEl;
  }

  // ---------------------------------------------------------------------------
  // 1. Background Port Bridge (Bypasses HTTPS Mixed-Content Restrictions)
  // ---------------------------------------------------------------------------
  function connectPort() {
    try {
      bgPort = chrome.runtime.connect({ name: "bjp-channel" });

      bgPort.onMessage.addListener((msg) => {
        if (!msg) return;

        if (msg.type === "server_status") {
          serverConnected = !!msg.connected;
          updateServerIndicator(serverConnected);
          if (serverConnected && (dealerZoneRel || playerZoneRel)) {
            syncZonesToServer();
          }
        } else if (msg.type === "server_result" && msg.payload) {
          isFrameInFlight = false;
          lastResultReceivedAt = Date.now();
          updateHudWithResult(msg.payload);
          if (drawBoxes) {
            renderBoundingBoxes(msg.payload.detections);
          }
        }
      });

      bgPort.onDisconnect.addListener(() => {
        isFrameInFlight = false;
        serverConnected = false;
        updateServerIndicator(false);
        clearBoundingBoxes();
        bgPort = null;
        setTimeout(connectPort, 2000);
      });
    } catch (e) {
      isFrameInFlight = false;
      serverConnected = false;
      updateServerIndicator(false);
      clearBoundingBoxes();
      setTimeout(connectPort, 2500);
    }
  }

  function sendCommand(action, payload = {}) {
    if (bgPort) {
      bgPort.postMessage({
        type: "command",
        payload: { action, ...payload },
      });
    }
  }

  function syncZonesToServer() {
    sendCommand("set_zones", {
      dealer_zone: dealerZoneRel,
      player_zone: playerZoneRel,
    });
  }

  function saveStoredCalibration() {
    try {
      chrome.storage.local.set({
        bjp_feed_rect: feedRect,
        bjp_dealer_zone: dealerZoneRel,
        bjp_player_zone: playerZoneRel,
      });
    } catch (e) {}
  }

  function clearStoredCalibration() {
    try {
      chrome.storage.local.remove([
        "bjp_feed_rect",
        "bjp_dealer_zone",
        "bjp_player_zone",
      ]);
    } catch (e) {}
  }

  function loadStoredCalibration() {
    try {
      chrome.storage.local.get(
        ["bjp_feed_rect", "bjp_dealer_zone", "bjp_player_zone"],
        (data) => {
          if (data && data.bjp_feed_rect) {
            feedRect = data.bjp_feed_rect;
            if (data.bjp_dealer_zone) dealerZoneRel = data.bjp_dealer_zone;
            if (data.bjp_player_zone) playerZoneRel = data.bjp_player_zone;
            applyOverlayPositions();
            if (serverConnected && (dealerZoneRel || playerZoneRel)) {
              syncZonesToServer();
            }
          }
        }
      );
    } catch (e) {}
  }

  // ---------------------------------------------------------------------------
  // 2. Real-Time Viewport Synchronized Overlays & Target Tracking
  // ---------------------------------------------------------------------------
  function getFeedViewportRect() {
    if (!feedRect) return null;

    if (feedTargetEl && document.contains(feedTargetEl)) {
      const r = feedTargetEl.getBoundingClientRect();
      return {
        x: Math.round(r.left + feedTargetOffset.relX),
        y: Math.round(r.top + feedTargetOffset.relY),
        width: feedTargetOffset.width,
        height: feedTargetOffset.height,
      };
    }

    // Casino tables (Evolution Gaming, Pragmatic Play, etc.) are fixed viewport players.
    // Coordinates stay pinned to the screen so mousewheel scroll on background page never breaks alignment.
    return {
      x: feedRect.x,
      y: feedRect.y,
      width: feedRect.width,
      height: feedRect.height,
    };
  }

  function initZoneOverlays() {
    if (document.getElementById("bjp-zone-overlays")) return;

    zoneOverlaysEl = document.createElement("div");
    zoneOverlaysEl.id = "bjp-zone-overlays";

    function makeCornerBox(className) {
      const box = document.createElement("div");
      box.className = `bjp-zone-box ${className}`;
      box.style.display = "none";
      box.innerHTML = `
        <span class="bjp-corner bjp-c-tl"></span>
        <span class="bjp-corner bjp-c-tr"></span>
        <span class="bjp-corner bjp-c-br"></span>
        <span class="bjp-corner bjp-c-bl"></span>
      `;
      return box;
    }

    feedBoxEl = document.createElement("div");
    feedBoxEl.className = "bjp-zone-box bjp-zone-feed";
    feedBoxEl.id = "bjp-zone-feed";
    feedBoxEl.style.display = "none";
    feedBoxEl.innerHTML = `<div class="bjp-zone-tag" id="bjp-tag-feed">🎥 1. VIDEO FEED</div>`;
    zoneOverlaysEl.appendChild(feedBoxEl);

    dealerBoxEl = makeCornerBox("bjp-zone-dealer");
    zoneOverlaysEl.appendChild(dealerBoxEl);

    playerBoxEl = makeCornerBox("bjp-zone-player");
    zoneOverlaysEl.appendChild(playerBoxEl);

    getBjpRoot().appendChild(zoneOverlaysEl);
  }

  function applyOverlayPositions() {
    if (!zoneOverlaysEl) initZoneOverlays();

    const rect = getFeedViewportRect();
    if (!rect) {
      if (feedBoxEl) feedBoxEl.style.display = "none";
      if (dealerBoxEl) dealerBoxEl.style.display = "none";
      if (playerBoxEl) playerBoxEl.style.display = "none";
      if (bboxCanvasEl) bboxCanvasEl.style.display = "none";
      return;
    }

    if (!showZones) {
      if (feedBoxEl) feedBoxEl.style.display = "none";
      if (dealerBoxEl) dealerBoxEl.style.display = "none";
      if (playerBoxEl) playerBoxEl.style.display = "none";
    } else {
      if (feedBoxEl) {
        feedBoxEl.style.display = "block";
        feedBoxEl.style.left = `${rect.x}px`;
        feedBoxEl.style.top = `${rect.y}px`;
        feedBoxEl.style.width = `${rect.width}px`;
        feedBoxEl.style.height = `${rect.height}px`;
        // Corner reticles only, no text label
      }

      if (dealerBoxEl && dealerZoneRel) {
        const dx = Math.round(rect.x + dealerZoneRel[0] * rect.width);
        const dy = Math.round(rect.y + dealerZoneRel[1] * rect.height);
        const dw = Math.round((dealerZoneRel[2] - dealerZoneRel[0]) * rect.width);
        const dh = Math.round((dealerZoneRel[3] - dealerZoneRel[1]) * rect.height);
        dealerBoxEl.style.display = "block";
        dealerBoxEl.style.left = `${dx}px`;
        dealerBoxEl.style.top = `${dy}px`;
        dealerBoxEl.style.width = `${dw}px`;
        dealerBoxEl.style.height = `${dh}px`;
      } else if (dealerBoxEl) {
        dealerBoxEl.style.display = "none";
      }

      if (playerBoxEl && playerZoneRel) {
        const px = Math.round(rect.x + playerZoneRel[0] * rect.width);
        const py = Math.round(rect.y + playerZoneRel[1] * rect.height);
        const pw = Math.round((playerZoneRel[2] - playerZoneRel[0]) * rect.width);
        const ph = Math.round((playerZoneRel[3] - playerZoneRel[1]) * rect.height);
        playerBoxEl.style.display = "block";
        playerBoxEl.style.left = `${px}px`;
        playerBoxEl.style.top = `${py}px`;
        playerBoxEl.style.width = `${pw}px`;
        playerBoxEl.style.height = `${ph}px`;
      } else if (playerBoxEl) {
        playerBoxEl.style.display = "none";
      }
    }

    if (!bboxCanvasEl) {
      bboxCanvasEl = document.createElement("canvas");
      bboxCanvasEl.id = "bjp-bbox-canvas";
      getBjpRoot().appendChild(bboxCanvasEl);
    }
    bboxCanvasEl.style.display = drawBoxes ? "block" : "none";
    bboxCanvasEl.style.left = `${rect.x}px`;
    bboxCanvasEl.style.top = `${rect.y}px`;
    bboxCanvasEl.style.width = `${rect.width}px`;
    bboxCanvasEl.style.height = `${rect.height}px`;
    if (bboxCanvasEl.width !== rect.width || bboxCanvasEl.height !== rect.height) {
      bboxCanvasEl.width = rect.width;
      bboxCanvasEl.height = rect.height;
    }
  }

  function startPositionTracking() {
    function tick() {
      applyOverlayPositions();
      rafTrackingId = requestAnimationFrame(tick);
    }
    if (!rafTrackingId) {
      rafTrackingId = requestAnimationFrame(tick);
    }
  }

  window.addEventListener("resize", applyOverlayPositions);
  window.addEventListener("scroll", applyOverlayPositions, { passive: true, capture: true });

  // ---------------------------------------------------------------------------
  // 3. In-Browser HUD Overlay & Options Panel (Never Closes on Outside Click)
  // ---------------------------------------------------------------------------
  function createHud() {
    const existing = document.getElementById("bjp-hud");
    if (existing) {
      hudEl = existing;
      hudEl.classList.remove("bjp-hidden");
      return;
    }

    hudEl = document.createElement("div");
    hudEl.id = "bjp-hud";
    hudEl.innerHTML = `
      <!-- Header -->
      <div class="bjp-header" id="bjp-drag-handle">
        <div class="bjp-title-row">
          <span class="bjp-title">🃏 Blackjack Pilot</span>
          <div class="bjp-build-badge-col" title="Build: ${BUILD_TIMESTAMP}">
            <span class="bjp-badge-date">${BUILD_DATE}</span>
            <span class="bjp-badge-ver">${BUILD_VERSION}</span>
          </div>
          <div class="bjp-server-pill disconnected" id="bjp-server-pill">
            <span class="bjp-pill-dot"></span>
            <span id="bjp-server-status-text">Server: OFF</span>
          </div>
        </div>
        <div class="bjp-header-actions">
          <button class="bjp-icon-btn" id="bjp-btn-options" title="Settings / Options">⚙</button>
          <button class="bjp-icon-btn" id="bjp-btn-min" title="Minimize">─</button>
          <button class="bjp-icon-btn" id="bjp-btn-close" title="Hide HUD">✕</button>
        </div>
      </div>

      <!-- Main Live HUD Readout -->
      <div class="bjp-body">
        <div class="bjp-move-card" id="bjp-move-card">
          <div class="bjp-move-label">Optimal Basic Strategy Action</div>
          <div class="bjp-move-text" id="bjp-move-text">WAITING</div>
          <div class="bjp-move-hint" id="bjp-move-hint" style="display:none;"></div>
        </div>

        <div class="bjp-hands-grid">
          <div class="bjp-hand-card bjp-hand-dealer">
            <div class="bjp-hand-header">👑 Dealer</div>
            <div class="bjp-hand-cards" id="bjp-dealer-cards">-</div>
            <div class="bjp-hand-total" id="bjp-dealer-total">Total: -</div>
          </div>
          <div class="bjp-hand-card bjp-hand-player">
            <div class="bjp-hand-header">👤 Player</div>
            <div class="bjp-hand-cards" id="bjp-player-cards">-</div>
            <div class="bjp-hand-total" id="bjp-player-total">Total: -</div>
          </div>
        </div>

        <div class="bjp-count-card">
          <div class="bjp-count-row">
            <span class="bjp-count-main" id="bjp-count-readout">RC: +0 | TC: +0.0 | Cards: 0</span>
            <span class="bjp-count-sub" id="bjp-decks-sub">Decks: 6.0</span>
          </div>
        </div>

        <div class="bjp-stats-card">
          <span id="bjp-winrate">Win%: 0.0%</span>
          <span id="bjp-rounds">0 rounds</span>
        </div>
      </div>

      <!-- In-Page Options & Controls Menu (Does NOT disappear on outside clicks) -->
      <div class="bjp-options-panel" id="bjp-options-panel">
        <div class="bjp-panel-title">Capture & Calibration</div>
        <button id="bjp-btn-toggle-capture" class="bjp-btn bjp-btn-primary">
          ▶ Start Browser Capture
        </button>

        <div class="bjp-btn-grid">
          <button id="bjp-btn-sel-feed" class="bjp-btn bjp-btn-secondary">📹 1. Feed Area</button>
          <button id="bjp-btn-sel-dealer" class="bjp-btn bjp-btn-secondary">👑 2. Dealer Zone</button>
          <button id="bjp-btn-sel-player" class="bjp-btn bjp-btn-secondary">👤 3. Player Zone</button>
          <button id="bjp-btn-reset-zones" class="bjp-btn bjp-btn-secondary">↺ Clear Zones</button>
        </div>

        <div class="bjp-panel-title" style="margin-top:6px;">Display Options</div>
        <label class="bjp-toggle-row" for="bjp-chk-zones">
          <span class="bjp-toggle-text" style="color: #ffffff !important; font-weight: 600 !important;">Always Show 3-Zone Corner Reticles</span>
          <span class="bjp-switch">
            <input type="checkbox" id="bjp-chk-zones" checked>
            <span class="bjp-slider"></span>
          </span>
        </label>
        <label class="bjp-toggle-row" for="bjp-chk-boxes">
          <span class="bjp-toggle-text" style="color: #ffffff !important; font-weight: 600 !important;">Draw Card Corner Overlays</span>
          <span class="bjp-switch">
            <input type="checkbox" id="bjp-chk-boxes" checked>
            <span class="bjp-slider"></span>
          </span>
        </label>

        <div class="bjp-panel-title" style="margin-top:6px;">Sensitivity & Rules</div>
        <div class="bjp-slider-row">
          <label>Confidence:</label>
          <input type="range" id="bjp-rng-conf" min="10" max="90" value="35">
          <span id="bjp-lbl-conf" class="bjp-val-lbl">35%</span>
        </div>
        <div class="bjp-slider-row">
          <label>Overlap (IoU):</label>
          <input type="range" id="bjp-rng-iou" min="20" max="80" value="50">
          <span id="bjp-lbl-iou" class="bjp-val-lbl">50%</span>
        </div>
        <div class="bjp-slider-row">
          <label>Decks in Shoe:</label>
          <input type="number" id="bjp-num-decks" min="1" max="8" value="6" class="bjp-num-input">
        </div>

        <div class="bjp-btn-grid" style="margin-top:6px;">
          <button id="bjp-btn-rst-count" class="bjp-btn bjp-btn-secondary">Reset Count</button>
          <button id="bjp-btn-rst-stats" class="bjp-btn bjp-btn-secondary">Reset Stats</button>
        </div>

        <div class="bjp-panel-title" style="margin-top:6px;">Extension & Code Sync</div>
        <div class="bjp-sync-info">
          <div><strong>Active Build:</strong> ${BUILD_TIMESTAMP} (${BUILD_VERSION})</div>
          <div class="bjp-sync-hint">Notice: DevTools refresh (F5) does NOT reload extension scripts in Chrome/Edge. Click below to reload extension and page in 1-click:</div>
        </div>
        <button id="bjp-btn-reload-ext" class="bjp-btn bjp-btn-reload" style="margin-top:4px;">
          🔄 Reload Extension & Page
        </button>

        <button id="bjp-btn-close-options" class="bjp-btn bjp-btn-secondary" style="margin-top:4px;">
          ✓ Done / Close Options
        </button>
      </div>
    `;

    getBjpRoot().appendChild(hudEl);

    // Draggable Window Logic
    const handle = document.getElementById("bjp-drag-handle");
    let isDragging = false;
    let startX = 0;
    let startY = 0;
    let initialLeft = 0;
    let initialTop = 0;

    handle.addEventListener("mousedown", (e) => {
      if (e.target.tagName === "BUTTON") return;
      isDragging = true;
      startX = e.clientX;
      startY = e.clientY;
      const rect = hudEl.getBoundingClientRect();
      initialLeft = rect.left;
      initialTop = rect.top;
      e.preventDefault();
    });

    window.addEventListener("mousemove", (e) => {
      if (!isDragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      hudEl.style.left = `${initialLeft + dx}px`;
      hudEl.style.top = `${initialTop + dy}px`;
      hudEl.style.right = "auto";
    });

    window.addEventListener("mouseup", () => {
      isDragging = false;
    });

    // Options Menu Toggle (Never disappears on outside clicks)
    const optionsPanel = document.getElementById("bjp-options-panel");
    const btnOptions = document.getElementById("bjp-btn-options");

    function toggleOptions() {
      optionsPanel.classList.toggle("open");
      btnOptions.classList.toggle("active");
    }

    btnOptions.addEventListener("click", toggleOptions);
    document.getElementById("bjp-btn-close-options").addEventListener("click", toggleOptions);

    // Minimize / Close Buttons
    document.getElementById("bjp-btn-min").addEventListener("click", () => {
      hudEl.classList.toggle("bjp-minimized");
    });

    document.getElementById("bjp-btn-close").addEventListener("click", () => {
      hudEl.classList.add("bjp-hidden");
    });

    // Capture Toggle Button
    const btnToggleCapture = document.getElementById("bjp-btn-toggle-capture");
    btnToggleCapture.addEventListener("click", () => {
      if (isCapturing) {
        stopCapture();
      } else {
        startCapture();
      }
    });

    // Zone Selection Buttons
    document.getElementById("bjp-btn-sel-feed").addEventListener("click", () => {
      startSelection("feed");
    });
    document.getElementById("bjp-btn-sel-dealer").addEventListener("click", () => {
      startSelection("dealer");
    });
    document.getElementById("bjp-btn-sel-player").addEventListener("click", () => {
      startSelection("player");
    });
    document.getElementById("bjp-btn-reset-zones").addEventListener("click", () => {
      feedRect = null;
      feedTargetEl = null;
      feedTargetOffset = null;
      dealerZoneRel = null;
      playerZoneRel = null;
      clearStoredCalibration();
      syncZonesToServer();
      applyOverlayPositions();
      clearBoundingBoxes();
    });

    // Display Toggles
    const chkZones = document.getElementById("bjp-chk-zones");
    chkZones.addEventListener("change", () => {
      showZones = chkZones.checked;
      applyOverlayPositions();
    });

    const chkBoxes = document.getElementById("bjp-chk-boxes");
    chkBoxes.addEventListener("change", () => {
      drawBoxes = chkBoxes.checked;
      if (!drawBoxes) clearBoundingBoxes();
    });

    // Sensitivity Controls
    const rngConf = document.getElementById("bjp-rng-conf");
    const lblConf = document.getElementById("bjp-lbl-conf");
    const rngIou = document.getElementById("bjp-rng-iou");
    const lblIou = document.getElementById("bjp-lbl-iou");
    const numDecks = document.getElementById("bjp-num-decks");

    rngConf.addEventListener("input", () => {
      confThresh = rngConf.value / 100;
      lblConf.textContent = `${rngConf.value}%`;
      sendCommand("set_thresholds", { conf: confThresh, iou: iouThresh });
    });

    rngIou.addEventListener("input", () => {
      iouThresh = rngIou.value / 100;
      lblIou.textContent = `${rngIou.value}%`;
      sendCommand("set_thresholds", { conf: confThresh, iou: iouThresh });
    });

    numDecks.addEventListener("change", () => {
      decksCount = parseInt(numDecks.value, 10);
      sendCommand("set_decks", { decks: decksCount });
    });

    // Reset Buttons
    document.getElementById("bjp-btn-rst-count").addEventListener("click", () => {
      sendCommand("reset_counter");
      const cntEl = document.getElementById("bjp-count-readout");
      if (cntEl) cntEl.textContent = "RC: +0  |  TC: +0.0  |  Cards: 0";
    });
    document.getElementById("bjp-btn-rst-stats").addEventListener("click", () => {
      sendCommand("reset_stats");
      const winrateEl = document.getElementById("bjp-winrate");
      const roundsEl = document.getElementById("bjp-rounds");
      if (winrateEl) {
        winrateEl.textContent = "Win%: 0.0%";
        winrateEl.style.setProperty("color", "#ffffff", "important");
      }
      if (roundsEl) {
        roundsEl.textContent = "0W / 0L / 0P";
        roundsEl.style.setProperty("color", "#ffffff", "important");
      }
    });

    // 1-Click Extension & Page Reload
    const btnReloadExt = document.getElementById("bjp-btn-reload-ext");
    if (btnReloadExt) {
      btnReloadExt.addEventListener("click", () => {
        btnReloadExt.textContent = "⏳ Reloading Extension...";
        btnReloadExt.disabled = true;

        try {
          if (bgPort) {
            bgPort.postMessage({ type: "reload_extension" });
          } else {
            chrome.runtime.sendMessage({ action: "reload_extension" });
          }
        } catch (e) {
          console.warn("[Blackjack Pilot] Reload signal failed:", e);
        }

        setTimeout(() => {
          window.location.reload();
        }, 400);
      });
    }
  }

  function updateServerIndicator(connected) {
    if (!hudEl) return;
    const pill = document.getElementById("bjp-server-pill");
    const txt = document.getElementById("bjp-server-status-text");
    if (connected) {
      pill.className = "bjp-server-pill connected";
      txt.textContent = "Server: ON";
    } else {
      pill.className = "bjp-server-pill disconnected";
      txt.textContent = "Server: OFF";
    }
  }

  function updateHudWithResult(res) {
    if (!hudEl) return;

    // Move Card
    const moveCard = document.getElementById("bjp-move-card");
    const moveText = document.getElementById("bjp-move-text");
    const moveHint = document.getElementById("bjp-move-hint");

    moveText.textContent = res.optimal_move || "WAITING";
    moveCard.style.borderColor = res.move_color || "#58a6ff";
    moveText.style.color = res.move_color || "#58a6ff";

    if (res.count_hint) {
      moveHint.style.display = "block";
      moveHint.textContent = `⚡ ${res.count_hint}`;
    } else {
      moveHint.style.display = "none";
    }

    // Hands
    document.getElementById("bjp-dealer-cards").textContent = res.dealer_text || "-";
    document.getElementById("bjp-dealer-total").textContent = `Total: ${res.dealer_sum || "-"}`;

    document.getElementById("bjp-player-cards").textContent = res.player_text || "-";
    document.getElementById("bjp-player-total").textContent = `Total: ${res.player_sum || "-"}`;

    // Count
    const cardsSeen = res.cards_seen ?? 0;
    document.getElementById("bjp-count-readout").textContent =
      `RC: ${res.running_count || "+0"}  |  TC: ${res.true_count || "+0.0"}  |  Cards: ${cardsSeen}`;
    document.getElementById("bjp-decks-sub").textContent =
      `Decks: ${res.decks_remaining || "6.0"}`;

    // Stats & Winrate Colors (Grön för flest wins, Röd för flest losses, Vit vid lika)
    const winrateEl = document.getElementById("bjp-winrate");
    const roundsEl = document.getElementById("bjp-rounds");
    if (winrateEl && roundsEl) {
      const wins = Number(res.wins) || 0;
      const losses = Number(res.losses) || 0;
      const pushes = Number(res.pushes) || 0;

      winrateEl.textContent = `Win%: ${res.win_pct || 0}%`;
      roundsEl.textContent = `${wins}W / ${losses}L / ${pushes}P`;

      let statColor = "#ffffff";
      if (wins > losses) {
        statColor = "#3fb950"; // Grön om mest wins
      } else if (losses > wins) {
        statColor = "#f85149"; // Röd om mest losses
      } else {
        statColor = "#ffffff"; // Vit om lika
      }

      winrateEl.style.setProperty("color", statColor, "important");
      roundsEl.style.setProperty("color", statColor, "important");
    }
  }

  // ---------------------------------------------------------------------------
  // 4. Screen / Tab Capture Loop
  // ---------------------------------------------------------------------------
  async function startCapture() {
    if (isCapturing) return;

    try {
      captureStream = await navigator.mediaDevices.getDisplayMedia({
        video: {
          displaySurface: "browser",
          frameRate: 15,
        },
        audio: false,
        preferCurrentTab: true,
        selfBrowserSurface: "include",
        surfaceSwitching: "include",
        systemAudio: "exclude",
      });

      captureVideo = document.createElement("video");
      captureVideo.srcObject = captureStream;
      captureVideo.muted = true;
      await captureVideo.play();

      captureCanvas = document.createElement("canvas");
      isCapturing = true;

      // Respect user settings: Never force-off overlays or uncheck boxes!
      applyOverlayPositions();

      const btn = document.getElementById("bjp-btn-toggle-capture");
      if (btn) {
        btn.textContent = "⏹ Stop Capture";
        btn.classList.add("recording");
      }

      captureStream.getVideoTracks()[0].onended = () => {
        stopCapture();
      };

      captureTimer = setInterval(captureAndSend, 120);
      console.log("[Blackjack Pilot] Capture running.");
    } catch (e) {
      console.warn("[Blackjack Pilot] getDisplayMedia error:", e);
      isCapturing = false;
    }
  }

  function stopCapture() {
    isCapturing = false;
    if (captureTimer) {
      clearInterval(captureTimer);
      captureTimer = null;
    }
    if (captureStream) {
      captureStream.getTracks().forEach((t) => t.stop());
      captureStream = null;
    }
    if (captureVideo) {
      captureVideo.pause();
      captureVideo.srcObject = null;
      captureVideo = null;
    }

    const btn = document.getElementById("bjp-btn-toggle-capture");
    if (btn) {
      btn.textContent = "▶ Start Browser Capture";
      btn.classList.remove("recording");
    }
    clearBoundingBoxes();
  }

  function captureAndSend() {
    if (!isCapturing || !captureVideo || !bgPort || !serverConnected) return;

    // Backpressure flow control: wait for server to acknowledge previous frame
    if (isFrameInFlight) {
      if (Date.now() - lastFrameSentAt > 1200) {
        // Timeout watchdog in case a frame was dropped
        isFrameInFlight = false;
      } else {
        return;
      }
    }

    const vw = captureVideo.videoWidth;
    const vh = captureVideo.videoHeight;
    if (vw === 0 || vh === 0) return;

    applyOverlayPositions();

    const curRect = getFeedViewportRect();
    const ctx = captureCanvas.getContext("2d");

    // Hide overlays during video snapshot to avoid capturing our own UI or boxes
    const rootEl = getBjpRoot();
    const prevDisplay = rootEl.style.visibility;
    rootEl.style.visibility = "hidden";

    try {
      if (curRect) {
        const clientW = window.innerWidth;
        const clientH = window.innerHeight;
        const scaleX = vw / clientW;
        const scaleY = vh / clientH;

        const sx = Math.max(0, Math.min(vw - 1, Math.round(curRect.x * scaleX)));
        const sy = Math.max(0, Math.min(vh - 1, Math.round(curRect.y * scaleY)));
        const sw = Math.max(1, Math.min(vw - sx, Math.round(curRect.width * scaleX)));
        const sh = Math.max(1, Math.min(vh - sy, Math.round(curRect.height * scaleY)));

        if (sw > 30 && sh > 30) {
          captureCanvas.width = sw;
          captureCanvas.height = sh;
          ctx.drawImage(captureVideo, sx, sy, sw, sh, 0, 0, sw, sh);
        } else {
          captureCanvas.width = vw;
          captureCanvas.height = vh;
          ctx.drawImage(captureVideo, 0, 0);
        }
      } else {
        captureCanvas.width = vw;
        captureCanvas.height = vh;
        ctx.drawImage(captureVideo, 0, 0);
      }
    } finally {
      rootEl.style.visibility = prevDisplay;
    }

    const dataUrl = captureCanvas.toDataURL("image/jpeg", 0.80);
    isFrameInFlight = true;
    lastFrameSentAt = Date.now();
    bgPort.postMessage({ type: "frame", image: dataUrl });
  }

  // ---------------------------------------------------------------------------
  // 5. Snipper Selection Tool
  // ---------------------------------------------------------------------------
  function startSelection(target) {
    if (document.getElementById("bjp-snipper-overlay")) return;

    if ((target === "dealer" || target === "player") && !feedRect) {
      alert("Please select the Feed Area (Step 1) first!");
      return;
    }

    const overlay = document.createElement("div");
    overlay.id = "bjp-snipper-overlay";

    const banner = document.createElement("div");
    banner.className = "bjp-snipper-banner";
    const prompts = {
      feed: "Step 1: Drag rectangle over the TABLE / VIDEO FEED (Press ESC to cancel)",
      dealer: "Step 2: Drag rectangle inside feed over the DEALER'S CARDS (Press ESC to cancel)",
      player: "Step 3: Drag rectangle inside feed over the PLAYER'S CARDS (Press ESC to cancel)",
    };
    banner.textContent = prompts[target] || "Drag rectangle with mouse";
    overlay.appendChild(banner);

    const box = document.createElement("div");
    box.className = "bjp-snipper-rect";
    box.style.display = "none";
    overlay.appendChild(box);

    const badge = document.createElement("div");
    badge.className = "bjp-snipper-badge";
    box.appendChild(badge);

    document.body.appendChild(overlay);

    let startX = 0;
    let startY = 0;
    let isDrawing = false;

    overlay.addEventListener("mousedown", (e) => {
      startX = e.clientX;
      startY = e.clientY;
      isDrawing = true;
      box.style.left = `${startX}px`;
      box.style.top = `${startY}px`;
      box.style.width = "0px";
      box.style.height = "0px";
      box.style.display = "block";
    });

    overlay.addEventListener("mousemove", (e) => {
      if (!isDrawing) return;
      const curX = e.clientX;
      const curY = e.clientY;
      const x = Math.min(startX, curX);
      const y = Math.min(startY, curY);
      const w = Math.abs(curX - startX);
      const h = Math.abs(curY - startY);

      box.style.left = `${x}px`;
      box.style.top = `${y}px`;
      box.style.width = `${w}px`;
      box.style.height = `${h}px`;
      badge.textContent = `${w} × ${h}`;
    });

    overlay.addEventListener("mouseup", (e) => {
      if (!isDrawing) return;
      isDrawing = false;
      const curX = e.clientX;
      const curY = e.clientY;
      const x = Math.min(startX, curX);
      const y = Math.min(startY, curY);
      const w = Math.abs(curX - startX);
      const h = Math.abs(curY - startY);

      overlay.remove();

      if (w > 20 && h > 20) {
        if (target === "feed") {
          feedRect = {
            x,
            y,
            width: w,
            height: h,
            pageX: x + window.scrollX,
            pageY: y + window.scrollY,
          };
          dealerZoneRel = null;
          playerZoneRel = null;

          // Attempt to find underlying game element for responsive viewport anchoring
          try {
            if (zoneOverlaysEl) zoneOverlaysEl.style.display = "none";
            if (bboxCanvasEl) bboxCanvasEl.style.display = "none";

            let underlying = null;
            if (document.elementsFromPoint) {
              const els = document.elementsFromPoint(x + w / 2, y + h / 2);
              for (const el of els) {
                if (
                  el &&
                  el !== document.body &&
                  el !== document.documentElement &&
                  !el.id?.startsWith("bjp-")
                ) {
                  const tag = el.tagName.toLowerCase();
                  if (tag === "video" || tag === "iframe" || tag === "canvas") {
                    underlying = el;
                    break;
                  }
                }
              }
              if (!underlying) {
                for (const el of els) {
                  if (
                    el &&
                    el !== document.body &&
                    el !== document.documentElement &&
                    !el.id?.startsWith("bjp-")
                  ) {
                    underlying = el;
                    break;
                  }
                }
              }
            }

            if (!underlying) {
              const testPoints = [
                [x + w / 2, y + h / 2],
                [x + 15, y + 15],
                [x + w - 15, y + h - 15],
              ];
              for (const [px, py] of testPoints) {
                const el = document.elementFromPoint(px, py);
                if (el && el !== document.body && el !== document.documentElement && !el.id?.startsWith("bjp-")) {
                  underlying = el;
                  break;
                }
              }
            }

            if (zoneOverlaysEl) zoneOverlaysEl.style.display = "";
            if (bboxCanvasEl) bboxCanvasEl.style.display = drawBoxes ? "block" : "none";

            if (underlying) {
              feedTargetEl = underlying;
              const r = underlying.getBoundingClientRect();
              feedTargetOffset = {
                relX: x - r.left,
                relY: y - r.top,
                width: w,
                height: h,
              };
            } else {
              feedTargetEl = null;
              feedTargetOffset = null;
            }
          } catch (err) {
            feedTargetEl = null;
            feedTargetOffset = null;
          }

          syncZonesToServer();
          applyOverlayPositions();
          saveStoredCalibration();
        } else if (target === "dealer" && feedRect) {
          const curFeed = getFeedViewportRect();
          if (curFeed) {
            const dx1 = Math.max(0, Math.min(1, (x - curFeed.x) / curFeed.width));
            const dy1 = Math.max(0, Math.min(1, (y - curFeed.y) / curFeed.height));
            const dx2 = Math.max(0, Math.min(1, (x + w - curFeed.x) / curFeed.width));
            const dy2 = Math.max(0, Math.min(1, (y + h - curFeed.y) / curFeed.height));
            dealerZoneRel = [dx1, dy1, dx2, dy2];
            syncZonesToServer();
            applyOverlayPositions();
            saveStoredCalibration();
          }
        } else if (target === "player" && feedRect) {
          const curFeed = getFeedViewportRect();
          if (curFeed) {
            const px1 = Math.max(0, Math.min(1, (x - curFeed.x) / curFeed.width));
            const py1 = Math.max(0, Math.min(1, (y - curFeed.y) / curFeed.height));
            const px2 = Math.max(0, Math.min(1, (x + w - curFeed.x) / curFeed.width));
            const py2 = Math.max(0, Math.min(1, (y + h - curFeed.y) / curFeed.height));
            playerZoneRel = [px1, py1, px2, py2];
            syncZonesToServer();
            applyOverlayPositions();
            saveStoredCalibration();
          }
        }
      }
    });

    window.addEventListener(
      "keydown",
      function onEsc(e) {
        if (e.key === "Escape") {
          overlay.remove();
          window.removeEventListener("keydown", onEsc);
        }
      },
      { once: true }
    );
  }

  // ---------------------------------------------------------------------------
  // 6. Bounding Box Canvas Layer
  // ---------------------------------------------------------------------------
  function renderBoundingBoxes(detections) {
    if (!bboxCanvasEl || !feedRect) return;
    const ctx = bboxCanvasEl.getContext("2d");
    ctx.clearRect(0, 0, bboxCanvasEl.width, bboxCanvasEl.height);

    if (!detections || detections.length === 0) return;

    const curFeed = getFeedViewportRect();
    if (!curFeed) return;

    for (const d of detections) {
      let x1, y1, w, h;
      if (d.bbox_norm && d.bbox_norm.length === 4) {
        // Precise normalized mapping directly to canvas dimensions
        const [nx1, ny1, nx2, ny2] = d.bbox_norm;
        x1 = Math.round(nx1 * curFeed.width);
        y1 = Math.round(ny1 * curFeed.height);
        w = Math.round((nx2 - nx1) * curFeed.width);
        h = Math.round((ny2 - ny1) * curFeed.height);
      } else if (d.bbox && d.bbox.length === 4) {
        const scaleDownX = curFeed.width / (captureCanvas ? captureCanvas.width : curFeed.width);
        const scaleDownY = curFeed.height / (captureCanvas ? captureCanvas.height : curFeed.height);
        x1 = Math.round(d.bbox[0] * scaleDownX);
        y1 = Math.round(d.bbox[1] * scaleDownY);
        w = Math.round((d.bbox[2] - d.bbox[0]) * scaleDownX);
        h = Math.round((d.bbox[3] - d.bbox[1]) * scaleDownY);
      } else {
        continue;
      }

      let strokeColor = "#3fb950"; // Green for table
      if (d.category === "dealer") strokeColor = "#d29922"; // Gold
      if (d.category === "player") strokeColor = "#00d2ff"; // Cyan

      // Draw ONLY CORNERS, NO TEXT, ONLY COLOR (half-length reticles)
      const cornerLen = Math.max(3, Math.min(7, Math.min(w, h) * 0.15));

      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 2.5;
      ctx.lineCap = "round";

      // Top-Left corner
      ctx.beginPath();
      ctx.moveTo(x1, y1 + cornerLen);
      ctx.lineTo(x1, y1);
      ctx.lineTo(x1 + cornerLen, y1);
      ctx.stroke();

      // Top-Right corner
      ctx.beginPath();
      ctx.moveTo(x1 + w - cornerLen, y1);
      ctx.lineTo(x1 + w, y1);
      ctx.lineTo(x1 + w, y1 + cornerLen);
      ctx.stroke();

      // Bottom-Right corner
      ctx.beginPath();
      ctx.moveTo(x1 + w, y1 + h - cornerLen);
      ctx.lineTo(x1 + w, y1 + h);
      ctx.lineTo(x1 + w - cornerLen, y1 + h);
      ctx.stroke();

      // Bottom-Left corner
      ctx.beginPath();
      ctx.moveTo(x1 + cornerLen, y1 + h);
      ctx.lineTo(x1, y1 + h);
      ctx.lineTo(x1, y1 + h - cornerLen);
      ctx.stroke();
    }
  }

  function clearBoundingBoxes() {
    if (bboxCanvasEl) {
      const ctx = bboxCanvasEl.getContext("2d");
      ctx.clearRect(0, 0, bboxCanvasEl.width, bboxCanvasEl.height);
    }
  }

  // ---------------------------------------------------------------------------
  // 7. Message Dispatcher (Triggered by Toolbar Icon Click)
  // ---------------------------------------------------------------------------
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.action === "toggle_hud") {
      if (!hudEl || !document.contains(hudEl)) {
        createHud();
      }
      if (hudEl) {
        hudEl.classList.toggle("bjp-hidden");
      }
      sendResponse({ toggled: true });
    }
  });

  // Initialization with DOM safety
  function initAll() {
    createHud();
    initZoneOverlays();
    loadStoredCalibration();
    startPositionTracking();
    connectPort();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAll);
  } else {
    initAll();
  }
})();
