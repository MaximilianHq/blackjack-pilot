/**
 * Blackjack Pilot - Popup UI Controller
 */

document.addEventListener("DOMContentLoaded", () => {
  const btnToggleCapture = document.getElementById("btnToggleCapture");
  const btnSelectFeed = document.getElementById("btnSelectFeed");
  const btnSelectDealer = document.getElementById("btnSelectDealer");
  const btnSelectPlayer = document.getElementById("btnSelectPlayer");
  const btnResetZones = document.getElementById("btnResetZones");
  const chkShowHud = document.getElementById("chkShowHud");
  const chkDrawBoxes = document.getElementById("chkDrawBoxes");
  const rangeConf = document.getElementById("rangeConf");
  const valConf = document.getElementById("valConf");
  const rangeIou = document.getElementById("rangeIou");
  const valIou = document.getElementById("valIou");
  const spinDecks = document.getElementById("spinDecks");
  const btnResetCounter = document.getElementById("btnResetCounter");
  const btnResetStats = document.getElementById("btnResetStats");
  const serverStatus = document.getElementById("serverStatus");
  const txtFeedStatus = document.getElementById("txtFeedStatus");
  const txtDealerStatus = document.getElementById("txtDealerStatus");
  const txtPlayerStatus = document.getElementById("txtPlayerStatus");

  function sendToContent(msg, callback) {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (!tabs[0] || !tabs[0].id) return;
      chrome.tabs.sendMessage(tabs[0].id, msg, (response) => {
        if (chrome.runtime.lastError) {
          console.warn("[Popup] Message error:", chrome.runtime.lastError.message);
          return;
        }
        if (callback && response) callback(response);
      });
    });
  }

  // Poll state from content script on popup open
  function refreshState() {
    sendToContent({ action: "get_state" }, (res) => {
      if (!res) return;

      // Server status
      if (res.serverConnected) {
        serverStatus.className = "status-indicator connected";
        serverStatus.querySelector(".status-text").textContent = "Server: Connected";
      } else {
        serverStatus.className = "status-indicator disconnected";
        serverStatus.querySelector(".status-text").textContent = "Server: Disconnected";
      }

      // Capture state
      if (res.isCapturing) {
        btnToggleCapture.textContent = "⏹ Stop Capture";
        btnToggleCapture.classList.add("recording");
      } else {
        btnToggleCapture.textContent = "▶ Start Browser Capture";
        btnToggleCapture.classList.remove("recording");
      }

      // Zone statuses
      txtFeedStatus.textContent = res.feedSelected ? `Feed: Active (${res.feedDim})` : "Feed: None";
      txtDealerStatus.textContent = res.dealerSelected ? "Dealer Zone: Active" : "Dealer Zone: None";
      txtPlayerStatus.textContent = res.playerSelected ? "Player Zone: Active" : "Player Zone: None";

      chkShowHud.checked = !!res.showHud;
      chkDrawBoxes.checked = !!res.drawBoxes;
    });
  }

  refreshState();
  const pollTimer = setInterval(refreshState, 1500);
  window.addEventListener("unload", () => clearInterval(pollTimer));

  // Capture toggle
  btnToggleCapture.addEventListener("click", () => {
    sendToContent({ action: "toggle_capture" }, refreshState);
  });

  // Zone selectors
  btnSelectFeed.addEventListener("click", () => {
    sendToContent({ action: "start_selection", target: "feed" });
    window.close(); // Close popup so user can drag selection on webpage
  });

  btnSelectDealer.addEventListener("click", () => {
    sendToContent({ action: "start_selection", target: "dealer" });
    window.close();
  });

  btnSelectPlayer.addEventListener("click", () => {
    sendToContent({ action: "start_selection", target: "player" });
    window.close();
  });

  btnResetZones.addEventListener("click", () => {
    sendToContent({ action: "reset_zones" }, refreshState);
  });

  // HUD and Box Toggles
  chkShowHud.addEventListener("change", () => {
    sendToContent({ action: "set_hud_visible", visible: chkShowHud.checked });
  });

  chkDrawBoxes.addEventListener("change", () => {
    sendToContent({ action: "set_draw_boxes", visible: chkDrawBoxes.checked });
  });

  // Sensitivity Sliders
  rangeConf.addEventListener("input", () => {
    valConf.textContent = `${rangeConf.value}%`;
    sendToContent({
      action: "set_thresholds",
      conf: rangeConf.value / 100,
      iou: rangeIou.value / 100,
    });
  });

  rangeIou.addEventListener("input", () => {
    valIou.textContent = `${rangeIou.value}%`;
    sendToContent({
      action: "set_thresholds",
      conf: rangeConf.value / 100,
      iou: rangeIou.value / 100,
    });
  });

  spinDecks.addEventListener("change", () => {
    sendToContent({ action: "set_decks", decks: parseInt(spinDecks.value, 10) });
  });

  // Resets
  btnResetCounter.addEventListener("click", () => {
    sendToContent({ action: "reset_counter" });
  });

  btnResetStats.addEventListener("click", () => {
    sendToContent({ action: "reset_stats" });
  });
});

