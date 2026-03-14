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
  CLARIFY: "clarify",
  PREVIEW: "preview",
  INSTALLING: "installing",
  SUCCESS: "success",
  ERROR: "error",
};

const TABS = {
  CREATE: "create",
  HISTORY: "history",
};

const DIRECT_ENDPOINT_PORT = "11434";
const DIRECT_MODEL_PREFERENCES = [
  "qwen2.5:3b-16k",
  "qwen2.5:7b",
  "phi3:mini",
];
const DIRECT_FINAL_MODEL_PREFERENCES = [
  "qwen2.5:3b-16k",
  "qwen2.5:7b",
  "phi3:mini",
];
const DIRECT_PLANNER_MODEL_PREFERENCES = [
  "qwen2.5:0.5b-16k",
  "qwen2.5:3b-16k",
  "qwen2.5:0.5b",
];
const DIRECT_MAX_TOKENS = 2048;
const DIRECT_COMPLEX_MAX_TOKENS = 3200;
const DIRECT_SYNTAX_REWRITE_MAX_TOKENS = 3200;
const DIRECT_PLANNER_MAX_TOKENS = 1400;
const DIRECT_YAML_ONLY_MAX_TOKENS = 3200;
const DIRECT_TEMPERATURE = 0.15;
const DIRECT_CONTEXT_LIMIT = 48;
const DIRECT_STATUS_POLL_INTERVAL_MS = 1000;
const DIRECT_REPAIR_ATTEMPTS = 4;
const DIRECT_REGENERATION_ATTEMPTS = 2;
const DIRECT_FENCE_RE = /```(?:[a-z0-9_+-]+)?\s*\n?(.*?)\n?\s*```/is;
const DIRECT_TOKEN_RE = /[a-z0-9]+/g;
const IMPORTANT_SHORT_TOKENS = new Set(["tv", "ac"]);
const DIRECT_GROUP_MARKER_RE =
  /\b(all|both|three|every|each|single phase|phase|phases|zones|channels|outputs|inputs)\b/i;
const DIRECT_VARIANT_SUFFIX_RE =
  /_(?:l\d+|phase_?\d+|\d+|left|right|rear|front|north|south|east|west|upstairs|downstairs)$/i;
const DIRECT_NAME_VARIANT_SUFFIX_RE =
  /(?:\s+(?:l\d+|phase\s*\d+|\d+|left|right|rear|front|north|south|east|west|upstairs|downstairs))$/i;
const DIRECT_IGNORE_TOKENS = new Set([
  "a",
  "an",
  "and",
  "at",
  "automation",
  "create",
  "for",
  "if",
  "in",
  "is",
  "it",
  "my",
  "of",
  "on",
  "please",
  "the",
  "then",
  "to",
  "turn",
  "when",
  "with",
]);
const DIRECT_AUTOMATION_MATCH_IGNORE_TOKENS = new Set([
  "active",
  "already",
  "disable",
  "disabled",
  "enable",
  "enabled",
  "off",
  "run",
  "running",
  "start",
  "started",
  "stop",
  "stopped",
  "switch",
]);
const DIRECT_GROUP_CLAUSE_IGNORE_TOKENS = new Set([
  "ac",
  "automation",
  "entity",
  "entities",
  "input",
  "output",
  "phase",
  "phases",
  "sensor",
]);
const DIRECT_SEMANTIC_CONTEXT_IGNORE_TOKENS = new Set([
  "above",
  "after",
  "all",
  "already",
  "any",
  "before",
  "below",
  "between",
  "both",
  "delay",
  "drops",
  "each",
  "every",
  "exceeds",
  "flash",
  "monitor",
  "not",
  "only",
  "single",
  "still",
  "than",
  "total",
  "triggered",
  "wait",
  "warning",
  "weekday",
  "weekdays",
  "whichever",
  "while",
]);
const DIRECT_QUESTION_STARTERS = [
  "which ",
  "what ",
  "when ",
  "where ",
  "who ",
  "how ",
  "do you ",
  "does ",
  "should ",
  "would ",
  "could ",
  "can you ",
  "is it ",
  "are there ",
];
const SIMPLE_ACTION_DOMAINS = new Set([
  "light",
  "switch",
  "fan",
  "input_boolean",
  "media_player",
]);
const DIRECT_COMPLEX_PROMPT_RE =
  /\b(if|then|else|otherwise|instead|wait|delay|unless|while|after|before|between|weekday|weekdays|weekend|weekends|above|below|exceeds|drops|greater than|less than|notification|notify|flash|brightness|whichever|triggered)\b/i;
const DIRECT_SYSTEM_PROMPT = `You are an expert Home Assistant automation engineer.
You will be given a plain-English description of a desired automation and a list of available entities in the user's Home Assistant installation.
The conversation may continue with follow-up questions, clarifications, corrections, or requested changes to the current automation.

Your job is to produce a valid Home Assistant automation in YAML format.

SYNTAX RULES - this is critical:
- Always use the HA 2024.10+ syntax. No exceptions.
- Use 'triggers:' (plural) for the trigger list
- Use 'trigger:' (singular) as the key inside each trigger item - NOT 'platform:'
- Use 'conditions:' (plural) for conditions
- Use 'actions:' (plural) for the action list
- Use 'action:' for service calls - NEVER use 'service:'

Example of correct syntax:
  triggers:
    - trigger: state
      entity_id: binary_sensor.front_door
      to: "on"
  actions:
    - action: light.turn_on
      target:
        entity_id: light.hallway

OUTPUT RULES:
- Only use entity_ids from the provided entity list. Never invent entity_ids.
- If the provided list includes notify.* entries, you may use those exact notify action service names in actions. Do not invent notify services.
- Output ONLY a JSON object with four keys:
    "yaml": the complete automation YAML as a string, or null when clarification is required
    "summary": a 1-2 sentence plain English description of what the automation does, or a brief explanation of what is missing
    "needs_clarification": true or false
    "clarifying_questions": an array of 0-3 short, specific questions
- Do not include any explanation, preamble, or markdown code fences outside the JSON.
- Keep the YAML concise. Do not add comments or explanatory prose inside or after the YAML.
- The YAML must include: alias, description, triggers, and actions at minimum.
- Use the most appropriate trigger type for the request. Prefer state triggers over template triggers where possible.
- If an entity_id is listed in the provided entity list, treat it as available for YAML generation even if its current state is "unknown" or "unavailable". Only ask for clarification when the needed entity is missing entirely.
- When prompt-specific guidance includes resolved entity, grouped-family, automation-guard, or notification-target mappings, treat those mappings as authoritative and use them without asking the user to choose again.
- For follow-up change requests, revise the current automation and return the full updated YAML, not a partial diff.
- For follow-up questions about the current automation, answer briefly in "summary" and also return the full current or updated YAML in "yaml".
- For complex multi-step requests, use variables, choose blocks, delay/wait steps, and template conditions or template values as needed. Return one complete automation unless the user explicitly asks for multiple automations.
- Read the entire request as one combined condition/action sequence before deciding anything is missing. Do not ask about a sub-step when the needed threshold, guard, time window, or follow-up action is already stated elsewhere in the same prompt.
- Interpret wattage/watts/kW as power, amps/amperage as current, and volts as voltage when matching sensor families from the provided entities.
- Treat time-window guards or exclusions such as "not between 9am and 5pm on a weekday" as conditions, not as the automation's trigger schedule.
- Preserve the user's boolean logic exactly when they combine OR and AND clauses across different sensor or entity families.
- When the user asks to report whichever sensor triggered, capture the triggering sensor name and value in variables so the notification text includes the real sensor and reading.
- When a matched entity has sibling variants such as left/right, L1/L2/L3, or numbered variants, and the user asks for all/both/three/every member of the set, include the full relevant sibling set.
- When the user refers to any/all/both/three/every member of a sibling set, use the whole listed set together and do not ask which single entity to use if the set is already present.
- When different threshold or state clauses clearly refer to different entity families, map each clause to its matching family and use all listed siblings in that family together. Do not ask the user to choose just one family when the prompt already distinguishes voltage vs current, temperature vs humidity, upstairs vs downstairs, or similar pairings.
- When the user refers to a named automation concept such as a balance, bedtime, heating, washing, or security automation, match the provided automation.* entities whose names share that concept. Use the matching automation entities as guards or conditions without asking which single automation to use when the concept is already specific enough.
- When the user names a phone, tablet, or mobile device and a matching notify.* service is present in the provided list, use that notify service directly instead of asking again which notification target to use.
- Preserve exact thresholds, colors, brightness, flash counts, delays, weekday/time exclusions, and guard conditions from the user's request unless they conflict.
- If you are unsure which available entity matches the user's intent, ask a clarifying question instead of guessing.
- If the user explicitly names an entity_id that exists in the provided list, treat it as authoritative and do not ask again which entity to use.
- If a provided entity name is an exact or near-exact match for the user's wording, use that entity directly without asking for confirmation.
- Home Assistant's built-in sun trigger is allowed for sunrise/sunset automations even when no sun entity_id is listed.
- Clear schedule phrases like "at 10am every morning", "every day at 7:30", "every weekday", or "at sunset" are already specific enough for a trigger and should not cause clarification.
- If there is one obvious entity match, you may substitute it and note that in the summary.
- If a missing detail would materially change the automation, do not guess. Set yaml to null, needs_clarification to true, and ask the minimum number of direct questions needed.
- Material missing details include things like target entity, area, time, day, threshold, duration, scene, notification target, brightness, color, or action mode.
- Do not mark the task complete with an empty yaml string.
- If the request cannot be fulfilled with the available entities even after clarification, set yaml to null, needs_clarification to false, and explain why in the summary.`;
const DIRECT_RESOLVED_SYSTEM_PROMPT = `${DIRECT_SYSTEM_PROMPT}

FINAL PASS RULES:
- This is the final resolved generation pass. Do not ask any further clarifying questions.
- Treat authoritative grouped-family, single-entity, automation-guard, and notification-target mappings as mandatory.
- When a clause refers to all/both/three/every/any single phase of a sibling family, implement that clause with the entire resolved sibling family. Never ask the user to choose only one entity from that family.
- When a sibling family contains an unlabeled base entity together with numbered variants like foo, foo_l2, foo_l3, treat the unlabeled base entity as the first/default member of that sibling family.
- Never wrap the result in a top-level automation:, sequence:, script:, or list item. The yaml string must start directly with alias:.
- For complex multi-step automations, prefer valid Home Assistant constructs such as variables, numeric_state or template triggers with ids, choose/default branches, repeat blocks, delays, and template values.
- Do not return planning keys such as resolved_request, resolved_requirements, or resolved_entities on this pass.
- On this pass, always return a complete JSON object with needs_clarification set to false and clarifying_questions set to an empty array.`;
const DIRECT_PLANNER_SYSTEM_PROMPT = `You are an expert Home Assistant automation planning assistant.
You will be given a Home Assistant automation request and a list of available entities.

Your job is to resolve the user's intent into a precise implementation plan before YAML is generated.

OUTPUT RULES:
- Output ONLY one JSON object. Do not include markdown or commentary.
- Use exactly these keys:
    "resolved_request": a concise paragraph restating the full intended automation
    "resolved_requirements": an array of specific implementation requirements in execution order, written as short imperative sentences
    "resolved_entities": an array of strings mapping user intent to exact entity_ids or sibling sets
    "needs_clarification": true or false
    "clarifying_questions": an array of 0-3 short, specific questions
- Treat listed entity_ids as valid even when their current state is "unknown" or "unavailable".
- When the request refers to all/both/each/three/every member of a sibling entity family, resolve that family as a complete set.
- When different threshold or state clauses clearly refer to different entity families, resolve each clause against its matching family instead of asking the user to choose only one family.
- Read the whole prompt before asking for clarification. Do not ask about one clause if the needed threshold, time window, guard, action, or notification target is already stated elsewhere in the request.
- Treat time-window guards or exclusions such as "not between 9am and 5pm on a weekday" as conditions, not as the automation's trigger schedule.
- If a named automation concept clearly matches one or more provided automation.* entities, resolve those matching automation entities and do not ask which single automation to use.
- resolved_requirements must preserve thresholds, delays, follow-up branches, notifications, and guard conditions from the request. Do not replace them with bare entity_ids.
- resolved_entities must be human-readable mapping strings such as "AC Output Voltage phases -> sensor.foo, sensor.foo_l2, sensor.foo_l3". Do not return JSON objects inside resolved_entities.
- Ask for clarification only when the request still cannot be implemented without guessing after using the provided entities and the full prompt context.`;
const DIRECT_SYNTAX_REWRITE_SYSTEM_PROMPT = `You are an expert Home Assistant automation syntax repair assistant.
You will be given the original automation request, a draft automation response, and the available entities.

Your job is to rewrite the draft into one valid Home Assistant automation in YAML while preserving the user's intended behavior.

OUTPUT RULES:
- Output ONLY one JSON object with these keys:
    "yaml": the complete automation YAML as a non-empty string
    "summary": a brief plain-English summary
    "needs_clarification": false
    "clarifying_questions": []
- Do not include markdown fences or commentary outside the JSON.
- Example response shape:
  {"yaml":"alias: Example\\ndescription: Example\\ntriggers:\\n  - trigger: time\\n    at: \\"10:00:00\\"\\nconditions: []\\nactions:\\n  - action: light.turn_on\\n    target:\\n      entity_id: light.example\\nmode: single","summary":"Turns on Example at 10:00.","needs_clarification":false,"clarifying_questions":[]}

REWRITE RULES:
- Keep the original behavior, entities, thresholds, delays, notification text, colors, brightness levels, and guard conditions unless the draft is obviously wrong or invalid.
- Convert invalid pseudo-fields into valid Home Assistant syntax instead of describing them. Examples:
  - replace top-level automation: wrappers with a single automation document
  - replace platform: with trigger:
  - replace service: with action:
  - translate pseudo conditions or pseudo template fields into valid condition:, variables:, choose:, repeat:, delay:, or template constructs
- Merge duplicate top-level triggers:, conditions:, or actions: sections into one valid section each.
- Every trigger item under triggers: must begin with "- trigger:".
- Every service-call step under actions: must begin with "- action:".
- Use valid numeric_state keys such as above: and below:. Do not invent fields like above_limit:, below_limit:, condition_entity_id:, condition_state:, or condition_value_template:.
- If an action targets entities from one domain, use a matching action service for that domain or a valid cross-domain service such as homeassistant.turn_on/off when appropriate.
- When the user says to disable or turn off a switch-like entity, do not convert that into turn_on.
- Use real entity state values such as "on" or "off", not pseudo states like "active".
- The YAML must start with alias: and include description:, triggers:, conditions:, and actions:.
- Use Home Assistant 2024.10+ syntax only.
- If the draft tries to refer to whichever trigger fired, capture trigger.entity_id, the friendly name, and the live value in variables and use those variables in the notification message.
- Return the corrected final automation JSON now.`;
const DIRECT_PLAN_TO_YAML_SYSTEM_PROMPT = `You are an expert Home Assistant automation compiler.
You will be given the original automation request, the available entities, and an authoritative implementation brief.

Your job is to compile that brief into one valid Home Assistant automation in YAML.

OUTPUT RULES:
- Output ONLY one JSON object with these keys:
    "yaml": the complete automation YAML as a non-empty string
    "summary": a brief plain-English summary
    "needs_clarification": false
    "clarifying_questions": []
- Do not include markdown fences or commentary outside the JSON.

COMPILATION RULES:
- Follow the original request and the implementation brief together. If they differ, prefer the original request.
- Use Home Assistant 2024.10+ syntax only.
- The yaml key must start with alias: and include description:, triggers:, conditions:, and actions:.
- Do not return planning keys such as resolved_request, resolved_requirements, or resolved_entities.
- For complex automations, use valid Home Assistant constructs such as numeric_state triggers with ids, template conditions, variables, choose/default branches, delays, repeat blocks, and template values as needed.
- When a request combines OR trigger thresholds with AND guard conditions across multiple entity families, preserve that boolean logic exactly using multiple triggers plus shared conditions and/or template conditions as needed.
- For delayed follow-up checks, re-check the relevant states after the delay using choose/default or conditional branches instead of describing the logic in prose.
- When a request refers to whichever entity triggered the automation, capture trigger.entity_id, a human-readable label, and the live value in variables and use those variables in actions or notifications.
- If a named automation guard or notify target is present in the provided entities or implementation brief, use it directly without asking again.
- If the automation needs to mention whichever sensor triggered, capture trigger.entity_id, a friendly sensor name, and the live value in variables and use those variables in the notification message.
- For multi-step automations, emit complete executable YAML using valid combinations of variables, trigger ids, choose/default branches, delays, template conditions, and sequential actions instead of summarizing the behavior.
- When a request includes nested outcomes such as "if still above X after Y, do A, otherwise do B", encode that exact branch structure directly in the actions.
- Return the final automation JSON now.`;

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
      _clarificationSummary: { type: String },
      _clarifyingQuestions: { type: Array },
      _clarificationCandidates: { type: Array },
      _clarificationAnswer: { type: String },
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
      _historyError: { type: String },
      _deletingHistoryEntryId: { type: String },
      _services: { type: Array },
      _selectedServiceId: { type: String },
      _chatMessages: { type: Array },
      _expandedHistory: { type: Number },
      _isPanel: { type: Boolean },
      _directEndpoint: { type: String },
      _directModel: { type: String },
    };
  }

  constructor() {
    super();
    this._state = STATES.IDLE;
    this._activeTab = TABS.CREATE;
    this._prompt = "";
    this._yaml = "";
    this._summary = "";
    this._clarificationSummary = "";
    this._clarifyingQuestions = [];
    this._clarificationCandidates = [];
    this._clarificationAnswer = "";
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
    this._historyError = "";
    this._deletingHistoryEntryId = "";
    this._services = [];
    this._selectedServiceId = "";
    this._chatMessages = [];
    this._expandedHistory = -1;
    this._isPanel = false;
    this._statusPollHandle = null;
    this._loadingTickerHandle = null;
    this._loadingStartedAt = 0;
    this._conversationMessages = null;
    this._clarificationContext = null;
    this._lastEntityPool = [];
    this._directEndpoint = "";
    this._directModel = "";
    this._wsUnavailable = false;
    this._lastRepairDetail = "";
  }

  setConfig(config) {
    this.config = config;
  }

  set panel(val) {
    this._isPanel = true;
  }

  connectedCallback() {
    super.connectedCallback();
    this._fetchServices();
    this._fetchEntityCount();
    this._fetchHistory();
  }

  updated(changedProperties) {
    if (
      changedProperties.has("_chatMessages") ||
      changedProperties.has("_state")
    ) {
      this._scrollChatToBottom();
    }
  }

  disconnectedCallback() {
    this._clearGenerationPolling();
    super.disconnectedCallback();
  }

  async _fetchEntityCount() {
    try {
      const resp = await this._requestEntities();
      if (resp && resp.entities) {
        this._entityCount = resp.entities.length;
      }
    } catch {
      // Silently ignore
    }
  }

  async _fetchHistory() {
    try {
      const resp = await this._requestHistory();
      if (resp && resp.history) {
        this._history = resp.history;
        this._historyError = "";
      }
    } catch {
      // Silently ignore
    }
  }

  async _fetchServices() {
    try {
      const resp = await this._requestServices();
      const services = Array.isArray(resp?.services) ? resp.services : [];
      this._services = services;

      const defaultServiceId = this._normalizeText(resp?.default_service_id);
      const currentSelection = this._normalizeText(this._selectedServiceId);
      const nextSelection = services.some(
        (service) => this._normalizeText(service?.service_id) === currentSelection
      )
        ? currentSelection
        : this._normalizeText(
            services.find(
              (service) =>
                this._normalizeText(service?.service_id) === defaultServiceId
            )?.service_id || services[0]?.service_id || ""
          );
      this._selectedServiceId = nextSelection;
    } catch {
      this._services = [];
    }
  }

  _scrollChatToBottom() {
    window.requestAnimationFrame(() => {
      const thread = this.renderRoot?.querySelector(".chat-thread");
      if (thread) {
        thread.scrollTop = thread.scrollHeight;
      }
    });
  }

  _appendChatMessage(message) {
    const nextMessage = {
      role: "assistant",
      type: "text",
      ...message,
    };
    if (nextMessage.type === "yaml") {
      nextMessage.yaml = this._normalizeAutomationYamlText(nextMessage.yaml);
      nextMessage.parsedAutomation = this._parseYaml(nextMessage.yaml);
    }
    this._chatMessages = [
      ...this._chatMessages,
      nextMessage,
    ];
    return this._chatMessages.length - 1;
  }

  _pushRepairStatus(issue) {
    const normalizedIssue = this._normalizeText(issue);
    if (!normalizedIssue) return;

    const detail =
      "The model returned automation YAML with a syntax or logic problem. " +
      "AutoMagic has automatically sent the latest specific error back to the AI " +
      `and is requesting another correction. Error: ${normalizedIssue}`;

    if (detail === this._lastRepairDetail) return;

    this._lastRepairDetail = detail;
    this._loadingMessage = "Fixing a YAML issue…";
    this._loadingDetail = detail;
    this._appendChatMessage({
      role: "assistant",
      type: "status",
      tone: "warning",
      text: detail,
    });
  }

  _updateChatMessage(index, patch) {
    if (index < 0 || index >= this._chatMessages.length) return;
    this._chatMessages = this._chatMessages.map((message, messageIndex) =>
      messageIndex === index
        ? {
            ...message,
            ...patch,
          }
        : message
    );
  }

  _lastUserChatText() {
    for (let index = this._chatMessages.length - 1; index >= 0; index -= 1) {
      const message = this._chatMessages[index];
      if (message?.role === "user" && message?.text) {
        return message.text;
      }
    }
    return "";
  }

  async _wsCommand(type, payload = {}) {
    if (this._wsUnavailable) {
      throw new Error("Home Assistant websocket command is unavailable");
    }
    if (!this.hass?.connection?.sendMessagePromise) {
      throw new Error("Home Assistant websocket connection is unavailable");
    }

    try {
      return await this.hass.connection.sendMessagePromise({
        type,
        ...payload,
      });
    } catch (err) {
      if (err?.code === "unknown_command") {
        this._wsUnavailable = true;
      }
      throw err;
    }
  }

  _apiPath(path) {
    return path.replace(/^\/api\//, "");
  }

  _authToken() {
    try {
      const stored =
        window.localStorage?.getItem("hassTokens") ||
        window.sessionStorage?.getItem("hassTokens") ||
        "";
      if (stored) {
        const parsed = JSON.parse(stored);
        const browserToken = parsed?.access_token || parsed?.accessToken || "";
        if (browserToken) return browserToken;
      }
    } catch {
      // Ignore storage parsing issues and fall back to hass properties.
    }

    return (
      this.hass?.connection?.options?.auth?.accessToken ||
      this.hass?.auth?.accessToken ||
      this.hass?.auth?.data?.access_token ||
      ""
    );
  }

  async _fetchJson(path, options = {}) {
    const resp = await fetch(path, options);
    const contentType = resp.headers.get("content-type") || "";
    const isJson = contentType.includes("application/json");
    const body = isJson ? await resp.json() : await resp.text();

    if (!resp.ok) {
      if (body && typeof body === "object" && body.error) {
        throw new Error(body.error);
      }
      if (typeof body === "string" && body.trim()) {
        throw new Error(body.trim());
      }
      throw new Error(`HTTP ${resp.status}`);
    }

    return body;
  }

  _formatError(err) {
    if (!err) return "Unknown error";
    if (typeof err === "string") return err;
    if (err instanceof Error && err.message) return err.message;
    if (typeof err === "object") {
      if (typeof err.error === "string" && err.error) return err.error;
      if (typeof err.message === "string" && err.message) return err.message;
      if (typeof err.body === "string" && err.body) return err.body;
      try {
        return JSON.stringify(err);
      } catch {
        return "Unknown error";
      }
    }
    return String(err);
  }

  _shouldRetryBackendStatus(err) {
    const text = this._formatError(err).toLowerCase();
    return (
      text.includes("internal server error") ||
      text.includes("server got itself in trouble") ||
      text.includes("failed to fetch") ||
      text.includes("http 500") ||
      text.includes("gateway timeout") ||
      text.includes("timed out")
    );
  }

  async _apiPost(path, body) {
    const apiPath = this._apiPath(path);
    if (this.hass?.callApi) {
      try {
        return await this.hass.callApi("POST", apiPath, body);
      } catch (err) {
        // Fall through to direct fetch for frontend/runtime compatibility issues.
      }
    }

    const token = this._authToken();
    if (token) {
      try {
        return await this._fetchJson(path, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify(body),
        });
      } catch (err) {
        // Fall through to same-origin fetch.
      }
    }

    return this._fetchJson(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      credentials: "same-origin",
      body: JSON.stringify(body),
    });
  }

  async _apiGet(path) {
    const apiPath = this._apiPath(path);
    if (this.hass?.callApi) {
      try {
        return await this.hass.callApi("GET", apiPath);
      } catch (err) {
        // Fall through to direct fetch for frontend/runtime compatibility issues.
      }
    }

    const token = this._authToken();
    if (token) {
      try {
        return await this._fetchJson(path, {
          method: "GET",
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });
      } catch (err) {
        // Fall through to same-origin fetch.
      }
    }

    return this._fetchJson(path, {
      method: "GET",
      credentials: "same-origin",
    });
  }

  async _apiDelete(path) {
    const apiPath = this._apiPath(path);
    if (this.hass?.callApi) {
      try {
        return await this.hass.callApi("DELETE", apiPath);
      } catch (err) {
        // Fall through to direct fetch for frontend/runtime compatibility issues.
      }
    }

    const token = this._authToken();
    if (token) {
      try {
        return await this._fetchJson(path, {
          method: "DELETE",
          headers: {
            Authorization: `Bearer ${token}`,
          },
        });
      } catch (err) {
        // Fall through to same-origin fetch.
      }
    }

    return this._fetchJson(path, {
      method: "DELETE",
      credentials: "same-origin",
    });
  }

  async _requestGenerate(payload) {
    try {
      return await this._wsCommand("automagic/generate", payload);
    } catch (err) {
      return this._apiPost("/api/automagic/generate", payload);
    }
  }

  async _requestGenerationStatus(jobId) {
    try {
      return await this._wsCommand("automagic/generate_status", {
        job_id: jobId,
      });
    } catch (err) {
      return this._apiGet(`/api/automagic/generate/${jobId}`);
    }
  }

  async _requestGenerateWithToken(payload) {
    try {
      return await this._requestGenerate(payload);
    } catch (err) {
      const token = this._authToken();
      if (!token) {
        throw err;
      }

      return this._fetchJson("/api/automagic/generate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(payload),
      });
    }
  }

  async _requestGenerationStatusWithToken(jobId) {
    try {
      return await this._requestGenerationStatus(jobId);
    } catch (err) {
      const token = this._authToken();
      if (!token) {
        throw err;
      }

      return this._fetchJson(`/api/automagic/generate/${jobId}`, {
        method: "GET",
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
    }
  }

  async _requestInstall(payload) {
    try {
      return await this._wsCommand("automagic/install", payload);
    } catch (err) {
      return this._apiPost("/api/automagic/install", payload);
    }
  }

  async _requestInstallRepair(payload) {
    try {
      return await this._wsCommand("automagic/install_repair", payload);
    } catch (err) {
      return this._apiPost("/api/automagic/install_repair", payload);
    }
  }

  async _requestEntities() {
    try {
      return await this._wsCommand("automagic/entities");
    } catch (err) {
      return this._apiGet("/api/automagic/entities");
    }
  }

  async _requestHistory() {
    try {
      return await this._wsCommand("automagic/history");
    } catch (err) {
      return this._apiGet("/api/automagic/history");
    }
  }

  async _requestDeleteHistory(entryId) {
    const normalizedEntryId = this._normalizeText(entryId);
    try {
      return await this._wsCommand("automagic/history_delete", {
        entry_id: normalizedEntryId,
      });
    } catch (err) {
      return this._apiDelete(
        `/api/automagic/history/${encodeURIComponent(normalizedEntryId)}`
      );
    }
  }

  async _requestServices() {
    try {
      return await this._wsCommand("automagic/services");
    } catch (err) {
      return this._apiGet("/api/automagic/services");
    }
  }

  _serviceLabel(service) {
    const explicitLabel = this._normalizeText(service?.label);
    if (explicitLabel) return explicitLabel;

    const model = this._normalizeText(service?.model);
    const endpoint = this._normalizeText(service?.endpoint_url);
    try {
      const parsed = new URL(endpoint);
      if (model && parsed.host) {
        return `${model} (${parsed.host})`;
      }
      return model || parsed.host;
    } catch {
      if (model && endpoint) {
        return `${model} (${endpoint})`;
      }
      return model || endpoint || "AI service";
    }
  }

  _selectedService() {
    const selectedServiceId = this._normalizeText(this._selectedServiceId);
    return (
      this._services.find(
        (service) => this._normalizeText(service?.service_id) === selectedServiceId
      ) ||
      this._services.find((service) => service?.is_default) ||
      this._services[0] ||
      null
    );
  }

  _isLikelyDirectFallbackHost(hostname) {
    const normalizedHost = this._normalizeText(hostname).toLowerCase();
    if (!normalizedHost) return false;
    if (
      normalizedHost === "localhost" ||
      normalizedHost === "127.0.0.1" ||
      normalizedHost === "::1" ||
      normalizedHost === "[::1]"
    ) {
      return true;
    }

    const currentHost = this._normalizeText(
      window?.location?.hostname || ""
    ).toLowerCase();
    if (currentHost && normalizedHost === currentHost) {
      return true;
    }

    if (normalizedHost.endsWith(".local")) {
      return true;
    }

    return (
      /^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(normalizedHost) ||
      /^192\.168\.\d{1,3}\.\d{1,3}$/.test(normalizedHost) ||
      /^172\.(1[6-9]|2\d|3[0-1])\.\d{1,3}\.\d{1,3}$/.test(normalizedHost)
    );
  }

  _canUseDirectGenerationFallback(service = this._selectedService()) {
    const endpoint = this._normalizeText(service?.endpoint_url);
    if (!endpoint) return false;

    try {
      const parsed = new URL(endpoint);
      const port =
        this._normalizeText(parsed.port) ||
        (parsed.protocol === "https:" ? "443" : "80");
      return (
        port === DIRECT_ENDPOINT_PORT &&
        this._isLikelyDirectFallbackHost(parsed.hostname)
      );
    } catch {
      return false;
    }
  }

  _buildGenerationRequestPayload(prompt, continueJobId = "") {
    const payload = { prompt };
    const serviceId = this._normalizeText(this._selectedService()?.service_id);
    if (serviceId) {
      payload.service_id = serviceId;
    }
    if (continueJobId) {
      payload.continue_job_id = continueJobId;
    }
    return payload;
  }

  _startLoadingTicker(message, detail) {
    this._clearGenerationPolling();
    this._state = STATES.LOADING;
    this._loadingMessage = message;
    this._loadingDetail = detail;
    this._loadingElapsedSeconds = 0;
    this._loadingStartedAt = Date.now();
    this._loadingTickerHandle = window.setInterval(() => {
      this._loadingElapsedSeconds = Math.max(
        0,
        Math.floor((Date.now() - this._loadingStartedAt) / 1000)
      );
    }, DIRECT_STATUS_POLL_INTERVAL_MS);
  }

  async _fetchWithTimeout(url, options = {}, timeoutMs = 10000) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, {
        ...options,
        signal: controller.signal,
      });
    } finally {
      window.clearTimeout(timer);
    }
  }

  _normalizeText(value) {
    if (value == null) return "";
    return String(value).trim();
  }

  _normalizePhrase(value) {
    return this._normalizeText(value)
      .toLowerCase()
      .replace(/[_\.]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  _normalizeQuestions(value) {
    const items = [];
    const candidates = Array.isArray(value)
      ? value
      : typeof value === "string"
        ? value.split(/\r?\n/)
        : value == null
          ? []
          : [value];

    for (const candidate of candidates) {
      const text = this._normalizeText(candidate).replace(
        /^(?:[-*]\s+|\d+[\).\s]+)/,
        ""
      );
      if (text) items.push(text);
    }

    return items;
  }

  _looksLikeQuestion(text) {
    const normalized = this._normalizeText(text).toLowerCase();
    return (
      normalized.endsWith("?") ||
      DIRECT_QUESTION_STARTERS.some((starter) => normalized.startsWith(starter))
    );
  }

  _unwrapSingleAutomationList(lines) {
    const listLines = Array.isArray(lines) ? lines : [];
    if (listLines.length === 0) return "";
    if (!/^\s*-\s*alias\s*:/i.test(listLines[0])) return "";

    const firstLine = listLines[0].replace(/^(\s*)-\s+/, "$1");
    const bodyLines = listLines.slice(1);
    const indents = bodyLines
      .filter((line) => this._normalizeText(line))
      .map((line) => line.length - line.trimStart().length);
    const minIndent = indents.length > 0 ? Math.min(...indents) : 0;
    const candidate = [
      firstLine,
      ...bodyLines.map((line) =>
        minIndent > 0 && line.length >= minIndent ? line.slice(minIndent) : line
      ),
    ]
      .join("\n")
      .trim();

    return /^alias\s*:/m.test(candidate) ? candidate : "";
  }

  _extractWrappedAutomationDocument(lines) {
    const sourceLines = Array.isArray(lines) ? lines : [];
    if (sourceLines.length === 0) return "";

    const wrapperIndex = sourceLines.findIndex((line) =>
      /^\s*(automation|sequence|script)\s*:\s*$/i.test(line)
    );
    if (wrapperIndex === -1) return "";

    const bodyLines = sourceLines
      .slice(wrapperIndex + 1)
      .filter((line, index, items) =>
        index >= items.findIndex((candidate) => this._normalizeText(candidate))
      );

    return this._unwrapSingleAutomationList(bodyLines);
  }

  _extractLooseYamlResponse(content) {
    const rawText = this._normalizeText(content);
    const fenceMatch = rawText.match(DIRECT_FENCE_RE);
    const text = this._normalizeText(fenceMatch?.[1] || rawText);
    if (!text) return null;

    let lines = text.split(/\r?\n/);
    const firstNonEmptyIndex = lines.findIndex((line) => this._normalizeText(line));
    if (
      firstNonEmptyIndex !== -1 &&
      /^\s*yaml\s*$/i.test(lines[firstNonEmptyIndex])
    ) {
      lines = lines.slice(firstNonEmptyIndex + 1);
    }
    const nextNonEmptyIndex = lines.findIndex((line) => this._normalizeText(line));
    if (
      nextNonEmptyIndex !== -1 &&
      /^\s*yaml\s*:?\s*(\|)?\s*$/i.test(lines[nextNonEmptyIndex])
    ) {
      let bodyLines = lines.slice(nextNonEmptyIndex + 1);
      if (lines[nextNonEmptyIndex].includes("|")) {
        const indents = bodyLines
          .filter((line) => line.trim())
          .map((line) => line.length - line.trimStart().length);
        if (indents.length > 0) {
          const minIndent = Math.min(...indents);
          bodyLines = bodyLines.map((line) =>
            line.length >= minIndent ? line.slice(minIndent) : ""
          );
        }
      }
      lines = bodyLines;
    }

    const summaryLine = lines.find((line) => /^\s*summary\s*:/i.test(line));
    const summary = summaryLine
      ? this._normalizeText(summaryLine.replace(/^\s*summary\s*:/i, ""))
      : "";

    let aliasIndex = lines.findIndex((line) => /^\s*(?:-\s*)?alias\s*:/i.test(line));
    if (aliasIndex === -1) {
      const yamlLabelIndex = lines.findIndex((line) => /^\s*yaml\s*:?\s*$/i.test(line));
      if (yamlLabelIndex !== -1) {
        aliasIndex = lines.findIndex(
          (line, index) => index > yamlLabelIndex && /^\s*(?:-\s*)?alias\s*:/i.test(line)
        );
      }
    }

    if (aliasIndex === -1) return null;

    let yamlLines = lines.slice(aliasIndex);
    const trailingFieldIndex = yamlLines.findIndex(
      (line, index) =>
        index > 0 &&
        /^\s*(summary|needs_clarification|clarifying_questions|questions|follow_up_questions)\s*:/i.test(
          line
        )
    );
    if (trailingFieldIndex !== -1) {
      yamlLines = yamlLines.slice(0, trailingFieldIndex);
    }

    let yaml = yamlLines.join("\n").trim();
    if (/^\s*-\s*alias\s*:/i.test(yaml)) {
      const candidate = this._unwrapSingleAutomationList(yaml.split(/\r?\n/));
      if (candidate) {
        yaml = candidate;
      }
    }
    const wrappedCandidate = this._extractWrappedAutomationDocument(
      yaml.split(/\r?\n/)
    );
    if (wrappedCandidate) {
      yaml = wrappedCandidate;
    }
    if (!yaml) return null;
    if (!/^alias\s*:/m.test(yaml)) return null;
    if (!/^(triggers?|trigger|platform)\s*:/m.test(yaml)) return null;
    if (!/^(actions?|action|service)\s*:/m.test(yaml)) return null;

    return {
      yaml,
      summary,
      needs_clarification: false,
      clarifying_questions: [],
    };
  }

  _extractJsonObjectText(content) {
    const text = this._normalizeText(content);
    if (!text) return "";

    const fenceMatch = text.match(DIRECT_FENCE_RE);
    if (fenceMatch?.[1]) {
      return this._normalizeText(fenceMatch[1]);
    }

    const firstBrace = text.indexOf("{");
    const lastBrace = text.lastIndexOf("}");
    if (firstBrace !== -1 && lastBrace > firstBrace) {
      return this._normalizeText(text.slice(firstBrace, lastBrace + 1));
    }

    return text;
  }

  _extractMalformedJsonYamlResponse(content) {
    const text = String(content || "");
    const yamlMatch = text.match(/"yaml"\s*:\s*"/);
    if (!yamlMatch) return null;

    const yamlTail = text.slice(yamlMatch.index + yamlMatch[0].length);
    const summaryMatch = yamlTail.match(/([\s\S]*?)"\s*,\s*"summary"\s*:/);
    const yamlOnlyMatch = yamlTail.match(/([\s\S]*?)"\s*(?:,|\x7d)/);

    let yaml = summaryMatch ? summaryMatch[1] : yamlOnlyMatch ? yamlOnlyMatch[1] : yamlTail;
    yaml = yaml
      .replace(/\\r/g, "")
      .replace(/\\n/g, "\n")
      .replace(/\\"/g, '"')
      .replace(/\\\\/g, "\\")
      .replace(/"\s*$/, "")
      .trim();
    if (!yaml) return null;

    let summary = "";
    if (summaryMatch) {
      const summaryStart = summaryMatch[0].length;
      const summaryTail = yamlTail.slice(summaryStart);
      const summaryEndMatch = summaryTail.match(
        /([\s\S]*?)"\s*,\s*"(?:needs_clarification|clarifying_questions|questions|follow_up_questions)"\s*:/
      );
      summary = summaryEndMatch ? summaryEndMatch[1] : summaryTail.replace(/"\s*$/, "");
      summary = this._normalizeText(
        summary
          .replace(/\\r/g, "")
          .replace(/\\n/g, "\n")
          .replace(/\\"/g, '"')
          .replace(/\\\\/g, "\\")
      );
    }

    if (!/^alias\s*:/m.test(yaml)) return null;

    return {
      yaml,
      summary,
      needs_clarification: false,
      clarifying_questions: [],
    };
  }

  _sanitizePlainYamlScalars(text) {
    const normalized = this._normalizeText(text);
    if (!normalized) return "";
    const openBrace = String.fromCharCode(123);
    const flowStartChars = new Set([
      "'",
      '"',
      "[",
      openBrace,
      "|",
      ">",
      "!",
      "&",
      "*",
    ]);

    return normalized
      .split(/\r?\n/)
      .map((line) => {
        const match = line.match(
          /^(\s*(?:-\s+)?[A-Za-z_][A-Za-z0-9_]*\s*:\s*)(.+?)\s*$/
        );
        if (!match) return line;

        const [, prefix, rawValue] = match;
        const value = this._normalizeText(rawValue);
        const firstChar = value.charAt(0);
        if (
          !value ||
          !value.includes(":") ||
          flowStartChars.has(firstChar) ||
          value.startsWith(openBrace + openBrace) ||
          value.startsWith(openBrace + "%")
        ) {
          return line;
        }

        return `${prefix}${JSON.stringify(value)}`;
      })
      .join("\n");
  }

  _normalizeAutomationYamlText(rawYaml) {
    const text = this._normalizeText(rawYaml);
    if (!text) return "";

    return this._sanitizePlainYamlScalars(
      this._extractLooseYamlResponse(text)?.yaml || text
    );
  }

  _buildClarificationMessage(summary, clarifyingQuestions) {
    const parts = [];
    const summaryText = this._normalizeText(summary);
    if (summaryText) parts.push(summaryText);

    if (Array.isArray(clarifyingQuestions) && clarifyingQuestions.length > 0) {
      if (clarifyingQuestions.length === 1) {
        parts.push(clarifyingQuestions[0]);
      } else {
        const numbered = clarifyingQuestions
          .map((question, index) => `${index + 1}. ${question}`)
          .join("\n");
        parts.push(
          "Please answer these questions so I can finish the automation:\n" +
            numbered
        );
      }
    }

    return parts.filter(Boolean).join("\n\n").trim();
  }

  _buildAutomationContextMessage(summary, yaml) {
    const parts = [];
    const summaryText = this._normalizeText(summary);
    const yamlText = this._normalizeText(yaml);

    if (summaryText) {
      parts.push(`Summary:\n${summaryText}`);
    }
    if (yamlText) {
      parts.push(`Current automation YAML:\n${yamlText}`);
    }

    return parts.filter(Boolean).join("\n\n").trim();
  }

  _extractTopLevelSectionBlock(yaml, sectionName) {
    const text = this._normalizeText(yaml);
    const target = this._normalizeText(sectionName).toLowerCase();
    if (!text || !target) return "";

    const lines = text.split(/\r?\n/);
    const startIndex = lines.findIndex((line) =>
      new RegExp(`^${target}\\s*:`, "i").test(line)
    );
    if (startIndex === -1) return "";

    const sectionLines = [lines[startIndex]];
    for (let index = startIndex + 1; index < lines.length; index += 1) {
      const line = lines[index];
      if (/^[a-z_][a-z0-9_]*\s*:/i.test(line)) {
        break;
      }
      sectionLines.push(line);
    }

    return sectionLines.join("\n");
  }

  _extractActionBlocks(yaml) {
    const section = this._extractTopLevelSectionBlock(yaml, "actions");
    if (!section) return [];

    const lines = section.split(/\r?\n/).slice(1);
    const blocks = [];
    let currentBlock = [];
    lines.forEach((line) => {
      if (/^\s*-\s+/.test(line)) {
        if (currentBlock.length > 0) {
          blocks.push(currentBlock.join("\n"));
        }
        currentBlock = [line];
        return;
      }
      if (currentBlock.length > 0) {
        currentBlock.push(line);
      }
    });
    if (currentBlock.length > 0) {
      blocks.push(currentBlock.join("\n"));
    }
    return blocks;
  }

  _collectYamlIssues(yaml) {
    const text = this._normalizeText(yaml);
    if (!text) return ["The response did not include automation YAML."];

    const issues = [];
    if (!/^alias\s*:/m.test(text)) {
      issues.push("Include an alias field.");
    }
    if (!/^triggers\s*:/m.test(text)) {
      issues.push("Use a top-level triggers: list.");
    }
    if (!/^actions\s*:/m.test(text)) {
      issues.push("Use a top-level actions: list.");
    }
    if (/^\s*(?:-\s*)?platform\s*:/m.test(text)) {
      issues.push("Inside each trigger item, use trigger: instead of platform:.");
    }
    if (/^\s*(?:-\s*)?service\s*:/m.test(text)) {
      issues.push("Inside each action item, use action: instead of service:.");
    }
    const triggerSection = this._extractTopLevelSectionBlock(text, "triggers");
    if (
      /\btrigger\s*:\s*state\b[\s\S]*?\n\s+(?:above|below)\s*:/i.test(
        triggerSection
      ) ||
      /\btrigger\s*:\s*state\b[\s\S]*?\n\s+to\s*:\s*["']?(?:above|below)["']?/i.test(
        triggerSection
      )
    ) {
      issues.push("Use numeric_state triggers for numeric thresholds, not state triggers with above:/below:.");
    }
    const conditionSection = this._extractTopLevelSectionBlock(text, "conditions");
    if (
      /\bcondition\s*:\s*state\b[\s\S]*?\n\s+(?:above|below)\s*:/i.test(
        conditionSection
      ) ||
      /\bcondition\s*:\s*state\b[\s\S]*?\n\s+state\s*:\s*["']?(?:above|below)["']?/i.test(
        conditionSection
      )
    ) {
      issues.push("Use numeric_state conditions for numeric thresholds, not state conditions with above:/below:.");
    }
    if (/^\s*automation\s*:/m.test(text)) {
      issues.push("Do not wrap the automation in a top-level automation: block.");
    }
    if (/^\s*trigger:\s*\w+/m.test(text) && !/^\s*-\s*trigger\s*:/m.test(text)) {
      issues.push("Trigger entries must be list items under triggers: using - trigger:.");
    }
    if (/^\s*action\s*:\s*\w+/m.test(text) && !/^\s*-\s*action\s*:/m.test(text)) {
      issues.push("Action entries must be list items under actions: using - action:.");
    }
    if (/^\s*conditions\s*:\s*\|/m.test(text)) {
      issues.push("conditions: must be a list, not a block string.");
    }
    if ((text.match(/^triggers\s*:/gm) || []).length > 1) {
      issues.push("Use a single top-level triggers: section.");
    }
    if ((text.match(/^conditions\s*:/gm) || []).length > 1) {
      issues.push("Use a single top-level conditions: section.");
    }
    if ((text.match(/^actions\s*:/gm) || []).length > 1) {
      issues.push("Use a single top-level actions: section.");
    }
    if (/^\s*-\s*condition\s*:/m.test(triggerSection)) {
      issues.push("Trigger items under triggers: must use - trigger:, not - condition:.");
    }
    if (/^\s*-\s*action\s*:/m.test(triggerSection)) {
      issues.push("Trigger items under triggers: must use - trigger:, not - action:.");
    }
    const actionSection = this._extractTopLevelSectionBlock(text, "actions");
    if (/^  -\s*condition\s*:/m.test(actionSection)) {
      issues.push("Action items under actions: must not be conditions.");
    }
    if (/^  -\s*trigger\s*:/m.test(actionSection)) {
      issues.push("Action items under actions: must not be triggers.");
    }
    if (/\b(?:above_limit|below_limit)\s*:/m.test(text)) {
      issues.push("Use valid numeric_state keys such as above: and below:, not above_limit: or below_limit:.");
    }
    if (/\b(?:condition_entity_id|condition_state|condition_value_template)\s*:/m.test(text)) {
      issues.push("Do not use pseudo trigger fields like condition_entity_id:, condition_state:, or condition_value_template:.");
    }
    if (/^\s*-\s*template\s*:/m.test(text)) {
      issues.push("Use valid actions such as action:, variables:, choose:, delay:, or conditions:, not - template:.");
    }
    if (
      /-\s*action:\s*notify\.[^\n]+[\s\S]*?\n\s+message\s*:/i.test(actionSection) &&
      !/-\s*action:\s*notify\.[^\n]+[\s\S]*?\n\s+data\s*:/i.test(actionSection)
    ) {
      issues.push("Put notify message text under data:, not directly under the action.");
    }
    if (/\bstate\s*:\s*active\b/i.test(text)) {
      issues.push("Use real Home Assistant entity states such as on or off, not active.");
    }
    return issues;
  }

  _yamlIncludesAllEntityIds(yaml, entityIds = []) {
    const text = this._normalizeText(yaml);
    const ids = Array.isArray(entityIds) ? entityIds : [];
    if (!text || ids.length === 0) return false;
    return ids.every((entityId) => text.includes(this._normalizeText(entityId)));
  }

  _collectYamlCoverageIssues(prompt, yaml, context = {}) {
    const text = this._normalizeText(yaml);
    const requestText = this._normalizeText(prompt);
    const normalizedPrompt = this._normalizePhrase(requestText);
    const entities = Array.isArray(context?.entities) ? context.entities : [];
    if (!text || !requestText || entities.length === 0) {
      return [];
    }

    const issues = [];
    const siblingGroups = this._collectSiblingGroups(requestText, entities);
    const groupClauseMappings = this._buildGroupClauseMappings(
      requestText,
      siblingGroups
    );
    const groupedMappings =
      groupClauseMappings.length > 0
        ? groupClauseMappings
        : siblingGroups.map((group) => ({
            label: this._siblingGroupLabel(group),
            clause: "",
            entities: group.map((entity) => entity.entity_id),
          }));
    const groupedEntityIds = new Set(
      groupedMappings.flatMap((mapping) => mapping.entities)
    );

    groupedMappings.forEach((mapping) => {
      if (
        Array.isArray(mapping.entities) &&
        mapping.entities.length > 1 &&
        !this._yamlIncludesAllEntityIds(text, mapping.entities)
      ) {
        issues.push(
          `Use the full resolved ${mapping.label} entity family together: ${mapping.entities.join(", ")}.`
        );
      }
    });

    const exactMatches = this._findObviousNamedEntities(requestText, entities, 20).filter(
      (entity) =>
        !groupedEntityIds.has(entity.entity_id) &&
        entity.domain !== "notify" &&
        entity.domain !== "automation"
    );
    exactMatches.forEach((entity) => {
      if (!text.includes(entity.entity_id)) {
        issues.push(`Include the resolved entity ${entity.entity_id}.`);
      }
    });

    const notifyMatches =
      /\b(notify|notification|iphone|phone|tablet|mobile)\b/i.test(requestText)
        ? this._relevantDomainMatches(requestText, entities, "notify", 1, 4)
        : [];
    if (
      notifyMatches.length > 0 &&
      !notifyMatches.some((entity) => text.includes(entity.entity_id))
    ) {
      issues.push(`Use the resolved notification target ${notifyMatches[0].entity_id}.`);
    }

    const automationMatches =
      normalizedPrompt.includes("automation")
        ? this._relevantDomainMatches(requestText, entities, "automation", 2, 8)
        : [];
    if (
      automationMatches.length > 0 &&
      !automationMatches.some((entity) => text.includes(entity.entity_id))
    ) {
      issues.push(`Use the resolved automation guard ${automationMatches[0].entity_id}.`);
    }

    const timeWindowGuard = this._extractTimeWindowGuard(requestText);
    if (
      timeWindowGuard?.after &&
      timeWindowGuard?.before &&
      (!text.includes(`after: "${timeWindowGuard.after}"`) ||
        !text.includes(`before: "${timeWindowGuard.before}"`) ||
        !/\bcondition:\s*(?:time|not)\b/i.test(text))
    ) {
      issues.push(
        `Preserve the requested time window between ${timeWindowGuard.after} and ${timeWindowGuard.before} as a condition.`
      );
    }

    const explicitStateGuards = this._extractExplicitStateGuardSpecs(
      requestText,
      entities
    );
    explicitStateGuards.forEach((guard) => {
      const expectedState = guard.requiredState || guard.blockedState;
      const statePattern = new RegExp(
        `entity_id:\\s*${guard.entity_id.replace(".", "\\.")}[\\s\\S]{0,160}?state:\\s*["']?${expectedState}["']?`,
        "i"
      );
      if (!statePattern.test(text)) {
        issues.push(
          `Respect the explicit guard ${guard.entity_id} before running the actions.`
        );
      }
    });

    if (/\b(wait|delay)\b/i.test(requestText) && !/^\s*-\s*delay:|^\s*delay:/m.test(text)) {
      issues.push("Include a delay action for the requested wait.");
    }
    if (
      /\b(otherwise|instead|if .* still|during the .* wait|fallback)\b/i.test(
        requestText
      ) &&
      !/^\s*-\s*choose:|^\s*choose:/m.test(text)
    ) {
      issues.push("Use choose/default branches to implement the requested follow-up outcomes.");
    }
    if (
      /\bwhichever sensor triggered\b|\bactual sensor value\b/i.test(requestText) &&
      !/\btrigger\.entity_id\b|\btrigger\.to_state\b|\btrigger\.to_state\.state\b|\bvariables:\b/i.test(
        text
      )
    ) {
      issues.push("Capture the triggering sensor and its live value in variables for the notification.");
    }
    if (/\bflash(?: it)? twice\b/i.test(requestText) && !/\bflash\b|\brepeat:\b/i.test(text)) {
      issues.push("Implement the requested flashing behavior.");
    }
    if (
      /\bred\b/i.test(requestText) &&
      !/\bcolor_name:\s*["']?red["']?\b|\brgb_color\b|\bxy_color\b/i.test(text)
    ) {
      issues.push("Preserve the requested red lamp color.");
    }
    if (
      /\bwhite\b/i.test(requestText) &&
      !/\bcolor_name:\s*["']?white["']?\b|\bkelvin\b|\bcolor_temp\b|\brgb_color\b|\bxy_color\b/i.test(
        text
      )
    ) {
      issues.push("Preserve the requested white lamp color in the fallback branch.");
    }
    if (
      /\b50\s*(?:%|percent)\s+brightness\b/i.test(requestText) &&
      !/brightness_pct:\s*50\b/i.test(text)
    ) {
      issues.push("Preserve the requested 50% brightness.");
    }
    if (
      /\b(?:full|100\s*(?:%|percent))\s+brightness\b/i.test(requestText) &&
      !/brightness_pct:\s*100\b/i.test(text)
    ) {
      issues.push("Preserve the requested full brightness in the fallback branch.");
    }
    if (
      /\bdisable\b/i.test(requestText) &&
      /action:\s*switch\.turn_on[\s\S]*?entity_id:\s*switch\./m.test(text)
    ) {
      issues.push("Use turn_off for switches the user asked to disable.");
    }

    for (const match of requestText.matchAll(/\b(\d+(?:\.\d+)?)\s*(volts?|amps?|watts?|w)\b/gi)) {
      if (!text.includes(match[1])) {
        issues.push(`Preserve the ${match[1]} ${match[2]} threshold from the request.`);
      }
    }

    const actionBlocks = this._extractActionBlocks(text);
    actionBlocks.forEach((block) => {
      const actionMatch = block.match(/-\s*action:\s*([a-z_]+)\.turn_(on|off)/i);
      if (!actionMatch) return;
      const serviceDomain = actionMatch[1].toLowerCase();
      const entityIds = [...block.matchAll(/\bentity_id:\s*([a-z0-9_]+\.[a-z0-9_]+)/gi)].map(
        (entry) => entry[1]
      );
      if (entityIds.length === 0) return;
      const targetDomains = [
        ...new Set(entityIds.map((entityId) => entityId.split(".")[0]).filter(Boolean)),
      ];
      if (
        targetDomains.length === 1 &&
        targetDomains[0] !== serviceDomain &&
        serviceDomain !== "homeassistant" &&
        serviceDomain !== "scene"
      ) {
        issues.push(
          `Use an action service that matches ${targetDomains[0]} targets instead of ${serviceDomain}.turn_${actionMatch[2]}.`
        );
      }
    });

    return issues.filter(
      (issue, index, items) => issue && items.indexOf(issue) === index
    );
  }

  _collectRepairIssues(prompt, yaml, context = {}) {
    return [
      ...this._collectYamlIssues(yaml),
      ...this._collectYamlCoverageIssues(prompt, yaml, context),
    ].filter(
      (issue, index, items) => issue && items.indexOf(issue) === index
    );
  }

  async _repairGeneratedYamlIfNeeded(prompt, messages, result, repairContext = null) {
    let currentResult = result;
    const preferYamlOnlyRepair = this._isComplexAutomationPrompt(prompt);
    const fallbackContext = {
      messages,
      entities: repairContext?.entities || [],
      resolvedPrompt: repairContext?.resolvedPrompt || "",
      plan: repairContext?.plan || null,
    };
    if (currentResult?.planner_only) {
      const compileContext = {
        ...fallbackContext,
        plan: currentResult?.plan_details || repairContext?.plan || null,
      };
      currentResult = await this._compilePlanToYaml(prompt, compileContext);
      if (currentResult?.planner_only) {
        this._pushRepairStatus(
          "The previous response did not include the required complete automation YAML."
        );
        currentResult = await this._regenerateAutomationYamlFromScratch(
          prompt,
          {
            ...compileContext,
            plan: currentResult?.plan_details || compileContext.plan || null,
          },
          ["The previous response returned planning keys instead of automation YAML."],
          currentResult?.yaml || ""
        );
      }
      if (currentResult?.needs_clarification) {
        return currentResult;
      }
    }
    if (currentResult?.missing_yaml) {
      if (preferYamlOnlyRepair) {
        this._pushRepairStatus(
          "The previous response did not include the required complete automation YAML."
        );
        currentResult = await this._regenerateAutomationYamlFromScratch(
          prompt,
          {
            ...fallbackContext,
            plan: currentResult?.plan_details || fallbackContext.plan || null,
          },
          [
            "The previous response did not include the required complete automation YAML.",
          ],
          currentResult?.yaml || ""
        );
        if (currentResult?.needs_clarification) {
          return currentResult;
        }
      } else {
        for (let attempt = 0; attempt < DIRECT_REPAIR_ATTEMPTS; attempt += 1) {
          this._pushRepairStatus(
            "The previous response did not include the required complete automation YAML."
          );
          const missingYamlMessages = [
            ...messages,
            {
              role: "assistant",
              content: JSON.stringify({
                yaml: currentResult?.yaml || null,
                summary: currentResult?.summary || "",
                needs_clarification: false,
                clarifying_questions: [],
              }),
            },
            {
              role: "user",
              content:
                "Your previous response did not include the required automation YAML. " +
                "Return the complete automation JSON now. " +
                "The yaml key must be a non-empty string containing the full Home Assistant automation. " +
                "Do not leave yaml null or empty. " +
                "Do not say the automation is ready, complete, or being generated. " +
                "Output only the final JSON object.",
            },
          ];
          currentResult = await this._directChatCompletion(missingYamlMessages);
          if (currentResult?.needs_clarification) {
            return currentResult;
          }
          if (!currentResult?.missing_yaml && currentResult?.yaml) {
            break;
          }
        }
      }
    }

    if (preferYamlOnlyRepair) {
      const deterministicFallback = this._buildDeterministicComplexAutomationResult(
        prompt,
        fallbackContext
      );
      if (deterministicFallback?.yaml) {
        const deterministicIssues = this._collectRepairIssues(
          prompt,
          deterministicFallback.yaml,
          fallbackContext
        );
        if (deterministicIssues.length === 0) {
          return deterministicFallback;
        }
      }
    }

    let remainingIssues = this._collectRepairIssues(
      prompt,
      currentResult?.yaml || "",
      fallbackContext
    );
    if (preferYamlOnlyRepair && remainingIssues.length > 0) {
      this._pushRepairStatus(remainingIssues.join(" "));
      currentResult = await this._regenerateAutomationYamlFromScratch(
        prompt,
        {
          ...fallbackContext,
          plan: currentResult?.plan_details || fallbackContext.plan || null,
        },
        remainingIssues,
        currentResult?.yaml || ""
      );
      if (currentResult?.needs_clarification) {
        return currentResult;
      }
      remainingIssues = this._collectRepairIssues(
        prompt,
        currentResult?.yaml || "",
        fallbackContext
      );
    }
    if (preferYamlOnlyRepair && remainingIssues.length > 0 && !currentResult?.needs_clarification) {
      this._pushRepairStatus(remainingIssues.join(" "));
      currentResult = await this._rewriteInvalidAutomationYaml(
        prompt,
        messages,
        currentResult,
        remainingIssues
      );
      if (currentResult?.needs_clarification) {
        return currentResult;
      }
      remainingIssues = this._collectRepairIssues(
        prompt,
        currentResult?.yaml || "",
        fallbackContext
      );
    }
    for (let attempt = 0; attempt < DIRECT_REPAIR_ATTEMPTS; attempt += 1) {
      if (remainingIssues.length === 0) {
        return currentResult;
      }
      const issues = remainingIssues;
      this._pushRepairStatus(issues.join(" "));

      const repairMessages = [
        ...messages,
        {
          role: "assistant",
          content: this._buildAutomationContextMessage(
            currentResult?.summary,
            currentResult?.yaml
          ),
        },
        {
          role: "user",
          content:
            "The automation YAML above is invalid or does not follow the required Home Assistant 2024.10+ syntax. " +
            "Fix it and return the complete corrected automation JSON only. " +
            `Issues to fix: ${issues.join(" ")} ` +
            "Do not ask new clarification questions unless the original prompt truly leaves a required detail unspecified.",
        },
      ];

      currentResult = await this._directChatCompletion(repairMessages);
      if (currentResult?.needs_clarification) {
        return currentResult;
      }
      remainingIssues = this._collectRepairIssues(
        prompt,
        currentResult?.yaml || "",
        fallbackContext
      );
    }

    if (remainingIssues.length > 0 && !currentResult?.needs_clarification) {
      this._pushRepairStatus(remainingIssues.join(" "));
      try {
        currentResult = await this._rewriteInvalidAutomationYaml(
          prompt,
          messages,
          currentResult,
          remainingIssues
        );
      } catch (err) {
        currentResult = await this._regenerateAutomationYamlFromScratch(
          prompt,
          {
            ...fallbackContext,
            plan: currentResult?.plan_details || fallbackContext.plan || null,
          },
          remainingIssues,
          currentResult?.yaml || ""
        );
      }
      if (currentResult?.needs_clarification) {
        return currentResult;
      }
      remainingIssues = this._collectRepairIssues(
        prompt,
        currentResult?.yaml || "",
        fallbackContext
      );
    }

    if (remainingIssues.length > 0 && !currentResult?.needs_clarification) {
      for (let attempt = 0; attempt < DIRECT_REGENERATION_ATTEMPTS; attempt += 1) {
        this._pushRepairStatus(remainingIssues.join(" "));
        currentResult = await this._regenerateAutomationYamlFromScratch(
          prompt,
          {
            ...fallbackContext,
            plan: currentResult?.plan_details || fallbackContext.plan || null,
          },
          remainingIssues,
          currentResult?.yaml || ""
        );
        remainingIssues = this._collectRepairIssues(
          prompt,
          currentResult?.yaml || "",
          fallbackContext
        );
        if (remainingIssues.length === 0) {
          return currentResult;
        }
      }
    }

    if (remainingIssues.length > 0 && !currentResult?.needs_clarification) {
      throw new Error(
        "AutoMagic sent each returned YAML error back to the AI, but the model still " +
          `did not produce valid automation YAML. Last issue: ${remainingIssues.join(" ")}`
      );
    }

    return currentResult;
  }

  _humanizeIdentifier(value) {
    return this._normalizeText(value)
      .replace(/^mobile_app_/, "")
      .replace(/^notify\./, "")
      .replace(/[_\.]+/g, " ")
      .replace(/\s+/g, " ")
      .trim()
      .replace(/\b\w/g, (char) => char.toUpperCase());
  }

  _notificationServiceEntries() {
    const notifyServices = this.hass?.services?.notify;
    if (!notifyServices || typeof notifyServices !== "object") {
      return [];
    }

    return Object.keys(notifyServices)
      .filter((serviceName) => Boolean(serviceName))
      .map((serviceName) => ({
        entity_id: `notify.${serviceName}`,
        name: serviceName.startsWith("mobile_app_")
          ? `Notify ${this._humanizeIdentifier(serviceName)}`
          : this._humanizeIdentifier(serviceName),
        domain: "notify",
        state: "service",
        device_class: "service",
      }));
  }

  _collectSemanticPromptMatches(prompt, entities, maxMatchesPerHint = 4) {
    const text = this._normalizePhrase(prompt);
    if (!text || !Array.isArray(entities) || entities.length === 0) return [];

    const concepts = [
      {
        label: "power",
        pattern: /\b(power|watt(?:age|s)?|kw|kilowatt(?:s)?)\b/,
        domains: new Set(["sensor", "number", "input_number"]),
        deviceClasses: new Set(["power", "energy"]),
        tokens: new Set(["power", "watt", "wattage", "kw", "kilowatt", "energy"]),
        requireAffinityMatch: true,
      },
      {
        label: "voltage",
        pattern: /\b(voltage|volt(?:s)?)\b/,
        domains: new Set(["sensor", "number", "input_number"]),
        deviceClasses: new Set(["voltage"]),
        tokens: new Set(["voltage", "volt", "volts"]),
        requireAffinityMatch: true,
      },
      {
        label: "current",
        pattern: /\b(current|amp(?:s|ere|erage)?|amperage)\b/,
        domains: new Set(["sensor", "number", "input_number"]),
        deviceClasses: new Set(["current"]),
        tokens: new Set(["current", "amp", "amps", "ampere", "amperage"]),
        requireAffinityMatch: true,
      },
      {
        label: "notification",
        pattern: /\b(notify|notification|iphone|phone|mobile)\b/,
        domains: new Set(["notify"]),
        deviceClasses: new Set(["service"]),
        tokens: new Set(["notify", "notification", "iphone", "phone", "mobile", "app"]),
        preferDomainMatches: true,
      },
      {
        label: "tv",
        pattern: /\b(tv|television)\b/,
        domains: new Set(["media_player"]),
        deviceClasses: new Set(),
        tokens: new Set(["tv", "television"]),
        excludeSpeakerLike: true,
      },
    ];

    const promptTokens = new Set(this._tokenizePrompt(prompt));
    const promptHasOutput = promptTokens.has("output");
    const promptHasInput = promptTokens.has("input");

    return concepts
      .filter((concept) => concept.pattern.test(text))
      .map((concept) => {
        const preferredPresent =
          concept.preferDomainMatches &&
          entities.some((entity) => concept.domains.has(String(entity.domain || "")));
        const contextTokens = [...promptTokens].filter(
          (token) =>
            !concept.tokens.has(token) &&
            !DIRECT_SEMANTIC_CONTEXT_IGNORE_TOKENS.has(token)
        );
        const scored = [];
        entities.forEach((entity, index) => {
          const domain = String(entity.domain || "");
          const deviceClass = this._normalizePhrase(entity.device_class);
          if (preferredPresent && !concept.domains.has(domain)) {
            return;
          }
          if (concept.excludeSpeakerLike && this._isSpeakerLike(entity)) {
            return;
          }

          const haystack = this._normalizePhrase(
            `${entity.entity_id || ""} ${entity.name || ""} ${entity.domain || ""} ${entity.device_class || ""} ${entity.state || ""}`
          );
          const haystackTokens = new Set(this._tokenizePrompt(haystack));

          let score = 0;
          let contextOverlap = 0;
          if (concept.domains.has(domain)) score += 3;
          if (concept.deviceClasses.has(deviceClass)) score += 5;
          const matchedAffinityTokens = [...concept.tokens].filter((token) =>
            haystackTokens.has(token)
          ).length;
          if (
            concept.requireAffinityMatch &&
            matchedAffinityTokens === 0 &&
            !concept.deviceClasses.has(deviceClass)
          ) {
            return;
          }
          score += matchedAffinityTokens * 2;
          contextTokens.forEach((token) => {
            if (!haystackTokens.has(token)) return;
            contextOverlap += 1;
            score += 2;
          });
          const matchesSpecificScope =
            (promptHasOutput && haystackTokens.has("output")) ||
            (promptHasInput && haystackTokens.has("input"));
          if (
            promptHasOutput &&
            haystackTokens.has("input") &&
            !haystackTokens.has("output")
          ) {
            score -= 4;
          }
          if (
            promptHasInput &&
            haystackTokens.has("output") &&
            !haystackTokens.has("input")
          ) {
            score -= 4;
          }
          if (domain === "notify" && concept.label === "notification") score += 5;
          if (domain === "media_player" && concept.label === "tv") score += 2;

          if (score > 0) {
            scored.push({
              score,
              index,
              entity,
              contextOverlap,
              matchesSpecificScope,
            });
          }
        });

        scored.sort((left, right) => {
          if (right.score !== left.score) return right.score - left.score;
          return left.index - right.index;
        });

        let filtered = scored;
        if (filtered.some((item) => item.matchesSpecificScope)) {
          filtered = filtered.filter((item) => item.matchesSpecificScope);
        }
        if (
          filtered.some((item) => item.contextOverlap > 0) &&
          (concept.requireAffinityMatch || concept.preferDomainMatches)
        ) {
          filtered = filtered.filter((item) => item.contextOverlap > 0);
        }
        const bestScore = filtered[0]?.score || 0;
        if (bestScore > 0 && concept.requireAffinityMatch) {
          filtered = filtered.filter((item) => item.score >= Math.max(5, bestScore - 4));
        }

        return {
          label: concept.label,
          entities: filtered
            .slice(0, maxMatchesPerHint)
            .map((item) => item.entity)
            .filter(
              (entity, index, items) =>
                items.findIndex(
                  (candidate) => candidate.entity_id === entity.entity_id
                ) === index
            ),
        };
      })
      .filter((match) => match.entities.length > 0);
  }

  _semanticEntityMatches(prompt, entities, maxMatches = 16) {
    const selected = [];
    const seen = new Set();

    this._collectSemanticPromptMatches(prompt, entities).forEach((match) => {
      match.entities.forEach((entity) => {
        if (seen.has(entity.entity_id)) return;
        seen.add(entity.entity_id);
        selected.push(entity);
      });
    });

    return selected.slice(0, maxMatches);
  }

  _collectHeuristicEntities(prompt, entities) {
    const text = this._normalizePhrase(prompt);
    if (!text || !Array.isArray(entities) || entities.length === 0) return [];

    const matches = [];
    const pushMatches = (predicate) => {
      entities.forEach((entity) => {
        if (!predicate(entity)) return;
        if (matches.some((candidate) => candidate.entity_id === entity.entity_id)) {
          return;
        }
        matches.push(entity);
      });
    };
    const pushPhraseMatches = (phrase, maxMatches = 6) => {
      this._findEntitiesByPhrase(phrase, entities, maxMatches).forEach((entity) => {
        if (matches.some((candidate) => candidate.entity_id === entity.entity_id)) {
          return;
        }
        matches.push(entity);
      });
    };
    const obviousEntities = this._findObviousNamedEntities(prompt, entities, 16);
    const semanticEntities = this._semanticEntityMatches(prompt, entities, 16);
    const rankedEntities = this._selectRelevantEntities(prompt, entities, 12, 0);
    const seedEntities = [...obviousEntities, ...semanticEntities, ...rankedEntities].filter(
      (entity, index, items) =>
        items.findIndex((candidate) => candidate.entity_id === entity.entity_id) === index
    );
    seedEntities.forEach((entity) => {
      if (matches.some((candidate) => candidate.entity_id === entity.entity_id)) {
        return;
      }
      matches.push(entity);
    });

    if (/\bautomation\b/.test(text)) {
      this._relevantDomainMatches(prompt, entities, "automation", 2, 8).forEach(
        (entity) => {
          if (matches.some((candidate) => candidate.entity_id === entity.entity_id)) {
            return;
          }
          matches.push(entity);
        }
      );
    }

    if (/\biphone\b|\bnotification\b|\bnotify\b/.test(text)) {
      this._relevantDomainMatches(prompt, entities, "notify", 1, 4).forEach(
        (entity) => {
          if (matches.some((candidate) => candidate.entity_id === entity.entity_id)) {
            return;
          }
          matches.push(entity);
        }
      );
    }

    this._expandEntityFamilies(prompt, seedEntities, entities).forEach((entity) => {
      if (matches.some((candidate) => candidate.entity_id === entity.entity_id)) {
        return;
      }
      matches.push(entity);
    });

    return matches;
  }

  _entitySummary(entities) {
    return entities
      .map(
        (entity) => `${entity.entity_id} (${entity.name})`
      )
      .join("\n");
  }

  _findExplicitEntities(prompt, entities) {
    const haystack = String(prompt || "").toLowerCase();
    if (!haystack || !Array.isArray(entities)) return [];

    return entities.filter((entity) =>
      haystack.includes(String(entity.entity_id || "").toLowerCase())
    );
  }

  _findEntitiesByPhrase(phrase, entities, maxMatches = 5) {
    const normalizedPhrase = this._normalizePhrase(phrase);
    if (!normalizedPhrase || !Array.isArray(entities)) return [];

    const phraseTokens = new Set(
      (normalizedPhrase.match(DIRECT_TOKEN_RE) || []).filter(
        (token) =>
          (token.length >= 3 || IMPORTANT_SHORT_TOKENS.has(token)) &&
          !DIRECT_IGNORE_TOKENS.has(token)
      )
    );
    const scored = [];

    entities.forEach((entity, index) => {
      const entityId = String(entity.entity_id || "");
      const normalizedName = this._normalizePhrase(entity.name || entityId);
      const nameTokens = new Set(
        (normalizedName.match(DIRECT_TOKEN_RE) || []).filter(
          (token) =>
            (token.length >= 3 || IMPORTANT_SHORT_TOKENS.has(token)) &&
            !DIRECT_IGNORE_TOKENS.has(token)
        )
      );
      if (nameTokens.size === 0) return;

      let score = 0;
      if (normalizedName === normalizedPhrase) score += 200;
      if (nameTokens.size >= 2 && normalizedPhrase.includes(normalizedName)) {
        score += 150;
      }
      if (this._normalizePhrase(entityId) === normalizedPhrase) score += 200;
      if (
        nameTokens.size === 1 &&
        phraseTokens.size === 1 &&
        phraseTokens.has([...nameTokens][0])
      ) {
        score += 120;
      }

      let matched = 0;
      for (const token of nameTokens) {
        if (phraseTokens.has(token)) matched += 1;
      }
      if (matched === nameTokens.size && nameTokens.size >= 2) {
        score += 100 + matched;
      } else if (matched >= 2) {
        score += 20 + matched;
      }

      if (score > 0) {
        scored.push({ score, index, entity });
      }
    });

    scored.sort((left, right) => {
      if (right.score !== left.score) return right.score - left.score;
      return left.index - right.index;
    });

    return scored
      .slice(0, maxMatches)
      .map((item) => item.entity)
      .filter(
        (entity, index, items) =>
          items.findIndex(
            (candidate) => candidate.entity_id === entity.entity_id
          ) === index
      );
  }

  _findObviousNamedEntities(prompt, entities, maxMatches = 12) {
    const normalizedPrompt = String(prompt || "").toLowerCase();
    if (!normalizedPrompt || !Array.isArray(entities)) return [];

    const promptTokens = new Set(this._tokenizePrompt(prompt));
    const scored = [];

    entities.forEach((entity, index) => {
      const rawName = String(entity.name || "").trim();
      if (!rawName) return;

      const normalizedName = rawName.toLowerCase();
      const baseName = normalizedName.replace(DIRECT_NAME_VARIANT_SUFFIX_RE, "").trim();
      const nameTokens = this._tokenizePrompt(rawName);
      if (nameTokens.length === 0) return;

      let score = 0;
      if (
        nameTokens.length >= 2 &&
        normalizedPrompt.includes(normalizedName)
      ) {
        score += 100;
      }
      if (
        baseName &&
        baseName !== normalizedName &&
        baseName.split(/\s+/).length >= 2 &&
        normalizedPrompt.includes(baseName)
      ) {
        score += 70;
      }
      if (
        nameTokens.length === 1 &&
        promptTokens.size === 1 &&
        promptTokens.has(nameTokens[0])
      ) {
        score += 80;
      }

      const matchedTokens = nameTokens.filter((token) => promptTokens.has(token));
      if (matchedTokens.length === nameTokens.length && nameTokens.length >= 2) {
        score += 80 + nameTokens.length;
      } else if (matchedTokens.length >= 2) {
        score += 20 + matchedTokens.length;
      }
      if (baseName && baseName !== normalizedName) {
        const baseTokens = this._tokenizePrompt(baseName);
        const matchedBaseTokens = baseTokens.filter((token) => promptTokens.has(token));
        if (
          matchedBaseTokens.length === baseTokens.length &&
          baseTokens.length >= 2
        ) {
          score += 50 + baseTokens.length;
        } else if (matchedBaseTokens.length >= 2) {
          score += 16 + matchedBaseTokens.length;
        }
      }

      if (score > 0) {
        scored.push({ score, index, entity });
      }
    });

    scored.sort((left, right) => {
      if (right.score !== left.score) return right.score - left.score;
      return left.index - right.index;
    });

    return scored
      .slice(0, maxMatches)
      .map((item) => item.entity)
      .filter(
        (entity, index, items) =>
          items.findIndex(
            (candidate) => candidate.entity_id === entity.entity_id
          ) === index
      );
  }

  _hasClearSchedule(prompt) {
    const text = String(prompt || "").toLowerCase();
    const hasRecurringContext =
      /\b(?:every ?day|daily|every morning|every evening|every night|every weekday|every weekdays|every weekend|every weekends|each day|each weekday|each weekend)\b/.test(
        text
      ) ||
      /\b(?:every|each)\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)s?\b/.test(
        text
      );
    const hasExplicitTriggerTime =
      /\bat\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b/.test(text) ||
      /\bat\s+\d{1,2}:\d{2}\b/.test(text);

    return (
      (hasExplicitTriggerTime && hasRecurringContext) ||
      /\bat (sunrise|sunset)\b/.test(text)
    );
  }

  _hasTimeWindowGuard(prompt) {
    const text = String(prompt || "").toLowerCase();
    return (
      /\b(?:not|except|outside)\s+between\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s+(?:and|to|-)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b/.test(
        text
      ) ||
      /\bbetween\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s+(?:and|to|-)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b/.test(
        text
      ) ||
      /\bbetween\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s+(?:and|to|-)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s+on a weekday\b/.test(
        text
      )
    );
  }

  _parseSimpleTime(timeText) {
    const match = String(timeText || "")
      .trim()
      .toLowerCase()
      .match(/^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$/);
    if (!match) return null;

    let hour = Number(match[1]);
    const minute = Number(match[2] || "0");
    const period = match[3];
    if (Number.isNaN(hour) || Number.isNaN(minute) || minute > 59) {
      return null;
    }
    if (!period) {
      if (hour < 0 || hour > 23) return null;
    } else if (hour < 1 || hour > 12) {
      return null;
    } else if (period === "am") {
      if (hour === 12) hour = 0;
    } else if (hour !== 12) {
      hour += 12;
    }

    return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}:00`;
  }

  _extractWeekdays(prompt) {
    const text = String(prompt || "").toLowerCase();
    if (/\bevery weekday\b|\bevery weekdays\b/.test(text)) {
      return ["mon", "tue", "wed", "thu", "fri"];
    }
    if (/\bevery weekend\b|\bevery weekends\b/.test(text)) {
      return ["sat", "sun"];
    }

    const mappings = [
      ["monday", "mon"],
      ["tuesday", "tue"],
      ["wednesday", "wed"],
      ["thursday", "thu"],
      ["friday", "fri"],
      ["saturday", "sat"],
      ["sunday", "sun"],
    ];
    const weekdays = mappings
      .filter(([word]) => new RegExp(`\\b${word}s?\\b`).test(text))
      .map(([, short]) => short);

    return weekdays.length > 0 ? weekdays : null;
  }

  _extractTimeWindowGuard(prompt) {
    const text = this._normalizeText(prompt);
    if (!text) return null;

    const match = text.match(
      /\b(not\s+|except\s+|outside\s+)?between\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(?:and|to|-)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b/i
    );
    if (!match) return null;

    const after = this._parseSimpleTime(match[2]);
    const before = this._parseSimpleTime(match[3]);
    if (!after || !before) return null;

    return {
      after,
      before,
      negate: /\b(?:not|except|outside)\b/i.test(match[1] || ""),
      weekdays: this._extractWeekdays(text),
    };
  }

  _invertEntityState(state) {
    const normalized = this._normalizeText(state).toLowerCase();
    const opposites = {
      active: "inactive",
      closed: "open",
      home: "not_home",
      inactive: "active",
      locked: "unlocked",
      not_home: "home",
      off: "on",
      on: "off",
      open: "closed",
      unlocked: "locked",
    };
    return opposites[normalized] || "";
  }

  _extractExplicitStateGuardSpecs(prompt, entities) {
    const text = this._normalizeText(prompt);
    const pool = Array.isArray(entities) ? entities : [];
    if (!text || pool.length === 0) return [];

    const patterns = [
      /(?:don't|do not)\s+run(?: any of this| this)?\s+if\s+(.+?)\s+is\s+already\s+(on|off|open|closed|locked|unlocked|active|inactive)\b/gi,
      /\bunless\s+(.+?)\s+is\s+(on|off|open|closed|locked|unlocked|active|inactive)\b/gi,
    ];
    const guards = [];

    patterns.forEach((pattern) => {
      for (const match of text.matchAll(pattern)) {
        const entityPhrase = this._normalizeText(match[1]);
        const blockedState = this._normalizeText(match[2]).toLowerCase();
        if (!entityPhrase || !blockedState) continue;

        const candidates = [
          ...this._findObviousNamedEntities(entityPhrase, pool, 4),
          ...this._findEntitiesByPhrase(entityPhrase, pool, 4),
        ].filter(
          (entity, index, items) =>
            items.findIndex(
              (candidate) => candidate.entity_id === entity.entity_id
            ) === index
        );
        const entity = candidates[0];
        if (!entity?.entity_id) continue;

        guards.push({
          entity_id: entity.entity_id,
          blockedState,
          requiredState: this._invertEntityState(blockedState),
        });
      }
    });

    return guards.filter(
      (guard, index, items) =>
        items.findIndex((candidate) => candidate.entity_id === guard.entity_id) ===
        index
    );
  }

  _buildSimpleAutomationYaml({
    alias,
    description,
    triggerLines,
    actionService,
    entityId,
  }) {
    return [
      `alias: ${alias}`,
      `description: ${description}`,
      "triggers:",
      ...triggerLines,
      "conditions: []",
      "actions:",
      `  - action: ${actionService}`,
      "    target:",
      `      entity_id: ${entityId}`,
      "mode: single",
    ].join("\n");
  }

  _isSpeakerLike(entity) {
    const deviceClass = this._normalizePhrase(entity?.device_class);
    if (deviceClass === "speaker") return true;

    const haystack = this._normalizePhrase(
      `${entity?.entity_id || ""} ${entity?.name || ""}`
    );
    return /\b(speaker|speakers|homepod|audio|sonos)\b|nestaudio/.test(
      haystack
    );
  }

  _candidateEntitiesForTarget(targetLabel, entities) {
    const directMatches = this._findEntitiesByPhrase(targetLabel, entities).filter(
      (entity) => SIMPLE_ACTION_DOMAINS.has(String(entity.domain || ""))
    );
    if (directMatches.length > 0) {
      return directMatches;
    }

    const normalizedTarget = this._normalizePhrase(targetLabel);
    if (/\b(tv|television)\b/.test(normalizedTarget)) {
      return (Array.isArray(entities) ? entities : []).filter(
        (entity) =>
          String(entity.domain || "") === "media_player" &&
          !this._isSpeakerLike(entity)
      );
    }

    return [];
  }

  _parseSimpleScheduledToggleIntent(prompt) {
    const text = String(prompt || "").trim();
    const patterns = [
      /\b(?:turn|switch)\s+(?:the\s+)?(.+?)\s+(on|off)\b.*?\bat\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b/i,
      /\b(?:the\s+)?(.+?)\s+(?:to\s+be\s+|be\s+)?turned\s+(on|off)\b.*?\bat\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b/i,
    ];

    for (const pattern of patterns) {
      const match = text.match(pattern);
      if (!match) continue;

      const targetLabel = this._normalizeText(match[1]);
      const actionWord = String(match[2] || "").toLowerCase();
      const atTime = this._parseSimpleTime(match[3]);
      if (!targetLabel || !actionWord || !atTime) return null;

      return {
        prompt: text,
        targetLabel,
        actionWord,
        atTime,
        weekdays: this._extractWeekdays(text),
      };
    }

    return null;
  }

  _buildDeterministicResult(intent, target) {
    const triggerLines = [
      "  - trigger: time",
      `    at: \"${intent.atTime}\"`,
    ];
    if (intent.weekdays && intent.weekdays.length > 0) {
      triggerLines.push("    weekday:");
      intent.weekdays.forEach((weekday) => {
        triggerLines.push(`      - ${weekday}`);
      });
    }

    const aliasTime = intent.atTime.slice(0, 5);
    const recurrenceText =
      intent.weekdays && intent.weekdays.length > 0
        ? `on ${intent.weekdays.join(", ")}`
        : "every day";
    const alias = `Turn ${intent.actionWord} ${target.name} at ${aliasTime}`;
    const description = `Turns ${intent.actionWord} ${target.name} ${recurrenceText} at ${aliasTime}.`;
    const actionService = `${target.domain}.turn_${intent.actionWord}`;

    return {
      yaml: this._buildSimpleAutomationYaml({
        alias,
        description,
        triggerLines,
        actionService,
        entityId: target.entity_id,
      }),
      summary: description,
      needs_clarification: false,
      clarifying_questions: [],
    };
  }

  _parseDurationPhrase(durationText) {
    const match = String(durationText || "")
      .trim()
      .toLowerCase()
      .match(/^(\d+(?:\.\d+)?)\s*(seconds?|minutes?|hours?)$/);
    if (!match) return "";

    const value = Number(match[1]);
    if (!Number.isFinite(value) || value <= 0) return "";

    let totalSeconds = value;
    if (match[2].startsWith("minute")) {
      totalSeconds *= 60;
    } else if (match[2].startsWith("hour")) {
      totalSeconds *= 3600;
    }
    totalSeconds = Math.max(1, Math.round(totalSeconds));

    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(
      2,
      "0"
    )}:${String(seconds).padStart(2, "0")}`;
  }

  _splitConditionClauses(text) {
    const normalized = this._normalizeText(text);
    if (!normalized) return [];

    const masked = normalized.replace(
      /\bbetween\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(?:and|to|-)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b/gi,
      (_match, start, end) => `between ${start} __range_and__ ${end}`
    );
    const parts = masked
      .split(/\s+\b(and|or)\b\s+/i)
      .map((part) => this._normalizeText(part))
      .filter(Boolean);

    const clauses = [];
    for (let index = 0; index < parts.length; index += 2) {
      const clause = parts[index]
        ?.replace(/__range_and__/gi, "and")
        .replace(/^(if|when)\s+/i, "")
        .replace(/^[,.\s]+|[,.\s]+$/g, "")
        .trim();
      if (!clause) continue;
      clauses.push({
        clause,
        connectorBefore:
          index === 0 ? "" : String(parts[index - 1] || "").toLowerCase(),
      });
    }

    return clauses;
  }

  _resolveEntitiesForThresholdClause(
    prompt,
    clause,
    concept,
    entities,
    semanticMatches = null,
    groupClauseMappings = null
  ) {
    if (!concept || !Array.isArray(entities) || entities.length === 0) return [];

    const normalizedClause = this._normalizePhrase(clause);
    const clauseTokens = new Set(this._tokenizePrompt(clause));
    const mappings = Array.isArray(groupClauseMappings)
      ? groupClauseMappings
      : this._buildGroupClauseMappings(prompt, this._collectSiblingGroups(prompt, entities));
    const scoredMappings = mappings
      .map((mapping) => {
        const normalizedLabel = this._normalizePhrase(mapping.label || "");
        const mappingText = this._normalizePhrase(
          `${mapping.label || ""} ${mapping.clause || ""}`
        );
        if (concept && !normalizedLabel.includes(concept)) {
          return { score: 0, mapping };
        }
        const mappingTokens = new Set(this._tokenizePrompt(mappingText));
        let score = 0;
        clauseTokens.forEach((token) => {
          if (mappingTokens.has(token)) score += 1;
        });
        if (mappingText.includes(concept)) score += 3;
        if (normalizedClause && mappingText.includes(normalizedClause)) score += 4;
        return { score, mapping };
      })
      .sort((left, right) => right.score - left.score);

    if (scoredMappings[0]?.score >= 2) {
      return scoredMappings[0].mapping.entities
        .map((entityId) =>
          entities.find((entity) => entity.entity_id === entityId)
        )
        .filter(Boolean);
    }

    const semantics = Array.isArray(semanticMatches)
      ? semanticMatches
      : this._collectSemanticPromptMatches(prompt, entities);
    const semanticMatch = semantics.find((match) => match.label === concept);
    if (semanticMatch?.entities?.length > 0) {
      return semanticMatch.entities;
    }

    return this._findEntitiesByPhrase(clause, entities, 8).filter((entity) =>
      new Set(["sensor", "number", "input_number"]).has(String(entity.domain || ""))
    );
  }

  _extractThresholdSpec(
    prompt,
    clause,
    entities,
    semanticMatches = null,
    groupClauseMappings = null
  ) {
    const cleanedClause = this._normalizeText(clause);
    if (!cleanedClause) return null;

    const match = cleanedClause.match(
      /(.+?)\b(drops?\s+below|falls?\s+below|has dropped below|dropped below|is below|below|under|less than|exceeds|is above|stays above|still above|remains above|above|over|greater than)\b\s+(\d+(?:\.\d+)?)\s*(volts?|amps?|amperes?|amperage|watts?|w|kw|kilowatts?)/i
    );
    if (!match) return null;

    const operator = String(match[2] || "").toLowerCase();
    let value = Number(match[3]);
    const unit = String(match[4] || "").toLowerCase();
    if (!Number.isFinite(value)) return null;

    let concept = "";
    if (/volt/.test(unit)) {
      concept = "voltage";
    } else if (/amp/.test(unit)) {
      concept = "current";
    } else if (/kw|watt|^w$/.test(unit)) {
      concept = "power";
      if (/^kw|kilowatt/.test(unit)) {
        value *= 1000;
      }
    }
    if (!concept) return null;

    const comparator = /\b(below|under|less)\b/.test(operator) ? "below" : "above";
    const matchedEntities = this._resolveEntitiesForThresholdClause(
      prompt,
      cleanedClause,
      concept,
      entities,
      semanticMatches,
      groupClauseMappings
    );
    if (matchedEntities.length === 0) return null;

    return {
      clause: cleanedClause,
      comparator,
      value: Number.isInteger(value) ? String(value) : String(Number(value.toFixed(3))),
      unit,
      concept,
      label:
        matchedEntities.length > 1
          ? this._siblingGroupLabel(matchedEntities)
          : this._normalizeText(matchedEntities[0]?.name || matchedEntities[0]?.entity_id),
      entityIds: matchedEntities.map((entity) => entity.entity_id),
    };
  }

  _extractImperativeSegments(text) {
    const normalized = this._normalizeText(text);
    if (!normalized) return [];

    const commandPattern =
      /\b(turn off|switch off|turn on|switch on|disable|enable|send(?: a)? notification|send(?: a)? message|send|notify|turn)\b/gi;
    const matches = [...normalized.matchAll(commandPattern)];
    if (matches.length === 0) return [];

    return matches
      .map((match, index) => {
        const start = match.index;
        const end =
          index + 1 < matches.length ? matches[index + 1].index : normalized.length;
        return normalized
          .slice(start, end)
          .replace(/^[,.\s]+|[,.\s]+$/g, "")
          .replace(/^(?:and|then)\s+/i, "")
          .trim();
      })
      .filter(Boolean);
  }

  _reindentYamlLines(lines, sourceIndent = "  ", targetIndent = "  ") {
    const items = Array.isArray(lines) ? lines : [];
    return items.map((line) => {
      const value = String(line ?? "");
      if (sourceIndent && value.startsWith(sourceIndent)) {
        return `${targetIndent}${value.slice(sourceIndent.length)}`;
      }
      return `${targetIndent}${value.trimStart()}`;
    });
  }

  _resolveActionEntities(text, entities, maxMatches = 12, allowedDomains = null) {
    if (!Array.isArray(entities) || entities.length === 0) return [];

    const allowedDomainSet = Array.isArray(allowedDomains)
      ? new Set(allowedDomains.map((domain) => String(domain || "")))
      : null;
    const normalizedText = this._normalizePhrase(text);
    const strictMatches = entities.filter((entity) => {
      const rawName = this._normalizeText(entity.name || entity.entity_id);
      if (!rawName) return false;
      const normalizedName = this._normalizePhrase(rawName);
      const baseName = normalizedName.replace(DIRECT_NAME_VARIANT_SUFFIX_RE, "").trim();
      return (
        normalizedText.includes(normalizedName) ||
        (baseName.split(/\s+/).length >= 2 && normalizedText.includes(baseName))
      );
    });
    const obviousMatches = [
      ...(strictMatches.length > 0
        ? strictMatches.slice(0, maxMatches)
        : this._findObviousNamedEntities(text, entities, maxMatches)),
      ...this._expandEntityFamilies(
        text,
        strictMatches.length > 0
          ? strictMatches.slice(0, maxMatches)
          : this._findObviousNamedEntities(text, entities, maxMatches),
        entities
      ),
    ].filter(
      (entity, index, items) =>
        items.findIndex(
          (candidate) => candidate.entity_id === entity.entity_id
        ) === index
    );
    const matched =
      obviousMatches.length > 0
        ? obviousMatches
        : this._findEntitiesByPhrase(text, entities, maxMatches);

    if (!allowedDomainSet) {
      return matched;
    }

    return matched.filter((entity) =>
      allowedDomainSet.has(String(entity.domain || ""))
    );
  }

  _buildEntityTargetLines(entityIds, indent = "    ") {
    const ids = Array.isArray(entityIds) ? entityIds.filter(Boolean) : [];
    if (ids.length === 0) return [];
    if (ids.length === 1) {
      return [`${indent}entity_id: ${ids[0]}`];
    }
    return [
      `${indent}entity_id:`,
      ...ids.map((entityId) => `${indent}  - ${entityId}`),
    ];
  }

  _buildServiceActionLines(service, entityIds, data = {}, indent = "  ") {
    const lines = [`${indent}- action: ${service}`];
    const ids = Array.isArray(entityIds) ? entityIds.filter(Boolean) : [];
    if (ids.length > 0) {
      lines.push(`${indent}  target:`);
      lines.push(...this._buildEntityTargetLines(ids, `${indent}    `));
    }

    const entries = Object.entries(data || {}).filter(([, value]) => value !== "");
    if (entries.length > 0) {
      lines.push(`${indent}  data:`);
      entries.forEach(([key, value]) => {
        const formattedValue =
          typeof value === "number" || typeof value === "boolean"
            ? value
            : JSON.stringify(String(value));
        lines.push(`${indent}    ${key}: ${formattedValue}`);
      });
    }

    return lines;
  }

  _buildAutomationGuardConditionLines(entityIds) {
    const ids = Array.isArray(entityIds) ? entityIds.filter(Boolean) : [];
    if (ids.length === 0) return [];

    const expression = ids
      .map(
        (entityId) =>
          `(state_attr('${entityId}', 'current') | int(0)) == 0`
      )
      .join(" and ");

    return [
      "  - condition: template",
      "    value_template: >-",
      `      {{ ${expression} }}`,
    ];
  }

  _buildExplicitStateGuardConditionLines(guards) {
    const items = Array.isArray(guards) ? guards : [];
    const lines = [];

    items.forEach((guard) => {
      if (!guard?.entity_id || !guard?.blockedState) return;
      if (guard.requiredState) {
        lines.push("  - condition: state");
        lines.push(`    entity_id: ${guard.entity_id}`);
        lines.push(`    state: "${guard.requiredState}"`);
        return;
      }

      lines.push("  - condition: not");
      lines.push("    conditions:");
      lines.push("      - condition: state");
      lines.push(`        entity_id: ${guard.entity_id}`);
      lines.push(`        state: "${guard.blockedState}"`);
    });

    return lines;
  }

  _normalizeConditionalSentenceLead(text) {
    return this._normalizeText(text).replace(/^(?:and|then|also|but)\s+/i, "").trim();
  }

  _buildDeterministicActionSequence(text, entities, options = {}) {
    const normalized = this._normalizeText(text);
    if (!normalized || !Array.isArray(entities) || entities.length === 0) {
      return [];
    }

    const notifyService = this._normalizeText(options.notifyService);
    const segments = this._extractImperativeSegments(normalized);
    const lines = [];

    segments.forEach((segment) => {
      if (/^(send(?: a)? (?:notification|message)|notify)\b/i.test(segment)) {
        if (!notifyService) return;
        const quotedMessage =
          segment.match(/saying\s+"([^"]+)"/i)?.[1] ||
          segment.match(/saying\s+'([^']+)'/i)?.[1] ||
          "";
        let message =
          quotedMessage ||
          "Warning: {{ triggered_sensor_name }} is out of range";
        message = message.replace(
          /\[\s*whichever sensor triggered\s*\]/gi,
          "{{ triggered_sensor_name }}"
        );
        if (
          /\bactual sensor value\b|\bactual value\b/i.test(segment) &&
          !/triggered_sensor_value/.test(message)
        ) {
          message = `${message} (value: {{ triggered_sensor_value }}{{ triggered_sensor_unit }})`;
        }
        lines.push(...this._buildServiceActionLines(notifyService, [], { message }));
        return;
      }

      const isTurnOff = /^(turn off|switch off|disable)\b/i.test(segment);
      const isTurnOn = /^(turn on|switch on|enable|turn)\b/i.test(segment);
      if (!isTurnOff && !isTurnOn) return;

      const wantsLightAttributes = /\b(red|white|blue|green|yellow|orange|purple|pink|brightness|flash)\b/i.test(
        segment
      );
      const targets = this._resolveActionEntities(
        segment,
        entities,
        12,
        wantsLightAttributes ? ["light"] : null
      );
      if (targets.length === 0) return;

      if (isTurnOff) {
        const byDomain = new Map();
        targets.forEach((entity) => {
          const domain = String(entity.domain || "");
          if (!byDomain.has(domain)) {
            byDomain.set(domain, []);
          }
          byDomain.get(domain).push(entity.entity_id);
        });
        byDomain.forEach((entityIds, domain) => {
          lines.push(...this._buildServiceActionLines(`${domain}.turn_off`, entityIds));
        });
        return;
      }

      const color =
        segment.match(/\b(red|white|blue|green|yellow|orange|purple|pink)\b/i)?.[1] ||
        "";
      const brightnessMatch = segment.match(
        /\b(\d+)\s*(?:%|percent)\s+brightness\b/i
      );
      const brightnessPct = /\bfull brightness\b|\b100\s*(?:%|percent)\s+brightness\b/i.test(
        segment
      )
        ? 100
        : brightnessMatch
          ? Number(brightnessMatch[1])
          : "";
      const flashCount = /\bflash(?: it)? twice\b/i.test(segment)
        ? 2
        : /\bflash(?: it)? once\b/i.test(segment)
          ? 1
          : Number(segment.match(/\bflash(?: it)? (\d+) times?\b/i)?.[1] || "0");
      const data = {};
      if (color) {
        data.color_name = color.toLowerCase();
      }
      if (brightnessPct !== "") {
        data.brightness_pct = brightnessPct;
      }

      const lightTargets = targets.filter((entity) => entity.domain === "light");
      if (flashCount > 0 && lightTargets.length > 0) {
        const lightIds = lightTargets.map((entity) => entity.entity_id);
        lines.push("  - repeat:");
        lines.push(`      count: ${flashCount}`);
        lines.push("      sequence:");
        lines.push(
          ...this._buildServiceActionLines(
            "light.turn_on",
            lightIds,
            {
              ...data,
              flash: "short",
            },
            "        "
          )
        );
        lines.push('        - delay: "00:00:01"');
        lines.push(...this._buildServiceActionLines("light.turn_on", lightIds, data));
        return;
      }

      const byDomain = new Map();
      targets.forEach((entity) => {
        const domain = String(entity.domain || "");
        if (!byDomain.has(domain)) {
          byDomain.set(domain, []);
        }
        byDomain.get(domain).push(entity.entity_id);
      });
      byDomain.forEach((entityIds, domain) => {
        lines.push(
          ...this._buildServiceActionLines(
            `${domain}.turn_on`,
            entityIds,
            domain === "light" ? data : {}
          )
        );
      });
    });

    return lines;
  }

  _buildDeterministicComplexAutomationResult(prompt, context = {}) {
    const requestText = this._normalizeText(prompt);
    const entities = Array.isArray(context?.entities) ? context.entities : [];
    if (
      !requestText ||
      entities.length === 0 ||
      !this._isComplexAutomationPrompt(requestText)
    ) {
      return null;
    }

    const conditionStart = requestText.search(/\b(?:if|when)\b/i);
    if (conditionStart === -1) return null;

    const actionLead = requestText
      .slice(conditionStart)
      .match(
        /\b(turn off|switch off|turn on|switch on|disable|enable|send(?: a)? notification|send(?: a)? message|turn)\b/i
      );
    if (!actionLead) return null;

    const actionStart = conditionStart + (actionLead.index || 0);
    const conditionText = requestText
      .slice(conditionStart, actionStart)
      .replace(/^\s*(if|when)\s+/i, "")
      .replace(/[,\s]+$/g, "")
      .trim();
    if (!conditionText) return null;

    const semanticMatches = this._collectSemanticPromptMatches(requestText, entities);
    const groupClauseMappings = this._buildGroupClauseMappings(
      requestText,
      this._collectSiblingGroups(requestText, entities)
    );
    const thresholdClauses = this._splitConditionClauses(conditionText)
      .map((item) => ({
        ...item,
        spec: this._extractThresholdSpec(
          requestText,
          item.clause,
          entities,
          semanticMatches,
          groupClauseMappings
        ),
      }))
      .filter((item) => item.spec);
    if (thresholdClauses.length === 0) return null;

    const triggerSpecs = [];
    const guardSpecs = [];
    let guardPhaseStarted = false;
    thresholdClauses.forEach((item, index) => {
      if (index === 0) {
        triggerSpecs.push(item.spec);
        return;
      }
      if (!guardPhaseStarted && item.connectorBefore === "or") {
        triggerSpecs.push(item.spec);
        return;
      }
      guardPhaseStarted = true;
      guardSpecs.push(item.spec);
    });
    if (triggerSpecs.length === 0) return null;

    const timeWindowGuard = this._extractTimeWindowGuard(conditionText);

    const automationGuardIds = this._relevantDomainMatches(
      requestText,
      entities,
      "automation",
      2,
      8
    ).map((entity) => entity.entity_id);
    const explicitStateGuards = this._extractExplicitStateGuardSpecs(
      requestText,
      entities
    );
    const notifyService =
      this._relevantDomainMatches(requestText, entities, "notify", 1, 4)[0]
        ?.entity_id || "";

    const actionText = requestText.slice(actionStart).trim();
    const waitMatch = actionText.match(
      /\bwait\s+(\d+(?:\.\d+)?)\s*(seconds?|minutes?|hours?)\b/i
    );
    const preWaitText = waitMatch
      ? actionText.slice(0, waitMatch.index).trim()
      : actionText;
    const waitDuration = waitMatch
      ? this._parseDurationPhrase(`${waitMatch[1]} ${waitMatch[2]}`)
      : "";
    const postWaitText = waitMatch
      ? actionText.slice((waitMatch.index || 0) + waitMatch[0].length).trim()
      : "";

    const initialActionLines = this._buildDeterministicActionSequence(
      preWaitText,
      entities,
      { notifyService }
    );
    if (initialActionLines.length === 0) return null;

    let followUpSpec = null;
    let followUpActionLines = [];
    let fallbackActionLines = [];
    if (postWaitText) {
      const postWaitSentences = postWaitText
        .split(/(?<=[.!?])\s+/)
        .map((sentence) => this._normalizeText(sentence))
        .filter(Boolean);
      const trueBranchSentences = [];
      let fallbackSentence = "";
      let collectingTrueBranch = false;
      postWaitSentences.forEach((sentence) => {
        const normalizedSentence = this._normalizeConditionalSentenceLead(sentence);
        if (!normalizedSentence) {
          return;
        }
        if (/^don't run\b/i.test(normalizedSentence)) {
          return;
        }
        if (/^if\b/i.test(normalizedSentence) && /\binstead\b/i.test(normalizedSentence)) {
          fallbackSentence = normalizedSentence;
          collectingTrueBranch = false;
          return;
        }
        if (/^if\b/i.test(normalizedSentence)) {
          collectingTrueBranch = true;
          trueBranchSentences.push(normalizedSentence);
          return;
        }
        if (collectingTrueBranch) {
          trueBranchSentences.push(normalizedSentence);
        }
      });
      const trueBranchText = trueBranchSentences.join(" ").trim();
      const trueBranchMatch = trueBranchText.match(/\bif\s+([\s\S]+?)\s*,\s*([\s\S]+)/i);
      if (trueBranchMatch) {
        followUpSpec = this._extractThresholdSpec(
          requestText,
          trueBranchMatch[1],
          entities,
          semanticMatches,
          groupClauseMappings
        );
        followUpActionLines = this._buildDeterministicActionSequence(
          trueBranchMatch[2],
          entities,
          { notifyService }
        );
      }
      if (fallbackSentence) {
        const fallbackMatch = fallbackSentence.match(
          /\bif\s+([\s\S]+?)\s*,\s*instead\s+([\s\S]+)/i
        );
        fallbackActionLines = this._buildDeterministicActionSequence(
          fallbackMatch?.[2] || "",
          entities,
          { notifyService }
        );
      }
    }

    const lines = [
      `alias: ${triggerSpecs[0].label} Monitor`,
      "description: Monitors the resolved thresholds and runs the requested corrective actions.",
      "triggers:",
    ];

    triggerSpecs.forEach((spec) => {
      spec.entityIds.forEach((entityId) => {
        lines.push("  - trigger: numeric_state");
        lines.push(`    entity_id: ${entityId}`);
        lines.push(`    ${spec.comparator}: ${spec.value}`);
        lines.push(`    id: ${entityId}`);
      });
    });

    lines.push("conditions:");
    guardSpecs.forEach((spec) => {
      if (spec.entityIds.length === 1) {
        lines.push("  - condition: numeric_state");
        lines.push(`    entity_id: ${spec.entityIds[0]}`);
        lines.push(`    ${spec.comparator}: ${spec.value}`);
      } else if (spec.entityIds.length > 1) {
        lines.push("  - condition: template");
        lines.push("    value_template: >-");
        lines.push(
          `      {{ ${spec.entityIds
            .map(
              (entityId) =>
                `(states('${entityId}') | float(default=0)) ${spec.comparator === "below" ? "<" : ">"} ${spec.value}`
            )
            .join(" or ")} }}`
        );
      }
    });
    if (timeWindowGuard?.after && timeWindowGuard?.before) {
      if (timeWindowGuard.negate) {
        lines.push("  - condition: not");
        lines.push("    conditions:");
        lines.push("      - condition: time");
        lines.push(`        after: "${timeWindowGuard.after}"`);
        lines.push(`        before: "${timeWindowGuard.before}"`);
        if (
          Array.isArray(timeWindowGuard.weekdays) &&
          timeWindowGuard.weekdays.length > 0
        ) {
          lines.push("        weekday:");
          timeWindowGuard.weekdays.forEach((weekday) => {
            lines.push(`          - ${weekday}`);
          });
        }
      } else {
        lines.push("  - condition: time");
        lines.push(`    after: "${timeWindowGuard.after}"`);
        lines.push(`    before: "${timeWindowGuard.before}"`);
        if (
          Array.isArray(timeWindowGuard.weekdays) &&
          timeWindowGuard.weekdays.length > 0
        ) {
          lines.push("    weekday:");
          timeWindowGuard.weekdays.forEach((weekday) => {
            lines.push(`      - ${weekday}`);
          });
        }
      }
    }
    lines.push(...this._buildAutomationGuardConditionLines(automationGuardIds));
    lines.push(...this._buildExplicitStateGuardConditionLines(explicitStateGuards));

    lines.push("actions:");
    lines.push("  - variables:");
    lines.push('      triggered_sensor_id: "{{ trigger.entity_id }}"');
    lines.push(
      '      triggered_sensor_name: "{{ state_attr(trigger.entity_id, \'friendly_name\') or trigger.entity_id }}"'
    );
    lines.push('      triggered_sensor_value: "{{ states(trigger.entity_id) }}"');
    lines.push(
      '      triggered_sensor_unit: "{{ state_attr(trigger.entity_id, \'unit_of_measurement\') or \'\' }}"'
    );
    lines.push(...initialActionLines);

    if (waitDuration) {
      lines.push(`  - delay: "${waitDuration}"`);
    }

    if (followUpSpec && followUpActionLines.length > 0) {
      lines.push("  - choose:");
      lines.push("      - conditions:");
      if (followUpSpec.entityIds.length === 1) {
        lines.push("          - condition: numeric_state");
        lines.push(`            entity_id: ${followUpSpec.entityIds[0]}`);
        lines.push(`            ${followUpSpec.comparator}: ${followUpSpec.value}`);
      } else {
        lines.push("          - condition: template");
        lines.push("            value_template: >-");
        lines.push(
          `              {{ ${followUpSpec.entityIds
            .map(
              (entityId) =>
                `(states('${entityId}') | float(default=0)) ${followUpSpec.comparator === "below" ? "<" : ">"} ${followUpSpec.value}`
            )
            .join(" or ")} }}`
        );
      }
      lines.push("        sequence:");
      lines.push(...this._reindentYamlLines(followUpActionLines, "  ", "          "));
      if (fallbackActionLines.length > 0) {
        lines.push("    default:");
        lines.push(...this._reindentYamlLines(fallbackActionLines, "  ", "      "));
      }
    }

    lines.push("mode: single");

    return {
      yaml: lines.join("\n"),
      summary:
        "Generated the automation from the resolved thresholds, guards, delay, follow-up branch, and notification details in the full request.",
      needs_clarification: false,
      clarifying_questions: [],
    };
  }

  _clearClarificationState() {
    this._clarificationSummary = "";
    this._clarifyingQuestions = [];
    this._clarificationCandidates = [];
    this._clarificationAnswer = "";
    this._clarificationContext = null;
  }

  _buildEntityPool(rawEntities = []) {
    return [...(Array.isArray(rawEntities) ? rawEntities : []), ...this._notificationServiceEntries()]
      .filter(
        (entity, index, items) =>
          this._normalizeText(entity?.entity_id) &&
          items.findIndex(
            (candidate) =>
              this._normalizeText(candidate?.entity_id) ===
              this._normalizeText(entity?.entity_id)
          ) === index
      );
  }

  async _ensureEntityPool(allEntities = null) {
    const rawEntityPool =
      Array.isArray(allEntities) && allEntities.length > 0
        ? allEntities
        : this._lastEntityPool.length > 0
          ? this._lastEntityPool
          : (await this._requestEntities())?.entities || [];
    const entityPool = this._buildEntityPool(rawEntityPool);
    this._lastEntityPool = entityPool;
    return entityPool;
  }

  _setPreviewResult(result) {
    this._generationJobId = "";
    this._clearClarificationState();
    this._yaml = this._normalizeAutomationYamlText(result?.yaml);
    this._summary = result?.summary || "";
    this._parsedAutomation = this._parseYaml(this._yaml);
    this._clearGenerationPolling();
    this._state = STATES.PREVIEW;
  }

  _setLocalClarification(summary, question, candidates, context = null) {
    this._clearGenerationPolling();
    this._clarificationSummary = summary;
    this._clarifyingQuestions = question ? [question] : [];
    this._clarificationCandidates = Array.isArray(candidates) ? candidates : [];
    this._clarificationAnswer = "";
    this._clarificationContext = context;
    this._state = STATES.CLARIFY;
  }

  _resolveClarificationCandidate(answer, candidates = null) {
    const pool = Array.isArray(candidates)
      ? candidates
      : this._clarificationCandidates;
    if (!Array.isArray(pool) || pool.length === 0) return null;

    const matches = this._findEntitiesByPhrase(answer, pool, pool.length);
    if (matches.length === 1) {
      return matches[0];
    }

    const normalizedAnswer = this._normalizePhrase(answer);
    return (
      pool.find(
        (entity) => this._normalizePhrase(entity.entity_id) === normalizedAnswer
      ) || null
    );
  }

  _buildExplicitEntityAnswer(candidate) {
    const entityId = this._normalizeText(candidate?.entity_id);
    const name = this._normalizeText(candidate?.name);
    if (!entityId) return "";
    if (name) {
      return `Use entity_id ${entityId} (${name}) as the target device. Do not ask again which entity to use. Continue and return the automation JSON.`;
    }
    return `Use entity_id ${entityId} as the target device. Do not ask again which entity to use. Continue and return the automation JSON.`;
  }

  async _handleClarificationCandidate(candidate) {
    if (!candidate?.entity_id) return;
    this._clarificationAnswer = "";
    await this._submitChatPrompt(
      candidate.name || candidate.entity_id,
      this._buildExplicitEntityAnswer(candidate)
    );
  }

  _deriveClarificationCandidates(prompt, result, entities) {
    const questions = this._normalizeQuestions(
      result?.clarifying_questions || result?.questions
    );
    const rawCombinedText = [prompt || "", result?.summary || "", ...questions]
      .map((text) => this._normalizeText(text))
      .filter(Boolean)
      .join(" ");
    const combinedText = this._normalizePhrase(
      rawCombinedText
    );
    const entityPool = Array.isArray(entities) ? entities : [];

    if (
      /\b(tv|television)\b/.test(combinedText) &&
      /\b(entity|entity id|device|media player)\b/.test(combinedText)
    ) {
      return this._candidateEntitiesForTarget("tv", entityPool);
    }

    const explicitEntityIds = [...rawCombinedText.matchAll(/\b[a-z0-9_]+\.[a-z0-9_]+\b/gi)]
      .map((match) => this._normalizeText(match[0]).toLowerCase())
      .filter(Boolean);
    const explicitEntityMatches = entityPool.filter((entity) =>
      explicitEntityIds.includes(this._normalizeText(entity?.entity_id).toLowerCase())
    );
    if (explicitEntityMatches.length > 0) {
      return explicitEntityMatches;
    }

    const optionTexts = questions
      .flatMap((question) => {
        const matches = [];
        const parentheticalOptions = question.match(/\(([^)]+)\)/g) || [];
        parentheticalOptions.forEach((segment) => {
          matches.push(segment.replace(/^[()]+|[()]+$/g, ""));
        });
        const targetMatch = question.match(
          /\bwhich\s+(?:single\s+)?(?:entity|entity id|device|sensor|light|switch|automation|media player)\s+should\s+i\s+use\s+for\s+(.+?)\?/i
        );
        if (targetMatch?.[1]) {
          matches.push(targetMatch[1]);
        }
        return matches;
      })
      .flatMap((segment) =>
        segment.split(/\s*(?:,|\bor\b)\s*/i).map((item) => this._normalizeText(item))
      )
      .filter(Boolean);
    const optionMatches = optionTexts.flatMap((option) =>
      this._findEntitiesByPhrase(option, entityPool, 8)
    );
    const dedupedOptionMatches = optionMatches.filter(
      (entity, index, items) =>
        items.findIndex(
          (candidate) => candidate.entity_id === entity.entity_id
        ) === index
    );
    if (dedupedOptionMatches.length > 0) {
      return dedupedOptionMatches;
    }

    return [];
  }

  _siblingGroupLabel(group) {
    const firstName = this._normalizeText(group?.[0]?.name);
    return firstName.replace(
      /\s+(L\d+|\d+|Left|Right|Rear|Front|North|South|East|West|Upstairs|Downstairs)$/i,
      ""
    );
  }

  _buildGroupClauseMappings(prompt, groups) {
    const rawPrompt = this._normalizeText(prompt).toLowerCase();
    if (!rawPrompt || !Array.isArray(groups) || groups.length === 0) {
      return [];
    }

    const maskedPrompt = rawPrompt.replace(
      /\bbetween\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(?:and|to|-)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b/gi,
      (_match, start, end) => `between ${start} __range_and__ ${end}`
    );
    const clauses = maskedPrompt
      .split(
        /\s+\bor\b\s+|\s+\bthen\b\s+|[.;]\s*|,\s*(?=(?:if|turn|switch|send|notify|disable|enable|wait)\b)/i
      )
      .map((clause) => clause.replace(/__range_and__/gi, "and"))
      .map((clause) => clause.trim())
      .filter(Boolean);

    return groups
      .map((group) => {
        const label = this._siblingGroupLabel(group);
        const labelTokens = this._tokenizePrompt(label).filter(
          (token) => !DIRECT_GROUP_CLAUSE_IGNORE_TOKENS.has(token)
        );
        if (labelTokens.length === 0) return null;

        let bestClause = "";
        let bestScore = 0;
        let bestTokenScore = 0;
        clauses.forEach((clause) => {
          const clauseTokens = new Set(this._tokenizePrompt(clause));
          let tokenScore = 0;
          labelTokens.forEach((token) => {
            if (clauseTokens.has(token)) tokenScore += 1;
          });
          let score = tokenScore;
          if (
            /\b(above|below|greater|less|exceeds|drops|between|outside|inside|equals|not)\b/.test(
              clause
            )
          ) {
            score += 1;
          }
          if (score > bestScore) {
            bestScore = score;
            bestTokenScore = tokenScore;
            bestClause = clause;
          }
        });

        if (
          bestScore === 0 ||
          !bestClause ||
          bestTokenScore < Math.min(2, labelTokens.length)
        ) {
          return null;
        }
        return {
          label,
          clause: bestClause,
          entities: group.map((entity) => entity.entity_id),
        };
      })
      .filter(Boolean);
  }

  _extractPromptClauses(prompt) {
    return String(prompt || "")
      .split(/(?<=[.!?])\s+|\s+\bthen\b\s+|\s+\bor\b\s+|,\s*/i)
      .map((clause) => this._normalizeText(clause))
      .filter(Boolean);
  }

  _buildPromptClauseClarificationAnswer(prompt, result) {
    const questions = this._normalizeQuestions(
      result?.clarifying_questions || result?.questions
    );
    if (questions.length === 0) return "";

    const clauses = this._extractPromptClauses(prompt);
    if (clauses.length === 0) return "";

    const selectedClauses = [];
    questions.forEach((question) => {
      const questionTokens = this._tokenizePrompt(question).filter(
        (token) => !DIRECT_GROUP_CLAUSE_IGNORE_TOKENS.has(token)
      );
      if (/\b(combine|single condition|kept separate|keep (?:them )?separate)\b/i.test(question)) {
        clauses.forEach((clause) => {
          if (
            /\b(above|below|greater|less|exceeds|drops|between|not)\b/i.test(
              clause
            )
          ) {
            selectedClauses.push(clause);
          }
        });
      }
      if (/\b(all three|all phases|each phase|every phase|single phase)\b/i.test(question)) {
        clauses.forEach((clause) => {
          if (/\b(phase|voltage|current)\b/i.test(clause)) {
            selectedClauses.push(clause);
          }
        });
      }
      if (questionTokens.length === 0) return;

      let bestClause = "";
      let bestScore = 0;
      clauses.forEach((clause) => {
        const normalizedClause = this._normalizePhrase(clause);
        let score = 0;
        questionTokens.forEach((token) => {
          if (normalizedClause.includes(token)) score += 1;
        });
        if (
          /\b(per phase|single phase|during the .* wait|wait|threshold|drops below|exceeds|above)\b/i.test(
            question
          ) &&
          /\b(single phase|wait|drops below|exceeds|above)\b/i.test(clause)
        ) {
          score += 2;
        }
        if (score > bestScore) {
          bestScore = score;
          bestClause = clause;
        }
      });

      if (bestScore >= 2 && bestClause) {
        selectedClauses.push(bestClause);
      }
    });

    const uniqueClauses = selectedClauses.filter(
      (clause, index, items) => items.indexOf(clause) === index
    );
    if (uniqueClauses.length === 0) return "";

    return `The original prompt already specifies these details. Use these exact clauses: ${uniqueClauses
      .map((clause) => `"${clause}"`)
      .join(" ")}. Continue and return the automation JSON.`;
  }

  _buildAutoClarificationAnswer(prompt, result, entities) {
    const clarificationText = this._normalizePhrase(
      `${result?.summary || ""} ${(result?.clarifying_questions || []).join(" ")}`
    );
    const promptClauseAnswer = this._buildPromptClauseClarificationAnswer(
      prompt,
      result
    );
    const semanticClarificationHints = [];
    if (
      /\b(all three|all phases|each phase|every phase|single phase|use only one|one entity)\b/i.test(
        clarificationText
      )
    ) {
      semanticClarificationHints.push(
        "For clauses that refer to all, each, every, or any single phase/member, use the full resolved sibling family, not a single entity."
      );
    }
    if (
      /\b(combine .*condition|single condition|kept separate|keep (?:them )?separate|separate conditions)\b/i.test(
        clarificationText
      )
    ) {
      semanticClarificationHints.push(
        "Preserve the original boolean logic exactly and keep distinct threshold checks or guard clauses separate unless the original request explicitly merges them."
      );
    }
    const semanticClarificationAnswer =
      semanticClarificationHints.length > 0
        ? `${semanticClarificationHints.join(" ")} Continue and return the automation JSON.`
        : "";
    const automationMatches = this._relevantDomainMatches(
      prompt,
      entities,
      "automation",
      2,
      8
    );
    const notifyMatches = this._relevantDomainMatches(
      prompt,
      entities,
      "notify",
      1,
      4
    );
    const domainHints = [];
    if (/\b(automation|guard|active|inactive)\b/i.test(clarificationText)) {
      if (automationMatches.length > 0) {
        domainHints.push(
          `Use these matching automation guard entities together: ${automationMatches
            .slice(0, 4)
            .map((entity) => `${entity.name} -> ${entity.entity_id}`)
            .join("; ")}.`
        );
      }
    }
    if (/\b(notify|notification|iphone|phone|mobile|message)\b/i.test(clarificationText)) {
      if (notifyMatches.length > 0) {
        domainHints.push(
          `Use the matching notification target: ${notifyMatches
            .slice(0, 2)
            .map((entity) => `${entity.name} -> ${entity.entity_id}`)
            .join("; ")}.`
        );
      }
    }
    const domainAnswer =
      domainHints.length > 0
        ? `${domainHints.join(" ")} Continue and return the automation JSON.`
        : "";
    if (
      promptClauseAnswer &&
      /\b(threshold|what should|how should|during the .* wait|per phase|total)\b/i.test(
        clarificationText
      )
    ) {
      return [semanticClarificationAnswer, promptClauseAnswer]
        .filter(Boolean)
        .join(" ");
    }

    const siblingGroups = this._collectSiblingGroups(prompt, entities);
    if (siblingGroups.length === 0) {
      const plainAnswer = [
        semanticClarificationAnswer,
        domainAnswer,
        promptClauseAnswer,
      ]
        .filter(Boolean)
        .join(" ");
      if (plainAnswer) {
        return plainAnswer;
      }
      return "";
    }
    const groupClauseMappings = this._buildGroupClauseMappings(prompt, siblingGroups);
    const wantsSensor = /\bsensor\b/.test(clarificationText);
    const explicitlyMatchedGroups = siblingGroups.filter((group) => {
      const label = this._normalizePhrase(this._siblingGroupLabel(group));
      return group.some((entity) => {
        const entityId = this._normalizePhrase(entity.entity_id);
        const entityName = this._normalizePhrase(entity.name);
        return (
          (entityId && clarificationText.includes(entityId)) ||
          (entityName && clarificationText.includes(entityName)) ||
          (label && clarificationText.includes(label))
        );
      });
    });
    const matchedGroups =
      explicitlyMatchedGroups.length > 0
        ? explicitlyMatchedGroups
        : wantsSensor
          ? siblingGroups.filter((group) =>
              group.every((entity) => entity.domain === "sensor")
            )
          : [];

    if (matchedGroups.length === 0) {
      const unresolvedGroupAnswer = [
        semanticClarificationAnswer,
        domainAnswer,
        promptClauseAnswer,
      ]
        .filter(Boolean)
        .join(" ");
      return unresolvedGroupAnswer || "";
    }

    const obviousSingles = this._findObviousNamedEntities(prompt, entities, 20).filter(
      (entity) =>
        !matchedGroups.some((group) =>
          group.some((candidate) => candidate.entity_id === entity.entity_id)
        )
    );
    const includeBroaderHints = explicitlyMatchedGroups.length === 0;
    const filteredAutomationMatches = automationMatches.filter(
      (entity) =>
        !obviousSingles.some((candidate) => candidate.entity_id === entity.entity_id)
    );

    const groupHints = matchedGroups
      .map(
        (group) =>
          `${this._siblingGroupLabel(group)} -> ${group
            .map((entity) => entity.entity_id)
            .join(", ")}`
      )
      .join("; ");
    const clauseHints = groupClauseMappings
      .filter((mapping) =>
        matchedGroups.some(
          (group) => this._siblingGroupLabel(group) === mapping.label
        )
      )
      .map(
        (mapping) =>
          `${mapping.label} -> ${mapping.entities.join(", ")} for "${mapping.clause}"`
      )
      .join("; ");
    const singleHints =
      includeBroaderHints && obviousSingles.length > 0
        ? ` Use these exact single-entity matches as already resolved too: ${obviousSingles
            .map((entity) => `${entity.name} -> ${entity.entity_id}`)
            .join("; ")}.`
        : "";
    const automationHints =
      includeBroaderHints && filteredAutomationMatches.length > 0
        ? ` Use all matching automation guard entities together too: ${filteredAutomationMatches
            .map((entity) => `${entity.name} -> ${entity.entity_id}`)
            .join("; ")}.`
        : "";
    const notificationHints =
      includeBroaderHints && notifyMatches.length > 0
        ? ` Use the matching notification target too: ${notifyMatches
            .slice(0, 2)
            .map((entity) => `${entity.name} -> ${entity.entity_id}`)
            .join("; ")}.`
        : "";

    const clauseMappingHints = clauseHints
      ? ` Apply these grouped families to their matching clauses too: ${clauseHints}.`
      : "";

    const groupAnswer = `Use all matching entities in these sibling sets together, not a single entity: ${groupHints}.${clauseMappingHints}${singleHints}${automationHints}${notificationHints} Do not ask which single entity to use. Continue and return the automation JSON.`;
    const combinedGroupAnswer = [
      semanticClarificationAnswer,
      groupAnswer,
      domainAnswer,
    ]
      .filter(Boolean)
      .join(" ");
    if (promptClauseAnswer) {
      return `${combinedGroupAnswer} ${promptClauseAnswer}`;
    }
    return combinedGroupAnswer;
  }

  _buildAuthoritativeClarificationResolution(prompt, entities) {
    const siblingGroups = this._collectSiblingGroups(prompt, entities);
    const groupClauseMappings = this._buildGroupClauseMappings(prompt, siblingGroups);
    const automationMatches = this._relevantDomainMatches(
      prompt,
      entities,
      "automation",
      2,
      8
    );
    const notifyMatches = this._relevantDomainMatches(
      prompt,
      entities,
      "notify",
      1,
      4
    );
    const lines = [];

    if (groupClauseMappings.length > 0) {
      lines.push(
        `Authoritative grouped mappings: ${groupClauseMappings
          .map(
            (mapping) =>
              `${mapping.label} = ${mapping.entities.join(", ")} for "${mapping.clause}"`
          )
          .join("; ")}.`
      );
    } else if (siblingGroups.length > 0) {
      lines.push(
        `Authoritative sibling sets: ${siblingGroups
          .map(
            (group) =>
              `${this._siblingGroupLabel(group)} = ${group
                .map((entity) => entity.entity_id)
                .join(", ")}`
          )
          .join("; ")}.`
      );
    }
    if (notifyMatches.length > 0) {
      lines.push(
        `Authoritative notification target: ${notifyMatches
          .slice(0, 2)
          .map((entity) => entity.entity_id)
          .join(", ")}.`
      );
    }
    if (automationMatches.length > 0) {
      lines.push(
        `Authoritative automation guards: ${automationMatches
          .slice(0, 4)
          .map((entity) => entity.entity_id)
          .join(", ")}.`
      );
    }
    if (lines.length === 0) return "";
    return `${lines.join(" ")} Use these exact mappings without asking again. Return the complete automation JSON now.`;
  }

  _buildResolvedPromptForRepeat(prompt, result, entities) {
    const authoritativeResolution = this._buildAuthoritativeClarificationResolution(
      prompt,
      entities
    );
    const promptClauseAnswer = this._buildPromptClauseClarificationAnswer(
      prompt,
      result
    );
    return [
      prompt,
      authoritativeResolution,
      promptClauseAnswer,
      "Use the original request plus these resolved mappings and clarifications. Do not ask again which sensor or notification target to use. Return the complete automation JSON now.",
    ]
      .filter(Boolean)
      .join("\n\n");
  }

  _buildResolvedFinalPrompt(prompt, entities) {
    const siblingGroups = this._collectSiblingGroups(prompt, entities);
    const groupClauseMappings = this._buildGroupClauseMappings(prompt, siblingGroups);
    const groupedEntityIds = new Set(
      siblingGroups.flatMap((group) => group.map((entity) => entity.entity_id))
    );
    const automationMatches = this._relevantDomainMatches(
      prompt,
      entities,
      "automation",
      2,
      8
    );
    const notifyMatches = this._relevantDomainMatches(
      prompt,
      entities,
      "notify",
      1,
      4
    );
    const automationEntityIds = new Set(
      automationMatches.map((entity) => entity.entity_id)
    );
    const notifyEntityIds = new Set(
      notifyMatches.map((entity) => entity.entity_id)
    );
    const exactMatches = this._findObviousNamedEntities(prompt, entities, 20).filter(
      (entity) =>
        !groupedEntityIds.has(entity.entity_id) &&
        !automationEntityIds.has(entity.entity_id) &&
        (entity.domain !== "notify" || notifyEntityIds.has(entity.entity_id))
    );
    const lines = ["Resolved grouped entity families:"];

    if (groupClauseMappings.length > 0) {
      groupClauseMappings.forEach((mapping) => {
        lines.push(
          `- ${mapping.label}: ${mapping.entities.join(", ")}`,
          `  Clause: "${mapping.clause}"`,
        );
      });
    } else if (siblingGroups.length > 0) {
      siblingGroups.forEach((group) => {
        lines.push(
          `- ${this._siblingGroupLabel(group)}: ${group
            .map((entity) => entity.entity_id)
            .join(", ")}`
        );
      });
    } else {
      lines.push("- None");
    }

    lines.push("", "Resolved exact entity matches:");
    if (exactMatches.length > 0) {
      exactMatches.forEach((entity) => {
        lines.push(`- ${entity.name}: ${entity.entity_id}`);
      });
    } else {
      lines.push("- None");
    }

    lines.push("", "Resolved automation guard entities:");
    if (automationMatches.length > 0) {
      automationMatches.slice(0, 4).forEach((entity) => {
        lines.push(`- ${entity.entity_id}`);
      });
    } else {
      lines.push("- None");
    }

    lines.push("", "Resolved notification target:");
    if (notifyMatches.length > 0) {
      lines.push(`- ${notifyMatches[0].entity_id}`);
    } else {
      lines.push("- None");
    }

    lines.push(
      "",
      "Required interpretation:",
      "- Treat an unlabeled base entity plus numbered variants as one sibling family where the unlabeled base entity is the first/default member.",
      "- Use every entity in each resolved sibling family for clauses that refer to all, both, three, each, or any single phase/member of that family.",
      "- Do not collapse a resolved sibling family down to a partial subset such as only one numbered variant. Use the full resolved family exactly as listed.",
      "- Use the resolved notification target and automation guard entities directly.",
      "- If multiple automation guard entities are listed, treat any active one as a blocking guard and do not run the actions.",
      "- Preserve the entire original request, including thresholds, time-window exclusions, delays, nested branches, notifications, and whichever-triggered sensor details.",
      "- Do not ask for clarification. Return the complete automation JSON now.",
    );

    return lines.join("\n");
  }

  _clarificationKey(message) {
    const text = this._normalizeText(message);
    if (!text) return "";
    const lines = text
      .split(/\r?\n+/)
      .map((line) => this._normalizeText(line))
      .filter(Boolean);
    const questionLines = lines.filter(
      (line) => line.includes("?") || this._looksLikeQuestion(line)
    );
    return this._normalizeText(
      (questionLines.length > 0 ? questionLines : lines).join(" ")
    );
  }

  _shouldRebuildResolvedPrompt(messages, assistantMessage, autoClarification) {
    const normalizedClarification = this._clarificationKey(assistantMessage);
    const normalizedAnswer = this._normalizeText(autoClarification);
    if (!normalizedClarification || !normalizedAnswer) {
      return false;
    }

    const history = Array.isArray(messages) ? messages : [];
    const clarificationAlreadyAsked = history.some(
      (message) =>
        message?.role === "assistant" &&
        this._clarificationKey(message.content) === normalizedClarification
    );
    if (!clarificationAlreadyAsked) {
      return false;
    }

    return history.some(
      (message) =>
        message?.role === "user" &&
        this._normalizeText(message.content) === normalizedAnswer
    );
  }

  _tryDeterministicGeneration(prompt, entities) {
    const intent = this._parseSimpleScheduledToggleIntent(prompt);
    if (!intent) return null;

    const candidates = this._candidateEntitiesForTarget(intent.targetLabel, entities);
    if (candidates.length === 1) {
      return this._buildDeterministicResult(intent, candidates[0]);
    }

    if (candidates.length > 1) {
      return {
        needs_clarification: true,
        summary: `I found multiple devices that could match "${intent.targetLabel}".`,
        clarifying_questions: [
          `Which ${intent.targetLabel} should I use for this automation?`,
        ],
        candidates,
        clarification_context: {
          type: "select_entity",
          intent,
        },
      };
    }

    return null;
  }

  _tokenizePrompt(prompt) {
    return (String(prompt || "").toLowerCase().match(DIRECT_TOKEN_RE) || []).filter(
      (token) =>
        (token.length >= 3 || IMPORTANT_SHORT_TOKENS.has(token)) &&
        !DIRECT_IGNORE_TOKENS.has(token)
    );
  }

  _isComplexAutomationPrompt(prompt) {
    return DIRECT_COMPLEX_PROMPT_RE.test(String(prompt || ""));
  }

  _shouldUsePlanner(prompt) {
    const text = this._normalizeText(prompt);
    if (!text || !this._isComplexAutomationPrompt(text)) {
      return false;
    }

    if (text.length > 3500) {
      return false;
    }

    if (this._extractPromptClauses(text).length > 18) {
      return false;
    }

    return true;
  }

  _shouldPreferResolvedFinalPass(prompt) {
    const text = this._normalizeText(prompt);
    if (!text || !this._isComplexAutomationPrompt(text)) {
      return false;
    }

    const clauseCount = this._extractPromptClauses(text).length;
    if (text.length > 650 || clauseCount > 6) {
      return true;
    }

    const hasGroupIntent = this._hasGroupIntent(text);
    const hasFollowUpBranching =
      /\b(wait|delay|then|otherwise|instead|still|after)\b/i.test(text);
    const hasNotificationTarget =
      /\b(notification|notify|iphone|phone|tablet|mobile)\b/i.test(text);
    const hasSharedBooleanLogic =
      /\b(and|or)\b/i.test(text) &&
      /\b(if|unless|while|between|weekday|weekdays)\b/i.test(text);

    return (
      hasGroupIntent &&
      hasSharedBooleanLogic &&
      (hasFollowUpBranching ||
        hasNotificationTarget ||
        this._hasTimeWindowGuard(text))
    );
  }

  _isLikelyEntityOnlyPlanItem(item) {
    const text = this._normalizeText(item);
    if (!text) return false;
    return /^[a-z0-9_]+\.[a-z0-9_]+(?:\s+threshold\s+.+)?(?:\s+state\s+.+)?$/i.test(
      text
    );
  }

  _isUsefulPlanningResult(plan, prompt = "") {
    if (!plan || typeof plan !== "object" || Array.isArray(plan)) {
      return false;
    }

    const promptText = this._normalizeText(prompt).toLowerCase();
    const resolvedRequest = this._normalizeText(plan?.resolved_request);
    const resolvedRequirements = this._normalizePlanItems(
      plan?.resolved_requirements
    );
    const resolvedEntities = this._normalizePlanItems(plan?.resolved_entities);
    const signalText = [
      resolvedRequest,
      ...resolvedRequirements,
      ...resolvedEntities,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();

    if (!signalText) {
      return false;
    }

    const nonEntityRequirements = resolvedRequirements.filter(
      (item) => !this._isLikelyEntityOnlyPlanItem(item)
    );
    const nonEntityMappings = resolvedEntities.filter(
      (item) => !this._isLikelyEntityOnlyPlanItem(item)
    );
    const requestTokens = this._tokenizePrompt(resolvedRequest);
    const promptTokens = new Set(this._tokenizePrompt(promptText));
    const overlappingTokens = requestTokens.filter((token, index, items) => {
      if (items.indexOf(token) !== index) return false;
      return promptTokens.has(token);
    });
    const preservedMarkers = [
      "wait",
      "delay",
      "otherwise",
      "instead",
      "notify",
      "notification",
      "iphone",
      "between",
      "weekday",
      "whichever",
      "triggered",
      "power",
      "voltage",
      "current",
    ].filter(
      (marker) => promptText.includes(marker) && signalText.includes(marker)
    );
    const isTruncatedRequest =
      promptText.length > 0 &&
      resolvedRequest.length < Math.min(220, promptText.length * 0.55);

    return (
      nonEntityRequirements.length > 0 ||
      nonEntityMappings.length > 0 ||
      (preservedMarkers.length >= 3 && !isTruncatedRequest) ||
      (requestTokens.length >= 8 &&
        overlappingTokens.length >= 6 &&
        preservedMarkers.length >= 2 &&
        !isTruncatedRequest)
    );
  }

  _shouldPreferYamlOnlyResolvedPass(prompt, plan = null) {
    const text = this._normalizeText(prompt);
    if (!text || !this._shouldPreferResolvedFinalPass(text)) {
      return false;
    }

    const clauseCount = this._extractPromptClauses(text).length;
    const hasDelayedBranching = /\b(wait|delay|after|still|otherwise|instead)\b/i.test(
      text
    );
    const hasTriggeredNotification =
      /\b(notification|notify|iphone|phone|tablet|mobile|whichever|triggered)\b/i.test(
        text
      );
    const hasGuardWindow = this._hasTimeWindowGuard(text);
    const hasNestedBooleanLogic = /\bor\b/i.test(text) && /\band\b/i.test(text);

    return (
      !this._isUsefulPlanningResult(plan, text) ||
      clauseCount > 6 ||
      (hasDelayedBranching &&
        (hasTriggeredNotification || hasGuardWindow || hasNestedBooleanLogic))
    );
  }

  _shouldUseBackendGeneration(prompt) {
    return true;
  }

  _hasGroupIntent(prompt) {
    return DIRECT_GROUP_MARKER_RE.test(String(prompt || ""));
  }

  _variantEntityStem(entityId) {
    const normalized = this._normalizeText(entityId).toLowerCase();
    if (!normalized.includes(".")) return normalized;
    return normalized.replace(DIRECT_VARIANT_SUFFIX_RE, "");
  }

  _expandEntityFamilies(prompt, seedEntities, entities) {
    if (!this._hasGroupIntent(prompt)) return [];
    if (!Array.isArray(seedEntities) || seedEntities.length === 0) return [];
    if (!Array.isArray(entities) || entities.length === 0) return [];

    const groups = new Map();
    entities.forEach((entity) => {
      const entityId = this._normalizeText(entity.entity_id).toLowerCase();
      if (!entityId) return;
      const stem = this._variantEntityStem(entityId);
      if (!groups.has(stem)) {
        groups.set(stem, []);
      }
      groups.get(stem).push(entity);
    });

    const expanded = [];
    const seen = new Set();
    seedEntities.forEach((entity) => {
      const entityId = this._normalizeText(entity.entity_id).toLowerCase();
      if (!entityId) return;
      const siblings = groups.get(this._variantEntityStem(entityId)) || [];
      if (siblings.length < 2) return;
      siblings.forEach((candidate) => {
        if (seen.has(candidate.entity_id)) return;
        seen.add(candidate.entity_id);
        expanded.push(candidate);
      });
    });

    return expanded;
  }

  _collectSiblingGroups(prompt, entities) {
    if (!this._hasGroupIntent(prompt)) return [];
    if (!Array.isArray(entities) || entities.length === 0) return [];

    const groups = new Map();
    entities.forEach((entity) => {
      const entityId = this._normalizeText(entity.entity_id).toLowerCase();
      if (!entityId) return;
      const stem = this._variantEntityStem(entityId);
      if (!groups.has(stem)) {
        groups.set(stem, []);
      }
      groups.get(stem).push(entity);
    });

    return [...groups.values()].filter((group) => group.length >= 2);
  }

  _extractDomainPhrases(prompt, domain) {
    const normalizedPrompt = this._normalizePhrase(prompt);
    if (!normalizedPrompt) return [];
    const cleanDomainPhrase = (phrase, targetDomain) => {
      const ignoredByDomain = {
        automation: new Set([
          "active",
          "already",
          "any",
          "automation",
          "currently",
          "disabled",
          "enabled",
          "if",
          "not",
          "off",
          "on",
          "run",
          "running",
          "that",
          "the",
          "these",
          "this",
          "those",
          "unless",
          "when",
          "while",
        ]),
        notify: new Set([
          "alert",
          "message",
          "notification",
          "notify",
          "saying",
          "send",
          "service",
          "target",
          "through",
          "to",
          "via",
          "with",
        ]),
      };
      return this._tokenizePrompt(phrase)
        .filter((token) => !ignoredByDomain[targetDomain]?.has(token))
        .join(" ");
    };

    if (domain === "automation") {
      const phrases = [];
      const automationPattern =
        /\b(?:the\s+)?([a-z0-9 ]{3,80}?)\s+automation\b(?:\s+is\b|\s+are\b|\s+was\b|\s+were\b|\s+already\b|\s+currently\b|[.,]|$)/gi;
      for (const match of normalizedPrompt.matchAll(automationPattern)) {
        const phrase = cleanDomainPhrase(match[1], domain);
        if (!phrase) continue;
        phrases.push(phrase);
      }
      return [...new Set(phrases.filter(Boolean))];
    }

    if (domain === "notify") {
      const phrases = [];
      const patterns = [
        /\b(?:send\s+)?(?:a\s+)?(?:notification|notify|message|alert)\s+(?:to\s+)?(?:my\s+)?([a-z0-9 ]{2,60}?)(?:\s+saying\b|\s+that\b|[.,]|$)/gi,
        /\b(?:to|for)\s+my\s+([a-z0-9 ]{2,60}?)(?:\s+saying\b|\s+that\b|[.,]|$)/gi,
      ];
      patterns.forEach((pattern) => {
        for (const match of normalizedPrompt.matchAll(pattern)) {
          const phrase = cleanDomainPhrase(match[1], domain);
          if (!phrase) continue;
          phrases.push(phrase);
        }
      });
      return [...new Set(phrases.filter(Boolean))];
    }

    return [];
  }

  _relevantDomainMatches(prompt, entities, domain, minMatchedTokens = 2, maxMatches = 8) {
    const domainPhrases = this._extractDomainPhrases(prompt, domain);
    if (domainPhrases.length > 0) {
      const phraseMatches = [];
      domainPhrases.forEach((phrase) => {
        const normalizedPhrase = this._normalizePhrase(phrase);
        const phraseTokens = this._tokenizePrompt(phrase);
        if (!normalizedPhrase || phraseTokens.length === 0) return;

        entities.forEach((entity, index) => {
          if (String(entity.domain || "") !== domain) return;
          const haystack = this._normalizePhrase(
            `${entity.entity_id || ""} ${entity.name || ""}`
          );
          const haystackTokens = new Set(this._tokenizePrompt(haystack));
          const matchedTokens = phraseTokens.filter((token) =>
            haystackTokens.has(token)
          );
          if (matchedTokens.length === 0) return;

          let score = matchedTokens.length * 4;
          if (haystack.includes(normalizedPhrase)) score += 8;
          if (
            phraseTokens.length === 1 &&
            haystackTokens.has(phraseTokens[0])
          ) {
            score += 4;
          }

          phraseMatches.push({ score, index, entity });
        });
      });

      phraseMatches.sort((left, right) => {
        if (right.score !== left.score) return right.score - left.score;
        return left.index - right.index;
      });

      const uniquePhraseMatches = phraseMatches
        .map((item) => item.entity)
        .filter(
          (entity, index, items) =>
            items.findIndex(
              (candidate) => candidate.entity_id === entity.entity_id
            ) === index
        );
      if (uniquePhraseMatches.length > 0) {
        return uniquePhraseMatches.slice(0, maxMatches);
      }
    }

    const promptTokens = new Set(this._tokenizePrompt(prompt));
    if (promptTokens.size === 0 || !Array.isArray(entities)) return [];

    const ignoredTokens =
      domain === "automation" ? DIRECT_AUTOMATION_MATCH_IGNORE_TOKENS : new Set();
    const scored = [];
    entities.forEach((entity, index) => {
      if (String(entity.domain || "") !== domain) return;
      const haystackTokens = new Set(
        this._tokenizePrompt(`${entity.entity_id || ""} ${entity.name || ""}`)
      );
      let matched = 0;
      for (const token of haystackTokens) {
        if (ignoredTokens.has(token)) continue;
        if (promptTokens.has(token)) matched += 1;
      }
      if (matched < minMatchedTokens) return;
      scored.push({ matched, index, entity });
    });

    scored.sort((left, right) => {
      if (right.matched !== left.matched) return right.matched - left.matched;
      return left.index - right.index;
    });

    return scored
      .slice(0, maxMatches)
      .map((item) => item.entity)
      .filter(
        (entity, index, items) =>
          items.findIndex(
            (candidate) => candidate.entity_id === entity.entity_id
          ) === index
      );
  }

  _selectRelevantEntities(prompt, entities, maxEntities, fallbackEntities = 6) {
    if (
      !Array.isArray(entities) ||
      maxEntities <= 0 ||
      entities.length <= maxEntities
    ) {
      return Array.isArray(entities) ? entities : [];
    }

    const tokens = this._tokenizePrompt(prompt);
    if (tokens.length === 0) {
      return entities.slice(0, maxEntities);
    }

    const scored = [];
    const semanticEntities = this._semanticEntityMatches(prompt, entities, maxEntities);
    const notifyMatches = /\b(notify|notification|iphone|phone|mobile)\b/i.test(
      this._normalizePhrase(prompt)
    )
      ? this._relevantDomainMatches(prompt, entities, "notify", 1, 4)
      : [];
    const automationMatches =
      this._normalizePhrase(prompt).includes("automation")
        ? this._relevantDomainMatches(prompt, entities, "automation", 2, 8)
        : [];
    entities.forEach((entity, index) => {
      const haystack = [
        entity.entity_id,
        entity.name,
        entity.domain,
        entity.device_class,
        entity.state,
      ]
        .map((value) => String(value || "").replaceAll("_", " "))
        .join(" ")
        .toLowerCase();

      let score = 0;
      for (const token of tokens) {
        if (!haystack.includes(token)) continue;
        score += 2;
        if (String(entity.entity_id || "").toLowerCase().includes(token)) score += 3;
        if (String(entity.name || "").toLowerCase().includes(token)) score += 4;
      }

      if (score > 0) {
        scored.push({ score, index, entity });
      }
    });

    scored.sort((left, right) => {
      if (right.score !== left.score) return right.score - left.score;
      return left.index - right.index;
    });

    const selected = [];
    const seen = new Set();
    const relevantLimit = Math.min(maxEntities, 18);
    const minimumRelevant = Math.min(maxEntities, 12);

    for (const entity of [...notifyMatches, ...automationMatches, ...semanticEntities]) {
      const entityId = String(entity.entity_id || "");
      if (!entityId || seen.has(entityId)) continue;
      selected.push(entity);
      seen.add(entityId);
      if (selected.length >= relevantLimit) {
        return selected.slice(0, relevantLimit);
      }
    }

    const primaryCapacity = Math.max(0, relevantLimit - selected.length);
    for (const item of scored.slice(0, primaryCapacity)) {
      const entityId = String(item.entity.entity_id || "");
      if (!entityId || seen.has(entityId)) continue;
      selected.push(item.entity);
      seen.add(entityId);
    }

    if (selected.length >= minimumRelevant) {
      return selected.slice(0, relevantLimit);
    }

    const fallbackTarget = Math.min(
      maxEntities,
      Math.max(selected.length, minimumRelevant)
    );

    for (const entity of entities) {
      if (selected.length >= fallbackTarget) break;
      const entityId = String(entity.entity_id || "");
      if (!entityId || seen.has(entityId)) continue;
      selected.push(entity);
      seen.add(entityId);
    }

    return selected.slice(0, fallbackTarget);
  }

  _buildDirectMessages(prompt, entities, plan = null) {
    const explicitEntities = this._findExplicitEntities(prompt, entities);
    const obviousEntities = this._findObviousNamedEntities(prompt, entities);
    const semanticMatches = this._collectSemanticPromptMatches(prompt, entities);
    const siblingGroups = this._collectSiblingGroups(prompt, entities);
    const groupClauseMappings = this._buildGroupClauseMappings(
      prompt,
      siblingGroups
    );
    const automationMatches = this._relevantDomainMatches(
      prompt,
      entities,
      "automation",
      2,
      8
    );
    const notifyMatches = this._relevantDomainMatches(
      prompt,
      entities,
      "notify",
      1,
      4
    );
    const extraGuidance = [];

    if (explicitEntities.length > 0) {
      extraGuidance.push(
        `Explicit entity_ids: ${explicitEntities
          .map((entity) => entity.entity_id)
          .join(", ")}.`
      );
    }

    if (obviousEntities.length > 0) {
      extraGuidance.push(
        `Resolved name matches: ${obviousEntities
          .slice(0, 6)
          .map((entity) => `${entity.name} -> ${entity.entity_id}`)
          .join("; ")}.`
      );
    }

    if (semanticMatches.length > 0) {
      extraGuidance.push(
        `Resolved entity families: ${semanticMatches
          .slice(0, 4)
          .map(
            (match) =>
              `${match.label} -> ${match.entities
                .slice(0, 4)
                .map((entity) => entity.entity_id)
                .join(", ")}`
          )
          .join("; ")}.`
      );
    }

    if (groupClauseMappings.length > 0) {
      extraGuidance.push(
        `Resolved clause families: ${groupClauseMappings
          .map(
            (mapping) =>
              `${mapping.label} -> ${mapping.entities.join(", ")} for "${mapping.clause}"`
          )
          .join("; ")}.`
      );
    } else if (siblingGroups.length > 0) {
      extraGuidance.push(
        `Grouped sibling sets: ${siblingGroups
          .map((group) => group.map((entity) => entity.entity_id).join(", "))
          .join(" | ")}.`
      );
    }

    if (automationMatches.length > 0) {
      extraGuidance.push(
        `Resolved automation guards: ${automationMatches
          .slice(0, 4)
          .map((entity) => entity.entity_id)
          .join(", ")}.`
      );
    }
    if (notifyMatches.length > 0) {
      extraGuidance.push(
        `Resolved notification targets: ${notifyMatches
          .slice(0, 3)
          .map((entity) => entity.entity_id)
          .join(", ")}.`
      );
    }

    if (plan?.resolved_request) {
      extraGuidance.push(
        `Implementation brief: ${plan.resolved_request}`
      );
    }

    if (Array.isArray(plan?.resolved_entities) && plan.resolved_entities.length > 0) {
      extraGuidance.push(
        `Implementation entity mappings: ${plan.resolved_entities.join("; ")}.`
      );
    }

    if (
      Array.isArray(plan?.resolved_requirements) &&
      plan.resolved_requirements.length > 0
    ) {
      extraGuidance.push(
        `Implementation steps: ${plan.resolved_requirements.join(
          " | "
        )}.`
      );
    }

    if (/\bsunrise\b|\bsunset\b/i.test(String(prompt || ""))) {
      extraGuidance.push(
        "You may use Home Assistant's built-in sun trigger for sunrise or sunset without a listed entity_id."
      );
    }

    if (this._hasClearSchedule(prompt)) {
      extraGuidance.push(
        "The user's schedule is already specific enough for a time-based trigger. Do not ask follow-up questions about the time or recurrence unless the request is actually contradictory."
      );
    }

    if (this._hasTimeWindowGuard(prompt)) {
      extraGuidance.push(
        "Treat time-window exclusions like 'not between 9am and 5pm on a weekday' as conditions or guards, not as the trigger schedule."
      );
    }

    if (/\b(notification|notify|iphone)\b/i.test(String(prompt || ""))) {
      extraGuidance.push(
        "If the provided list includes notify.* entries, use those exact action service names for notifications."
      );
    }

    if (
      /\b(if|then|otherwise|instead|wait|still|unless)\b/i.test(
        String(prompt || "")
      )
    ) {
      extraGuidance.push(
        "This is a multi-step automation. Use variables, choose blocks, delays, template conditions, and template values as needed, and return one complete automation."
      );
    }

    if (/\bwhichever sensor triggered\b|\bactual sensor value\b/i.test(String(prompt || ""))) {
      extraGuidance.push(
        "Capture the triggering sensor and its live value in variables so the notification message includes the real out-of-range sensor and reading."
      );
    }

    return [
      { role: "system", content: DIRECT_SYSTEM_PROMPT },
      {
        role: "user",
        content:
          `Available entities:\n${this._entitySummary(entities)}\n\n` +
          (extraGuidance.length > 0
            ? `${extraGuidance.join("\n")}\n\n`
            : "") +
          `Create an automation for:\n${prompt}`,
      },
    ];
  }

  _normalizePlanItems(value) {
    if (!Array.isArray(value)) return [];
    return value
      .map((item) => {
        if (typeof item === "string") {
          return this._normalizeText(item);
        }
        if (!item || typeof item !== "object" || Array.isArray(item)) {
          return "";
        }
        const entityId = this._normalizeText(item.entity_id || item.entityId);
        const threshold = this._normalizeText(item.threshold);
        const state = this._normalizeText(item.state);
        const details = [entityId];
        if (threshold) {
          details.push(`threshold ${threshold}`);
        }
        if (state && state !== "unknown") {
          details.push(`state ${state}`);
        }
        return details.filter(Boolean).join(" ");
      })
      .filter(Boolean);
  }

  _buildResolvedFinalMessages(prompt, resolvedPrompt, entities, plan = null) {
    const combinedEntities = Array.isArray(entities) ? entities : [];
    const planLines = [];
    if (plan?.resolved_request) {
      planLines.push(
        `Implementation brief: ${plan.resolved_request}`
      );
    }
    if (Array.isArray(plan?.resolved_entities) && plan.resolved_entities.length > 0) {
      planLines.push(
        `Implementation entity mappings: ${plan.resolved_entities.join("; ")}.`
      );
    }
    if (
      Array.isArray(plan?.resolved_requirements) &&
      plan.resolved_requirements.length > 0
    ) {
      planLines.push(
        `Implementation steps: ${plan.resolved_requirements.join(
          " | "
        )}.`
      );
    }

    return [
      { role: "system", content: DIRECT_RESOLVED_SYSTEM_PROMPT },
      {
        role: "user",
        content:
          `Available entities:\n${this._entitySummary(combinedEntities)}\n\n` +
          (planLines.length > 0 ? `${planLines.join("\n")}\n\n` : "") +
          `${resolvedPrompt}\n\n` +
          "Return the complete automation JSON now.",
      },
    ];
  }

  _buildPlanToYamlMessages(prompt, context = {}) {
    const combinedEntities = Array.isArray(context?.entities) ? context.entities : [];
    const plan = this._isUsefulPlanningResult(context?.plan, prompt)
      ? context.plan
      : {};
    const fallbackUserContent = this._normalizeText(
      (Array.isArray(context?.messages) ? context.messages : []).find(
        (message) => message?.role === "user"
      )?.content
    );
    const resolvedPrompt = this._normalizeText(context?.resolvedPrompt);
    const sections = [];

    if (combinedEntities.length > 0) {
      sections.push(`Available entities:\n${this._entitySummary(combinedEntities)}`);
    } else if (fallbackUserContent) {
      sections.push(fallbackUserContent);
    }

    sections.push(`Original request:\n${this._normalizeText(prompt)}`);

    if (resolvedPrompt) {
      sections.push(`Prompt interpretation:\n${resolvedPrompt}`);
    }

    const briefLines = [];
    if (plan?.resolved_request) {
      briefLines.push(`- Automation intent: ${plan.resolved_request}`);
    }
    if (
      Array.isArray(plan?.resolved_requirements) &&
      plan.resolved_requirements.length > 0
    ) {
      plan.resolved_requirements.forEach((item) => {
        briefLines.push(`- Requirement: ${item}`);
      });
    }
    if (Array.isArray(plan?.resolved_entities) && plan.resolved_entities.length > 0) {
      plan.resolved_entities.forEach((item) => {
        briefLines.push(`- Entity mapping: ${item}`);
      });
    }
    if (briefLines.length > 0) {
      sections.push(`Implementation facts:\n${briefLines.join("\n")}`);
    }

    sections.push(
      "Return one complete Home Assistant automation as JSON now.",
      "Do not ask for clarification and do not return planning keys."
    );

    return [
      { role: "system", content: DIRECT_PLAN_TO_YAML_SYSTEM_PROMPT },
      {
        role: "user",
        content: sections.filter(Boolean).join("\n\n"),
      },
    ];
  }

  _buildYamlOnlyFallbackPrompt(prompt, context = {}, issues = [], draftYaml = "") {
    const combinedEntities = Array.isArray(context?.entities) ? context.entities : [];
    const resolvedPrompt = this._normalizeText(context?.resolvedPrompt);
    const plan = this._isUsefulPlanningResult(context?.plan, prompt)
      ? context.plan
      : {};
    const sections = [
      "You are an expert Home Assistant automation engineer.",
      "Return ONLY one complete Home Assistant automation in YAML.",
      "Do not return JSON, markdown fences, commentary, or explanations.",
      "Use Home Assistant 2024.10+ syntax only.",
      "The YAML must start with alias: and include description:, triggers:, conditions:, and actions:.",
      "Read the entire request before deciding how to structure the automation.",
      "Preserve all thresholds, delays, nested branches, notifications, guard conditions, and whichever-triggered sensor details from the request.",
      "For OR trigger thresholds combined with AND guard conditions, preserve that boolean logic exactly.",
      "Treat time-window exclusions such as not between 9am and 5pm on a weekday as conditions, not as the trigger schedule.",
      "When the request refers to whichever sensor triggered, capture trigger.entity_id, a friendly sensor label, and the live sensor value in variables and use them in the notification message.",
    ];

    if (combinedEntities.length > 0) {
      sections.push(`Available entities:\n${this._entitySummary(combinedEntities)}`);
    }

    sections.push(`Original request:\n${this._normalizeText(prompt)}`);

    if (resolvedPrompt) {
      sections.push(`Prompt interpretation:\n${resolvedPrompt}`);
    }

    const factLines = [];
    if (plan?.resolved_request) {
      factLines.push(`- Automation intent: ${plan.resolved_request}`);
    }
    this._normalizePlanItems(plan?.resolved_requirements).forEach((item) => {
      factLines.push(`- Requirement: ${item}`);
    });
    this._normalizePlanItems(plan?.resolved_entities).forEach((item) => {
      factLines.push(`- Entity mapping: ${item}`);
    });
    if (factLines.length > 0) {
      sections.push(`Implementation facts:\n${factLines.join("\n")}`);
    }

    const draftText = this._normalizeText(draftYaml);
    if (draftText) {
      sections.push(`Incomplete draft to replace:\n${draftText}`);
    }

    if (Array.isArray(issues) && issues.length > 0) {
      sections.push(`Problems to fix:\n- ${issues.join("\n- ")}`);
    }

    sections.push(
      "Regenerate the entire automation from scratch if the draft is incomplete.",
      "Use valid Home Assistant constructs such as variables, trigger ids, choose/default branches, delays, numeric_state triggers, state conditions, and template conditions when the request requires them.",
      "For nested outcomes such as 'if still above X after Y, do A, otherwise do B', implement that exact branch logic in YAML rather than describing it.",
      "Preserve the full requested behavior, including thresholds, guards, time exclusions, delays, notifications, and whichever-triggered sensor details.",
      "Return only YAML now."
    );

    return sections.filter(Boolean).join("\n\n");
  }

  _summarizeGeneratedYaml(prompt, yaml) {
    const alias = this._normalizeText(
      String(yaml || "").match(/^alias\s*:\s*(.+)$/m)?.[1]
    );
    if (alias) {
      return `Generated ${alias}.`;
    }

    const requestText = this._normalizeText(prompt);
    if (!requestText) {
      return "Generated the automation YAML.";
    }

    return `Generated an automation for: ${requestText.slice(0, 120)}${
      requestText.length > 120 ? "..." : ""
    }`;
  }

  _ensureResultSummary(prompt, result) {
    if (!result || result.needs_clarification || !this._normalizeText(result?.yaml)) {
      return result;
    }

    if (this._normalizeText(result?.summary)) {
      return result;
    }

    return {
      ...result,
      summary: this._summarizeGeneratedYaml(prompt, result.yaml),
    };
  }

  async _rewriteInvalidAutomationYaml(prompt, messages, result, issues = []) {
    const nonSystemMessages = (Array.isArray(messages) ? messages : []).filter(
      (message) => message?.role !== "system"
    );
    const rewriteMessages = [
      { role: "system", content: DIRECT_SYNTAX_REWRITE_SYSTEM_PROMPT },
      ...nonSystemMessages,
      {
        role: "assistant",
        content: this._buildAutomationContextMessage(
          result?.summary,
          result?.yaml
        ),
      },
      {
        role: "user",
        content:
          `Original request:\n${this._normalizeText(prompt)}\n\n` +
          "Rewrite the draft above into one valid Home Assistant automation. " +
          "The yaml key must be a non-empty string and must preserve the original intent. " +
          "Do not ask any more clarification questions. " +
          `Syntax problems to fix: ${(Array.isArray(issues) ? issues : [])
            .filter(Boolean)
            .join(" ")}`,
      },
    ];

    return this._directChatCompletion(
      rewriteMessages,
      this._parseDirectResponse.bind(this),
      DIRECT_SYNTAX_REWRITE_MAX_TOKENS,
      DIRECT_FINAL_MODEL_PREFERENCES
    );
  }

  async _compilePlanToYaml(prompt, context = {}) {
    const compileMessages = this._buildPlanToYamlMessages(prompt, context);

    return this._directChatCompletion(
      compileMessages,
      this._parseDirectResponse.bind(this),
      DIRECT_COMPLEX_MAX_TOKENS,
      DIRECT_FINAL_MODEL_PREFERENCES
    );
  }

  async _rewritePlannerResponseToYaml(prompt, context = {}) {
    const plan = context?.plan || {};
    const rewriteMessages = [
      ...this._buildPlanToYamlMessages(prompt, context),
      {
        role: "assistant",
        content: JSON.stringify({
          resolved_request: this._normalizeText(plan?.resolved_request),
          resolved_requirements: this._normalizePlanItems(
            plan?.resolved_requirements
          ),
          resolved_entities: this._normalizePlanItems(plan?.resolved_entities),
          needs_clarification: false,
          clarifying_questions: [],
        }),
      },
      {
        role: "user",
        content:
          "Your previous reply was invalid because it returned planning keys instead of the required final automation JSON. " +
          "Rewrite that reply into the final Home Assistant automation JSON now. " +
          "The top-level object must contain exactly four keys: yaml, summary, needs_clarification, clarifying_questions. " +
          "The yaml value must be a non-empty Home Assistant automation string that starts with alias:. " +
          "Do not return resolved_request, resolved_requirements, resolved_entities, or any extra keys.",
      },
    ];

    return this._directChatCompletion(
      rewriteMessages,
      this._parseDirectResponse.bind(this),
      DIRECT_COMPLEX_MAX_TOKENS,
      DIRECT_FINAL_MODEL_PREFERENCES
    );
  }

  async _directYamlGeneration(promptText, maxTokens = DIRECT_YAML_ONLY_MAX_TOKENS) {
    const { endpoint, model } = await this._resolveDirectEndpoint(
      DIRECT_FINAL_MODEL_PREFERENCES
    );
    const resp = await this._fetchWithTimeout(
      `${endpoint}/api/generate`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model,
          prompt: promptText,
          stream: false,
          options: {
            temperature: DIRECT_TEMPERATURE,
            num_predict: maxTokens,
          },
        }),
      },
      15 * 60 * 1000
    );

    if (!resp.ok) {
      const body = await resp.text();
      throw new Error(`LLM returned HTTP ${resp.status}: ${body.slice(0, 500)}`);
    }

    const payload = await resp.json();
    const responseText = this._normalizeText(payload?.response);
    const parsed =
      this._extractLooseYamlResponse(responseText) ||
      this._extractMalformedJsonYamlResponse(responseText);
    if (!parsed?.yaml) {
      throw new Error("The YAML-only fallback did not return automation YAML.");
    }
    return {
      yaml: parsed.yaml,
      summary: "",
      needs_clarification: false,
      clarifying_questions: [],
    };
  }

  async _regenerateAutomationYamlFromScratch(
    prompt,
    context = {},
    issues = [],
    draftYaml = ""
  ) {
    const yamlOnlyPrompt = this._buildYamlOnlyFallbackPrompt(
      prompt,
      context,
      issues,
      draftYaml
    );
    return this._directYamlGeneration(yamlOnlyPrompt);
  }

  _buildPlanningMessages(prompt, entities) {
    const baseMessages = this._buildDirectMessages(prompt, entities);
    const userContent = baseMessages[1]?.content || "";
    return [
      { role: "system", content: DIRECT_PLANNER_SYSTEM_PROMPT },
      {
        role: "user",
        content:
          `${userContent}\n\n` +
          "Analyze the entire request, resolve the intended entities and grouped conditions, and return the planning JSON. " +
          "resolved_requirements must be ordered natural-language implementation steps, not a list of raw entity_ids. " +
          "resolved_entities must be human-readable mapping strings, not nested JSON objects.",
      },
    ];
  }

  _parsePlanningResponse(payload) {
    const choices = payload?.choices;
    if (!Array.isArray(choices) || choices.length === 0) {
      throw new Error("No choices in LLM planning response");
    }

    let content = this._normalizeText(choices[0]?.message?.content);
    if (!content) {
      throw new Error("Empty content in LLM planning response");
    }

    let parsed;
    try {
      parsed = JSON.parse(this._extractJsonObjectText(content));
    } catch (err) {
      throw new Error(`Failed to parse planning response: ${err.message || err}`);
    }

    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("LLM planning response is not a JSON object");
    }

    return {
      resolved_request: this._normalizeText(parsed.resolved_request),
      resolved_requirements: this._normalizePlanItems(
        parsed.resolved_requirements
      ),
      resolved_entities: this._normalizePlanItems(parsed.resolved_entities),
      needs_clarification: Boolean(parsed.needs_clarification),
      clarifying_questions: this._normalizeQuestions(
        parsed.clarifying_questions || parsed.questions
      ),
    };
  }

  _selectDirectModel(models, preferences = DIRECT_MODEL_PREFERENCES) {
    const available = Array.isArray(models) ? models : [];
    const preferredModels = Array.isArray(preferences) && preferences.length > 0
      ? preferences
      : DIRECT_MODEL_PREFERENCES;
    for (const preferred of preferredModels) {
      if (available.includes(preferred)) {
        return preferred;
      }
    }
    return available[0] || preferredModels[0] || DIRECT_MODEL_PREFERENCES[0];
  }

  _buildDirectEndpointCandidates() {
    const candidates = [];
    const pushCandidate = (value) => {
      const endpoint = this._normalizeText(value).replace(/\/+$/g, "");
      if (!endpoint || candidates.includes(endpoint)) {
        return;
      }
      candidates.push(endpoint);
    };

    const selectedServiceEndpoint = this._canUseDirectGenerationFallback()
      ? this._normalizeText(this._selectedService()?.endpoint_url)
      : "";
    pushCandidate(selectedServiceEndpoint);
    pushCandidate(this._configuredDirectEndpoint);

    const hostname = this._normalizeText(
      window?.location?.hostname || ""
    ).toLowerCase();
    if (hostname) {
      const protocol = window?.location?.protocol === "https:" ? "https:" : "http:";
      pushCandidate(`${protocol}//${hostname}:${DIRECT_ENDPOINT_PORT}`);
      if (hostname !== "localhost" && hostname !== "127.0.0.1") {
        pushCandidate(`http://localhost:${DIRECT_ENDPOINT_PORT}`);
      }
    }

    return candidates;
  }

  async _resolveDirectEndpoint(preferences = DIRECT_MODEL_PREFERENCES) {
    if (
      this._directEndpoint &&
      this._directModel &&
      preferences === DIRECT_MODEL_PREFERENCES
    ) {
      return {
        endpoint: this._directEndpoint,
        model: this._directModel,
      };
    }

    let lastError = null;
    for (const endpoint of this._buildDirectEndpointCandidates()) {
      try {
        const resp = await this._fetchWithTimeout(`${endpoint}/api/tags`);
        if (!resp.ok) {
          lastError = new Error(`HTTP ${resp.status}`);
          continue;
        }
        const body = await resp.json();
        const models = Array.isArray(body?.models)
          ? body.models
              .map((model) => model?.name)
              .filter((name) => typeof name === "string" && name)
          : [];
        this._directEndpoint = endpoint;
        const selectedModel = this._selectDirectModel(models, preferences);
        if (preferences === DIRECT_MODEL_PREFERENCES) {
          this._directModel = selectedModel;
        }
        return {
          endpoint: this._directEndpoint,
          model: selectedModel,
        };
      } catch (err) {
        lastError = err;
      }
    }

    throw new Error(
      `Cannot connect to the local Ollama server: ${this._formatError(lastError)}`
    );
  }

  async _directChatCompletion(
    messages,
    responseParser = this._parseDirectResponse.bind(this),
    maxTokens = DIRECT_MAX_TOKENS,
    modelPreferences = DIRECT_MODEL_PREFERENCES
  ) {
    const { endpoint, model } = await this._resolveDirectEndpoint(modelPreferences);
    const resp = await this._fetchWithTimeout(
      `${endpoint}/v1/chat/completions`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model,
          messages,
          max_tokens: maxTokens,
          temperature: DIRECT_TEMPERATURE,
          response_format: { type: "json_object" },
          stream: false,
        }),
      },
      15 * 60 * 1000
    );

    if (!resp.ok) {
      const body = await resp.text();
      throw new Error(`LLM returned HTTP ${resp.status}: ${body.slice(0, 500)}`);
    }

    const payload = await resp.json();
    return responseParser(payload);
  }

  _parseDirectResponse(payload) {
    const choices = payload?.choices;
    if (!Array.isArray(choices) || choices.length === 0) {
      throw new Error("No choices in LLM response");
    }

    let content = this._normalizeText(choices[0]?.message?.content);
    if (!content) {
      throw new Error("Empty content in LLM response");
    }

    let parsed;
    try {
      parsed = JSON.parse(this._extractJsonObjectText(content));
    } catch (err) {
      parsed =
        this._extractMalformedJsonYamlResponse(content) ||
        this._extractLooseYamlResponse(content);
      if (!parsed) {
        throw new Error(`Failed to parse LLM response: ${err.message || err}`);
      }
    }

    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("LLM response is not a JSON object");
    }

    const yaml = this._normalizeAutomationYamlText(parsed.yaml);
    let summary = this._normalizeText(parsed.summary);
    let needsClarification = Boolean(parsed.needs_clarification);
    let clarifyingQuestions = this._normalizeQuestions(
      parsed.clarifying_questions ||
        parsed.questions ||
        parsed.follow_up_questions
    );
    const plannerRequirements = this._normalizePlanItems(
      parsed.resolved_requirements
    );
    const plannerEntities = this._normalizePlanItems(parsed.resolved_entities);
    const plannerOnlyResponse = Boolean(
      !yaml &&
      (this._normalizeText(parsed.resolved_request) ||
        plannerRequirements.length > 0 ||
        plannerEntities.length > 0)
    );

    if (!yaml) {
      if (plannerOnlyResponse) {
        const planDetails = [
          this._normalizeText(parsed.resolved_request),
          ...plannerRequirements.slice(0, 6),
          plannerEntities.length > 0
            ? `Resolved entities: ${plannerEntities.slice(0, 8).join("; ")}`
            : "",
        ].filter(Boolean);
        summary =
          summary ||
          planDetails.join(" ") ||
          "The model returned an implementation plan instead of automation YAML.";
      } else if (clarifyingQuestions.length > 0) {
        needsClarification = true;
      } else if (needsClarification && summary) {
        clarifyingQuestions = [summary];
      } else if (summary && this._looksLikeQuestion(summary)) {
        needsClarification = true;
        clarifyingQuestions = [summary];
      }
    }

    if (needsClarification) {
      if (!summary) {
        summary = "I need a bit more detail before I can generate the automation.";
      }
      if (clarifyingQuestions.length === 0) {
        clarifyingQuestions = [summary];
      }
      return {
        yaml: null,
        summary,
        needs_clarification: true,
        clarifying_questions: clarifyingQuestions,
      };
    }

    if (!yaml) {
      if (summary) {
        return {
          yaml: "",
          summary,
          needs_clarification: false,
          clarifying_questions: [],
          missing_yaml: true,
          planner_only: plannerOnlyResponse,
          plan_details: plannerOnlyResponse
            ? {
                resolved_request: this._normalizeText(parsed.resolved_request),
                resolved_requirements: plannerRequirements,
                resolved_entities: plannerEntities,
              }
            : null,
        };
      }
      throw new Error(
        "The model did not return automation YAML or clarification questions."
      );
    }

    return {
      yaml,
      summary,
      needs_clarification: false,
      clarifying_questions: [],
    };
  }

  async _pollBackendGeneration(jobId) {
    const startedAt = Date.now();
    let retryDelayMs = DIRECT_STATUS_POLL_INTERVAL_MS;

    while (Date.now() - startedAt < 15 * 60 * 1000) {
      try {
        const payload = await this._requestGenerationStatusWithToken(jobId);

        if (payload?.repair_in_progress && (payload.detail || "") !== this._lastRepairDetail) {
          this._lastRepairDetail = payload.detail || "";
          this._loadingMessage = payload.message || "Fixing an issue…";
          this._loadingDetail = payload.detail || "AutoMagic is asking the AI to correct an issue.";
          this._appendChatMessage({
            role: "assistant",
            type: "status",
            tone: "warning",
            text: payload.detail ||
              "AutoMagic detected an issue with the generated automation and has " +
              "automatically sent the specific error back to the AI, asking for a correction.",
          });
        } else if (payload?.message && !payload?.repair_in_progress) {
          this._loadingMessage = payload.message;
          this._loadingDetail = payload.detail || "";
        }

        if (
          ["completed", "error", "needs_clarification"].includes(payload?.status)
        ) {
          return payload;
        }
        retryDelayMs = payload?.poll_after_ms || DIRECT_STATUS_POLL_INTERVAL_MS;
      } catch (err) {
        if (!this._shouldRetryBackendStatus(err)) {
          throw err;
        }
        retryDelayMs = Math.min(retryDelayMs + 2000, 10000);
      }

      await new Promise((resolve) => {
        window.setTimeout(resolve, retryDelayMs);
      });
    }

    throw new Error("Backend generation timed out");
  }

  async _runBackendGeneration(prompt, requestText = null, continueJobId = "") {
    this._lastRepairDetail = "";
    const selectedService = this._selectedService();
    this._startLoadingTicker(
      "Waiting for your model to respond...",
      selectedService
        ? `Using ${this._serviceLabel(selectedService)} via Home Assistant's background generation job.`
        : "Using Home Assistant's background generation job."
    );

    const payload = this._buildGenerationRequestPayload(prompt, continueJobId);
    const job = await this._requestGenerateWithToken(payload);
    const finalJob = await this._pollBackendGeneration(job.job_id);
    this._generationJobId = finalJob.job_id || job.job_id || "";

    if (finalJob.status === "error") {
      throw new Error(
        finalJob.error || finalJob.detail || "Generation failed."
      );
    }

    if (finalJob.status === "needs_clarification") {
      const entityPool = await this._ensureEntityPool();
      this._conversationMessages = null;
      this._clarificationSummary = finalJob.summary || "";
      this._clarifyingQuestions = finalJob.clarifying_questions || [];
      this._clarificationCandidates = this._deriveClarificationCandidates(
        prompt,
        {
          summary: finalJob.summary || "",
          clarifying_questions: finalJob.clarifying_questions || [],
        },
        entityPool
      );
      this._clarificationAnswer = "";
      this._clarificationContext = null;
      this._appendChatMessage({
        role: "assistant",
        type: "clarification",
        summary: this._clarificationSummary,
        questions: [...this._clarifyingQuestions],
        candidates: [...this._clarificationCandidates],
      });
      this._clearGenerationPolling();
      this._state = STATES.CLARIFY;
      return;
    }

    const result = {
      yaml: finalJob.yaml || "",
      summary: finalJob.summary || "",
      needs_clarification: false,
      clarifying_questions: [],
    };
    this._conversationMessages = null;
    this._appendChatMessage({
      role: "assistant",
      type: "yaml",
      summary: result.summary || "",
      yaml: result.yaml || "",
      parsedAutomation: this._parseYaml(result.yaml || ""),
      requestText: this._normalizeText(requestText || prompt),
      installStatus: "ready",
      installAlias: "",
      installError: "",
    });
    this._setPreviewResult(result);
  }

  async _runResolvedFinalGeneration(
    prompt,
    resolvedPrompt,
    allEntities = null,
    requestText = null
  ) {
    const loadingTarget = await this._resolveDirectEndpoint(
      DIRECT_FINAL_MODEL_PREFERENCES
    );
    this._startLoadingTicker(
      "Finalizing the automation with resolved entity mappings...",
      `Using ${loadingTarget.model} on ${loadingTarget.endpoint}.`
    );

    const entityPool = await this._ensureEntityPool(allEntities);
    const explicitEntities = this._findExplicitEntities(prompt, entityPool);
    const obviousEntities = this._findObviousNamedEntities(prompt, entityPool);
    const heuristicEntities = this._collectHeuristicEntities(prompt, entityPool);
    const selectedEntities = this._selectRelevantEntities(
      prompt,
      entityPool,
      DIRECT_CONTEXT_LIMIT
    );
    const combinedEntities = [
      ...explicitEntities,
      ...obviousEntities.slice(0, 16),
      ...heuristicEntities.slice(0, 8),
      ...selectedEntities,
    ].filter(
      (entity, index, items) =>
        items.findIndex(
          (candidate) => candidate.entity_id === entity.entity_id
        ) === index
    );

    const shouldSkipPlannerForResolvedPass = this._shouldPreferYamlOnlyResolvedPass(
      requestText || prompt,
      null
    );
    let planningResult = null;
    if (
      !shouldSkipPlannerForResolvedPass &&
      this._shouldUsePlanner(requestText || prompt)
    ) {
      try {
        planningResult = await this._directChatCompletion(
          this._buildPlanningMessages(
            requestText || prompt,
            combinedEntities.slice(0, DIRECT_CONTEXT_LIMIT)
          ),
          this._parsePlanningResponse.bind(this),
          DIRECT_PLANNER_MAX_TOKENS,
          DIRECT_PLANNER_MODEL_PREFERENCES
        );
      } catch (err) {
        planningResult = null;
      }
    }

    const usablePlanningResult = this._isUsefulPlanningResult(
      planningResult,
      requestText || prompt
    )
      ? planningResult
      : null;

    const baseMessages = this._buildResolvedFinalMessages(
      requestText || prompt,
      resolvedPrompt,
      combinedEntities.slice(0, DIRECT_CONTEXT_LIMIT),
      usablePlanningResult
    );
    const repairContext = {
      entities: combinedEntities.slice(0, DIRECT_CONTEXT_LIMIT),
      resolvedPrompt,
      plan: usablePlanningResult,
    };
    const preferYamlOnlyResolvedPass =
      shouldSkipPlannerForResolvedPass ||
      this._shouldPreferYamlOnlyResolvedPass(
        requestText || prompt,
        usablePlanningResult
      );
    let result;
    if (preferYamlOnlyResolvedPass) {
      result = await this._regenerateAutomationYamlFromScratch(
        requestText || prompt,
        repairContext
      );
      result = this._ensureResultSummary(requestText || prompt, result);
    } else if (usablePlanningResult && !usablePlanningResult.needs_clarification) {
      result = await this._compilePlanToYaml(requestText || prompt, repairContext);
    } else {
      result = await this._directChatCompletion(
        baseMessages,
        this._parseDirectResponse.bind(this),
        DIRECT_COMPLEX_MAX_TOKENS,
        DIRECT_FINAL_MODEL_PREFERENCES
      );
    }
    if (!result.needs_clarification) {
      result = await this._repairGeneratedYamlIfNeeded(
        requestText || prompt,
        baseMessages,
        result,
        repairContext
      );
      result = this._ensureResultSummary(requestText || prompt, result);
    }

    if (result.needs_clarification) {
      const assistantMessage = this._buildClarificationMessage(
        result.summary,
        result.clarifying_questions
      );
      const autoClarification = this._buildAutoClarificationAnswer(
        requestText || prompt,
        result,
        combinedEntities.slice(0, DIRECT_CONTEXT_LIMIT)
      );
      if (autoClarification) {
        const retryMessages = [
          ...baseMessages,
          { role: "assistant", content: assistantMessage },
          {
            role: "user",
            content:
              `${autoClarification} This is the final resolved generation pass. ` +
              "Do not ask for any more clarification. Return the complete automation JSON now.",
          },
        ];
        result = await this._directChatCompletion(
          retryMessages,
          this._parseDirectResponse.bind(this),
          DIRECT_COMPLEX_MAX_TOKENS,
          DIRECT_FINAL_MODEL_PREFERENCES
        );
        if (!result.needs_clarification) {
          result = await this._repairGeneratedYamlIfNeeded(
            requestText || prompt,
            retryMessages,
            result,
            repairContext
          );
          result = this._ensureResultSummary(requestText || prompt, result);
        }
      }
    }

    return result;
  }

  async _runDirectGeneration(
    prompt,
    conversationMessages = null,
    allEntities = null,
    requestText = null
  ) {
    const loadingTarget = await this._resolveDirectEndpoint(
      DIRECT_FINAL_MODEL_PREFERENCES
    );
    this._startLoadingTicker(
      "Waiting for your model to respond...",
      `Using ${loadingTarget.model} on ${loadingTarget.endpoint}.`
    );

    const entityPool = await this._ensureEntityPool(allEntities);
    const explicitEntities = this._findExplicitEntities(prompt, entityPool);
    const obviousEntities = this._findObviousNamedEntities(prompt, entityPool);
    const heuristicEntities = this._collectHeuristicEntities(prompt, entityPool);
    const selectedEntities = this._selectRelevantEntities(
      prompt,
      entityPool,
      DIRECT_CONTEXT_LIMIT
    );
    const combinedEntities = [
      ...explicitEntities,
      ...obviousEntities.slice(0, 16),
      ...heuristicEntities.slice(0, 8),
      ...selectedEntities,
    ].filter(
      (entity, index, items) =>
        items.findIndex(
          (candidate) => candidate.entity_id === entity.entity_id
        ) === index
    );

    const shouldPreferResolvedFinalPass =
      !Array.isArray(conversationMessages) ||
      conversationMessages.length === 0
        ? this._shouldPreferResolvedFinalPass(prompt)
        : false;
    let planningResult = null;
    if (
      (!Array.isArray(conversationMessages) || conversationMessages.length === 0) &&
      !shouldPreferResolvedFinalPass &&
      this._shouldUsePlanner(prompt)
    ) {
      try {
        planningResult = await this._directChatCompletion(
          this._buildPlanningMessages(
            prompt,
            combinedEntities.slice(0, DIRECT_CONTEXT_LIMIT)
          ),
          this._parsePlanningResponse.bind(this),
          DIRECT_PLANNER_MAX_TOKENS,
          DIRECT_PLANNER_MODEL_PREFERENCES
        );
      } catch (err) {
        planningResult = null;
      }
    }
    const usablePlanningResult = this._isUsefulPlanningResult(
      planningResult,
      requestText || prompt
    )
      ? planningResult
      : null;

    const initialConversationMessages =
      Array.isArray(conversationMessages) && conversationMessages.length > 0
        ? conversationMessages
        : null;
    let messages = initialConversationMessages
      ? initialConversationMessages
      : this._buildDirectMessages(
          prompt,
          combinedEntities.slice(0, DIRECT_CONTEXT_LIMIT),
          usablePlanningResult
        );

    let result;
    if (shouldPreferResolvedFinalPass) {
      const resolvedFinalPrompt = this._buildResolvedFinalPrompt(
        requestText || prompt,
        combinedEntities.slice(0, DIRECT_CONTEXT_LIMIT)
      );
      messages = this._buildResolvedFinalMessages(
        requestText || prompt,
        resolvedFinalPrompt,
        combinedEntities.slice(0, DIRECT_CONTEXT_LIMIT)
      );
      this._appendChatMessage({
        role: "assistant",
        type: "status",
        tone: "info",
        text: "Resolved the complex prompt into grouped entity mappings before asking the model to generate the final automation.",
      });
      result = await this._runResolvedFinalGeneration(
        prompt,
        resolvedFinalPrompt,
        entityPool,
        requestText || prompt
      );
    } else {
      result = await this._directChatCompletion(
        messages,
        this._parseDirectResponse.bind(this),
        DIRECT_MAX_TOKENS,
        DIRECT_FINAL_MODEL_PREFERENCES
      );
      if (!result.needs_clarification) {
        result = await this._repairGeneratedYamlIfNeeded(prompt, messages, result);
        result = this._ensureResultSummary(requestText || prompt, result);
      }
    }

    if (result.needs_clarification) {
      let clarificationCandidates = this._deriveClarificationCandidates(
        prompt,
        result,
        entityPool
      );
      let assistantMessage = this._buildClarificationMessage(
        result.summary,
        result.clarifying_questions
      );
      const autoClarification = this._buildAutoClarificationAnswer(
        prompt,
        result,
        combinedEntities.slice(0, DIRECT_CONTEXT_LIMIT)
      );
      if (autoClarification) {
        const autoClarificationAlreadySent = messages.some(
          (message) =>
            message?.role === "user" &&
            this._normalizeText(message.content) ===
              this._normalizeText(autoClarification)
        );
        if (
          this._shouldRebuildResolvedPrompt(
            messages,
            assistantMessage,
            autoClarification
          )
        ) {
          this._appendChatMessage({
            role: "assistant",
            type: "status",
            tone: "info",
            text: "Converted repeated clarification into an explicit resolved prompt and asked the model again.",
          });
          const resolvedFinalPrompt = this._buildResolvedFinalPrompt(
            requestText || prompt,
            combinedEntities.slice(0, DIRECT_CONTEXT_LIMIT)
          );
          const resolvedResult = await this._runResolvedFinalGeneration(
            requestText || prompt,
            resolvedFinalPrompt,
            entityPool,
            requestText || prompt
          );
          if (!resolvedResult?.needs_clarification) {
            this._conversationMessages = [
              ...messages,
              {
                role: "assistant",
                content: this._buildAutomationContextMessage(
                  resolvedResult.summary,
                  resolvedResult.yaml
                ),
              },
            ];
            this._appendChatMessage({
              role: "assistant",
              type: "yaml",
              summary: resolvedResult.summary || "",
              yaml: resolvedResult.yaml || "",
              parsedAutomation: this._parseYaml(resolvedResult.yaml || ""),
              requestText: this._normalizeText(requestText || prompt),
              installStatus: "ready",
              installAlias: "",
              installError: "",
            });
            this._setPreviewResult(resolvedResult);
            return;
          }
          result = resolvedResult;
          clarificationCandidates = this._deriveClarificationCandidates(
            prompt,
            result,
            entityPool
          );
          assistantMessage = this._buildClarificationMessage(
            result.summary,
            result.clarifying_questions
          );
        }
        if (!autoClarificationAlreadySent) {
          const authoritativeResolution =
            messages.length >= 6
              ? this._buildAuthoritativeClarificationResolution(
                  prompt,
                  combinedEntities.slice(0, DIRECT_CONTEXT_LIMIT)
                )
              : "";
          const strengthenedAutoClarification =
            messages.length >= 6
              ? [autoClarification, authoritativeResolution]
                  .filter(Boolean)
                  .join(" ") +
                " This clarification has already been answered from the original prompt and prior context. Do not ask it again. Return the complete automation JSON now."
              : autoClarification;
          this._appendChatMessage({
            role: "assistant",
            type: "status",
            tone: "info",
            text: "Resolved a grouped-entity clarification automatically and asked the model to continue.",
          });
          return this._runDirectGeneration(
            prompt,
            [
              ...messages,
              { role: "assistant", content: assistantMessage },
              { role: "user", content: strengthenedAutoClarification },
            ],
            entityPool,
            requestText
          );
        }
      }
      this._conversationMessages = [
        ...messages,
        { role: "assistant", content: assistantMessage },
      ];
      this._generationJobId = "direct";
      this._clarificationSummary = result.summary || "";
      this._clarifyingQuestions = result.clarifying_questions || [];
      this._clarificationCandidates = clarificationCandidates;
      this._clarificationAnswer = "";
      this._clarificationContext = null;
      this._appendChatMessage({
        role: "assistant",
        type: "clarification",
        summary: this._clarificationSummary,
        questions: [...this._clarifyingQuestions],
        candidates: [...clarificationCandidates],
      });
      this._clearGenerationPolling();
      this._state = STATES.CLARIFY;
      return;
    }

    this._conversationMessages = [
      ...messages,
      {
        role: "assistant",
        content: this._buildAutomationContextMessage(
          result.summary,
          result.yaml
        ),
      },
    ];
    this._appendChatMessage({
      role: "assistant",
      type: "yaml",
      summary: result.summary || "",
      yaml: result.yaml || "",
      parsedAutomation: this._parseYaml(result.yaml || ""),
      requestText: this._normalizeText(requestText || prompt),
      installStatus: "ready",
      installAlias: "",
      installError: "",
    });
    this._setPreviewResult(result);
  }

  async _submitChatPrompt(userText, modelText = null) {
    const visibleText = this._normalizeText(userText);
    const aiText = this._normalizeText(modelText || userText);
    if (!visibleText || !aiText) return;
    if (this._state === STATES.LOADING || this._state === STATES.INSTALLING) {
      return;
    }

    const previousState = this._state;
    const previousGenerationJobId = this._generationJobId;
    const previousConversationMessages = this._conversationMessages;

    this._appendChatMessage({
      role: "user",
      type: "text",
      text: visibleText,
    });
    this._prompt = "";
    this._clearGenerationPolling();
    this._error = "";
    this._clearClarificationState();
    this._generationJobId = "";

    try {
      const continueBackendJobId =
        previousGenerationJobId &&
        !previousConversationMessages &&
        [
          STATES.CLARIFY,
          STATES.PREVIEW,
          STATES.SUCCESS,
        ].includes(previousState)
          ? previousGenerationJobId
          : "";
      const canUseDirectFallback = this._canUseDirectGenerationFallback();
      if (continueBackendJobId || this._shouldUseBackendGeneration(aiText)) {
        try {
          await this._runBackendGeneration(
            aiText,
            visibleText,
            continueBackendJobId
          );
          return;
        } catch (backendErr) {
          if (continueBackendJobId || !canUseDirectFallback) {
            throw backendErr;
          }
          this._appendChatMessage({
            role: "assistant",
            type: "status",
            tone: "warning",
            text: "Home Assistant background generation failed, so AutoMagic is trying a direct local model connection.",
          });
        }
      }

      const allEntities =
        this._lastEntityPool.length > 0
          ? this._lastEntityPool
          : (await this._requestEntities())?.entities || [];
      this._lastEntityPool = allEntities;
      const nextConversation =
        Array.isArray(this._conversationMessages) &&
        this._conversationMessages.length > 0
          ? [...this._conversationMessages, { role: "user", content: aiText }]
          : null;
      await this._runDirectGeneration(
        aiText,
        nextConversation,
        allEntities,
        visibleText
      );
    } catch (err) {
      if (this._shouldRetryBackendStatus(err) && !this._generationJobId) {
        try {
          await this._runBackendGeneration(aiText, visibleText);
          return;
        } catch (backendErr) {
          err = backendErr;
        }
      }
      this._clearGenerationPolling();
      this._state = STATES.ERROR;
      this._error = `Request failed: ${this._formatError(err)}`;
      this._appendChatMessage({
        role: "assistant",
        type: "error",
        text: this._error,
      });
    }
  }

  async _handleGenerate() {
    const prompt = this._prompt.trim();
    if (!prompt) return;

    const matchedCandidate =
      this._clarificationCandidates.length > 0
        ? this._resolveClarificationCandidate(prompt)
        : null;
    await this._submitChatPrompt(
      prompt,
      matchedCandidate ? this._buildExplicitEntityAnswer(matchedCandidate) : prompt
    );
  }

  async _handleInstall(messageIndex = -1) {
    const targetMessage =
      messageIndex >= 0 ? this._chatMessages[messageIndex] : null;
    let yaml = this._normalizeAutomationYamlText(
      targetMessage?.yaml || this._yaml
    );
    if (!yaml) return;

    if (messageIndex >= 0) {
      this._updateChatMessage(messageIndex, {
        installStatus: "installing",
        installError: "",
      });
    }

    this._state = STATES.INSTALLING;
    this._error = "";

    try {
      let result = await this._requestInstall({
        yaml,
        prompt: targetMessage?.requestText || this._lastUserChatText(),
        summary: targetMessage?.summary || this._summary,
      });

      // --- Install-error repair: send HA error back to AI to fix ---
      if (!result.success && result.error) {
        this._appendChatMessage({
          role: "assistant",
          type: "status",
          tone: "warning",
          text:
            "Home Assistant rejected the automation with an error. " +
            "AutoMagic is sending the error back to the AI for correction.\n\n" +
            `Error: ${result.error}`,
        });
        this._state = STATES.LOADING;
        this._loadingMessage = "Fixing install error…";
        this._loadingDetail =
          "The AI is correcting the automation based on the Home Assistant error.";

        try {
          const selectedService = this._selectedService();
          const repairPayload = {
            yaml,
            error: result.error,
            summary: targetMessage?.summary || this._summary,
          };
          if (selectedService?.service_id) {
            repairPayload.service_id = selectedService.service_id;
          }
          const repairResult = await this._requestInstallRepair(repairPayload);

          if (repairResult.success && repairResult.yaml) {
            yaml = this._normalizeAutomationYamlText(repairResult.yaml);
            this._yaml = yaml;
            this._parsedAutomation = this._parseYaml(yaml);
            this._summary = repairResult.summary || this._summary;

            this._appendChatMessage({
              role: "assistant",
              type: "status",
              tone: "info",
              text: "The AI corrected the automation. Retrying install…",
            });

            this._state = STATES.INSTALLING;
            result = await this._requestInstall({
              yaml,
              prompt: targetMessage?.requestText || this._lastUserChatText(),
              summary: repairResult.summary || this._summary,
            });
          } else {
            // Repair endpoint itself failed
            const repairError =
              repairResult.error || "AI could not fix the automation.";
            this._error = repairError;
            if (messageIndex >= 0) {
              this._updateChatMessage(messageIndex, {
                installStatus: "error",
                installError: repairError,
              });
            }
            this._appendChatMessage({
              role: "assistant",
              type: "error",
              text: `Install repair failed: ${repairError}`,
            });
            this._state = STATES.ERROR;
            return;
          }
        } catch (repairErr) {
          this._error = `Install repair failed: ${this._formatError(repairErr)}`;
          if (messageIndex >= 0) {
            this._updateChatMessage(messageIndex, {
              installStatus: "error",
              installError: this._error,
            });
          }
          this._appendChatMessage({
            role: "assistant",
            type: "error",
            text: this._error,
          });
          this._state = STATES.ERROR;
          return;
        }
      }

      if (result.success) {
        this._installedAlias = result.alias || "Automation";
        if (messageIndex >= 0) {
          this._updateChatMessage(messageIndex, {
            installStatus: "installed",
            installAlias: this._installedAlias,
            installError: "",
          });
        }
        this._appendChatMessage({
          role: "assistant",
          type: "status",
          tone: "success",
          text: `Installed ${this._installedAlias}.`,
        });
        this._state = STATES.SUCCESS;
        this._fetchHistory();
      } else {
        this._error = result.error || "Installation failed";
        if (messageIndex >= 0) {
          this._updateChatMessage(messageIndex, {
            installStatus: "error",
            installError: this._error,
          });
        }
        this._appendChatMessage({
          role: "assistant",
          type: "error",
          text: `Install failed: ${this._error}`,
        });
        this._state = STATES.ERROR;
      }
    } catch (err) {
      this._error = `Install failed: ${this._formatError(err)}`;
      if (messageIndex >= 0) {
        this._updateChatMessage(messageIndex, {
          installStatus: "error",
          installError: this._error,
        });
      }
      this._appendChatMessage({
        role: "assistant",
        type: "error",
        text: this._error,
      });
      this._state = STATES.ERROR;
      return;
    }

    this._state = STATES.IDLE;
  }

  async _handleClarificationSubmit() {
    const answer = this._clarificationAnswer.trim();
    if (!answer) return;
    const matchedCandidate =
      this._clarificationCandidates.length > 0
        ? this._resolveClarificationCandidate(answer)
        : null;
    this._clarificationAnswer = "";
    await this._submitChatPrompt(
      answer,
      matchedCandidate ? this._buildExplicitEntityAnswer(matchedCandidate) : answer
    );
  }

  _handleReset() {
    this._clearGenerationPolling();
    this._state = STATES.IDLE;
    this._prompt = "";
    this._yaml = "";
    this._summary = "";
    this._clearClarificationState();
    this._parsedAutomation = null;
    this._error = "";
    this._generationJobId = "";
    this._loadingMessage = "";
    this._loadingDetail = "";
    this._loadingElapsedSeconds = 0;
    this._installedAlias = "";
    this._showYaml = false;
    this._chatMessages = [];
    this._conversationMessages = null;
    this._lastEntityPool = [];
    this._directEndpoint = "";
    this._directModel = "";
    this._lastRepairDetail = "";
  }

  _handleRetry() {
    this._clearGenerationPolling();
    this._state = STATES.IDLE;
    this._error = "";
    this._generationJobId = "";
    this._loadingMessage = "";
    this._loadingDetail = "";
    this._loadingElapsedSeconds = 0;
    this._conversationMessages = null;
    this._clearClarificationState();
  }

  _clearGenerationPolling() {
    if (this._statusPollHandle !== null) {
      window.clearTimeout(this._statusPollHandle);
      this._statusPollHandle = null;
    }
    if (this._loadingTickerHandle !== null) {
      window.clearInterval(this._loadingTickerHandle);
      this._loadingTickerHandle = null;
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
      const result = await this._requestGenerationStatus(this._generationJobId);

      if (result.error && !result.status) {
        this._clearGenerationPolling();
        this._state = STATES.ERROR;
        this._error = result.error;
        return;
      }

      this._updateLoadingState(result);

      if (result.repair_in_progress && (result.detail || "") !== this._lastRepairDetail) {
        this._lastRepairDetail = result.detail || "";
        this._appendChatMessage({
          role: "assistant",
          type: "status",
          tone: "warning",
          text: result.detail ||
            "AutoMagic detected an issue with the generated automation and has " +
            "automatically sent the specific error back to the AI, asking for a correction.",
        });
      }

      if (result.status === "needs_clarification") {
        this._clearGenerationPolling();
        this._clarificationSummary = result.summary || result.message || "";
        this._clarifyingQuestions = Array.isArray(result.clarifying_questions)
          ? result.clarifying_questions
          : [];
        this._clarificationAnswer = "";
        this._state = STATES.CLARIFY;
        return;
      }

      if (result.status === "completed") {
        this._clearGenerationPolling();
        if (!result.yaml) {
          this._generationJobId = "";
          this._state = STATES.ERROR;
          this._error = "The model finished without returning automation YAML.";
          return;
        }
        this._yaml = this._normalizeAutomationYamlText(result.yaml);
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
      this._error = `Request failed: ${this._formatError(err)}`;
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
    if (!text) return;
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

  _threadAssistantLabel(message) {
    if (message?.type === "yaml" || message?.type === "clarification") {
      return (
        this._normalizeText(this._selectedService()?.model) ||
        this._normalizeText(this._directModel) ||
        "AI"
      );
    }
    return "AutoMagic";
  }

  _threadMessageBody(message) {
    if (!message) return "";
    if (message.role === "user") {
      return this._normalizeText(message.text);
    }

    if (message.type === "yaml") {
      const parts = [];
      if (message.summary) parts.push(this._normalizeText(message.summary));
      if (message.yaml) parts.push(`YAML:\n${message.yaml}`);
      if (message.installAlias) parts.push(`Install result: ${message.installAlias}`);
      if (message.installError) parts.push(`Install error: ${message.installError}`);
      return parts.filter(Boolean).join("\n\n");
    }

    if (message.type === "clarification") {
      const parts = [];
      if (message.summary) parts.push(this._normalizeText(message.summary));
      if (Array.isArray(message.questions) && message.questions.length > 0) {
        parts.push(
          message.questions
            .map((question, index) => `${index + 1}. ${this._normalizeText(question)}`)
            .join("\n")
        );
      }
      return parts.filter(Boolean).join("\n\n");
    }

    return this._normalizeText(message.text);
  }

  _formatChatThread() {
    return this._chatMessages
      .map((message) => {
        const body = this._threadMessageBody(message);
        if (!body) return "";
        const label =
          message?.role === "user"
            ? "User"
            : this._threadAssistantLabel(message);
        return `${label} said:\n${body}`;
      })
      .filter(Boolean)
      .join("\n\n");
  }

  async _copyChatThread() {
    const text = this._formatChatThread();
    if (!text) return;
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

  _installedAutomationAliases() {
    const states = this.hass?.states || {};
    const aliases = new Set();

    for (const [entityId, state] of Object.entries(states)) {
      if (!String(entityId).startsWith("automation.")) continue;
      const friendlyName = this._normalizeText(
        state?.attributes?.friendly_name || state?.attributes?.alias
      );
      if (friendlyName) aliases.add(friendlyName);
    }

    return aliases;
  }

  _historyStatus(item, installedAliases = null) {
    const explicitStatus = this._normalizeText(item?.status).toLowerCase();
    if (["failed", "deleted", "installed"].includes(explicitStatus)) {
      return explicitStatus;
    }
    if (!item?.success) return "failed";

    const alias = this._normalizeText(item.alias);
    if (!alias) return "installed";

    const aliases = installedAliases || this._installedAutomationAliases();
    return aliases.has(alias) ? "installed" : "deleted";
  }

  _historyCanDelete(item, installedAliases = null) {
    if (typeof item?.can_delete === "boolean") {
      return item.can_delete;
    }
    const status = this._historyStatus(item, installedAliases);
    return status === "failed" || status === "deleted";
  }

  _historyStatusBadge(item, installedAliases = null) {
    const status = this._historyStatus(item, installedAliases);
    if (status === "failed") {
      return { label: "Failed", className: "badge-error" };
    }
    if (status === "deleted") {
      return { label: "Deleted", className: "badge-warning" };
    }
    return { label: "Installed", className: "badge-success" };
  }

  async _handleDeleteHistory(event, item) {
    event?.stopPropagation?.();
    const entryId = this._normalizeText(item?.entry_id);
    if (!entryId || !this._historyCanDelete(item)) {
      return;
    }

    this._historyError = "";
    this._deletingHistoryEntryId = entryId;
    try {
      const response = await this._requestDeleteHistory(entryId);
      this._history = Array.isArray(response?.history) ? response.history : [];
      this._expandedHistory = -1;
    } catch (err) {
      this._historyError = `Delete failed: ${this._formatError(err)}`;
    } finally {
      this._deletingHistoryEntryId = "";
    }
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
    const isBusy =
      this._state === STATES.LOADING || this._state === STATES.INSTALLING;
    const isFollowUp = this._chatMessages.length > 0;
    const isModelLocked = isFollowUp;

    return html`
      <div class="chat-layout">
        <div class="chat-toolbar">
          <p class="chat-subtitle">
            ${isFollowUp
              ? "Continue the thread with follow-up questions or changes. Every message goes back to the AI."
              : "Describe the automation you want. AutoMagic keeps the whole exchange in one chat thread."}
          </p>
          <div class="chat-toolbar-actions">
            ${isFollowUp
              ? html`
                  <button class="btn btn-secondary chat-toolbar-btn" @click=${this._copyChatThread}>
                    <ha-icon icon="mdi:content-copy"></ha-icon>
                    Copy Thread
                  </button>
                  <button class="btn btn-secondary chat-toolbar-btn" @click=${this._handleReset}>
                    <ha-icon icon="mdi:refresh"></ha-icon>
                    Start Over
                  </button>
                `
              : ""}
          </div>
        </div>

        <div class="chat-thread">
          ${!isFollowUp
            ? html`
                <div class="chat-empty">
                  <ha-icon icon="mdi:robot-excited-outline" class="chat-empty-icon"></ha-icon>
                  <p class="chat-empty-title">Chat your automation into shape</p>
                  <p class="chat-empty-sub">
                    Ask for a new automation, answer clarifying questions, then keep refining it in the same thread.
                  </p>
                </div>
              `
            : ""}

          ${this._chatMessages.map((message, index) =>
            this._renderChatMessage(message, index)
          )}

          ${this._state === STATES.LOADING
            ? html`
                <div class="chat-row assistant">
                  <div class="chat-bubble assistant assistant-loading">
                    <ha-circular-progress indeterminate></ha-circular-progress>
                    <div class="chat-loading-text">
                      <p class="loading-text">
                        ${this._loadingMessage || "Waiting for your model to respond..."}
                      </p>
                      <p class="loading-sub">${this._loadingDetail}</p>
                      <span class="loading-meta">
                        Elapsed: ${this._formatDuration(this._loadingElapsedSeconds)}
                      </span>
                    </div>
                  </div>
                </div>
              `
            : ""}

          ${this._state === STATES.INSTALLING
            ? html`
                <div class="chat-row assistant">
                  <div class="chat-bubble assistant assistant-status">
                    <ha-circular-progress indeterminate></ha-circular-progress>
                    <div class="chat-loading-text">
                      <p class="loading-text">Installing automation...</p>
                      <p class="loading-sub">Writing YAML file and reloading automations</p>
                    </div>
                  </div>
                </div>
              `
            : ""}
        </div>

        <div class="chat-composer">
          ${this._services.length > 0
            ? html`
                <label class="service-picker composer-service-picker">
                  <span class="service-picker-label">
                    Model
                    ${isModelLocked ? html`<span class="service-picker-note">Locked for this thread</span>` : ""}
                  </span>
                  <select
                    class="service-select"
                    .value=${this._normalizeText(
                      this._selectedService()?.service_id || ""
                    )}
                    ?disabled=${isBusy || isModelLocked || this._services.length <= 1}
                    @change=${(e) => {
                      this._selectedServiceId = this._normalizeText(
                        e.target.value
                      );
                    }}
                  >
                    ${this._services.map(
                      (service) => html`
                        <option value=${this._normalizeText(service?.service_id)}>
                          ${this._serviceLabel(service)}
                        </option>
                      `
                    )}
                  </select>
                </label>
              `
            : ""}
          <textarea
            class="prompt-input chat-input"
            rows="3"
            placeholder=${isFollowUp
              ? "Ask a follow-up question or describe a change"
              : "e.g. Turn on the lounge lamp at 10pm every day"}
            .value=${this._prompt}
            @input=${(e) => (this._prompt = e.target.value)}
            @keydown=${(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                this._handleGenerate();
              }
            }}
            ?disabled=${isBusy}
          ></textarea>
          <div class="input-footer">
            <span class="hint">
              ${isFollowUp
                ? "Press Enter to send, Shift+Enter for new line"
                : "Press Enter to start, Shift+Enter for new line"}
            </span>
            <button
              class="btn btn-primary"
              @click=${this._handleGenerate}
              ?disabled=${!this._prompt.trim() || isBusy}
            >
              <ha-icon icon=${isFollowUp ? "mdi:send" : "mdi:auto-fix"}></ha-icon>
              ${isFollowUp ? "Send" : "Generate"}
            </button>
          </div>
        </div>
      </div>
    `;
  }

  _renderChatMessage(message, index) {
    const roleClass = message.role === "user" ? "user" : "assistant";
    return html`
      <div class="chat-row ${roleClass}">
        <div class="chat-bubble ${roleClass} ${message.type || "text"}">
          ${message.role === "user"
            ? html`<p class="chat-text">${message.text}</p>`
            : this._renderAssistantChatMessage(message, index)}
        </div>
      </div>
    `;
  }

  _renderAssistantChatMessage(message, index) {
    if (message.type === "yaml") {
      const auto = message.parsedAutomation || this._parseYaml(message.yaml || "");
      const installLabel =
        message.installStatus === "installed"
          ? "Installed"
          : message.installStatus === "installing"
            ? "Installing..."
            : "Install Automation";
      return html`
        ${message.summary
          ? html`<p class="chat-text">${message.summary}</p>`
          : ""}
        ${auto ? this._renderAutomationBreakdown(auto) : ""}
        ${message.yaml
          ? html`
              <details class="yaml-toggle">
                <summary>
                  <ha-icon icon="mdi:code-braces"></ha-icon>
                  View YAML
                  <ha-icon icon="mdi:chevron-down" class="chevron"></ha-icon>
                </summary>
                <div class="yaml-container">
                  <pre class="yaml-code">${message.yaml}</pre>
                  <button
                    class="copy-btn"
                    @click=${() => this._copyYaml(message.yaml)}
                    title="Copy YAML"
                  >
                    <ha-icon icon="mdi:content-copy"></ha-icon>
                  </button>
                </div>
              </details>
            `
          : ""}
        <div class="action-buttons chat-actions">
          <button
            class="btn btn-primary"
            @click=${() => this._handleInstall(index)}
            ?disabled=${message.installStatus === "installing" || message.installStatus === "installed" || this._state === STATES.INSTALLING}
          >
            <ha-icon icon="mdi:download"></ha-icon>
            ${installLabel}
          </button>
        </div>
        ${message.installAlias
          ? html`<p class="chat-meta success">${message.installAlias}</p>`
          : ""}
        ${message.installError
          ? html`<p class="chat-meta error">${message.installError}</p>`
          : ""}
      `;
    }

    if (message.type === "clarification") {
      return html`
        ${message.summary
          ? html`<p class="chat-text">${message.summary}</p>`
          : ""}
        ${Array.isArray(message.questions) && message.questions.length > 0
          ? html`
              <div class="clarify-list">
                ${message.questions.map(
                  (question, questionIndex) => html`
                    <div class="clarify-item">
                      <span class="clarify-index">${questionIndex + 1}</span>
                      <span class="clarify-question">${question}</span>
                    </div>
                  `
                )}
              </div>
            `
          : ""}
        ${Array.isArray(message.candidates) && message.candidates.length > 0
          ? html`
              <div class="candidate-section">
                <p class="candidate-label">Quick replies</p>
                <div class="candidate-pills">
                  ${message.candidates.map(
                    (candidate) => html`
                      <button
                        class="candidate-pill"
                        @click=${() => this._handleClarificationCandidate(candidate)}
                        ?disabled=${this._state === STATES.LOADING || this._state === STATES.INSTALLING}
                      >
                        <span class="candidate-pill-name">
                          ${candidate.name || candidate.entity_id}
                        </span>
                        <span class="candidate-pill-id">${candidate.entity_id}</span>
                      </button>
                    `
                  )}
                </div>
              </div>
            `
          : ""}
      `;
    }

    if (message.type === "status") {
      return html`<p class="chat-text">${message.text}</p>`;
    }

    return html`<p class="chat-text">${message.text || message.summary || this._error}</p>`;
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

  _renderClarify() {
    return html`
      <div class="preview-section">
        <div class="summary-card warning-card">
          <ha-icon icon="mdi:message-question-outline" class="summary-icon"></ha-icon>
          <span class="summary-text">
            ${this._clarificationSummary || "I need a bit more detail before I can generate the automation."}
          </span>
        </div>

        ${this._clarifyingQuestions.length > 0
          ? html`
              <div class="clarify-list">
                ${this._clarifyingQuestions.map(
                  (question, index) => html`
                    <div class="clarify-item">
                      <span class="clarify-index">${index + 1}</span>
                      <span class="clarify-question">${question}</span>
                    </div>
                  `
                )}
              </div>
            `
          : ""}

        ${this._clarificationCandidates.length > 0
          ? html`
              <div class="candidate-section">
                <p class="candidate-label">Available devices</p>
                <div class="candidate-pills">
                  ${this._clarificationCandidates.map(
                    (candidate) => html`
                      <button
                        class="candidate-pill"
                        @click=${() => this._handleClarificationCandidate(candidate)}
                      >
                        <span class="candidate-pill-name">
                          ${candidate.name || candidate.entity_id}
                        </span>
                        <span class="candidate-pill-id">${candidate.entity_id}</span>
                      </button>
                    `
                  )}
                </div>
              </div>
            `
          : ""}

        <div class="input-section">
          <p class="input-label">Answer the question${this._clarifyingQuestions.length > 1 ? "s" : ""} and AutoMagic will continue.</p>
          <textarea
            class="prompt-input"
            rows="4"
            placeholder="Type your clarification here"
            .value=${this._clarificationAnswer}
            @input=${(e) => (this._clarificationAnswer = e.target.value)}
            @keydown=${(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                this._handleClarificationSubmit();
              }
            }}
          ></textarea>
          <div class="input-footer">
            <span class="hint">Press Enter to continue, Shift+Enter for new line</span>
            <div class="action-buttons">
              <button class="btn btn-secondary" @click=${this._handleReset}>
                <ha-icon icon="mdi:refresh"></ha-icon>
                Start Over
              </button>
              <button
                class="btn btn-primary"
                @click=${this._handleClarificationSubmit}
                ?disabled=${!this._clarificationAnswer.trim()}
              >
                <ha-icon icon="mdi:reply"></ha-icon>
                Continue
              </button>
            </div>
          </div>
        </div>
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

    const installedAliases = this._installedAutomationAliases();

    return html`
      <div class="history-list">
        ${this._historyError
          ? html`
              <div class="history-banner error">
                <ha-icon icon="mdi:alert-circle-outline"></ha-icon>
                <span>${this._historyError}</span>
              </div>
            `
          : ""}
        ${this._history.map(
          (item, i) => {
            const badge = this._historyStatusBadge(item, installedAliases);
            const canDelete = this._historyCanDelete(item, installedAliases);
            const isDeleting =
              this._normalizeText(this._deletingHistoryEntryId) ===
              this._normalizeText(item?.entry_id);
            return html`
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
                  <span class="badge ${badge.className}">${badge.label}</span>
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
                      ${canDelete
                        ? html`
                            <div class="history-actions">
                              <button
                                class="btn btn-secondary"
                                @click=${(e) => this._handleDeleteHistory(e, item)}
                                ?disabled=${isDeleting}
                              >
                                <ha-icon icon="mdi:delete-outline"></ha-icon>
                                ${isDeleting ? "Deleting..." : "Delete History Entry"}
                              </button>
                            </div>
                          `
                        : ""}
                    </div>
                  `
                : ""}
            </div>
          `;
          }
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

      .chat-layout {
        display: flex;
        flex-direction: column;
        gap: 16px;
      }
      .chat-toolbar {
        display: flex;
        align-items: flex-start;
        justify-content: space-between;
        flex-wrap: wrap;
        gap: 12px;
      }
      .chat-subtitle {
        margin: 0;
        color: var(--secondary-text-color);
        font-size: 0.92em;
        line-height: 1.45;
      }
      .chat-toolbar-actions {
        display: flex;
        align-items: flex-end;
        gap: 12px;
        flex-wrap: wrap;
        margin-left: auto;
      }
      .service-picker {
        display: flex;
        flex-direction: column;
        gap: 6px;
        min-width: min(100%, 280px);
      }
      .service-picker-label {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        color: var(--secondary-text-color);
        font-size: 0.76em;
        font-weight: 600;
        letter-spacing: 0.04em;
        text-transform: uppercase;
      }
      .service-picker-note {
        color: var(--secondary-text-color);
        font-size: 0.82em;
        font-weight: 500;
        letter-spacing: normal;
        text-transform: none;
      }
      .service-select {
        border: 1px solid var(--divider-color);
        border-radius: 12px;
        background: var(--card-background-color, var(--primary-background-color));
        color: var(--primary-text-color);
        min-height: 42px;
        padding: 0 14px;
        font: inherit;
      }
      .service-select:focus {
        outline: none;
        border-color: var(--primary-color);
        box-shadow: 0 0 0 1px var(--primary-color);
      }
      .service-select:disabled {
        opacity: 0.7;
        cursor: default;
      }
      .chat-toolbar-btn {
        flex-shrink: 0;
      }
      .composer-service-picker {
        width: 100%;
      }
      .chat-thread {
        display: flex;
        flex-direction: column;
        gap: 14px;
        min-height: 360px;
        max-height: 65vh;
        overflow-y: auto;
        padding-right: 4px;
      }
      .chat-row {
        display: flex;
      }
      .chat-row.user {
        justify-content: flex-end;
      }
      .chat-row.assistant {
        justify-content: flex-start;
      }
      .chat-bubble {
        max-width: min(100%, 42rem);
        border-radius: 18px;
        padding: 14px 16px;
        border: 1px solid var(--divider-color);
        background: var(--card-background-color, var(--primary-background-color));
      }
      .chat-bubble.user {
        background: var(--primary-color);
        color: var(--text-primary-color, #fff);
        border-color: transparent;
      }
      .chat-bubble.assistant {
        background: var(--primary-background-color);
      }
      .chat-bubble.error {
        border-color: rgba(244, 67, 54, 0.28);
        background: rgba(244, 67, 54, 0.08);
      }
      .chat-bubble.status {
        border-color: rgba(76, 175, 80, 0.28);
        background: rgba(76, 175, 80, 0.08);
      }
      .assistant-loading,
      .assistant-status {
        display: flex;
        align-items: flex-start;
        gap: 12px;
      }
      .chat-loading-text {
        display: flex;
        flex-direction: column;
        gap: 4px;
      }
      .chat-text {
        margin: 0;
        line-height: 1.55;
        font-size: 0.95em;
        color: inherit;
        white-space: pre-wrap;
      }
      .chat-meta {
        margin: 8px 0 0;
        font-size: 0.8em;
        line-height: 1.4;
      }
      .chat-meta.success {
        color: var(--success-color, #4caf50);
      }
      .chat-meta.error {
        color: var(--error-color, #f44336);
      }
      .chat-empty {
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 8px;
        padding: 36px 24px;
        border: 1px dashed var(--divider-color);
        border-radius: 18px;
        text-align: center;
        background: linear-gradient(
          180deg,
          rgba(33, 150, 243, 0.06),
          rgba(33, 150, 243, 0)
        );
      }
      .chat-empty-icon {
        --mdc-icon-size: 38px;
        color: var(--primary-color);
      }
      .chat-empty-title {
        margin: 0;
        font-size: 1.02em;
        font-weight: 600;
        color: var(--primary-text-color);
      }
      .chat-empty-sub {
        margin: 0;
        max-width: 32rem;
        color: var(--secondary-text-color);
        font-size: 0.9em;
        line-height: 1.5;
      }
      .chat-composer {
        display: flex;
        flex-direction: column;
        gap: 12px;
        padding-top: 4px;
      }
      .chat-input {
        min-height: 86px;
      }
      .chat-actions {
        margin-top: 14px;
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
      .warning-card {
        border-color: rgba(255, 152, 0, 0.35);
        background: rgba(255, 152, 0, 0.10);
      }
      .summary-icon {
        --mdc-icon-size: 22px;
        color: var(--success-color, #4caf50);
        flex-shrink: 0;
        margin-top: 1px;
      }
      .warning-card .summary-icon {
        color: var(--warning-color, #ff9800);
      }
      .summary-text {
        color: var(--primary-text-color);
        line-height: 1.5;
        font-size: 0.95em;
      }
      .clarify-list {
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .clarify-item {
        display: flex;
        align-items: flex-start;
        gap: 12px;
        padding: 12px 14px;
        border-radius: 12px;
        border: 1px solid var(--divider-color);
        background: var(--primary-background-color);
      }
      .clarify-index {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-width: 24px;
        height: 24px;
        border-radius: 999px;
        background: rgba(255, 152, 0, 0.16);
        color: var(--primary-text-color);
        font-size: 0.78em;
        font-weight: 700;
        flex-shrink: 0;
      }
      .clarify-question {
        color: var(--primary-text-color);
        line-height: 1.45;
        font-size: 0.92em;
      }
      .candidate-section {
        display: flex;
        flex-direction: column;
        gap: 10px;
      }
      .candidate-label {
        margin: 0;
        font-size: 0.82em;
        font-weight: 700;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: var(--secondary-text-color);
      }
      .candidate-pills {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
      }
      .candidate-pill {
        display: inline-flex;
        flex-direction: column;
        align-items: flex-start;
        gap: 2px;
        padding: 10px 14px;
        border-radius: 999px;
        border: 1px solid rgba(25, 118, 210, 0.24);
        background: rgba(25, 118, 210, 0.10);
        color: var(--primary-text-color);
        cursor: pointer;
        transition: transform 0.15s ease, border-color 0.15s ease,
          background 0.15s ease;
        font-family: inherit;
        text-align: left;
      }
      .candidate-pill:hover {
        transform: translateY(-1px);
        border-color: rgba(25, 118, 210, 0.4);
        background: rgba(25, 118, 210, 0.16);
      }
      .candidate-pill-name {
        font-size: 0.92em;
        font-weight: 600;
        line-height: 1.3;
      }
      .candidate-pill-id {
        font-size: 0.76em;
        color: var(--secondary-text-color);
        line-height: 1.2;
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
      .history-banner {
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 12px 14px;
        border-radius: 12px;
        border: 1px solid var(--divider-color);
        background: var(--card-background-color);
      }
      .history-banner.error {
        border-color: rgba(244, 67, 54, 0.3);
        background: rgba(244, 67, 54, 0.08);
        color: var(--error-color, #f44336);
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
      .badge-warning {
        background: rgba(255, 152, 0, 0.18);
        color: var(--warning-color, #ff9800);
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
      .history-actions {
        display: flex;
        justify-content: flex-end;
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
