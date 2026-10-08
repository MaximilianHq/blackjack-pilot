/**
 * Blackjack Pilot - In-Browser Content Script
 * 1. Maintains always-visible 3-zone overlays (Feed, Dealer, Player) on the webpage.
 * 2. In-page Options Panel that never disappears when clicking outside.
 * 3. Bridges frame streaming to local Python AI engine via background service worker.
 */

(() => {
  if (window.__bjp_active) return;
  window.__bjp_active = true;

  const BUILD_VERSION = "v1.6.1";
  const BUILD_DATE = "2026-10-08";
  const BUILD_TIMESTAMP = "2026-10-08 (GitHub Server Prompt & Direct Launcher)";
  console.log(
    `%c[Blackjack Pilot] Loaded ${BUILD_VERSION} (${BUILD_TIMESTAMP})`,
    "color: #58a6ff; font-weight: bold; font-size: 13px;"
  );

  // Background port bridge & Tab activation state
  let bgPort = null;
  let serverConnected = false;
  let promptDismissed = false;
  let isHudActiveOnThisTab = false; // Only active when user presses the extension icon on this tab!

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
  let playerPointsRel = []; // [[x, y], ...] normalized positions picked for player hands

  // Settings
  let showHud = true;
  let showZones = true;
  let drawBoxes = true; // Minimalist corner reticles on cards (0 text)
  let confThresh = 0.35;
  let iouThresh = 0.50;
  let decksCount = 6;
  const HAND_ZONE_SIZE = 2; // Constant 2% detection radius (not user-configurable)

  // DOM elements & Root Container
  let bjpRootEl = null;
  let hudEl = null;
  let zoneOverlaysEl = null;
  let feedBoxEl = null;
  let dealerBoxEl = null;
  let playerBoxEl = null;
  let playerSpotsContainerEl = null;
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
          updateServerIndicator(serverConnected, !!msg.starting, msg.error);
          if (serverConnected) {
            const ov = document.getElementById("bjp-rng-overlap");
            sendCommand("set_hand_overlap", { pct: ov ? Number(ov.value) : 15 });
          }
          if (serverConnected && (dealerZoneRel || (playerPointsRel && playerPointsRel.length))) {
            syncZonesToServer();
          }
        } else if (msg.type === "server_start_result") {
          if (msg.result && !msg.result.success) {
            updateServerIndicator(false, false, msg.result.error);
          }
        } else if (msg.type === "server_result" && msg.payload) {
          isFrameInFlight = false;
          lastResultReceivedAt = Date.now();
          updateHudWithResult(msg.payload);
          if (drawBoxes) {
            renderBoundingBoxes(msg.payload.detections, msg.payload.hands);
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
      player_points: playerPointsRel,
      player_point: playerPointsRel.length ? playerPointsRel[0] : null,
      hand_zone_size: HAND_ZONE_SIZE,
    });
  }

  function saveStoredCalibration() {
    try {
      chrome.storage.local.set({
        bjp_feed_rect: feedRect,
        bjp_dealer_zone: dealerZoneRel,
        bjp_player_points: playerPointsRel,
        bjp_player_point: playerPointsRel.length ? playerPointsRel[0] : null,
      });
    } catch (e) {}
  }

  function clearStoredCalibration() {
    try {
      chrome.storage.local.remove([
        "bjp_feed_rect",
        "bjp_dealer_zone",
        "bjp_player_point",
        "bjp_player_points",
      ]);
    } catch (e) {}
  }

  function loadStoredCalibration() {
    try {
      chrome.storage.local.get(
        ["bjp_feed_rect", "bjp_dealer_zone", "bjp_player_point", "bjp_player_points"],
        (data) => {
          if (data && data.bjp_feed_rect) {
            feedRect = data.bjp_feed_rect;
            if (data.bjp_dealer_zone) dealerZoneRel = data.bjp_dealer_zone;
            if (Array.isArray(data.bjp_player_points)) {
              playerPointsRel = data.bjp_player_points;
            } else if (data.bjp_player_point) {
              playerPointsRel = [data.bjp_player_point];
            } else {
              playerPointsRel = [];
            }
            applyOverlayPositions();
            if (serverConnected && (dealerZoneRel || (playerPointsRel && playerPointsRel.length))) {
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
    zoneOverlaysEl.style.display = "none";

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

    playerSpotsContainerEl = document.createElement("div");
    playerSpotsContainerEl.id = "bjp-player-spots-container";
    zoneOverlaysEl.appendChild(playerSpotsContainerEl);

    getBjpRoot().appendChild(zoneOverlaysEl);
  }

  function applyOverlayPositions() {
    if (!zoneOverlaysEl) initZoneOverlays();

    const rect = getFeedViewportRect();
    if (!rect || !isHudActiveOnThisTab || document.hidden) {
      if (feedBoxEl) feedBoxEl.style.display = "none";
      if (dealerBoxEl) dealerBoxEl.style.display = "none";
      if (playerBoxEl) playerBoxEl.style.display = "none";
      if (playerSpotsContainerEl) playerSpotsContainerEl.innerHTML = "";
      if (bboxCanvasEl) bboxCanvasEl.style.display = "none";
      if (zoneOverlaysEl) zoneOverlaysEl.style.display = "none";
      return;
    }
    if (zoneOverlaysEl) zoneOverlaysEl.style.display = "block";

    if (!showZones) {
      if (feedBoxEl) feedBoxEl.style.display = "none";
      if (dealerBoxEl) dealerBoxEl.style.display = "none";
      if (playerBoxEl) playerBoxEl.style.display = "none";
      if (playerSpotsContainerEl) playerSpotsContainerEl.innerHTML = "";
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

      if (playerBoxEl) playerBoxEl.style.display = "none";

      if (playerSpotsContainerEl) {
        if (!playerPointsRel || playerPointsRel.length === 0) {
          playerSpotsContainerEl.innerHTML = "";
        } else {
          playerSpotsContainerEl.innerHTML = playerPointsRel
            .map((pt, idx) => {
              const px = Math.round(rect.x + pt[0] * rect.width);
              const py = Math.round(rect.y + pt[1] * rect.height);
              return `
                <div class="bjp-spot-marker" style="display:flex; position:absolute; left:${px}px; top:${py}px; transform:translate(-50%, -50%); pointer-events:none; z-index:2147483632;">
                  <span class="bjp-spot-num">${idx + 1}</span>
                </div>
              `;
            })
            .join("");
        }
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
      if (isHudActiveOnThisTab && !document.hidden) {
        applyOverlayPositions();
      }
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
      if (isHudActiveOnThisTab) {
        hudEl.classList.remove("bjp-hidden");
      } else {
        hudEl.classList.add("bjp-hidden");
      }
      return;
    }

    hudEl = document.createElement("div");
    hudEl.id = "bjp-hud";
    hudEl.className = isHudActiveOnThisTab ? "" : "bjp-hidden";
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
        <!-- Server Offline / GitHub Download Prompt -->
        <div class="bjp-server-prompt" id="bjp-server-prompt" style="display:none;">
          <div class="bjp-prompt-header">
            <div class="bjp-prompt-badge">⚡ AI Server Offline</div>
            <button class="bjp-prompt-close-btn" id="bjp-btn-dismiss-prompt" title="Dölj varning">✕</button>
          </div>
          <div class="bjp-prompt-text">
            Krävs för kortläsning & Hi-Lo counting. Klicka <strong>Öppna Server</strong> nedan, eller dubbelklicka <strong>Start-Blackjack-Server.bat</strong> i nedladdade mappen (ingen Python krävs!).
          </div>
          <div class="bjp-prompt-buttons">
            <a href="https://github.com/MaximilianHq/blackjack-pilot" target="_blank" class="bjp-btn bjp-btn-github" id="bjp-btn-github-dl">
              <svg viewBox="0 0 16 16" width="13" height="13" fill="currentColor" style="vertical-align:text-bottom; margin-right:4px;">
                <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
              </svg>
              Ladda ner (GitHub)
            </a>
            <button class="bjp-btn bjp-btn-primary bjp-btn-open-server" id="bjp-btn-prompt-start">
              ⚡ Öppna Server
            </button>
          </div>
        </div>

        <div class="bjp-hands-grid" id="bjp-hands-grid">
          <div class="bjp-hand-card bjp-hand-dealer">
            <div class="bjp-hand-header">👑 Dealer</div>
            <div class="bjp-hand-dealer-bottom">
              <div class="bjp-hand-cards" id="bjp-dealer-cards">-</div>
              <div class="bjp-hand-total" id="bjp-dealer-total">Total: -</div>
            </div>
          </div>
          <div class="bjp-hand-card bjp-hand-player" id="bjp-player-card">
            <div class="bjp-hand-header" id="bjp-player-header">👤 Player</div>
            <div id="bjp-player-single-content">
              <div class="bjp-player-single-bottom">
                <div class="bjp-hand-cards" id="bjp-player-cards">-</div>
                <div class="bjp-player-meta-row">
                  <div class="bjp-hand-total" id="bjp-player-total">Total: -</div>
                  <span class="bjp-hand-badge" id="bjp-player-action-badge" style="display:none;"></span>
                </div>
              </div>
            </div>
            <div id="bjp-multi-hands-sublist" style="display:none;"></div>
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
          <button id="bjp-btn-sel-player" class="bjp-btn bjp-btn-secondary">👤 3. Player Hands</button>
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
          <span class="bjp-toggle-text" style="color: #ffffff !important; font-weight: 600 !important;">Draw Card Color Tint Overlays</span>
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
        <div class="bjp-slider-row" title="Cards join the same hand only if they overlap MORE than this share of the smaller card">
          <label>Hand overlap:</label>
          <input type="range" id="bjp-rng-overlap" min="0" max="80" value="15">
          <span id="bjp-lbl-overlap" class="bjp-val-lbl">15%</span>
        </div>
        <div class="bjp-slider-row">
          <label>Decks in Shoe:</label>
          <input type="number" id="bjp-num-decks" min="1" max="8" value="6" class="bjp-num-input">
        </div>

        <div class="bjp-btn-grid" style="margin-top:6px;">
          <button id="bjp-btn-rst-count" class="bjp-btn bjp-btn-secondary">Reset Count</button>
          <button id="bjp-btn-rst-stats" class="bjp-btn bjp-btn-secondary">Reset Stats</button>
        </div>

        <div class="bjp-panel-title" style="margin-top:6px;">Python AI Server</div>
        <div style="display:flex; gap:6px; margin-top:4px;">
          <a href="https://github.com/MaximilianHq/blackjack-pilot" target="_blank" class="bjp-btn bjp-btn-github" style="flex:1;">
            <svg viewBox="0 0 16 16" width="13" height="13" fill="currentColor" style="vertical-align:text-bottom; margin-right:4px;">
              <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/>
            </svg>
            GitHub Repo
          </a>
          <button id="bjp-btn-start-server-opt" class="bjp-btn bjp-btn-primary" style="flex:1;">
            ⚡ Öppna Server
          </button>
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
      setHudActive(false);
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
      startMultiHandSelection();
    });
    document.getElementById("bjp-btn-reset-zones").addEventListener("click", () => {
      feedRect = null;
      feedTargetEl = null;
      feedTargetOffset = null;
      dealerZoneRel = null;
      playerPointsRel = [];
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

    // Hand overlap threshold (% of the smaller card that must overlap to join a hand)
    const rngOverlap = document.getElementById("bjp-rng-overlap");
    const lblOverlap = document.getElementById("bjp-lbl-overlap");
    rngOverlap.addEventListener("input", () => {
      lblOverlap.textContent = `${rngOverlap.value}%`;
      sendCommand("set_hand_overlap", { pct: Number(rngOverlap.value) });
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

    // Direct Server Launch Controls
    const serverPillEl = document.getElementById("bjp-server-pill");
    if (serverPillEl) {
      serverPillEl.addEventListener("click", () => {
        if (!serverConnected) {
          triggerStartServer();
        }
      });
    }

    const btnStartServerOpt = document.getElementById("bjp-btn-start-server-opt");
    if (btnStartServerOpt) {
      btnStartServerOpt.addEventListener("click", () => {
        if (!serverConnected) {
          triggerStartServer();
        }
      });
    }

    const btnDismissPrompt = document.getElementById("bjp-btn-dismiss-prompt");
    if (btnDismissPrompt) {
      btnDismissPrompt.addEventListener("click", () => {
        promptDismissed = true;
        const promptEl = document.getElementById("bjp-server-prompt");
        if (promptEl) promptEl.style.display = "none";
      });
    }

    const btnPromptStart = document.getElementById("bjp-btn-prompt-start");
    if (btnPromptStart) {
      btnPromptStart.addEventListener("click", () => {
        triggerStartServer();
      });
    }
  }

  function triggerStartServer() {
    updateServerIndicator(false, true);

    // 1. Try protocol handler in background iframe (works if user previously ran .bat/.exe)
    try {
      const ifr = document.createElement("iframe");
      ifr.style.display = "none";
      ifr.src = "blackjack-pilot://start";
      document.body.appendChild(ifr);
      setTimeout(() => {
        try { ifr.remove(); } catch (e) {}
      }, 1500);
    } catch (e) {}

    // 2. Try Chrome Native Messaging host
    try {
      if (bgPort) {
        bgPort.postMessage({ type: "start_server" });
      } else {
        connectPort();
        setTimeout(() => {
          if (bgPort) bgPort.postMessage({ type: "start_server" });
        }, 300);
      }
    } catch (e) {
      console.warn("[Blackjack Pilot] Start server error:", e);
    }
  }

  function updateServerIndicator(connected, starting = false, error = null) {
    if (!hudEl) return;
    const pill = document.getElementById("bjp-server-pill");
    const txt = document.getElementById("bjp-server-status-text");
    const btnStart = document.getElementById("bjp-btn-start-server-opt");
    const promptEl = document.getElementById("bjp-server-prompt");
    const promptStartBtn = document.getElementById("bjp-btn-prompt-start");

    if (pill && txt) {
      if (connected) {
        pill.className = "bjp-server-pill connected";
        txt.textContent = "Server: ON";
        pill.title = "AI Engine körs och är ansluten på port 8765";
      } else if (starting) {
        pill.className = "bjp-server-pill starting";
        txt.textContent = "Server: Startar...";
        pill.title = "Startar Blackjack Pilot AI Engine...";
      } else {
        pill.className = "bjp-server-pill disconnected";
        txt.textContent = "Server: OFF";
        pill.title = error ? `AI Server Offline (${error}). Klicka för att starta.` : "AI Server Offline. Klicka för att starta.";
      }
    }

    if (promptEl) {
      if (connected || promptDismissed) {
        promptEl.style.display = "none";
      } else {
        promptEl.style.display = "flex";
      }
    }

    if (promptStartBtn) {
      if (starting) {
        promptStartBtn.textContent = "⏳ Startar Server...";
        promptStartBtn.disabled = true;
      } else if (connected) {
        promptStartBtn.textContent = "✔ Server Igång";
        promptStartBtn.disabled = true;
      } else {
        promptStartBtn.textContent = "⚡ Öppna Server";
        promptStartBtn.disabled = false;
      }
    }

    if (btnStart) {
      if (connected) {
        btnStart.textContent = "✔ Server Igång";
        btnStart.style.backgroundColor = "#238636";
        btnStart.disabled = true;
      } else if (starting) {
        btnStart.textContent = "⏳ Startar Server...";
        btnStart.style.backgroundColor = "#9e6a03";
        btnStart.disabled = true;
      } else {
        btnStart.textContent = "⚡ Öppna Server";
        btnStart.style.backgroundColor = "";
        btnStart.disabled = false;
      }
    }
  }

  function updateHudWithResult(res) {
    if (!hudEl) return;

    // Dealer
    document.getElementById("bjp-dealer-cards").textContent = res.dealer_text || "-";
    document.getElementById("bjp-dealer-total").textContent = `Total: ${res.dealer_sum || "-"}`;

    // Player Cards & Strategy Actions
    const playerHeaderEl = document.getElementById("bjp-player-header");
    const playerCardsEl = document.getElementById("bjp-player-cards");
    const playerTotalEl = document.getElementById("bjp-player-total");
    const playerSingleContent = document.getElementById("bjp-player-single-content");
    const playerActionBadge = document.getElementById("bjp-player-action-badge");
    const multiHandsSublistEl = document.getElementById("bjp-multi-hands-sublist");

    const numChosen = playerPointsRel ? playerPointsRel.length : 0;
    const isMultiMode = numChosen > 1 || (res.player_hands && res.player_hands.length > 1);

    if (isMultiMode) {
      const totalHandsCount = Math.max(numChosen, res.player_hands ? res.player_hands.length : 0);
      if (playerHeaderEl) playerHeaderEl.textContent = `👤 Player (${totalHandsCount} Hands)`;
      if (playerSingleContent) playerSingleContent.style.display = "none";
      if (multiHandsSublistEl) {
        multiHandsSublistEl.style.display = "flex";

        const matchedMap = new Map();
        if (res.player_hands) {
          for (const h of res.player_hands) {
            matchedMap.set(h.hand_idx, h);
          }
        }

        const rows = [];
        for (let i = 1; i <= totalHandsCount; i++) {
          const h = matchedMap.get(i);
          if (h) {
            rows.push(`
              <div class="bjp-hand-subrow" style="display:flex; justify-content:space-between; align-items:center; background:rgba(255,255,255,0.06); padding:4px 8px; border-radius:4px;">
                <div style="display:flex; align-items:center; gap:8px; overflow:hidden;">
                  <span style="font-weight:800; color:#00d2ff; font-size:11px;">H${h.hand_idx}</span>
                  <span style="color:#ffffff; font-size:12px; font-weight:700; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${h.text || "-"}</span>
                  <span style="color:#8b949e; font-size:11px;">(${h.sum || 0})</span>
                </div>
                <span class="bjp-hand-badge" style="background-color:${h.move_color || "#1f6feb"}; font-size:10px; font-weight:800; padding:2.5px 7px; border-radius:3px; color:#ffffff; flex-shrink:0;">
                  ${h.optimal_move}
                </span>
              </div>
            `);
          } else {
            rows.push(`
              <div class="bjp-hand-subrow" style="display:flex; justify-content:space-between; align-items:center; background:rgba(255,255,255,0.04); padding:4px 8px; border-radius:4px;">
                <div style="display:flex; align-items:center; gap:8px; overflow:hidden;">
                  <span style="font-weight:800; color:#8b949e; font-size:11px;">H${i}</span>
                  <span style="color:#8b949e; font-size:12px; font-weight:600;">-</span>
                  <span style="color:#6e7681; font-size:11px;">(0)</span>
                </div>
                <span class="bjp-hand-badge" style="background-color:#30363d; font-size:10px; font-weight:800; padding:2.5px 7px; border-radius:3px; color:#8b949e; flex-shrink:0;">
                  WAITING
                </span>
              </div>
            `);
          }
        }
        multiHandsSublistEl.innerHTML = rows.join("");
      }
    } else {
      const singleHand = (res.player_hands && res.player_hands[0]) || null;
      if (playerHeaderEl) playerHeaderEl.textContent = singleHand ? `👤 Player (Hand 1)` : `👤 Player`;
      if (playerSingleContent) playerSingleContent.style.display = "flex";
      if (playerCardsEl) {
        playerCardsEl.textContent = (singleHand ? singleHand.text : res.player_text) || "-";
      }
      if (playerTotalEl) {
        playerTotalEl.textContent = `Total: ${(singleHand ? singleHand.sum : res.player_sum) || "-"}`;
      }
      if (playerActionBadge) {
        const move = singleHand ? singleHand.optimal_move : res.optimal_move;
        const color = singleHand ? singleHand.move_color : res.move_color;
        if (move && move !== "WAITING" && move !== "") {
          playerActionBadge.style.display = "inline-block";
          playerActionBadge.textContent = move;
          playerActionBadge.style.backgroundColor = color || "#1f6feb";
        } else {
          playerActionBadge.style.display = "none";
        }
      }
      if (multiHandsSublistEl) {
        multiHandsSublistEl.style.display = "none";
        multiHandsSublistEl.innerHTML = "";
      }
    }

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
  function startMultiHandSelection() {
    if (document.getElementById("bjp-snipper-overlay")) return;

    if (!feedRect) {
      alert("Please select the Feed Area (Step 1) first!");
      return;
    }

    const curFeed = getFeedViewportRect();
    if (!curFeed) {
      alert("Could not determine feed coordinates!");
      return;
    }

    const overlay = document.createElement("div");
    overlay.id = "bjp-snipper-overlay";
    overlay.style.cursor = "crosshair";

    // Working copy of player spot points
    let tempPoints = playerPointsRel.map((p) => [p[0], p[1]]);

    const banner = document.createElement("div");
    banner.className = "bjp-snipper-banner bjp-multi-banner";
    banner.innerHTML = `
      <div class="bjp-multi-title">👤 Step 3: Select Player Hands</div>
      <div class="bjp-multi-hint">
        Click on your seat(s) or cards to add or remove player hands.<br>
        (Click an existing number to remove it. Press Enter or Done when finished)
      </div>
      <div style="font-size:12px; font-weight:700; color:#00d2ff; margin-top:2px;" id="bjp-multi-count-status">
        Selected: ${tempPoints.length} hand(s)
      </div>
      <div class="bjp-multi-buttons">
        <button class="bjp-btn bjp-btn-primary" id="bjp-multi-btn-done">✓ Done (${tempPoints.length} hands)</button>
        <button class="bjp-btn bjp-btn-secondary" id="bjp-multi-btn-clear">↺ Clear All</button>
        <button class="bjp-btn bjp-btn-secondary" id="bjp-multi-btn-cancel">✕ Cancel (ESC)</button>
      </div>
    `;
    overlay.appendChild(banner);

    const spotsContainer = document.createElement("div");
    spotsContainer.id = "bjp-multi-temp-spots";
    overlay.appendChild(spotsContainer);

    document.body.appendChild(overlay);

    function updateBannerAndSpots() {
      const statusEl = document.getElementById("bjp-multi-count-status");
      const doneBtn = document.getElementById("bjp-multi-btn-done");
      if (statusEl) statusEl.textContent = `Selected: ${tempPoints.length} hand(s)`;
      if (doneBtn) doneBtn.textContent = `✓ Done (${tempPoints.length} hand${tempPoints.length === 1 ? "" : "s"})`;

      spotsContainer.innerHTML = tempPoints
        .map((pt, idx) => {
          const sx = Math.round(curFeed.x + pt[0] * curFeed.width);
          const sy = Math.round(curFeed.y + pt[1] * curFeed.height);
          return `
            <div class="bjp-spot-marker" style="display:flex; position:fixed; left:${sx}px; top:${sy}px; transform:translate(-50%, -50%); pointer-events:none; z-index:2147483646;">
              <span class="bjp-spot-num">${idx + 1}</span>
            </div>
          `;
        })
        .join("");
    }

    updateBannerAndSpots();

    function finishSelection() {
      playerPointsRel = tempPoints;
      syncZonesToServer();
      applyOverlayPositions();
      saveStoredCalibration();
      cleanup();
    }

    function cleanup() {
      window.removeEventListener("keydown", onKeyDown);
      overlay.remove();
    }

    function onKeyDown(e) {
      if (e.key === "Escape") {
        cleanup();
      } else if (e.key === "Enter") {
        finishSelection();
      }
    }
    window.addEventListener("keydown", onKeyDown);

    overlay.addEventListener("click", (e) => {
      // If clicking inside banner or buttons, do nothing
      if (banner.contains(e.target)) return;

      const clickX = e.clientX;
      const clickY = e.clientY;

      // Check if clicking near an existing spot to remove it (toggle off)
      let removedIdx = -1;
      for (let i = 0; i < tempPoints.length; i++) {
        const sx = curFeed.x + tempPoints[i][0] * curFeed.width;
        const sy = curFeed.y + tempPoints[i][1] * curFeed.height;
        if (Math.hypot(clickX - sx, clickY - sy) < 22) {
          removedIdx = i;
          break;
        }
      }

      if (removedIdx >= 0) {
        tempPoints.splice(removedIdx, 1);
      } else {
        const nx = Math.max(0, Math.min(1, (clickX - curFeed.x) / curFeed.width));
        const ny = Math.max(0, Math.min(1, (clickY - curFeed.y) / curFeed.height));
        tempPoints.push([Number(nx.toFixed(4)), Number(ny.toFixed(4))]);
      }

      updateBannerAndSpots();
    });

    document.getElementById("bjp-multi-btn-done")?.addEventListener("click", (e) => {
      e.stopPropagation();
      finishSelection();
    });
    document.getElementById("bjp-multi-btn-clear")?.addEventListener("click", (e) => {
      e.stopPropagation();
      tempPoints = [];
      updateBannerAndSpots();
    });
    document.getElementById("bjp-multi-btn-cancel")?.addEventListener("click", (e) => {
      e.stopPropagation();
      cleanup();
    });
  }

  function startSelection(target) {
    if (target === "player") {
      startMultiHandSelection();
      return;
    }

    if (document.getElementById("bjp-snipper-overlay")) return;

    if (target === "dealer" && !feedRect) {
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
          playerPointsRel = [];

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
  function renderBoundingBoxes(detections, hands) {
    if (!bboxCanvasEl || !feedRect) return;
    const ctx = bboxCanvasEl.getContext("2d");
    ctx.clearRect(0, 0, bboxCanvasEl.width, bboxCanvasEl.height);

    if (!detections || detections.length === 0) return;

    const curFeed = getFeedViewportRect();
    if (!curFeed) return;

    // Hand labels: subtle text tag H1, H2 above player hand (NO box brackets around hands)
    if (hands && hands.length) {
      for (const hand of hands) {
        if (hand.is_player && hand.hand_idx && hand.bbox_norm) {
          const hx1 = Math.round(hand.bbox_norm[0] * curFeed.width);
          const hy1 = Math.round(hand.bbox_norm[1] * curFeed.height);
          const pHue = (192 + ((hand.hand_idx - 1) * 65)) % 360;
          ctx.fillStyle = `hsla(${pHue}, 95%, 65%, 0.95)`;
          ctx.font = "bold 11px system-ui, sans-serif";
          ctx.fillText(`H${hand.hand_idx}`, hx1, Math.max(12, hy1 - 4));
        }
      }
    }

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

      // Shared Hand Hue: all cards in the same hand share the EXACT same hue
      let hue = 0;
      if (d.category === "dealer" || d.hand_id === "dealer") {
        hue = 42; // Warm casino gold for dealer cards
      } else if (d.category === "player" || (d.hand_id && d.hand_id.startsWith("player_"))) {
        const pIdx = d.hand_idx || (d.hand_id ? parseInt(d.hand_id.split("_")[1], 10) : 1) || 1;
        // Hand 1: 192 (Cyan), Hand 2: 257 (Purple-Blue), Hand 3: 322 (Magenta)
        hue = (192 + (pIdx - 1) * 65) % 360;
      } else if (d.hand_id && d.hand_id.startsWith("table_")) {
        const tIdx = parseInt(d.hand_id.split("_")[1], 10) || 0;
        hue = (115 + tIdx * 70) % 360; // Distinct shared hue per table hand
      } else if (hands && hands.length && d.bbox_norm) {
        // Spatial fallback: check which hand bounds contain this card's center
        const cx = (d.bbox_norm[0] + d.bbox_norm[2]) / 2;
        const cy = (d.bbox_norm[1] + d.bbox_norm[3]) / 2;
        let matchedHue = null;
        for (let i = 0; i < hands.length; i++) {
          const [hx1, hy1, hx2, hy2] = hands[i].bbox_norm;
          if (cx >= hx1 - 0.02 && cx <= hx2 + 0.02 && cy >= hy1 - 0.02 && cy <= hy2 + 0.02) {
            if (hands[i].is_player) {
              const pIdx = hands[i].hand_idx || 1;
              matchedHue = (192 + (pIdx - 1) * 65) % 360;
            } else {
              matchedHue = (115 + i * 70) % 360;
            }
            break;
          }
        }
        hue = matchedHue !== null ? matchedHue : (typeof d.id === "number" ? Math.round((d.id * 137.5) % 360) : 120);
      } else {
        hue = typeof d.id === "number" ? Math.round((d.id * 137.5) % 360) : 120;
      }

      // Subtle translucent color wash over the card (~13% opacity)
      ctx.fillStyle = `hsla(${hue}, 85%, 55%, 0.13)`;
      const r = Math.min(6, Math.min(w, h) * 0.08);
      ctx.beginPath();
      if (ctx.roundRect) {
        ctx.roundRect(x1, y1, w, h, r);
      } else {
        ctx.rect(x1, y1, w, h);
      }
      ctx.fill();

      // Soft hairline border for crisp tint edge
      ctx.strokeStyle = `hsla(${hue}, 90%, 65%, 0.24)`;
      ctx.lineWidth = 1;
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
  // 7. Message Dispatcher & Tab Lifecycle Management
  // ---------------------------------------------------------------------------
  function setHudActive(active) {
    isHudActiveOnThisTab = !!active;

    if (isHudActiveOnThisTab) {
      if (!hudEl || !document.contains(hudEl)) {
        createHud();
      }
      if (hudEl) {
        hudEl.classList.remove("bjp-hidden");
        hudEl.classList.remove("bjp-hidden-tab");
      }
      if (zoneOverlaysEl) {
        zoneOverlaysEl.style.display = "block";
      }
      if (bboxCanvasEl) {
        bboxCanvasEl.style.display = drawBoxes ? "block" : "none";
      }
      applyOverlayPositions();
      connectPort();
    } else {
      if (hudEl) {
        hudEl.classList.add("bjp-hidden");
      }
      if (zoneOverlaysEl) {
        zoneOverlaysEl.style.display = "none";
      }
      if (bboxCanvasEl) {
        bboxCanvasEl.style.display = "none";
      }
      if (feedBoxEl) feedBoxEl.style.display = "none";
      if (dealerBoxEl) dealerBoxEl.style.display = "none";
      if (playerBoxEl) playerBoxEl.style.display = "none";
      if (playerSpotsContainerEl) playerSpotsContainerEl.innerHTML = "";
      clearBoundingBoxes();
      if (isCapturing) {
        stopCapture();
      }
    }
  }

  // Automatically hide overlays whenever the user switches tabs or minimizes
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      // Switched away from tab -> immediately hide HUD, zone reticles, and canvas
      if (hudEl) {
        hudEl.classList.add("bjp-hidden-tab");
      }
      if (zoneOverlaysEl) {
        zoneOverlaysEl.style.display = "none";
      }
      if (bboxCanvasEl) {
        bboxCanvasEl.style.display = "none";
      }
      if (feedBoxEl) feedBoxEl.style.display = "none";
      if (dealerBoxEl) dealerBoxEl.style.display = "none";
      if (playerBoxEl) playerBoxEl.style.display = "none";
      if (playerSpotsContainerEl) playerSpotsContainerEl.innerHTML = "";
    } else {
      // Switched back to tab -> restore overlays ONLY IF this tab was active
      if (hudEl) {
        hudEl.classList.remove("bjp-hidden-tab");
      }
      if (isHudActiveOnThisTab) {
        if (hudEl) {
          hudEl.classList.remove("bjp-hidden");
        }
        if (zoneOverlaysEl) {
          zoneOverlaysEl.style.display = "block";
        }
        if (bboxCanvasEl) {
          bboxCanvasEl.style.display = drawBoxes ? "block" : "none";
        }
        applyOverlayPositions();
      } else {
        if (hudEl) {
          hudEl.classList.add("bjp-hidden");
        }
      }
    }
  });

  // Triggered when user presses the extension icon in browser toolbar
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.action === "toggle_hud") {
      setHudActive(!isHudActiveOnThisTab);
      sendResponse({ toggled: true, active: isHudActiveOnThisTab });
    }
  });

  // Initialization with DOM safety (Starts 100% hidden on all tabs)
  function initAll() {
    createHud();
    initZoneOverlays();
    loadStoredCalibration();
    startPositionTracking();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAll);
  } else {
    initAll();
  }
})();
