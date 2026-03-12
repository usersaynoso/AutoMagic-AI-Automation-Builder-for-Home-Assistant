/**
 * AutoMagic - AI Automation Builder Card
 * Custom Lovelace panel element for Home Assistant
 */

import {
  LitElement,
  html,
  css,
} from "https://unpkg.com/lit-element@4.1.1/lit-element.js?module";

const STATES = {
  IDLE: "idle",
  LOADING: "loading",
  PREVIEW: "preview",
  INSTALLING: "installing",
  SUCCESS: "success",
  ERROR: "error",
};

const TABS = {
  CREATE: "create",
  HISTORY: "history",
};

class AutoMagicCard extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      config: { type: Object },
      _state: { type: String },
      _activeTab: { type: String },
      _prompt: { type: String },
      _yaml: { type: String },
      _summary: { type: String },
      _parsedAutomation: { type: Object },
      _error: { type: String },
      _generationJobId: { type: String },
      _loadingMessage: { type: String },
      _loadingDetail: { type: String },
      _loadingElapsedSeconds: { type: Number },
      _installedAlias: { type: String },
      _showYaml: { type: Boolean },
      _entityCount: { type: Number },
      _history: { type: Array },
      _expandedHistory: { type: Number },
      _isPanel: { type: Boolean },
    };
  }

  constructor() {
    super();
    this._state = STATES.IDLE;
    this._activeTab = TABS.CREATE;
    this._prompt = "";
    this._yaml = "";
    this._summary = "";
    this._parsedAutomation = null;
    this._error = "";
    this._generationJobId = "";
    this._loadingMessage = "";
    this._loadingDetail = "";
    this._loadingElapsedSeconds = 0;
    this._installedAlias = "";
    this._showYaml = false;
    this._entityCount = 0;
    this._history = [];
    this._expandedHistory = -1;
    this._isPanel = false;
    this._statusPollHandle = null;
  }

  setConfig(config) {
    this.config = config;
  }

  set panel(val) {
    this._isPanel = true;
  }

  connectedCallback() {
    super.connectedCallback();
    this._fetchEntityCount();
    this._fetchHistory();
  }

  disconnectedCallback() {
    this._clearGenerationPolling();
    super.disconnectedCallback();
  }

  async _fetchEntityCount() {
    try {
      const resp = await this._apiGet("/api/automagic/entities");
      if (resp && resp.entities) {
        this._entityCount = resp.entities.length;
      }
    } catch {
      // Silently ignore
    }
  }

  async _fetchHistory() {
    try {
      const resp = await this._apiGet("/api/automagic/history");
      if (resp && resp.history) {
        this._history = resp.history;
      }
    } catch {
      // Silently ignore
    }
  }

  async _apiPost(path, body) {
    const resp = await fetch(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.hass.auth.data.access_token}`,
      },
      body: JSON.stringify(body),
    });
    return resp.json();
  }

  async _apiGet(path) {
    const resp = await fetch(path, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${this.hass.auth.data.access_token}`,
      },
    });
    return resp.json();
  }

  async _handleGenerate() {
    const prompt = this._prompt.trim();
    if (!prompt) return;

    this._clearGenerationPolling();
    this._state = STATES.LOADING;
    this._error = "";
    this._yaml = "";
    this._summary = "";
    this._parsedAutomation = null;
    this._loadingMessage = "Submitting your request...";
    this._loadingElapsedSeconds = 0;
    this._loadingDetail = "Submitting your request to the server.";

    try {
      const result = await this._apiPost("/api/automagic/generate", {
        prompt,
      });

      if (result.error) {
        this._state = STATES.ERROR;
        this._error = result.error;
        return;
      }

      if (!result.job_id) {
        throw new Error("Server did not return a generation job id");
      }

      this._generationJobId = result.job_id;
      this._updateLoadingState(result);
      this._scheduleGenerationPoll(result.poll_after_ms || 1000);
    } catch (err) {
      this._state = STATES.ERROR;
      this._error = `Request failed: ${err.message}`;
    }
  }

  async _handleInstall() {
    if (!this._yaml) return;

    this._state = STATES.INSTALLING;
    this._error = "";

    try {
      const result = await this._apiPost("/api/automagic/install", {
        yaml: this._yaml,
        prompt: this._prompt,
        summary: this._summary,
      });

      if (result.success) {
        this._installedAlias = result.alias || "Automation";
        this._state = STATES.SUCCESS;
        this._fetchHistory();
      } else {
        this._state = STATES.ERROR;
        this._error = result.error || "Installation failed";
      }
    } catch (err) {
      this._state = STATES.ERROR;
      this._error = `Install failed: ${err.message}`;
    }
  }

  _handleReset() {
    this._clearGenerationPolling();
    this._state = STATES.IDLE;
    this._prompt = "";
    this._yaml = "";
    this._summary = "";
    this._parsedAutomation = null;
    this._error = "";
    this._generationJobId = "";
    this._loadingMessage = "";
    this._loadingDetail = "";
    this._loadingElapsedSeconds = 0;
    this._installedAlias = "";
    this._showYaml = false;
  }

  _handleRetry() {
    this._clearGenerationPolling();
    this._state = STATES.IDLE;
    this._error = "";
    this._generationJobId = "";
    this._loadingMessage = "";
    this._loadingDetail = "";
    this._loadingElapsedSeconds = 0;
  }

  _clearGenerationPolling() {
    if (this._statusPollHandle !== null) {
      window.clearTimeout(this._statusPollHandle);
      this._statusPollHandle = null;
    }
  }

  _scheduleGenerationPoll(delayMs = 2000) {
    this._clearGenerationPolling();
    this._statusPollHandle = window.setTimeout(() => {
      this._pollGenerationJob();
    }, delayMs);
  }

  async _pollGenerationJob() {
    if (!this._generationJobId || this._state !== STATES.LOADING) return;

    try {
      const result = await this._apiGet(`/api/automagic/generate/${this._generationJobId}`);

      if (result.error && !result.status) {
        this._clearGenerationPolling();
        this._state = STATES.ERROR;
        this._error = result.error;
        return;
      }

      this._updateLoadingState(result);

      if (result.status === "completed") {
        this._clearGenerationPolling();
        this._yaml = result.yaml || "";
        this._summary = result.summary || "";
        this._parsedAutomation = this._parseYaml(this._yaml);
        this._generationJobId = "";
        this._state = STATES.PREVIEW;
        return;
      }

      if (result.status === "error") {
        this._clearGenerationPolling();
        this._generationJobId = "";
        this._state = STATES.ERROR;
        this._error = result.error || "Generation failed";
        return;
      }

      this._scheduleGenerationPoll(result.poll_after_ms || 2000);
    } catch (err) {
      this._clearGenerationPolling();
      this._state = STATES.ERROR;
      this._error = `Request failed: ${err.message}`;
    }
  }

  _updateLoadingState(result) {
    this._loadingElapsedSeconds = Number(result.elapsed_seconds || 0);

    const statusMessage = result.message || "Generating your automation...";
    const detailParts = [];
    if (result.detail) detailParts.push(result.detail);
    if (result.backend_status && result.backend_status.message) {
      detailParts.push(result.backend_status.message);
    }

    if (detailParts.length === 0) {
      detailParts.push(
        this._loadingElapsedSeconds >= 60
          ? "The request is still active on the server. Slower local models can take a few minutes."
          : "This can take a few minutes depending on your model and hardware."
      );
    }

    this._loadingMessage = statusMessage;
    this._loadingDetail = detailParts.join(" ");
  }

  _parseYaml(yamlStr) {
    if (!yamlStr) return null;

    const automation = {
      alias: "",
      triggers: [],
      conditions: [],
      actions: [],
    };

    try {
      const lines = yamlStr.split("\n");
      let currentSection = null;
      let currentItem = [];

      const aliasMatch = yamlStr.match(/^alias:\s*(.+)$/m);
      if (aliasMatch) automation.alias = aliasMatch[1].trim().replace(/^["']|["']$/g, "");

      for (const line of lines) {
        if (line.match(/^triggers:/)) { currentSection = "triggers"; continue; }
        if (line.match(/^conditions:/)) { currentSection = "conditions"; continue; }
        if (line.match(/^actions:/)) { currentSection = "actions"; continue; }
        if (line.match(/^(alias|description|mode|id):/)) { currentSection = null; continue; }

        if (currentSection && line.trim().startsWith("- ")) {
          if (currentItem.length > 0) {
            automation[currentSection].push(currentItem.join(" ").trim());
          }
          currentItem = [line.trim().substring(2)];
        } else if (currentSection && line.trim() && !line.trim().startsWith("#")) {
          currentItem.push(line.trim());
        }
      }
      if (currentSection && currentItem.length > 0) {
        automation[currentSection].push(currentItem.join(" ").trim());
      }
    } catch {
      // If parsing fails, just return minimal info
    }

    return automation;
  }

  _describeTrigger(trigStr) {
    if (trigStr.includes("trigger: state")) {
      const entityMatch = trigStr.match(/entity_id:\s*([\w.]+)/);
      const toMatch = trigStr.match(/to:\s*["']?(\w+)["']?/);
      const entity = entityMatch ? entityMatch[1] : "entity";
      const toState = toMatch ? ` \u2192 ${toMatch[1]}` : "";
      return `${entity} state changes${toState}`;
    }
    if (trigStr.includes("trigger: time")) {
      const atMatch = trigStr.match(/at:\s*["']?([\d:]+)["']?/);
      return atMatch ? `Time: ${atMatch[1]}` : "Time trigger";
    }
    if (trigStr.includes("trigger: sun")) {
      return trigStr.includes("sunset") ? "At sunset" : "At sunrise";
    }
    return trigStr.substring(0, 60);
  }

  _describeAction(actStr) {
    const actionMatch = actStr.match(/action:\s*([\w.]+)/);
    const entityMatch = actStr.match(/entity_id:\s*([\w.]+)/);
    const action = actionMatch ? actionMatch[1] : "action";
    const entity = entityMatch ? ` \u2192 ${entityMatch[1]}` : "";
    return `${action}${entity}`;
  }

  _describeCondition(condStr) {
    if (condStr.includes("condition: time")) {
      const afterMatch = condStr.match(/after:\s*["']?([\d:]+)["']?/);
      const beforeMatch = condStr.match(/before:\s*["']?([\d:]+)["']?/);
      let desc = "Time";
      if (afterMatch) desc += ` after ${afterMatch[1]}`;
      if (beforeMatch) desc += ` before ${beforeMatch[1]}`;
      return desc;
    }
    if (condStr.includes("condition: state")) {
      const entityMatch = condStr.match(/entity_id:\s*([\w.]+)/);
      return entityMatch ? `${entityMatch[1]} state check` : "State condition";
    }
    return condStr.substring(0, 60);
  }

  async _copyYaml(yamlText) {
    const text = yamlText || this._yaml;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
  }

  _formatTime(isoStr) {
    try {
      const d = new Date(isoStr);
      return d.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return isoStr;
    }
  }

  _formatDuration(totalSeconds) {
    const seconds = Math.max(0, Number(totalSeconds || 0));
    const minutes = Math.floor(seconds / 60);
    const remainder = String(seconds % 60).padStart(2, "0");
    return `${minutes}:${remainder}`;
  }

  render() {
    return html`
      <div class="root ${this._isPanel ? "panel-mode" : ""}">
        <div class="container">
          <div class="header">
            <div class="header-left">
              <ha-icon icon="mdi:robot" class="header-icon"></ha-icon>
              <span class="header-title">AutoMagic</span>
            </div>
            ${this._entityCount > 0
              ? html`<span class="entity-chip">
                  <ha-icon icon="mdi:home-assistant" class="chip-icon"></ha-icon>
                  ${this._entityCount} entities
                </span>`
              : ""}
          </div>

          <div class="tabs">
            <button
              class="tab ${this._activeTab === TABS.CREATE ? "active" : ""}"
              @click=${() => (this._activeTab = TABS.CREATE)}
            >
              <ha-icon icon="mdi:creation"></ha-icon>
              Create
            </button>
            <button
              class="tab ${this._activeTab === TABS.HISTORY ? "active" : ""}"
              @click=${() => {
                this._activeTab = TABS.HISTORY;
                this._fetchHistory();
              }}
            >
              <ha-icon icon="mdi:history"></ha-icon>
              History
              ${this._history.length > 0
                ? html`<span class="tab-badge">${this._history.length}</span>`
                : ""}
            </button>
          </div>

          <div class="content">
            ${this._activeTab === TABS.CREATE
              ? this._renderCreate()
              : this._renderHistory()}
          </div>
        </div>
      </div>
    `;
  }

  _renderCreate() {
    switch (this._state) {
      case STATES.IDLE:
        return this._renderIdle();
      case STATES.LOADING:
        return this._renderLoading();
      case STATES.PREVIEW:
        return this._renderPreview();
      case STATES.INSTALLING:
        return this._renderInstalling();
      case STATES.SUCCESS:
        return this._renderSuccess();
      case STATES.ERROR:
        return this._renderError();
      default:
        return this._renderIdle();
    }
  }

  _renderIdle() {
    return html`
      <div class="input-section">
        <p class="input-label">Describe what you want automated in plain English.</p>
        <textarea
          class="prompt-input"
          rows="4"
          placeholder="e.g. Flash the hallway lights red when the front door opens after 10pm"
          .value=${this._prompt}
          @input=${(e) => (this._prompt = e.target.value)}
          @keydown=${(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              this._handleGenerate();
            }
          }}
        ></textarea>
        <div class="input-footer">
          <span class="hint">Press Enter to generate, Shift+Enter for new line</span>
          <button
            class="btn btn-primary"
            @click=${this._handleGenerate}
            ?disabled=${!this._prompt.trim()}
          >
            <ha-icon icon="mdi:auto-fix"></ha-icon>
            Generate Automation
          </button>
        </div>
      </div>
    `;
  }

  _renderLoading() {
    return html`
      <div class="loading-section">
        <ha-circular-progress indeterminate></ha-circular-progress>
        <p class="loading-text">${this._loadingMessage || "Generating your automation..."}</p>
        <p class="loading-sub">${this._loadingDetail}</p>
        <span class="loading-meta">Elapsed: ${this._formatDuration(this._loadingElapsedSeconds)}</span>
      </div>
    `;
  }

  _renderPreview() {
    const auto = this._parsedAutomation;

    return html`
      <div class="preview-section">
        ${auto && auto.alias
          ? html`<h3 class="preview-title">${auto.alias}</h3>`
          : ""}
        <div class="summary-card">
          <ha-icon icon="mdi:check-circle-outline" class="summary-icon"></ha-icon>
          <span class="summary-text">${this._summary}</span>
        </div>

        ${auto ? this._renderAutomationBreakdown(auto) : ""}

        <details class="yaml-toggle" ?open=${this._showYaml}>
          <summary @click=${() => (this._showYaml = !this._showYaml)}>
            <ha-icon icon="mdi:code-braces"></ha-icon>
            View YAML
            <ha-icon icon=${this._showYaml ? "mdi:chevron-up" : "mdi:chevron-down"} class="chevron"></ha-icon>
          </summary>
          <div class="yaml-container">
            <pre class="yaml-code">${this._yaml}</pre>
            <button class="copy-btn" @click=${() => this._copyYaml()} title="Copy YAML">
              <ha-icon icon="mdi:content-copy"></ha-icon>
            </button>
          </div>
        </details>

        <div class="action-buttons">
          <button class="btn btn-secondary" @click=${this._handleReset}>
            <ha-icon icon="mdi:refresh"></ha-icon>
            Start Over
          </button>
          <button class="btn btn-primary" @click=${this._handleInstall}>
            <ha-icon icon="mdi:download"></ha-icon>
            Install Automation
          </button>
        </div>
      </div>
    `;
  }

  _renderAutomationBreakdown(auto) {
    return html`
      <div class="breakdown">
        ${auto.triggers.map(
          (t) => html`
            <div class="breakdown-row">
              <span class="breakdown-icon trigger-icon">
                <ha-icon icon="mdi:flash"></ha-icon>
              </span>
              <span class="breakdown-label">TRIGGER</span>
              <span class="breakdown-desc">${this._describeTrigger(t)}</span>
            </div>
          `
        )}
        ${auto.conditions.map(
          (c) => html`
            <div class="breakdown-row">
              <span class="breakdown-icon condition-icon">
                <ha-icon icon="mdi:filter-outline"></ha-icon>
              </span>
              <span class="breakdown-label">CONDITION</span>
              <span class="breakdown-desc">${this._describeCondition(c)}</span>
            </div>
          `
        )}
        ${auto.actions.map(
          (a) => html`
            <div class="breakdown-row">
              <span class="breakdown-icon action-icon">
                <ha-icon icon="mdi:play-circle-outline"></ha-icon>
              </span>
              <span class="breakdown-label">ACTION</span>
              <span class="breakdown-desc">${this._describeAction(a)}</span>
            </div>
          `
        )}
      </div>
    `;
  }

  _renderInstalling() {
    return html`
      <div class="loading-section">
        <ha-circular-progress indeterminate></ha-circular-progress>
        <p class="loading-text">Installing automation...</p>
        <p class="loading-sub">Writing YAML file and reloading automations</p>
      </div>
    `;
  }

  _renderSuccess() {
    return html`
      <div class="success-section">
        <div class="success-banner">
          <ha-icon icon="mdi:check-circle" class="success-icon"></ha-icon>
          <div class="success-content">
            <p class="success-title">Automation Installed!</p>
            <p class="success-alias">${this._installedAlias}</p>
          </div>
        </div>
        <button class="btn btn-primary full-width" @click=${this._handleReset}>
          <ha-icon icon="mdi:plus"></ha-icon>
          Create Another
        </button>
      </div>
    `;
  }

  _renderError() {
    return html`
      <div class="error-section">
        <div class="error-banner">
          <ha-icon icon="mdi:alert-circle" class="error-icon"></ha-icon>
          <span class="error-text">${this._error}</span>
        </div>
        <div class="action-buttons">
          <button class="btn btn-secondary" @click=${this._handleReset}>
            <ha-icon icon="mdi:refresh"></ha-icon>
            Start Over
          </button>
          <button class="btn btn-primary" @click=${this._handleRetry}>
            <ha-icon icon="mdi:reload"></ha-icon>
            Try Again
          </button>
        </div>
      </div>
    `;
  }

  _renderHistory() {
    if (this._history.length === 0) {
      return html`
        <div class="empty-state">
          <ha-icon icon="mdi:history" class="empty-icon"></ha-icon>
          <p class="empty-title">No automations yet</p>
          <p class="empty-sub">Automations you create will appear here</p>
          <button class="btn btn-primary" @click=${() => (this._activeTab = TABS.CREATE)}>
            <ha-icon icon="mdi:plus"></ha-icon>
            Create Your First
          </button>
        </div>
      `;
    }

    return html`
      <div class="history-list">
        ${this._history.map(
          (item, i) => html`
            <div
              class="history-item ${this._expandedHistory === i ? "expanded" : ""}"
              @click=${() =>
                (this._expandedHistory = this._expandedHistory === i ? -1 : i)}
            >
              <div class="history-header">
                <div class="history-info">
                  <span class="history-alias">${item.alias || "Untitled"}</span>
                  <span class="history-time">${this._formatTime(item.timestamp)}</span>
                </div>
                <div class="history-badges">
                  ${item.success
                    ? html`<span class="badge badge-success">Installed</span>`
                    : html`<span class="badge badge-error">Failed</span>`}
                  <ha-icon
                    icon=${this._expandedHistory === i ? "mdi:chevron-up" : "mdi:chevron-down"}
                    class="history-chevron"
                  ></ha-icon>
                </div>
              </div>
              ${this._expandedHistory === i
                ? html`
                    <div class="history-detail" @click=${(e) => e.stopPropagation()}>
                      ${item.prompt
                        ? html`<div class="detail-row">
                            <span class="detail-label">Prompt</span>
                            <span class="detail-value">${item.prompt}</span>
                          </div>`
                        : ""}
                      ${item.summary
                        ? html`<div class="detail-row">
                            <span class="detail-label">Summary</span>
                            <span class="detail-value">${item.summary}</span>
                          </div>`
                        : ""}
                      ${item.yaml
                        ? html`
                            <div class="detail-yaml">
                              <pre class="yaml-code">${item.yaml}</pre>
                              <button
                                class="copy-btn"
                                @click=${() => this._copyYaml(item.yaml)}
                                title="Copy YAML"
                              >
                                <ha-icon icon="mdi:content-copy"></ha-icon>
                              </button>
                            </div>
                          `
                        : ""}
                    </div>
                  `
                : ""}
            </div>
          `
        )}
      </div>
    `;
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }

      /* Panel mode — full viewport when used as sidebar panel */
      .root.panel-mode {
        min-height: 100vh;
        background: var(--primary-background-color);
        display: flex;
        justify-content: center;
        padding: 24px;
        box-sizing: border-box;
      }
      .root.panel-mode .container {
        max-width: 680px;
        width: 100%;
      }

      /* Container */
      .container {
        display: flex;
        flex-direction: column;
        gap: 0;
      }

      /* Header */
      .header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 20px 24px 16px;
      }
      .header-left {
        display: flex;
        align-items: center;
        gap: 10px;
      }
      .header-icon {
        --mdc-icon-size: 28px;
        color: var(--primary-color);
      }
      .header-title {
        font-size: 1.4em;
        font-weight: 600;
        color: var(--primary-text-color);
        letter-spacing: -0.01em;
      }
      .entity-chip {
        display: flex;
        align-items: center;
        gap: 4px;
        font-size: 0.8em;
        background: var(--primary-color);
        color: var(--text-primary-color, #fff);
        padding: 4px 12px;
        border-radius: 16px;
        font-weight: 500;
      }
      .chip-icon {
        --mdc-icon-size: 14px;
      }

      /* Tabs */
      .tabs {
        display: flex;
        gap: 0;
        padding: 0 24px;
        border-bottom: 1px solid var(--divider-color);
      }
      .tab {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 10px 20px;
        border: none;
        background: none;
        color: var(--secondary-text-color);
        font-size: 0.9em;
        font-weight: 500;
        cursor: pointer;
        border-bottom: 2px solid transparent;
        transition: color 0.2s, border-color 0.2s;
        font-family: inherit;
        --mdc-icon-size: 18px;
        position: relative;
      }
      .tab:hover {
        color: var(--primary-text-color);
      }
      .tab.active {
        color: var(--primary-color);
        border-bottom-color: var(--primary-color);
      }
      .tab-badge {
        font-size: 0.75em;
        background: var(--secondary-text-color);
        color: var(--text-primary-color, #fff);
        padding: 1px 7px;
        border-radius: 10px;
        min-width: 18px;
        text-align: center;
      }
      .tab.active .tab-badge {
        background: var(--primary-color);
      }

      /* Content area */
      .content {
        padding: 24px;
      }

      /* Buttons */
      .btn {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 10px 20px;
        border: none;
        border-radius: 8px;
        font-size: 0.95em;
        font-weight: 500;
        cursor: pointer;
        transition: all 0.15s ease;
        font-family: inherit;
        --mdc-icon-size: 18px;
        line-height: 1.2;
      }
      .btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
      }
      .btn-primary {
        background: var(--primary-color);
        color: var(--text-primary-color, #fff);
      }
      .btn-primary:hover:not(:disabled) {
        filter: brightness(1.1);
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
      }
      .btn-primary:active:not(:disabled) {
        filter: brightness(0.95);
      }
      .btn-secondary {
        background: transparent;
        color: var(--primary-text-color);
        border: 1px solid var(--divider-color);
      }
      .btn-secondary:hover:not(:disabled) {
        background: var(--secondary-background-color, rgba(0,0,0,0.05));
      }
      .full-width {
        width: 100%;
        justify-content: center;
      }

      /* Input */
      .input-section {
        display: flex;
        flex-direction: column;
        gap: 12px;
      }
      .input-label {
        font-size: 0.95em;
        color: var(--secondary-text-color);
        margin: 0;
        line-height: 1.4;
      }
      .prompt-input {
        width: 100%;
        min-height: 90px;
        padding: 14px 16px;
        border: 2px solid var(--divider-color);
        border-radius: 12px;
        background: var(--card-background-color, var(--primary-background-color));
        color: var(--primary-text-color);
        font-family: inherit;
        font-size: 1em;
        resize: vertical;
        box-sizing: border-box;
        transition: border-color 0.15s;
        line-height: 1.5;
      }
      .prompt-input:focus {
        outline: none;
        border-color: var(--primary-color);
      }
      .prompt-input::placeholder {
        color: var(--secondary-text-color);
        opacity: 0.6;
      }
      .input-footer {
        display: flex;
        justify-content: space-between;
        align-items: center;
      }
      .hint {
        font-size: 0.8em;
        color: var(--secondary-text-color);
        opacity: 0.7;
      }

      /* Loading */
      .loading-section {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 12px;
        padding: 48px 0;
      }
      .loading-text {
        color: var(--primary-text-color);
        font-size: 1.05em;
        font-weight: 500;
        margin: 0;
      }
      .loading-sub {
        color: var(--secondary-text-color);
        font-size: 0.85em;
        margin: 0;
        text-align: center;
        line-height: 1.5;
        max-width: 32rem;
      }
      .loading-meta {
        font-size: 0.78em;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: var(--secondary-text-color);
        padding: 5px 10px;
        border-radius: 999px;
        border: 1px solid var(--divider-color);
      }

      /* Preview */
      .preview-section {
        display: flex;
        flex-direction: column;
        gap: 20px;
      }
      .preview-title {
        margin: 0;
        font-size: 1.15em;
        font-weight: 600;
        color: var(--primary-text-color);
      }
      .summary-card {
        display: flex;
        align-items: flex-start;
        gap: 10px;
        padding: 14px 16px;
        background: var(--primary-background-color);
        border-radius: 12px;
        border: 1px solid var(--divider-color);
      }
      .summary-icon {
        --mdc-icon-size: 22px;
        color: var(--success-color, #4caf50);
        flex-shrink: 0;
        margin-top: 1px;
      }
      .summary-text {
        color: var(--primary-text-color);
        line-height: 1.5;
        font-size: 0.95em;
      }

      /* Breakdown */
      .breakdown {
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      .breakdown-row {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 10px 14px;
        background: var(--primary-background-color);
        border-radius: 10px;
        border: 1px solid var(--divider-color);
      }
      .breakdown-icon {
        display: flex;
        align-items: center;
        --mdc-icon-size: 20px;
        flex-shrink: 0;
      }
      .trigger-icon {
        color: var(--warning-color, #ff9800);
      }
      .condition-icon {
        color: var(--info-color, #2196f3);
      }
      .action-icon {
        color: var(--success-color, #4caf50);
      }
      .breakdown-label {
        font-size: 0.7em;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--secondary-text-color);
        min-width: 76px;
      }
      .breakdown-desc {
        color: var(--primary-text-color);
        font-size: 0.9em;
        overflow: hidden;
        text-overflow: ellipsis;
      }

      /* YAML toggle */
      .yaml-toggle {
        border: 1px solid var(--divider-color);
        border-radius: 12px;
        overflow: hidden;
      }
      .yaml-toggle summary {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 12px 16px;
        cursor: pointer;
        font-size: 0.9em;
        font-weight: 500;
        color: var(--secondary-text-color);
        user-select: none;
        list-style: none;
        --mdc-icon-size: 18px;
      }
      .yaml-toggle summary::-webkit-details-marker {
        display: none;
      }
      .yaml-toggle summary .chevron {
        margin-left: auto;
      }
      .yaml-container {
        position: relative;
        padding: 16px;
        background: var(--primary-background-color);
        border-top: 1px solid var(--divider-color);
      }
      .yaml-code {
        margin: 0;
        white-space: pre-wrap;
        word-break: break-word;
        font-size: 0.83em;
        color: var(--primary-text-color);
        font-family: "Roboto Mono", "SF Mono", "Courier New", monospace;
        line-height: 1.5;
      }
      .copy-btn {
        position: absolute;
        top: 10px;
        right: 10px;
        background: var(--card-background-color);
        border: 1px solid var(--divider-color);
        border-radius: 6px;
        padding: 6px;
        cursor: pointer;
        --mdc-icon-size: 16px;
        color: var(--secondary-text-color);
        display: flex;
        transition: all 0.15s;
      }
      .copy-btn:hover {
        background: var(--divider-color);
        color: var(--primary-text-color);
      }

      /* Action buttons */
      .action-buttons {
        display: flex;
        justify-content: flex-end;
        gap: 10px;
      }

      /* Success */
      .success-section {
        display: flex;
        flex-direction: column;
        gap: 20px;
      }
      .success-banner {
        display: flex;
        align-items: center;
        gap: 14px;
        padding: 20px;
        background: rgba(76, 175, 80, 0.1);
        border: 1px solid rgba(76, 175, 80, 0.3);
        border-radius: 12px;
      }
      .success-icon {
        --mdc-icon-size: 36px;
        color: var(--success-color, #4caf50);
        flex-shrink: 0;
      }
      .success-content {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .success-title {
        font-weight: 600;
        font-size: 1.05em;
        color: var(--primary-text-color);
        margin: 0;
      }
      .success-alias {
        color: var(--secondary-text-color);
        font-size: 0.9em;
        margin: 0;
      }

      /* Error */
      .error-section {
        display: flex;
        flex-direction: column;
        gap: 20px;
      }
      .error-banner {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        padding: 16px;
        background: rgba(244, 67, 54, 0.1);
        border: 1px solid rgba(244, 67, 54, 0.3);
        border-radius: 12px;
      }
      .error-icon {
        --mdc-icon-size: 22px;
        color: var(--error-color, #f44336);
        flex-shrink: 0;
        margin-top: 1px;
      }
      .error-text {
        color: var(--primary-text-color);
        font-size: 0.9em;
        line-height: 1.4;
      }

      /* Empty state */
      .empty-state {
        text-align: center;
        padding: 40px 20px;
      }
      .empty-icon {
        --mdc-icon-size: 48px;
        color: var(--divider-color);
        margin-bottom: 12px;
      }
      .empty-title {
        font-size: 1.1em;
        font-weight: 500;
        color: var(--primary-text-color);
        margin: 0 0 4px;
      }
      .empty-sub {
        font-size: 0.9em;
        color: var(--secondary-text-color);
        margin: 0 0 20px;
      }

      /* History */
      .history-list {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .history-item {
        border: 1px solid var(--divider-color);
        border-radius: 12px;
        overflow: hidden;
        cursor: pointer;
        transition: border-color 0.15s;
      }
      .history-item:hover {
        border-color: var(--primary-color);
      }
      .history-item.expanded {
        border-color: var(--primary-color);
      }
      .history-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 14px 16px;
        gap: 12px;
      }
      .history-info {
        display: flex;
        flex-direction: column;
        gap: 2px;
        min-width: 0;
      }
      .history-alias {
        font-weight: 500;
        color: var(--primary-text-color);
        font-size: 0.95em;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .history-time {
        font-size: 0.8em;
        color: var(--secondary-text-color);
      }
      .history-badges {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-shrink: 0;
      }
      .history-chevron {
        --mdc-icon-size: 18px;
        color: var(--secondary-text-color);
      }
      .badge {
        font-size: 0.72em;
        font-weight: 600;
        padding: 3px 10px;
        border-radius: 10px;
        text-transform: uppercase;
        letter-spacing: 0.03em;
      }
      .badge-success {
        background: rgba(76, 175, 80, 0.15);
        color: var(--success-color, #4caf50);
      }
      .badge-error {
        background: rgba(244, 67, 54, 0.15);
        color: var(--error-color, #f44336);
      }
      .history-detail {
        border-top: 1px solid var(--divider-color);
        padding: 16px;
        display: flex;
        flex-direction: column;
        gap: 12px;
        cursor: default;
      }
      .detail-row {
        display: flex;
        flex-direction: column;
        gap: 2px;
      }
      .detail-label {
        font-size: 0.75em;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: var(--secondary-text-color);
      }
      .detail-value {
        font-size: 0.9em;
        color: var(--primary-text-color);
        line-height: 1.4;
      }
      .detail-yaml {
        position: relative;
        background: var(--primary-background-color);
        border-radius: 8px;
        padding: 14px;
        border: 1px solid var(--divider-color);
      }
    `;
  }
}

customElements.define("automagic-card", AutoMagicCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "automagic-card",
  name: "AutoMagic - AI Automation Builder",
  description: "Generate and install Home Assistant automations using AI",
  preview: true,
});
