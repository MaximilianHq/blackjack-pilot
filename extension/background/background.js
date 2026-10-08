/**
 * Blackjack Pilot - Background Service Worker
 * Manages WebSocket connection to local AI engine (avoiding HTTPS mixed-content restrictions)
 * and relays streaming frames and inference results to content scripts.
 */

const WS_URL = "ws://127.0.0.1:8765";
let ws = null;
let isConnected = false;
let activePorts = new Set();

function updateBadge(connected) {
  if (connected) {
    chrome.action.setBadgeText({ text: "ON" });
    chrome.action.setBadgeBackgroundColor({ color: "#238636" });
    chrome.action.setTitle({ title: "Blackjack Pilot: AI Server Connected" });
  } else {
    chrome.action.setBadgeText({ text: "OFF" });
    chrome.action.setBadgeBackgroundColor({ color: "#da3633" });
    chrome.action.setTitle({ title: "Blackjack Pilot: AI Server Disconnected (Start server.py)" });
  }
}

function broadcastToPorts(msg) {
  for (const port of activePorts) {
    try {
      port.postMessage(msg);
    } catch (e) {
      activePorts.delete(port);
    }
  }
}

function connectWebSocket() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }

  try {
    console.log("[Background] Connecting to AI Engine at", WS_URL);
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      console.log("[Background] Connected to local AI engine!");
      isConnected = true;
      updateBadge(true);
      broadcastToPorts({ type: "server_status", connected: true });
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        broadcastToPorts({ type: "server_result", payload: data });
      } catch (err) {
        console.warn("[Background] Parse error from server:", err);
      }
    };

    ws.onclose = () => {
      isConnected = false;
      updateBadge(false);
      broadcastToPorts({ type: "server_status", connected: false });
      setTimeout(connectWebSocket, 2000);
    };

    ws.onerror = (err) => {
      console.warn("[Background] WebSocket error:", err);
      isConnected = false;
      updateBadge(false);
    };
  } catch (err) {
    console.error("[Background] Failed to initialize WebSocket:", err);
    isConnected = false;
    updateBadge(false);
    setTimeout(connectWebSocket, 2500);
  }
}

// Initialize connection
connectWebSocket();
setInterval(() => {
  if (!isConnected) {
    connectWebSocket();
  }
}, 3000);

// Toolbar click toggles the on-page HUD overlay
chrome.action.onClicked.addListener((tab) => {
  if (!tab.id) return;
  chrome.tabs.sendMessage(tab.id, { action: "toggle_hud" }, (res) => {
    if (chrome.runtime.lastError) {
      console.log("[Background] Content script not ready on tab, injecting manually...");
      chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ["content/content.js"]
      }, () => {
        chrome.scripting.insertCSS({
          target: { tabId: tab.id },
          files: ["content/content.css"]
        });
      });
    }
  });
});

// Message listener for extension reload commands
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.action === "reload_extension") {
    console.log("[Background] Reload extension signal received.");
    sendResponse({ reloaded: true });
    setTimeout(() => {
      chrome.runtime.reload();
    }, 100);
    return true;
  }
});

// Port connection with content scripts
chrome.runtime.onConnect.addListener((port) => {
  if (port.name === "bjp-channel") {
    activePorts.add(port);
    console.log("[Background] Content script port connected. Active ports:", activePorts.size);

    // Send immediate server status
    port.postMessage({ type: "server_status", connected: isConnected });

    port.onMessage.addListener((msg) => {
      if (!msg) return;

      if (msg.type === "frame") {
        if (ws && ws.readyState === WebSocket.OPEN) {
          // Send base64 frame payload to server
          ws.send(JSON.stringify({ type: "frame", image: msg.image }));
        }
      } else if (msg.type === "command") {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify(msg.payload));
        }
      } else if (msg.type === "get_status") {
        port.postMessage({ type: "server_status", connected: isConnected });
      } else if (msg.type === "reload_extension") {
        console.log("[Background] Reload requested via port.");
        setTimeout(() => {
          chrome.runtime.reload();
        }, 100);
      }
    });

    port.onDisconnect.addListener(() => {
      activePorts.delete(port);
      console.log("[Background] Content script port disconnected. Active ports:", activePorts.size);
    });
  }
});
