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

class AutoMagicCard extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      config: { type: Object },
      _state: { type: String },
      _prompt: { type: String },
      _yaml: { type: String },
      _summary: { type: String },
      _parsedAutomation: { type: Object },
      _error: { type: String },
      _installedAlias: { type: String },
      _showYaml: { type: Boolean },
      _entityCount: { type: Number },
    };
  }

  constructor() {
    super();
    this._state = STATES.IDLE;
    this._prompt = "";
    this._yaml = "";
    this._summary = "";
    this._parsedAutomation = null;
    this._error = "";
    this._installedAlias = "";
    this._showYaml = false;
    this._entityCount = 0;
  }

  setConfig(config) {
    this.config = config;
  }

  connectedCallback() {
    super.connectedCallback();
    this._fetchEntityCount();
  }

  async _fetchEntityCount() {
    try {
      const resp = await this._apiGet("/api/automagic/entities");
      if (resp && resp.entities) {
        this._entityCount = resp.entities.length;
      }
    } catch {
      // Silently ignore - entity count is cosmetic
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

    this._state = STATES.LOADING;
    this._error = "";

    try {
      const result = await this._apiPost("/api/automagic/generate", {
        prompt,
      });

      if (result.error) {
        this._state = STATES.ERROR;
        this._error = result.error;
        return;
      }

      this._yaml = result.yaml || "";
      this._summary = result.summary || "";
      this._parsedAutomation = this._parseYaml(this._yaml);
      this._state = STATES.PREVIEW;
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
      });

      if (result.success) {
        this._installedAlias = result.alias || "Automation";
        this._state = STATES.SUCCESS;
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
    this._state = STATES.IDLE;
    this._prompt = "";
    this._yaml = "";
    this._summary = "";
    this._parsedAutomation = null;
    this._error = "";
    this._installedAlias = "";
    this._showYaml = false;
  }

  _handleRetry() {
    this._state = STATES.IDLE;
    this._error = "";
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
      // Simple YAML key extraction - no dependency needed
      const lines = yamlStr.split("\n");
      let currentSection = null;
      let currentItem = [];

      // Extract alias
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
      const toState = toMatch ? ` → ${toMatch[1]}` : "";
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
    const entity = entityMatch ? ` → ${entityMatch[1]}` : "";
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

  async _copyYaml() {
    try {
      await navigator.clipboard.writeText(this._yaml);
    } catch {
      // Fallback for older browsers
      const ta = document.createElement("textarea");
      ta.value = this._yaml;
      ta.style.position = "fixed";
      ta.style.left = "-9999px";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
    }
  }

  render() {
    const title = this.config?.title || "AutoMagic";
    const showChips = this.config?.show_entity_chips !== false;

    return html`
      <ha-card>
        <div class="card-header">
          <span class="title">✨ ${title}</span>
          ${showChips && this._entityCount > 0
            ? html`<span class="entity-chip">${this._entityCount} entities</span>`
            : ""}
        </div>
        <div class="card-content">
          ${this._renderContent()}
        </div>
      </ha-card>
    `;
  }

  _renderContent() {
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
        <label class="input-label">Describe your automation...</label>
        <textarea
          class="prompt-input"
          rows="3"
          placeholder="Flash the hallway lights red when the front door opens after 10pm"
          .value=${this._prompt}
          @input=${(e) => (this._prompt = e.target.value)}
          @keydown=${(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              this._handleGenerate();
            }
          }}
        ></textarea>
        <mwc-button
          raised
          class="generate-btn"
          @click=${this._handleGenerate}
          ?disabled=${!this._prompt.trim()}
        >
          Generate Automation
        </mwc-button>
      </div>
    `;
  }

  _renderLoading() {
    return html`
      <div class="loading-section">
        <ha-circular-progress indeterminate></ha-circular-progress>
        <span class="loading-text">Asking AI...</span>
      </div>
    `;
  }

  _renderPreview() {
    const auto = this._parsedAutomation;

    return html`
      <div class="preview-section">
        <div class="summary-card">
          <span class="summary-icon">✅</span>
          <span class="summary-text">${this._summary}</span>
        </div>

        ${auto ? this._renderAutomationBreakdown(auto) : ""}

        <details class="yaml-toggle" ?open=${this._showYaml}>
          <summary @click=${() => (this._showYaml = !this._showYaml)}>
            View YAML ${this._showYaml ? "▲" : "▼"}
          </summary>
          <div class="yaml-container">
            <pre class="yaml-code">${this._yaml}</pre>
            <button class="copy-btn" @click=${this._copyYaml} title="Copy YAML">
              📋
            </button>
          </div>
        </details>

        <div class="action-buttons">
          <mwc-button outlined @click=${this._handleReset}>Start Over</mwc-button>
          <mwc-button raised @click=${this._handleInstall}>
            Install Automation
          </mwc-button>
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
                <ha-icon icon="mdi:filter"></ha-icon>
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
                <ha-icon icon="mdi:play"></ha-icon>
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
      <div class="preview-section">
        <div class="summary-card">
          <span class="summary-text">${this._summary}</span>
        </div>
        <div class="loading-section">
          <ha-circular-progress indeterminate></ha-circular-progress>
          <span class="loading-text">Installing automation...</span>
        </div>
      </div>
    `;
  }

  _renderSuccess() {
    return html`
      <div class="success-banner">
        <ha-icon icon="mdi:check-circle"></ha-icon>
        <span>Automation installed: <strong>${this._installedAlias}</strong></span>
      </div>
      <mwc-button raised @click=${this._handleReset}>Create Another</mwc-button>
    `;
  }

  _renderError() {
    return html`
      <div class="error-banner">
        <ha-icon icon="mdi:alert-circle"></ha-icon>
        <span>${this._error}</span>
      </div>
      <div class="action-buttons">
        <mwc-button outlined @click=${this._handleRetry}>Try Again</mwc-button>
        <mwc-button outlined @click=${this._handleReset}>Start Over</mwc-button>
      </div>
    `;
  }

  static get styles() {
    return css`
      :host {
        display: block;
      }
      ha-card {
        padding: 0;
        overflow: hidden;
      }
      .card-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px 16px 0;
      }
      .title {
        font-size: 1.2em;
        font-weight: 500;
        color: var(--primary-text-color);
      }
      .entity-chip {
        font-size: 0.8em;
        background: var(--primary-color);
        color: var(--text-primary-color, #fff);
        padding: 2px 10px;
        border-radius: 12px;
      }
      .card-content {
        padding: 16px;
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
      }
      .prompt-input {
        width: 100%;
        min-height: 60px;
        padding: 12px;
        border: 1px solid var(--divider-color);
        border-radius: 8px;
        background: var(--card-background-color, var(--primary-background-color));
        color: var(--primary-text-color);
        font-family: inherit;
        font-size: 1em;
        resize: vertical;
        box-sizing: border-box;
      }
      .prompt-input:focus {
        outline: none;
        border-color: var(--primary-color);
      }
      .generate-btn {
        align-self: flex-end;
      }

      /* Loading */
      .loading-section {
        display: flex;
        align-items: center;
        justify-content: center;
        gap: 12px;
        padding: 32px 0;
      }
      .loading-text {
        color: var(--secondary-text-color);
        font-size: 1em;
      }

      /* Preview */
      .preview-section {
        display: flex;
        flex-direction: column;
        gap: 16px;
      }
      .summary-card {
        display: flex;
        align-items: flex-start;
        gap: 8px;
        padding: 12px;
        background: var(--primary-background-color);
        border-radius: 8px;
      }
      .summary-icon {
        font-size: 1.2em;
        flex-shrink: 0;
      }
      .summary-text {
        color: var(--primary-text-color);
        line-height: 1.4;
      }

      /* Breakdown */
      .breakdown {
        display: flex;
        flex-direction: column;
        gap: 8px;
      }
      .breakdown-row {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 8px 12px;
        background: var(--primary-background-color);
        border-radius: 6px;
      }
      .breakdown-icon {
        display: flex;
        align-items: center;
        --mdc-icon-size: 20px;
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
        font-size: 0.75em;
        font-weight: 600;
        text-transform: uppercase;
        color: var(--secondary-text-color);
        min-width: 80px;
      }
      .breakdown-desc {
        color: var(--primary-text-color);
        font-size: 0.9em;
      }

      /* YAML toggle */
      .yaml-toggle {
        border: 1px solid var(--divider-color);
        border-radius: 8px;
        overflow: hidden;
      }
      .yaml-toggle summary {
        padding: 10px 14px;
        cursor: pointer;
        font-size: 0.9em;
        color: var(--secondary-text-color);
        user-select: none;
        list-style: none;
      }
      .yaml-toggle summary::-webkit-details-marker {
        display: none;
      }
      .yaml-container {
        position: relative;
        padding: 12px;
        background: var(--primary-background-color);
        border-top: 1px solid var(--divider-color);
      }
      .yaml-code {
        margin: 0;
        white-space: pre-wrap;
        word-break: break-word;
        font-size: 0.85em;
        color: var(--primary-text-color);
        font-family: "Roboto Mono", "Courier New", monospace;
      }
      .copy-btn {
        position: absolute;
        top: 8px;
        right: 8px;
        background: var(--card-background-color);
        border: 1px solid var(--divider-color);
        border-radius: 4px;
        padding: 4px 8px;
        cursor: pointer;
        font-size: 1em;
      }
      .copy-btn:hover {
        background: var(--divider-color);
      }

      /* Action buttons */
      .action-buttons {
        display: flex;
        justify-content: flex-end;
        gap: 8px;
      }

      /* Success / Error banners */
      .success-banner {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 14px;
        background: rgba(76, 175, 80, 0.15);
        border-radius: 8px;
        color: var(--success-color, #4caf50);
        margin-bottom: 16px;
      }
      .success-banner strong {
        color: var(--primary-text-color);
      }
      .error-banner {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 14px;
        background: rgba(244, 67, 54, 0.15);
        border-radius: 8px;
        color: var(--error-color, #f44336);
        margin-bottom: 16px;
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
});
