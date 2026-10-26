/**
 * Minimal Box-Shaped Chat Console Controller
 * Supports dynamic model selection (DeepSeek, Qwen, Groq OSS) and clean conversation management.
 */

let currentSessionId = "session_" + Math.random().toString(36).substring(2, 9);

document.addEventListener("DOMContentLoaded", () => {
  initChat();
});

function initChat() {
  const form = document.getElementById("chatForm");
  const input = document.getElementById("chatInput");
  const sendBtn = document.getElementById("chatSendBtn");
  const modelSelect = document.getElementById("chatModelSelect");
  const resetBtn = document.getElementById("resetChatBtn");

  if (form) {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const message = input.value.trim();
      if (!message) return;

      const selectedModel = modelSelect ? modelSelect.value : "llama";

      appendMessage("user", message);
      input.value = "";
      input.disabled = true;
      if (sendBtn) sendBtn.disabled = true;

      showTypingIndicator();

      try {
        const response = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            session_id: currentSessionId,
            message: message,
            model: selectedModel,
          }),
        });

        removeTypingIndicator();

        if (!response.ok) {
          const err = await response.json();
          appendMessage("agent", `Error: ${err.detail || "Failed to get response"}`);
          return;
        }

        const data = await response.json();
        appendMessage("agent", data.answer, data.ticket_issued, data.ticket_details);
      } catch (err) {
        removeTypingIndicator();
        appendMessage("agent", `Network Error: ${err.message}`);
      } finally {
        input.disabled = false;
        if (sendBtn) sendBtn.disabled = false;
        input.focus();
      }
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener("click", async () => {
      try {
        await fetch("/api/chat/reset", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: currentSessionId }),
        });

        const messagesContainer = document.getElementById("messagesList");
        if (messagesContainer) {
          messagesContainer.innerHTML = `
            <div class="chat-bubble-card agent">
              <div class="bubble-role-meta">Refund Specialist Agent</div>
              <div class="bubble-content">
                Conversation reset. Hello, I am your customer refund specialist. Please let me know your username and which purchased item you would like to return.
              </div>
            </div>
          `;
        }
      } catch (e) {
        console.error("Reset failed", e);
      }
    });
  }
}

function formatContent(text) {
  if (!text) return "";
  if (typeof marked !== "undefined" && marked.parse) {
    try {
      return marked.parse(text, { breaks: true, gfm: true });
    } catch (e) {
      console.warn("marked parse error", e);
    }
  }

  // Fallback markdown and table parser
  let html = String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.*?)\*/g, "<em>$1</em>");
  html = html.replace(/```([\s\S]*?)```/g, "<pre><code>$1</code></pre>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(/\n/g, "<br>");
  return html;
}

function appendMessage(role, text, ticketIssued = false, ticketDetails = null) {
  const container = document.getElementById("messagesList");
  if (!container) return;

  const card = document.createElement("div");
  card.className = `chat-bubble-card ${role}`;

  const meta = document.createElement("div");
  meta.className = "bubble-role-meta";
  const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  meta.textContent = role === "user" ? `You · ${now}` : `Agent · ${now}`;

  const bubble = document.createElement("div");
  bubble.className = "bubble-content";
  if (role === "agent") {
    bubble.innerHTML = formatContent(text);
  } else {
    bubble.textContent = text;
  }

  card.appendChild(meta);
  card.appendChild(bubble);

  if (ticketIssued && ticketDetails) {
    const ticketBadge = document.createElement("div");
    ticketBadge.className = "chat-ticket-badge";
    ticketBadge.innerHTML = `
      <span>Refund Ticket Issued for <strong>${ticketDetails.user}</strong></span>
      <span>$${ticketDetails.refund_amount}.00</span>
    `;
    bubble.appendChild(ticketBadge);
  }

  container.appendChild(card);
  container.scrollTop = container.scrollHeight;
}

function showTypingIndicator() {
  const container = document.getElementById("messagesList");
  if (!container) return;

  const indicator = document.createElement("div");
  indicator.id = "typingIndicator";
  indicator.className = "chat-bubble-card agent";
  indicator.innerHTML = `
    <div class="bubble-role-meta">Agent</div>
    <div class="bubble-content typing-box">
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <div class="typing-dot"></div>
      <span style="margin-left: 4px;">Processing request...</span>
    </div>
  `;
  container.appendChild(indicator);
  container.scrollTop = container.scrollHeight;
}

function removeTypingIndicator() {
  const el = document.getElementById("typingIndicator");
  if (el) el.remove();
}
