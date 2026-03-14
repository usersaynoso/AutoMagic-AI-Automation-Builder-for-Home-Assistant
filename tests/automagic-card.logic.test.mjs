import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

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
const DIRECT_MODEL_PREFERENCES = ["qwen2.5:3b-16k"];
const DIRECT_FINAL_MODEL_PREFERENCES = ["qwen2.5:3b-16k"];
const DIRECT_PLANNER_MODEL_PREFERENCES = ["qwen2.5:0.5b-16k"];
const DIRECT_MAX_TOKENS = 2048;
const DIRECT_TEMPERATURE = 0.15;
const DIRECT_FENCE_RE = /```(?:[a-z0-9_+-]+)?\s*\n?(.*?)\n?\s*```/is;
const DIRECT_SYSTEM_PROMPT = "Test system prompt";
const DIRECT_RESOLVED_SYSTEM_PROMPT = "Test resolved system prompt";
const DIRECT_PLANNER_SYSTEM_PROMPT = "Test planner prompt";
const DIRECT_PLAN_TO_YAML_SYSTEM_PROMPT = "Test plan-to-yaml prompt";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const cardPath = path.join(
  __dirname,
  "..",
  "custom_components",
  "automagic",
  "www",
  "automagic-card.js"
);
const cardSource = fs.readFileSync(cardPath, "utf8");

function extractMethodSource(name) {
  const signatures = [`  ${name}(`, `  async ${name}(`];
  const start = signatures
    .map((signature) => cardSource.indexOf(signature))
    .find((index) => index !== -1);
  if (start === -1) {
    throw new Error(`Could not find method ${name}`);
  }

  let paramsDepth = 0;
  let braceStart = -1;
  for (let index = start; index < cardSource.length; index += 1) {
    const char = cardSource[index];
    if (char === "(") paramsDepth += 1;
    if (char === ")") paramsDepth -= 1;
    if (char === "{" && paramsDepth === 0) {
      braceStart = index;
      break;
    }
  }
  if (braceStart === -1) {
    throw new Error(`Could not locate body for method ${name}`);
  }

  let depth = 0;
  for (let index = braceStart; index < cardSource.length; index += 1) {
    const char = cardSource[index];
    if (char === "{") depth += 1;
    if (char === "}") depth -= 1;
    if (depth === 0) {
      return cardSource.slice(start, index + 1).trim();
    }
  }

  throw new Error(`Could not parse method ${name}`);
}

function buildMethod(name) {
  const methodSource = extractMethodSource(name);
  const functionSource = methodSource.startsWith("async ")
    ? methodSource.replace(/^async\s+/, "async function ")
    : `function ${methodSource}`;
  return new Function(
    "DIRECT_TOKEN_RE",
    "IMPORTANT_SHORT_TOKENS",
    "DIRECT_GROUP_MARKER_RE",
    "DIRECT_VARIANT_SUFFIX_RE",
    "DIRECT_NAME_VARIANT_SUFFIX_RE",
    "DIRECT_IGNORE_TOKENS",
    "DIRECT_AUTOMATION_MATCH_IGNORE_TOKENS",
    "DIRECT_GROUP_CLAUSE_IGNORE_TOKENS",
    "DIRECT_SEMANTIC_CONTEXT_IGNORE_TOKENS",
    "DIRECT_QUESTION_STARTERS",
    "SIMPLE_ACTION_DOMAINS",
    "DIRECT_COMPLEX_PROMPT_RE",
    "DIRECT_ENDPOINT_PORT",
    "DIRECT_MAX_TOKENS",
    "DIRECT_TEMPERATURE",
    "DIRECT_MODEL_PREFERENCES",
    "DIRECT_FINAL_MODEL_PREFERENCES",
    "DIRECT_PLANNER_MODEL_PREFERENCES",
    "DIRECT_FENCE_RE",
    "DIRECT_SYSTEM_PROMPT",
    "DIRECT_RESOLVED_SYSTEM_PROMPT",
    "DIRECT_PLANNER_SYSTEM_PROMPT",
    "DIRECT_PLAN_TO_YAML_SYSTEM_PROMPT",
    `return (${functionSource});`
  )(
    DIRECT_TOKEN_RE,
    IMPORTANT_SHORT_TOKENS,
    DIRECT_GROUP_MARKER_RE,
    DIRECT_VARIANT_SUFFIX_RE,
    DIRECT_NAME_VARIANT_SUFFIX_RE,
    DIRECT_IGNORE_TOKENS,
    DIRECT_AUTOMATION_MATCH_IGNORE_TOKENS,
    DIRECT_GROUP_CLAUSE_IGNORE_TOKENS,
    DIRECT_SEMANTIC_CONTEXT_IGNORE_TOKENS,
    DIRECT_QUESTION_STARTERS,
    SIMPLE_ACTION_DOMAINS,
    DIRECT_COMPLEX_PROMPT_RE,
    "11434",
    DIRECT_MAX_TOKENS,
    DIRECT_TEMPERATURE,
    DIRECT_MODEL_PREFERENCES,
    DIRECT_FINAL_MODEL_PREFERENCES,
    DIRECT_PLANNER_MODEL_PREFERENCES,
    DIRECT_FENCE_RE,
    DIRECT_SYSTEM_PROMPT,
    DIRECT_RESOLVED_SYSTEM_PROMPT,
    DIRECT_PLANNER_SYSTEM_PROMPT,
    DIRECT_PLAN_TO_YAML_SYSTEM_PROMPT
  );
}

function buildHarness() {
  const harness = {};
  [
    "_normalizeText",
    "_normalizePhrase",
    "_normalizeQuestions",
    "_looksLikeQuestion",
    "_unwrapSingleAutomationList",
    "_extractWrappedAutomationDocument",
    "_extractLooseYamlResponse",
    "_extractMalformedJsonYamlResponse",
    "_normalizeAutomationYamlText",
    "_extractJsonObjectText",
    "_buildAutomationContextMessage",
    "_extractTopLevelSectionBlock",
    "_extractActionBlocks",
    "_collectYamlIssues",
    "_yamlIncludesAllEntityIds",
    "_collectYamlCoverageIssues",
    "_collectRepairIssues",
    "_entitySummary",
    "_humanizeIdentifier",
    "_formatError",
    "_shouldRetryBackendStatus",
    "_serviceLabel",
    "_selectedService",
    "_isLikelyDirectFallbackHost",
    "_canUseDirectGenerationFallback",
    "_buildGenerationRequestPayload",
    "_notificationServiceEntries",
    "_collectSemanticPromptMatches",
    "_semanticEntityMatches",
    "_collectHeuristicEntities",
    "_findExplicitEntities",
    "_findEntitiesByPhrase",
    "_findObviousNamedEntities",
    "_tokenizePrompt",
    "_isComplexAutomationPrompt",
    "_shouldUsePlanner",
    "_shouldPreferResolvedFinalPass",
    "_isLikelyEntityOnlyPlanItem",
    "_isUsefulPlanningResult",
    "_shouldPreferYamlOnlyResolvedPass",
    "_shouldUseBackendGeneration",
    "_selectRelevantEntities",
    "_hasGroupIntent",
    "_variantEntityStem",
    "_expandEntityFamilies",
    "_collectSiblingGroups",
    "_buildGroupClauseMappings",
    "_extractPromptClauses",
    "_buildPromptClauseClarificationAnswer",
    "_buildAuthoritativeClarificationResolution",
    "_buildResolvedPromptForRepeat",
    "_buildResolvedFinalPrompt",
    "_clarificationKey",
    "_shouldRebuildResolvedPrompt",
    "_extractDomainPhrases",
    "_relevantDomainMatches",
    "_parseSimpleTime",
    "_extractWeekdays",
    "_extractTimeWindowGuard",
    "_hasClearSchedule",
    "_hasTimeWindowGuard",
    "_invertEntityState",
    "_buildSimpleAutomationYaml",
    "_isSpeakerLike",
    "_candidateEntitiesForTarget",
    "_parseSimpleScheduledToggleIntent",
    "_buildDeterministicResult",
    "_parseDurationPhrase",
    "_splitConditionClauses",
    "_resolveEntitiesForThresholdClause",
    "_extractThresholdSpec",
    "_extractImperativeSegments",
    "_resolveActionEntities",
    "_buildEntityTargetLines",
    "_buildServiceActionLines",
    "_reindentYamlLines",
    "_buildAutomationGuardConditionLines",
    "_extractExplicitStateGuardSpecs",
    "_buildExplicitStateGuardConditionLines",
    "_normalizeConditionalSentenceLead",
    "_buildDeterministicActionSequence",
    "_buildDeterministicComplexAutomationResult",
    "_tryDeterministicGeneration",
    "_buildEntityPool",
    "_ensureEntityPool",
    "_resolveClarificationCandidate",
    "_buildExplicitEntityAnswer",
    "_deriveClarificationCandidates",
    "_siblingGroupLabel",
    "_buildAutoClarificationAnswer",
    "_buildDirectMessages",
    "_normalizePlanItems",
    "_buildResolvedFinalMessages",
    "_buildPlanToYamlMessages",
    "_summarizeGeneratedYaml",
    "_ensureResultSummary",
    "_repairGeneratedYamlIfNeeded",
    "_parsePlanningResponse",
    "_parseDirectResponse",
    "_buildDirectEndpointCandidates",
  ].forEach((name) => {
    harness[name] = buildMethod(name);
  });
  return harness;
}

const entities = [
  {
    entity_id: "media_player.living_room",
    name: "Living Room",
    domain: "media_player",
  },
  {
    entity_id: "media_player.bedroom_2",
    name: "Bedroom (2)",
    domain: "media_player",
  },
  {
    entity_id: "media_player.living_room_speaker",
    name: "Living Room Speaker",
    domain: "media_player",
  },
  {
    entity_id: "media_player.all_speakers",
    name: "All Speakers",
    domain: "media_player",
  },
  {
    entity_id: "media_player.kitchen_homepod",
    name: "Kitchen HomePod",
    domain: "media_player",
  },
  {
    entity_id: "media_player.nestaudio3283",
    name: "NestAudio3283",
    domain: "media_player",
  },
];

const victronComplexPrompt =
  'Monitor all three AC output phases from the Victron. If any single phase voltage drops below 210 volts OR any single phase current exceeds 15 amps, AND the total AC output power is above 100 watts, AND it\'s not between 9am and 5pm on a weekday, turn the lounge lamp red at 50% brightness and flash it twice, then turn off both lounge strip lights and the bar lamp. Wait 2 minutes. If the output power is still above 100 watts, turn off the bedroom strip light and disable the battery monitor switch. Then send a notification to my iPhone saying "Warning: Victron phase imbalance detected - [whichever sensor triggered] is out of range" with the actual sensor value included in the message. If the output power has dropped below 100 watts during the 2 minute wait, instead turn the lounge lamp back to white at full brightness and do nothing else. Don\'t run any of this if the electricity balance automation is already active.';

const victronComplexEntities = [
  {
    entity_id: "sensor.victron_mk3_ac_output_voltage",
    name: "AC Output Voltage",
    domain: "sensor",
    device_class: "voltage",
  },
  {
    entity_id: "sensor.victron_mk3_ac_output_voltage_l2",
    name: "AC Output Voltage L2",
    domain: "sensor",
    device_class: "voltage",
  },
  {
    entity_id: "sensor.victron_mk3_ac_output_voltage_l3",
    name: "AC Output Voltage L3",
    domain: "sensor",
    device_class: "voltage",
  },
  {
    entity_id: "sensor.victron_mk3_ac_output_current",
    name: "AC Output Current",
    domain: "sensor",
    device_class: "current",
  },
  {
    entity_id: "sensor.victron_mk3_ac_output_current_l2",
    name: "AC Output Current L2",
    domain: "sensor",
    device_class: "current",
  },
  {
    entity_id: "sensor.victron_mk3_ac_output_current_l3",
    name: "AC Output Current L3",
    domain: "sensor",
    device_class: "current",
  },
  {
    entity_id: "sensor.victron_mk3_ac_output_power",
    name: "AC Output Power",
    domain: "sensor",
    device_class: "power",
  },
  {
    entity_id: "light.lounge_lamp",
    name: "Lounge Lamp",
    domain: "light",
  },
  {
    entity_id: "light.lounge_strip_lights_left",
    name: "Lounge Strip Lights Left",
    domain: "light",
  },
  {
    entity_id: "light.lounge_strip_lights_right",
    name: "Lounge Strip Lights Right",
    domain: "light",
  },
  {
    entity_id: "light.bar_lamp",
    name: "Bar Lamp",
    domain: "light",
  },
  {
    entity_id: "light.bedroom_strip_light_left",
    name: "Bedroom Strip Light Left",
    domain: "light",
  },
  {
    entity_id: "switch.victron_mk3_battery_monitor",
    name: "Battery Monitor",
    domain: "switch",
  },
  {
    entity_id: "notify.mobile_app_iphone_13",
    name: "Notify Iphone 13",
    domain: "notify",
  },
  {
    entity_id: "automation.electricity_balance_above_ps1",
    name: "Electricity balance ABOVE £1",
    domain: "automation",
  },
  {
    entity_id: "automation.electricity_balance_low",
    name: "Electricity balance low",
    domain: "automation",
  },
];

const lowPowerLightsPrompt =
  'When the AC output power from the Victron drops below 200 watts and it\'s between 11pm and 6am, turn off the lounge lamp and both lounge strip lights immediately, then wait 5 minutes and if the AC output power is still below 200 watts, also turn off the bar lamp and send a notification to my iPhone saying "Shore power is critically low - lights turned off automatically". But don\'t run this if the electricity supply switch for The Architeuthis (3378) is already off.';

const lowPowerLightsEntities = [
  {
    entity_id: "sensor.victron_mk3_ac_output_power",
    name: "AC Output Power",
    domain: "sensor",
    device_class: "power",
  },
  {
    entity_id: "light.lounge_lamp",
    name: "Lounge Lamp",
    domain: "light",
  },
  {
    entity_id: "light.lounge_strip_lights_left",
    name: "Lounge Strip Lights Left",
    domain: "light",
  },
  {
    entity_id: "light.lounge_strip_lights_right",
    name: "Lounge Strip Lights Right",
    domain: "light",
  },
  {
    entity_id: "light.bar_lamp",
    name: "Bar Lamp",
    domain: "light",
  },
  {
    entity_id: "notify.mobile_app_iphone_13",
    name: "Notify Iphone 13",
    domain: "notify",
  },
  {
    entity_id: "switch.meter_macs_the_architeuthis_electricity_supply_switch",
    name: "The Architeuthis (3378) Electricity Supply Switch",
    domain: "switch",
  },
];

test("TV prompt yields local clarification candidates without speaker devices", () => {
  const harness = buildHarness();
  const result = harness._tryDeterministicGeneration.call(
    harness,
    "turn the tv on at 10 every day",
    entities
  );

  assert.equal(result?.needs_clarification, true);
  assert.deepEqual(
    result.candidates.map((candidate) => candidate.entity_id),
    ["media_player.living_room", "media_player.bedroom_2"]
  );
  assert.equal(
    result.clarifying_questions[0],
    "Which tv should I use for this automation?"
  );
});

test("Clarification answer resolves to the matching TV entity", () => {
  const harness = buildHarness();
  const candidates = harness._candidateEntitiesForTarget.call(
    harness,
    "tv",
    entities
  );

  const result = harness._resolveClarificationCandidate.call(
    harness,
    "living room tv",
    candidates
  );

  assert.equal(result?.entity_id, "media_player.living_room");
});

test("Clarification candidates are rebuilt from explicitly listed entity ids", () => {
  const harness = buildHarness();
  const result = harness._deriveClarificationCandidates.call(
    harness,
    victronComplexPrompt,
    {
      summary:
        "AC Output Voltage entities are sensor.victron_mk3_ac_output_voltage_l2, sensor.victron_mk3_ac_output_voltage_l3, and sensor.victron_mk3_ac_output_voltage. The automation YAML is missing these details.",
      clarifying_questions: [
        "Which single entity should I use for AC Output Voltage? (sensor.victron_mk3_ac_output_voltage_l2, sensor.victron_mk3_ac_output_voltage_l3, or sensor.victron_mk3_ac_output_voltage)",
      ],
    },
    victronComplexEntities
  );

  assert.deepEqual(
    result.map((candidate) => candidate.entity_id),
    [
      "sensor.victron_mk3_ac_output_voltage",
      "sensor.victron_mk3_ac_output_voltage_l2",
      "sensor.victron_mk3_ac_output_voltage_l3",
    ]
  );
});

test("Entity pool is fetched and augmented when backend clarification arrives first", async () => {
  const harness = buildHarness();
  harness._lastEntityPool = [];
  harness._requestEntities = async () => ({
    entities: victronComplexEntities.filter(
      (entity) => entity.domain !== "notify"
    ),
  });
  harness.hass = {
    services: {
      notify: {
        mobile_app_iphone_13: {},
      },
    },
  };

  const entityPool = await harness._ensureEntityPool.call(harness);
  const entityIds = entityPool.map((entity) => entity.entity_id);

  assert.ok(entityIds.includes("sensor.victron_mk3_ac_output_voltage"));
  assert.ok(entityIds.includes("notify.mobile_app_iphone_13"));
  assert.equal(
    entityIds.filter((entityId) => entityId === "notify.mobile_app_iphone_13").length,
    1
  );
});

test("Selected TV produces deterministic automation YAML", () => {
  const harness = buildHarness();
  const intent = harness._parseSimpleScheduledToggleIntent.call(
    harness,
    "turn the tv on at 10 every day"
  );
  const livingRoom = entities[0];
  const result = harness._buildDeterministicResult.call(
    harness,
    intent,
    livingRoom
  );

  assert.match(result.yaml, /action: media_player\.turn_on/);
  assert.match(result.yaml, /entity_id: media_player\.living_room/);
  assert.match(result.yaml, /at: "10:00:00"/);
  assert.match(result.summary, /Turns on Living Room every day at 10:00\./);
});

test("Explicit entity follow-up uses the resolved entity id", () => {
  const harness = buildHarness();
  const answer = harness._buildExplicitEntityAnswer.call(harness, entities[0]);

  assert.match(answer, /media_player\.living_room/);
  assert.match(answer, /Living Room/);
  assert.match(answer, /Do not ask again which entity to use/);
});

test("Useful short tokens remain searchable for prompt ranking", () => {
  const harness = buildHarness();
  const tokens = harness._tokenizePrompt.call(
    harness,
    "Monitor AC output and TV status"
  );

  assert.ok(tokens.includes("ac"));
  assert.ok(tokens.includes("tv"));
});

test("Notification services are exposed as AI-selectable prompt entries", () => {
  const harness = buildHarness();
  harness.hass = {
    services: {
      notify: {
        mobile_app_iphone_13: {},
        notify: {},
      },
    },
  };

  const result = harness._notificationServiceEntries.call(harness);

  assert.deepEqual(
    result.map((entry) => entry.entity_id),
    ["notify.mobile_app_iphone_13", "notify.notify"]
  );
  assert.equal(result[0].name, "Notify Iphone 13");
  assert.equal(result[0].state, "service");
});

test("Heuristic entity collection keeps Victron outputs and notify targets in scope", () => {
  const harness = buildHarness();
  const prompt =
    "Monitor the Victron output phases and send a notification to my iPhone";
  const candidates = [
    {
      entity_id: "sensor.victron_mk3_ac_output_voltage",
      name: "AC Output Voltage",
      domain: "sensor",
    },
    {
      entity_id: "sensor.victron_mk3_ac_output_current",
      name: "AC Output Current",
      domain: "sensor",
    },
    {
      entity_id: "sensor.victron_mk3_ac_output_voltage_l2",
      name: "AC Output Voltage L2",
      domain: "sensor",
    },
    {
      entity_id: "sensor.victron_mk3_ac_output_current_l2",
      name: "AC Output Current L2",
      domain: "sensor",
    },
    {
      entity_id: "sensor.victron_mk3_ac_output_voltage_l3",
      name: "AC Output Voltage L3",
      domain: "sensor",
    },
    {
      entity_id: "sensor.victron_mk3_ac_output_current_l3",
      name: "AC Output Current L3",
      domain: "sensor",
    },
    {
      entity_id: "notify.mobile_app_iphone_13",
      name: "Notify Iphone 13",
      domain: "notify",
    },
    {
      entity_id: "light.lounge_lamp",
      name: "Lounge Lamp",
      domain: "light",
    },
  ];

  const result = harness._collectHeuristicEntities.call(
    harness,
    prompt,
    candidates
  );

  const entityIds = result.map((entry) => entry.entity_id);
  assert.ok(entityIds.includes("sensor.victron_mk3_ac_output_voltage"));
  assert.ok(entityIds.includes("sensor.victron_mk3_ac_output_current"));
  assert.ok(entityIds.includes("sensor.victron_mk3_ac_output_voltage_l2"));
  assert.ok(entityIds.includes("sensor.victron_mk3_ac_output_current_l2"));
  assert.ok(entityIds.includes("sensor.victron_mk3_ac_output_voltage_l3"));
  assert.ok(entityIds.includes("sensor.victron_mk3_ac_output_current_l3"));
  assert.ok(entityIds.includes("notify.mobile_app_iphone_13"));
});

test("Semantic prompt matching keeps power, voltage, current, and notify families in scope", () => {
  const harness = buildHarness();
  const prompt =
    "If any AC output voltage drops below 210 volts or any AC output current exceeds 15 amps, notify my iPhone if AC output power stays above 100 watts";
  const candidates = [
    {
      entity_id: "sensor.victron_mk3_ac_output_voltage",
      name: "AC Output Voltage",
      domain: "sensor",
      device_class: "voltage",
    },
    {
      entity_id: "sensor.victron_mk3_ac_output_voltage_l2",
      name: "AC Output Voltage L2",
      domain: "sensor",
      device_class: "voltage",
    },
    {
      entity_id: "sensor.victron_mk3_ac_output_current",
      name: "AC Output Current",
      domain: "sensor",
      device_class: "current",
    },
    {
      entity_id: "sensor.victron_mk3_ac_output_current_l2",
      name: "AC Output Current L2",
      domain: "sensor",
      device_class: "current",
    },
    {
      entity_id: "sensor.victron_mk3_ac_output_power",
      name: "AC Output Power",
      domain: "sensor",
      device_class: "power",
    },
    {
      entity_id: "notify.mobile_app_iphone_13",
      name: "Notify Iphone 13",
      domain: "notify",
      device_class: "service",
    },
  ];

  const matches = harness._collectSemanticPromptMatches.call(
    harness,
    prompt,
    candidates
  );
  const flattened = harness._semanticEntityMatches.call(
    harness,
    prompt,
    candidates
  );
  const ids = flattened.map((entry) => entry.entity_id);

  assert.ok(matches.some((match) => match.label === "voltage"));
  assert.ok(matches.some((match) => match.label === "current"));
  assert.ok(matches.some((match) => match.label === "power"));
  assert.ok(matches.some((match) => match.label === "notification"));
  assert.ok(ids.includes("sensor.victron_mk3_ac_output_voltage"));
  assert.ok(ids.includes("sensor.victron_mk3_ac_output_current"));
  assert.ok(ids.includes("sensor.victron_mk3_ac_output_power"));
  assert.ok(ids.includes("notify.mobile_app_iphone_13"));
});

test("Semantic prompt matching prefers scope-specific output entities over nearby input or battery sensors", () => {
  const harness = buildHarness();
  const prompt =
    "Alert me if any Victron AC output voltage drops below 210 volts or AC output power stays above 100 watts";
  const candidates = [
    {
      entity_id: "sensor.victron_mk3_ac_output_voltage",
      name: "AC Output Voltage",
      domain: "sensor",
      device_class: "voltage",
    },
    {
      entity_id: "sensor.victron_mk3_ac_input_voltage",
      name: "AC Input Voltage",
      domain: "sensor",
      device_class: "voltage",
    },
    {
      entity_id: "sensor.victron_mk3_battery_voltage",
      name: "Battery Voltage",
      domain: "sensor",
      device_class: "voltage",
    },
    {
      entity_id: "sensor.victron_mk3_ac_output_power",
      name: "AC Output Power",
      domain: "sensor",
      device_class: "power",
    },
    {
      entity_id: "sensor.victron_mk3_ac_input_power",
      name: "AC Input Power",
      domain: "sensor",
      device_class: "power",
    },
    {
      entity_id: "sensor.victron_mk3_battery_power",
      name: "Battery Power",
      domain: "sensor",
      device_class: "power",
    },
  ];

  const matches = harness._collectSemanticPromptMatches.call(
    harness,
    prompt,
    candidates
  );
  const voltageMatch = matches.find((match) => match.label === "voltage");
  const powerMatch = matches.find((match) => match.label === "power");

  assert.deepEqual(
    voltageMatch?.entities.map((entry) => entry.entity_id),
    ["sensor.victron_mk3_ac_output_voltage"]
  );
  assert.deepEqual(
    powerMatch?.entities.map((entry) => entry.entity_id),
    ["sensor.victron_mk3_ac_output_power"]
  );
});

test("Obvious entity matching ignores generic single-word names inside longer phrases", () => {
  const harness = buildHarness();
  const result = harness._findObviousNamedEntities.call(
    harness,
    "Disable the battery monitor switch",
    [
      {
        entity_id: "switch.victron_mk3_battery_monitor",
        name: "Battery Monitor",
        domain: "switch",
      },
      {
        entity_id: "sensor.random_battery",
        name: "Battery",
        domain: "sensor",
      },
      {
        entity_id: "switch.finger_robot_switch",
        name: "Switch",
        domain: "switch",
      },
    ]
  );

  assert.deepEqual(
    result.map((entry) => entry.entity_id),
    ["switch.victron_mk3_battery_monitor"]
  );
});

test("Obvious entity matching treats sibling variants as matches when the prompt uses the base name", () => {
  const harness = buildHarness();
  const result = harness._findObviousNamedEntities.call(
    harness,
    "Turn off both lounge strip lights and the bedroom strip light.",
    [
      {
        entity_id: "light.lounge_strip_lights_left",
        name: "Lounge Strip Lights Left",
        domain: "light",
      },
      {
        entity_id: "light.lounge_strip_lights_right",
        name: "Lounge Strip Lights Right",
        domain: "light",
      },
      {
        entity_id: "light.bedroom_strip_light_left",
        name: "Bedroom Strip Light Left",
        domain: "light",
      },
    ]
  );

  assert.ok(
    result.some((entry) => entry.entity_id === "light.lounge_strip_lights_left")
  );
  assert.ok(
    result.some((entry) => entry.entity_id === "light.lounge_strip_lights_right")
  );
  assert.ok(
    result.some((entry) => entry.entity_id === "light.bedroom_strip_light_left")
  );
});

test("Sibling groups are surfaced for grouped prompts", () => {
  const harness = buildHarness();
  const groups = harness._collectSiblingGroups.call(
    harness,
    "Monitor all three AC output phases",
    [
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage",
        name: "AC Output Voltage",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l2",
        name: "AC Output Voltage L2",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l3",
        name: "AC Output Voltage L3",
        domain: "sensor",
      },
      {
        entity_id: "notify.mobile_app_iphone_13",
        name: "Notify Iphone 13",
        domain: "notify",
      },
    ]
  );

  assert.deepEqual(
    groups.map((group) => group.map((entry) => entry.entity_id)),
    [[
      "sensor.victron_mk3_ac_output_voltage",
      "sensor.victron_mk3_ac_output_voltage_l2",
      "sensor.victron_mk3_ac_output_voltage_l3",
    ]]
  );
});

test("Grouped sensor clarifications can be auto-resolved back into the AI thread", () => {
  const harness = buildHarness();
  const answer = harness._buildAutoClarificationAnswer.call(
    harness,
    "Monitor all three AC output phases from the Victron and alert if any phase is out of range unless the electricity balance automation is already active",
    {
      summary: "The YAML cannot be generated due to missing details about which specific sensors to monitor for phase imbalance.",
      clarifying_questions: [
        "Which sensor should I use for monitoring AC Output Current? (sensor.victron_mk3_ac_output_current, sensor.victron_mk3_ac_output_current_l2, or sensor.victron_mk3_ac_output_current_l3)",
      ],
    },
    [
      {
        entity_id: "sensor.victron_mk3_ac_output_current",
        name: "AC Output Current",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_current_l2",
        name: "AC Output Current L2",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_current_l3",
        name: "AC Output Current L3",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_power",
        name: "AC Output Power",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage",
        name: "AC Output Voltage",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l2",
        name: "AC Output Voltage L2",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l3",
        name: "AC Output Voltage L3",
        domain: "sensor",
      },
      {
        entity_id: "automation.electricity_balance_above_ps1",
        name: "Electricity balance ABOVE £1",
        domain: "automation",
      },
      {
        entity_id: "automation.electricity_balance_low",
        name: "Electricity balance low",
        domain: "automation",
      },
    ]
  );

  assert.match(answer, /Use all matching entities in these sibling sets together/);
  assert.match(answer, /sensor\.victron_mk3_ac_output_current_l2/);
  assert.doesNotMatch(answer, /sensor\.victron_mk3_ac_output_voltage_l2/);
  assert.match(answer, /Do not ask which single entity to use/);
});

test("Grouped sensor clause mappings stay tied to their own threshold clauses", () => {
  const harness = buildHarness();
  const mappings = harness._buildGroupClauseMappings.call(
    harness,
    "If any single phase voltage drops below 210 volts or any single phase current exceeds 15 amps, alert me.",
    [
      [
        {
          entity_id: "sensor.victron_mk3_ac_output_voltage",
          name: "AC Output Voltage",
          domain: "sensor",
        },
        {
          entity_id: "sensor.victron_mk3_ac_output_voltage_l2",
          name: "AC Output Voltage L2",
          domain: "sensor",
        },
      ],
      [
        {
          entity_id: "sensor.victron_mk3_ac_output_current",
          name: "AC Output Current",
          domain: "sensor",
        },
        {
          entity_id: "sensor.victron_mk3_ac_output_current_l2",
          name: "AC Output Current L2",
          domain: "sensor",
        },
      ],
    ]
  );

  assert.equal(mappings.length, 2);
  assert.equal(mappings[0].label, "AC Output Voltage");
  assert.match(mappings[0].clause, /voltage drops below 210 volts/);
  assert.equal(mappings[1].label, "AC Output Current");
  assert.match(mappings[1].clause, /current exceeds 15 amps/);
});

test("Grouped sensor clause mappings ignore unrelated sibling groups that only share partial words", () => {
  const harness = buildHarness();
  const mappings = harness._buildGroupClauseMappings.call(
    harness,
    "Monitor all three AC output phases from the Victron and send a warning to my iPhone if any single phase voltage drops below 210 volts while turning off the bedroom strip light.",
    [
      [
        {
          entity_id: "sensor.victron_mk3_ac_output_voltage",
          name: "AC Output Voltage",
          domain: "sensor",
        },
        {
          entity_id: "sensor.victron_mk3_ac_output_voltage_l2",
          name: "AC Output Voltage L2",
          domain: "sensor",
        },
      ],
      [
        {
          entity_id: "sensor.main_router_wan_ip",
          name: "WAN IP",
          domain: "sensor",
        },
        {
          entity_id: "sensor.main_router_wan_ip_2",
          name: "WAN IP 2",
          domain: "sensor",
        },
      ],
      [
        {
          entity_id: "media_player.bedroom_speaker",
          name: "Bedroom speaker",
          domain: "media_player",
        },
        {
          entity_id: "media_player.bedroom_speaker_2",
          name: "Bedroom speaker 2",
          domain: "media_player",
        },
      ],
    ]
  );

  assert.deepEqual(
    mappings.map((mapping) => mapping.label),
    ["AC Output Voltage"]
  );
});

test("Specific grouped sensor clarifications answer only the named family", () => {
  const harness = buildHarness();
  const answer = harness._buildAutoClarificationAnswer.call(
    harness,
    "If any single phase voltage drops below 210 volts or any single phase current exceeds 15 amps, alert me.",
    {
      summary: "Clarification needed for specific sensors to monitor AC Output Voltage.",
      clarifying_questions: [
        "Which sensor should I use for AC Output Voltage? (sensor.victron_mk3_ac_output_voltage, sensor.victron_mk3_ac_output_voltage_l2, or sensor.victron_mk3_ac_output_voltage_l3)?",
      ],
    },
    [
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage",
        name: "AC Output Voltage",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l2",
        name: "AC Output Voltage L2",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l3",
        name: "AC Output Voltage L3",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_current",
        name: "AC Output Current",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_current_l2",
        name: "AC Output Current L2",
        domain: "sensor",
      },
    ]
  );

  assert.match(answer, /AC Output Voltage -> sensor\.victron_mk3_ac_output_voltage/);
  assert.doesNotMatch(answer, /AC Output Current -> sensor\.victron_mk3_ac_output_current/);
  assert.match(answer, /voltage drops below 210 volts/);
});

test("Automation guard clarifications are auto-answered even when sibling sensor groups exist", () => {
  const harness = buildHarness();
  const answer = harness._buildAutoClarificationAnswer.call(
    harness,
    "Monitor all three AC output phases from the Victron and don't run any of this if the electricity balance automation is already active.",
    {
      summary:
        "The provided request cannot be fully satisfied without clarification.",
      clarifying_questions: [
        "Is it necessary for the automation to run if the 'electricity_balance_above_ps1' automation is already active? If not, should this condition be removed?",
      ],
    },
    [
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage",
        name: "AC Output Voltage",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l2",
        name: "AC Output Voltage L2",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l3",
        name: "AC Output Voltage L3",
        domain: "sensor",
      },
      {
        entity_id: "automation.electricity_balance_above_ps1",
        name: "Electricity balance ABOVE £1",
        domain: "automation",
      },
      {
        entity_id: "automation.electricity_balance_low",
        name: "Electricity balance low",
        domain: "automation",
      },
    ]
  );

  assert.match(answer, /Use these matching automation guard entities together/);
  assert.match(answer, /automation\.electricity_balance_above_ps1/);
  assert.match(answer, /don't run any of this if the electricity balance automation is already active/i);
});

test("Phase-family and boolean-logic clarifications are answered directly from the original prompt", () => {
  const harness = buildHarness();
  const answer = harness._buildAutoClarificationAnswer.call(
    harness,
    "Monitor all three AC output phases from the Victron. If any single phase voltage drops below 210 volts OR any single phase current exceeds 15 amps, AND the total AC output power is above 100 watts, AND it's not between 9am and 5pm on a weekday, alert me.",
    {
      summary:
        "The request may need clarification around phase coverage and condition grouping.",
      clarifying_questions: [
        "Is it necessary to include all three AC output phases in the voltage and current checks, or should only one entity be used?",
        "Should the voltage/current thresholds and total power threshold be combined into one condition or kept separate?",
      ],
    },
    [
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage",
        name: "AC Output Voltage",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l2",
        name: "AC Output Voltage L2",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l3",
        name: "AC Output Voltage L3",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_current",
        name: "AC Output Current",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_current_l2",
        name: "AC Output Current L2",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_current_l3",
        name: "AC Output Current L3",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_power",
        name: "AC Output Power",
        domain: "sensor",
      },
    ]
  );

  assert.match(answer, /use the full resolved sibling family, not a single entity/i);
  assert.match(answer, /keep distinct threshold checks or guard clauses separate/i);
  assert.match(answer, /voltage drops below 210 volts/i);
  assert.match(answer, /total AC output power is above 100 watts/i);
});

test("Authoritative clarification resolution restates grouped mappings and notify targets", () => {
  const harness = buildHarness();
  const answer = harness._buildAuthoritativeClarificationResolution.call(
    harness,
    "Monitor all three AC output phases and notify my iPhone if any single phase voltage drops below 210 volts or any single phase current exceeds 15 amps while the electricity balance automation is active.",
    [
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage",
        name: "AC Output Voltage",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l2",
        name: "AC Output Voltage L2",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l3",
        name: "AC Output Voltage L3",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_current",
        name: "AC Output Current",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_current_l2",
        name: "AC Output Current L2",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_current_l3",
        name: "AC Output Current L3",
        domain: "sensor",
      },
      {
        entity_id: "notify.mobile_app_iphone_13",
        name: "Notify Iphone 13",
        domain: "notify",
      },
      {
        entity_id: "automation.electricity_balance_above_ps1",
        name: "Electricity balance ABOVE PS1",
        domain: "automation",
      },
    ]
  );

  assert.match(answer, /Authoritative grouped mappings:/);
  assert.match(answer, /AC Output Voltage = sensor\.victron_mk3_ac_output_voltage/);
  assert.match(answer, /Authoritative notification target: notify\.mobile_app_iphone_13/);
  assert.match(answer, /Authoritative automation guards: automation\.electricity_balance_above_ps1/);
});

test("Repeated clarification prompt rebuild inlines the resolved mappings back into the request", () => {
  const harness = buildHarness();
  const rebuilt = harness._buildResolvedPromptForRepeat.call(
    harness,
    "Monitor all three AC output phases and notify my iPhone if any single phase voltage drops below 210 volts.",
    {
      summary: "Missing voltage sensor details.",
      clarifying_questions: [
        "Which sensor(s) should I use for monitoring AC output phases?",
      ],
    },
    [
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage",
        name: "AC Output Voltage",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l2",
        name: "AC Output Voltage L2",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l3",
        name: "AC Output Voltage L3",
        domain: "sensor",
      },
      {
        entity_id: "notify.mobile_app_iphone_13",
        name: "Notify Iphone 13",
        domain: "notify",
      },
    ]
  );

  assert.match(rebuilt, /Monitor all three AC output phases/);
  assert.match(rebuilt, /Authoritative grouped mappings:/);
  assert.match(rebuilt, /notify\.mobile_app_iphone_13/);
  assert.match(rebuilt, /Do not ask again which sensor or notification target to use/);
});

test("Guard windows are not mistaken for trigger schedules", () => {
  const harness = buildHarness();

  assert.equal(
    harness._hasClearSchedule.call(
      harness,
      "Alert me if output power is above 100 watts and it's not between 9am and 5pm on a weekday"
    ),
    false
  );
  assert.equal(
    harness._hasTimeWindowGuard.call(
      harness,
      "Alert me if output power is above 100 watts and it's not between 9am and 5pm on a weekday"
    ),
    true
  );
  assert.equal(
    harness._hasClearSchedule.call(
      harness,
      "Turn on the lounge lamp at 10pm every day"
    ),
    true
  );
});

test("Planner stays enabled for both medium and long complex prompts within the supported window", () => {
  const harness = buildHarness();

  assert.equal(
    harness._shouldUsePlanner.call(
      harness,
      "Monitor all three AC output phases from the Victron. If any single phase voltage drops below 210 volts OR any single phase current exceeds 15 amps, AND the total AC output power is above 100 watts, AND it's not between 9am and 5pm on a weekday, turn the lounge lamp red at 50% brightness and flash it twice, then turn off both lounge strip lights and the bar lamp. Wait 2 minutes. If the output power is still above 100 watts, turn off the bedroom strip light and disable the battery monitor switch."
    ),
    true
  );
  assert.equal(
    harness._shouldUsePlanner.call(
      harness,
      "If the TV turns on after sunset, notify me."
    ),
    true
  );
});

test("Weak planner output that mostly echoes entity ids is ignored for resolved final generation", () => {
  const harness = buildHarness();
  const prompt =
    "Monitor all three AC output phases from the Victron. If any single phase voltage drops below 210 volts OR any single phase current exceeds 15 amps, AND the total AC output power is above 100 watts, AND it's not between 9am and 5pm on a weekday, turn the lounge lamp red at 50% brightness and flash it twice, then turn off both lounge strip lights and the bar lamp. Wait 2 minutes. If the output power is still above 100 watts, turn off the bedroom strip light and disable the battery monitor switch. Then send a notification to my iPhone with the triggering sensor and value.";

  assert.equal(
    harness._isUsefulPlanningResult.call(
      harness,
      {
        resolved_request:
          "Monitor all three AC output phases from the Victron and turn the lounge lamp red.",
        resolved_requirements: [
          "sensor.victron_mk3_ac_output_power",
          "light.lounge_lamp",
          "switch.victron_mk3_battery_monitor",
        ],
        resolved_entities: [
          "sensor.victron_mk3_ac_output_power",
          "light.lounge_lamp",
        ],
      },
      prompt
    ),
    false
  );
});

test("Rich planner output that preserves steps and branching remains usable", () => {
  const harness = buildHarness();
  const prompt =
    "Monitor all three AC output phases from the Victron. If any single phase voltage drops below 210 volts OR any single phase current exceeds 15 amps, AND the total AC output power is above 100 watts, AND it's not between 9am and 5pm on a weekday, turn the lounge lamp red at 50% brightness and flash it twice, then turn off both lounge strip lights and the bar lamp. Wait 2 minutes. If the output power is still above 100 watts, turn off the bedroom strip light and disable the battery monitor switch. Then send a notification to my iPhone with the triggering sensor and value.";

  assert.equal(
    harness._isUsefulPlanningResult.call(
      harness,
      {
        resolved_request:
          "Monitor the Victron AC output voltage and current phase families, guard on total output power above 100 watts, skip weekdays between 9am and 5pm, then run the warning and delayed follow-up branches.",
        resolved_requirements: [
          "Trigger when any AC output voltage phase drops below 210 volts or any AC output current phase exceeds 15 amps.",
          "Only continue while AC output power stays above 100 watts and none of the matching electricity balance automations are already active.",
          "After a 2 minute delay, branch on the current power reading and include the triggering sensor label and value in the iPhone notification.",
        ],
        resolved_entities: [
          "AC Output Voltage phases -> sensor.victron_mk3_ac_output_voltage, sensor.victron_mk3_ac_output_voltage_l2, sensor.victron_mk3_ac_output_voltage_l3",
          "AC Output Current phases -> sensor.victron_mk3_ac_output_current, sensor.victron_mk3_ac_output_current_l2, sensor.victron_mk3_ac_output_current_l3",
        ],
      },
      prompt
    ),
    true
  );
});

test("Very long grouped prompts prefer the resolved final pass even when planner is skipped", () => {
  const harness = buildHarness();

  assert.equal(
    harness._shouldPreferResolvedFinalPass.call(
      harness,
      "Monitor all three AC output phases from the Victron. If any single phase voltage drops below 210 volts OR any single phase current exceeds 15 amps, AND the total AC output power is above 100 watts, AND it's not between 9am and 5pm on a weekday, turn the lounge lamp red at 50% brightness and flash it twice, then turn off both lounge strip lights and the bar lamp. Wait 2 minutes. If the output power is still above 100 watts, turn off the bedroom strip light and disable the battery monitor switch. Then send a notification to my iPhone with the triggering sensor and value."
    ),
    true
  );
  assert.equal(
    harness._shouldPreferResolvedFinalPass.call(
      harness,
      "If the TV turns on after sunset, notify me."
    ),
    false
  );
});

test("Very long multi-branch prompts prefer the YAML-only resolved pass when planner output is weak", () => {
  const harness = buildHarness();
  const prompt =
    "Monitor all three AC output phases from the Victron. If any single phase voltage drops below 210 volts OR any single phase current exceeds 15 amps, AND the total AC output power is above 100 watts, AND it's not between 9am and 5pm on a weekday, turn the lounge lamp red at 50% brightness and flash it twice, then turn off both lounge strip lights and the bar lamp. Wait 2 minutes. If the output power is still above 100 watts, turn off the bedroom strip light and disable the battery monitor switch. Then send a notification to my iPhone with the triggering sensor and value.";

  assert.equal(
    harness._shouldPreferYamlOnlyResolvedPass.call(
      harness,
      prompt,
      {
        resolved_request:
          "Monitor all three AC output phases from the Victron and turn the lounge lamp red.",
        resolved_requirements: [
          "sensor.victron_mk3_ac_output_power",
          "light.lounge_lamp",
        ],
        resolved_entities: ["sensor.victron_mk3_ac_output_power"],
      }
    ),
    true
  );
});

test("Repeated auto-answered clarifications trigger a rebuilt resolved prompt", () => {
  const harness = buildHarness();

  assert.equal(
    harness._shouldRebuildResolvedPrompt.call(
      harness,
      [
        {
          role: "assistant",
          content:
            "Missing clarification on which specific sensors to use for AC Output Voltage monitoring.\nWhich sensor should I use for AC Output Voltage? (sensor.victron_mk3_ac_output_voltage_l2, sensor.victron_mk3_ac_output_voltage_l3, or sensor.victron_mk3_ac_output_voltage)",
        },
        {
          role: "user",
          content:
            "Use all matching entities in these sibling sets together, not a single entity: AC Output Voltage -> sensor.victron_mk3_ac_output_voltage, sensor.victron_mk3_ac_output_voltage_l2, sensor.victron_mk3_ac_output_voltage_l3.",
        },
      ],
      "Missing clarification on which specific sensors to use for AC Output Voltage monitoring.\nWhich sensor should I use for AC Output Voltage? (sensor.victron_mk3_ac_output_voltage_l2, sensor.victron_mk3_ac_output_voltage_l3, or sensor.victron_mk3_ac_output_voltage)",
      "Use all matching entities in these sibling sets together, not a single entity: AC Output Voltage -> sensor.victron_mk3_ac_output_voltage, sensor.victron_mk3_ac_output_voltage_l2, sensor.victron_mk3_ac_output_voltage_l3."
    ),
    true
  );
});

test("Repeated clarification questions trigger a rebuild even when the summary wording changes", () => {
  const harness = buildHarness();

  assert.equal(
    harness._shouldRebuildResolvedPrompt.call(
      harness,
      [
        {
          role: "assistant",
          content:
            "The provided entities are sufficient, but clarification is needed.\nWhich single phase voltage sensor should be monitored: sensor.victron_mk3_ac_output_voltage_l2 or sensor.victron_mk3_ac_output_voltage_l3?",
        },
        {
          role: "user",
          content:
            "Use all matching entities in these sibling sets together, not a single entity: AC Output Voltage -> sensor.victron_mk3_ac_output_voltage, sensor.victron_mk3_ac_output_voltage_l2, sensor.victron_mk3_ac_output_voltage_l3.",
        },
      ],
      "Clarifying questions needed regarding which specific sensors to monitor.\nWhich single phase voltage sensor should be monitored: sensor.victron_mk3_ac_output_voltage_l2 or sensor.victron_mk3_ac_output_voltage_l3?",
      "Use all matching entities in these sibling sets together, not a single entity: AC Output Voltage -> sensor.victron_mk3_ac_output_voltage, sensor.victron_mk3_ac_output_voltage_l2, sensor.victron_mk3_ac_output_voltage_l3."
    ),
    true
  );
});

test("Object-style planner items are normalized into guidance strings", () => {
  const harness = buildHarness();
  const items = harness._normalizePlanItems.call(harness, [
    {
      entity_id: "sensor.victron_mk3_ac_output_power",
      threshold: "100 watts",
      state: "unknown",
    },
    {
      entity_id: "sensor.victron_mk3_ac_output_voltage_l2",
      threshold: "210 volts",
      state: "low",
    },
  ]);

  assert.deepEqual(items, [
    "sensor.victron_mk3_ac_output_power threshold 100 watts",
    "sensor.victron_mk3_ac_output_voltage_l2 threshold 210 volts state low",
  ]);
});

test("Resolved final messages keep the original request and authoritative prompt together", () => {
  const harness = buildHarness();
  const messages = harness._buildResolvedFinalMessages.call(
    harness,
    "Monitor all three AC output phases from the Victron.",
    "Authoritative grouped mappings: AC Output Voltage = sensor.victron_mk3_ac_output_voltage, sensor.victron_mk3_ac_output_voltage_l2, sensor.victron_mk3_ac_output_voltage_l3.",
    [
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage",
        name: "AC Output Voltage",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l2",
        name: "AC Output Voltage L2",
        domain: "sensor",
      },
    ]
  );

  assert.equal(messages[0].content, DIRECT_RESOLVED_SYSTEM_PROMPT);
  assert.match(messages[1].content, /Available entities:/);
  assert.match(messages[1].content, /Authoritative grouped mappings:/);
  assert.match(messages[1].content, /Return the complete automation JSON now/);
  assert.doesNotMatch(messages[1].content, /Original user request:/);
});

test("Structured resolved final prompt separates grouped families, exact matches, guards, and notify target", () => {
  const harness = buildHarness();
  const prompt =
    "Monitor all three AC output phases from the Victron and notify my iPhone if any single phase voltage drops below 210 volts or any single phase current exceeds 15 amps while turning off both lounge strip lights and the bar lamp unless the electricity balance automation is active.";
  const resolvedPrompt = harness._buildResolvedFinalPrompt.call(
    harness,
    prompt,
    [
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage",
        name: "AC Output Voltage",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l2",
        name: "AC Output Voltage L2",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l3",
        name: "AC Output Voltage L3",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_current",
        name: "AC Output Current",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_current_l2",
        name: "AC Output Current L2",
        domain: "sensor",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_current_l3",
        name: "AC Output Current L3",
        domain: "sensor",
      },
      {
        entity_id: "light.lounge_strip_lights_left",
        name: "Lounge Strip Lights Left",
        domain: "light",
      },
      {
        entity_id: "light.lounge_strip_lights_right",
        name: "Lounge Strip Lights Right",
        domain: "light",
      },
      {
        entity_id: "light.bar_lamp",
        name: "Bar Lamp",
        domain: "light",
      },
      {
        entity_id: "notify.mobile_app_iphone_13",
        name: "Notify Iphone 13",
        domain: "notify",
      },
      {
        entity_id: "notify.send_message",
        name: "Send Message",
        domain: "notify",
      },
      {
        entity_id: "automation.electricity_balance_above_ps1",
        name: "Electricity balance ABOVE £1",
        domain: "automation",
      },
    ]
  );

  assert.match(resolvedPrompt, /Resolved grouped entity families:/);
  assert.match(resolvedPrompt, /AC Output Voltage:/);
  assert.match(resolvedPrompt, /AC Output Current:/);
  assert.match(resolvedPrompt, /Resolved exact entity matches:/);
  assert.match(resolvedPrompt, /Bar Lamp: light\.bar_lamp/);
  assert.match(resolvedPrompt, /Resolved automation guard entities:/);
  assert.match(resolvedPrompt, /automation\.electricity_balance_above_ps1/);
  assert.match(resolvedPrompt, /Resolved notification target:/);
  assert.match(resolvedPrompt, /notify\.mobile_app_iphone_13/);
  assert.doesNotMatch(resolvedPrompt, /Send Message: notify\.send_message/);
  assert.match(
    resolvedPrompt,
    /Do not collapse a resolved sibling family down to a partial subset/
  );
  assert.match(resolvedPrompt, /Do not ask for clarification/);
});

test("Prompts prefer backend generation and keep direct generation as a fallback", () => {
  const harness = buildHarness();

  assert.equal(
    harness._shouldUseBackendGeneration.call(
      harness,
      "Turn on the lounge lamp at 10pm every day."
    ),
    true
  );
  assert.equal(
    harness._shouldUseBackendGeneration.call(
      harness,
      "Monitor all three AC output phases from the Victron. If any single phase voltage drops below 210 volts OR any single phase current exceeds 15 amps, AND the total AC output power is above 100 watts, AND it's not between 9am and 5pm on a weekday, turn the lounge lamp red at 50% brightness and flash it twice."
    ),
    true
  );
});

test("Direct local fallback is disabled for remote OpenAI services", () => {
  const harness = buildHarness();
  harness._services = [
    {
      service_id: "openai",
      model: "gpt-4o-mini",
      endpoint_url: "https://api.openai.com",
      is_default: true,
    },
  ];
  harness._selectedServiceId = "openai";

  assert.equal(harness._canUseDirectGenerationFallback.call(harness), false);
});

test("Direct local fallback reuses the selected Ollama endpoint when it is local", () => {
  const harness = buildHarness();
  const originalWindow = globalThis.window;
  globalThis.window = {
    location: {
      hostname: "ha.local",
      protocol: "http:",
    },
  };

  try {
    harness._services = [
      {
        service_id: "local",
        model: "qwen2.5:14b",
        endpoint_url: "http://192.168.1.5:11434",
        is_default: true,
      },
    ];
    harness._selectedServiceId = "local";

    assert.equal(harness._canUseDirectGenerationFallback.call(harness), true);
    assert.deepEqual(harness._buildDirectEndpointCandidates.call(harness), [
      "http://192.168.1.5:11434",
      "http://ha.local:11434",
      "http://localhost:11434",
    ]);
  } finally {
    globalThis.window = originalWindow;
  }
});

test("Transient backend polling errors are retried", () => {
  const harness = buildHarness();

  assert.equal(
    harness._shouldRetryBackendStatus.call(
      harness,
      new Error("500 Internal Server Error: Server got itself in trouble")
    ),
    true
  );
  assert.equal(
    harness._shouldRetryBackendStatus.call(
      harness,
      new Error("Request failed: Failed to fetch")
    ),
    true
  );
  assert.equal(
    harness._shouldRetryBackendStatus.call(
      harness,
      new Error("401: Unauthorized")
    ),
    false
  );
});

test("Prompt clause clarifications quote the relevant original branches back to the model", () => {
  const harness = buildHarness();
  const answer = harness._buildPromptClauseClarificationAnswer.call(
    harness,
    "If any single phase current exceeds 15 amps and the total AC output power is above 100 watts, alert me. If the output power has dropped below 100 watts during the 2 minute wait, instead turn the lounge lamp back to white at full brightness and do nothing else.",
    {
      clarifying_questions: [
        "What is the threshold for a single phase current exceeding 15 amps? Should it be per phase or total AC output current?",
        "What should be done if the output power drops below 100 watts during the 2-minute wait?",
      ],
    }
  );

  assert.match(answer, /The original prompt already specifies these details/);
  assert.match(answer, /single phase current exceeds 15 amps/);
  assert.match(answer, /output power has dropped below 100 watts during the 2 minute wait/);
  assert.match(answer, /Continue and return the automation JSON/);
});

test("Automation domain matching prefers the named automation concept", () => {
  const harness = buildHarness();
  const result = harness._relevantDomainMatches.call(
    harness,
    "Don't run this if the electricity balance automation is already active",
    [
      {
        entity_id: "automation.electricity_balance_above_ps1",
        name: "Electricity balance ABOVE £1",
        domain: "automation",
      },
      {
        entity_id: "automation.electricity_balance_low",
        name: "Electricity balance low",
        domain: "automation",
      },
      {
        entity_id: "automation.start_auto_wash_and_dry",
        name: "Turn Off Switch When Wash Complete",
        domain: "automation",
      },
      {
        entity_id: "automation.bedroom_mirror_off",
        name: "Bedroom Mirror Off",
        domain: "automation",
      },
    ],
    "automation",
    2,
    8
  );

  assert.deepEqual(
    result.map((entry) => entry.entity_id),
    [
      "automation.electricity_balance_above_ps1",
      "automation.electricity_balance_low",
    ]
  );
});

test("Automation domain matching strips wrapper clause noise", () => {
  const harness = buildHarness();
  const result = harness._relevantDomainMatches.call(
    harness,
    "Don't run any of this if the electricity balance automation is already active.",
    [
      {
        entity_id: "automation.electricity_balance_above_ps1",
        name: "Electricity balance ABOVE £1",
        domain: "automation",
      },
      {
        entity_id: "automation.electricity_balance_low",
        name: "Electricity balance low",
        domain: "automation",
      },
      {
        entity_id: "automation.left_lounge_light_on_during_bedtime",
        name: "Left Lounge Light on during bedtime",
        domain: "automation",
      },
    ],
    "automation",
    2,
    8
  );

  assert.deepEqual(
    result.map((entry) => entry.entity_id),
    [
      "automation.electricity_balance_above_ps1",
      "automation.electricity_balance_low",
    ]
  );
});

test("Relevant entity selection prefers notify services over named device sensors", () => {
  const harness = buildHarness();
  const result = harness._selectRelevantEntities.call(
    harness,
    "Notify my iPhone if AC output power goes above 1000 watts.",
    [
      {
        entity_id: "notify.mobile_app_iphone_13",
        name: "Notify Iphone 13",
        domain: "notify",
        state: "service",
        device_class: "service",
      },
      {
        entity_id: "sensor.iphone_13_audio_output",
        name: "iPhone 13 Audio Output",
        domain: "sensor",
        state: "Built-in Speaker",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_power",
        name: "AC Output Power",
        domain: "sensor",
        state: "1200",
        device_class: "power",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage",
        name: "AC Output Voltage",
        domain: "sensor",
        state: "230",
        device_class: "voltage",
      },
    ],
    3,
    0
  );

  const ids = result.map((entry) => entry.entity_id);
  assert.ok(ids.includes("notify.mobile_app_iphone_13"));
  assert.ok(
    ids.indexOf("notify.mobile_app_iphone_13") <
      ids.indexOf("sensor.iphone_13_audio_output")
  );
});

test("Notification domain matching prefers the named mobile-app target over generic notify services", () => {
  const harness = buildHarness();
  const result = harness._relevantDomainMatches.call(
    harness,
    "Send a notification to my iPhone saying the Victron output is out of range.",
    [
      {
        entity_id: "notify.send_message",
        name: "Send Message",
        domain: "notify",
      },
      {
        entity_id: "notify.mobile_app_iphone_13",
        name: "Notify Iphone 13",
        domain: "notify",
      },
      {
        entity_id: "notify.persistent_notification",
        name: "Persistent Notification",
        domain: "notify",
      },
    ],
    "notify",
    1,
    4
  );

  assert.deepEqual(
    result.map((entry) => entry.entity_id),
    ["notify.mobile_app_iphone_13"]
  );
});

test("Planner guidance is injected into generation prompts for complex requests", () => {
  const harness = buildHarness();
  const messages = harness._buildDirectMessages.call(
    harness,
    "Monitor all three AC output phases and notify me if any phase is out of range",
    [
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage",
        name: "AC Output Voltage",
        domain: "sensor",
        state: "243.69",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l2",
        name: "AC Output Voltage L2",
        domain: "sensor",
        state: "unknown",
      },
      {
        entity_id: "sensor.victron_mk3_ac_output_voltage_l3",
        name: "AC Output Voltage L3",
        domain: "sensor",
        state: "unknown",
      },
    ],
    {
      resolved_request:
        "Monitor the full AC output voltage family and notify when any phase is out of range.",
      resolved_entities: [
        "AC Output Voltage phases -> sensor.victron_mk3_ac_output_voltage, sensor.victron_mk3_ac_output_voltage_l2, sensor.victron_mk3_ac_output_voltage_l3",
      ],
      resolved_requirements: [
        "Use all three voltage entities as a sibling set.",
        "Send a notification when any one phase is out of range.",
      ],
    }
  );

  assert.equal(messages[0].role, "system");
  assert.match(messages[1].content, /Implementation brief:/);
  assert.match(messages[1].content, /Implementation entity mappings:/);
  assert.match(messages[1].content, /Implementation steps:/);
});

test("Generation prompts explain that guard windows are conditions, not schedules", () => {
  const harness = buildHarness();
  const messages = harness._buildDirectMessages.call(
    harness,
    "Alert me if the power is above 100 watts and it's not between 9am and 5pm on a weekday.",
    [
      {
        entity_id: "sensor.victron_mk3_ac_output_power",
        name: "AC Output Power",
        domain: "sensor",
        state: "333",
      },
    ]
  );

  assert.match(messages[1].content, /conditions or guards, not as the trigger schedule/i);
  assert.doesNotMatch(messages[1].content, /The user's schedule is already specific enough/i);
});

test("Automation context message keeps summary and full YAML for follow-ups", () => {
  const harness = buildHarness();
  const message = harness._buildAutomationContextMessage.call(
    harness,
    "Turns on Living Room every day at 10:00.",
    "alias: Turn on Living Room at 10:00\nactions:\n  - action: media_player.turn_on"
  );

  assert.match(message, /Summary:/);
  assert.match(message, /Turns on Living Room every day at 10:00\./);
  assert.match(message, /Current automation YAML:/);
  assert.match(message, /media_player\.turn_on/);
});

test("Loose YAML responses are salvaged when the model skips the JSON wrapper", () => {
  const harness = buildHarness();
  const result = harness._parseDirectResponse.call(harness, {
    choices: [
      {
        message: {
          content:
            "yaml\nyaml:\nalias: Phase Imbalance Alert\ndescription: Test\ntriggers:\n  - trigger: template\nactions:\n  - action: light.turn_on\n",
        },
      },
    ],
  });

  assert.equal(result.needs_clarification, false);
  assert.match(result.yaml, /^alias: Phase Imbalance Alert/m);
  assert.match(result.yaml, /^triggers:/m);
  assert.match(result.yaml, /^actions:/m);
});

test("Loose YAML responses are still salvaged before repair when legacy section keys are used", () => {
  const harness = buildHarness();
  const result = harness._parseDirectResponse.call(harness, {
    choices: [
      {
        message: {
          content:
            "yaml\nyaml:\nalias: Phase Imbalance Alert\ndescription: Test\ntrigger:\n  - platform: template\naction:\n  - service: light.turn_on\n",
        },
      },
    ],
  });

  assert.equal(result.needs_clarification, false);
  assert.match(result.yaml, /^alias: Phase Imbalance Alert/m);
  assert.match(result.yaml, /^trigger:/m);
  assert.match(result.yaml, /^action:/m);
});

test("JSON payload yaml strings are normalized before returning", () => {
  const harness = buildHarness();
  const result = harness._parseDirectResponse.call(harness, {
    choices: [
      {
        message: {
          content: JSON.stringify({
            yaml:
              "yaml\nyaml:\nalias: Phase Imbalance Alert\ndescription: Test\ntriggers:\n  - trigger: template\nactions:\n  - action: light.turn_on\n",
            summary: "Ready to install",
            needs_clarification: false,
            clarifying_questions: [],
          }),
        },
      },
    ],
  });

  assert.equal(result.needs_clarification, false);
  assert.match(result.yaml, /^alias: Phase Imbalance Alert/m);
  assert.doesNotMatch(result.yaml, /^yaml/m);
});

test("Malformed JSON wrappers with a raw yaml string are salvaged", () => {
  const harness = buildHarness();
  const result = harness._parseDirectResponse.call(harness, {
    choices: [
      {
        message: {
          content: `{"yaml":"
alias: Phase Imbalance Alert
description: Demo
triggers:
  - platform: state
    entity_id: sensor.victron_mk3_ac_output_voltage
actions:
  - service: light.turn_on
    target:
      entity_id: light.lounge_lamp
","summary":"Ready for repair","needs_clarification":false}`,
        },
      },
    ],
  });

  assert.equal(result.needs_clarification, false);
  assert.match(result.yaml, /^alias: Phase Imbalance Alert/m);
  assert.match(result.summary, /Ready for repair/);
});

test("Truncated JSON wrappers with only a partial yaml string are salvaged for repair", () => {
  const harness = buildHarness();
  const result = harness._parseDirectResponse.call(harness, {
    choices: [
      {
        message: {
          content:
            '{\n "yaml": "alias: Victron Phase Imbalance Monitor\\n"\n \t\t\n \t\t}',
        },
      },
    ],
  });

  assert.equal(result.needs_clarification, false);
  assert.match(result.yaml, /^alias: Victron Phase Imbalance Monitor/m);
  assert.equal(result.summary, "");
});

test("Fenced yaml block scalars with a single-item list are unwrapped into one automation", () => {
  const harness = buildHarness();
  const result = harness._parseDirectResponse.call(harness, {
    choices: [
      {
        message: {
          content: `\`\`\`yaml
yaml: |
  - alias: Phase Imbalance Alert
    description: Test
    trigger:
      - platform: template
    action:
      - service: light.turn_on
\`\`\``,
        },
      },
    ],
  });

  assert.equal(result.needs_clarification, false);
  assert.match(result.yaml, /^alias: Phase Imbalance Alert/m);
  assert.match(result.yaml, /^trigger:/m);
  assert.match(result.yaml, /^action:/m);
});

test("Wrapped automation documents are unwrapped into a single salvageable automation", () => {
  const harness = buildHarness();
  const result = harness._extractLooseYamlResponse.call(
    harness,
    `alias: Victron Phase Imbalance Automation
description: Example
automation:
- alias: Victron Phase Imbalance Automation
 description: Example
 trigger:
  - platform: state
    entity_id: sensor.victron_mk3_ac_output_voltage
 action:
  - service: light.turn_on
    target:
      entity_id: light.lounge_lamp`
  );

  assert.ok(result);
  assert.match(result.yaml, /^alias: Victron Phase Imbalance Automation/m);
  assert.doesNotMatch(result.yaml, /^automation:/m);
  assert.match(result.yaml, /^trigger:/m);
  assert.match(result.yaml, /^action:/m);
});

test("YAML issue detection catches list-item platform and service keys", () => {
  const harness = buildHarness();
  const issues = harness._collectYamlIssues.call(
    harness,
    `alias: Broken Example
description: Example
triggers:
  - platform: state
    entity_id: sensor.test
conditions: []
actions:
  - service: light.turn_on
    target:
      entity_id: light.test`
  );

  assert.ok(
    issues.includes("Inside each trigger item, use trigger: instead of platform:.")
  );
  assert.ok(
    issues.includes("Inside each action item, use action: instead of service:.")
  );
});

test("YAML issue detection catches duplicated sections, pseudo fields, and invalid trigger items", () => {
  const harness = buildHarness();
  const issues = harness._collectYamlIssues.call(
    harness,
    `alias: Broken Example
description: Example
triggers:
  - condition: numeric_state
    entity_id: sensor.test
    below_limit: 210
    condition_value_template: "{{ value < 210 }}"
conditions: []
actions:
  - action: switch.turn_off
    target:
      entity_id: light.test
conditions:
  - condition: state
    entity_id: automation.test
    state: active
actions:
  - template:
      message: bad`
  );

  assert.ok(
    issues.includes("Trigger items under triggers: must use - trigger:, not - condition:.")
  );
  assert.ok(
    issues.includes("Use valid numeric_state keys such as above: and below:, not above_limit: or below_limit:.")
  );
  assert.ok(
    issues.includes("Do not use pseudo trigger fields like condition_entity_id:, condition_state:, or condition_value_template:.")
  );
  assert.ok(issues.includes("Use a single top-level conditions: section."));
  assert.ok(issues.includes("Use a single top-level actions: section."));
  assert.ok(
    issues.includes("Use valid actions such as action:, variables:, choose:, delay:, or conditions:, not - template:.")
  );
  assert.ok(
    issues.includes("Use real Home Assistant entity states such as on or off, not active.")
  );
});

test("Prompt-aware repair issues catch missing grouped entities, notify targets, and follow-up branches", () => {
  const harness = buildHarness();
  const prompt =
    "Monitor all three AC output phases from the Victron. If any single phase voltage drops below 210 volts OR any single phase current exceeds 15 amps, AND the total AC output power is above 100 watts, AND it's not between 9am and 5pm on a weekday, turn the lounge lamp red at 50% brightness and flash it twice, then turn off both lounge strip lights and the bar lamp. Wait 2 minutes. If the output power is still above 100 watts, turn off the bedroom strip light and disable the battery monitor switch. Then send a notification to my iPhone saying warning with the actual sensor value included in the message. If the output power has dropped below 100 watts during the 2 minute wait, instead turn the lounge lamp back to white at full brightness and do nothing else. Don't run any of this if the electricity balance automation is already active.";
  const entities = [
    {
      entity_id: "sensor.victron_mk3_ac_output_voltage",
      name: "AC Output Voltage",
      domain: "sensor",
    },
    {
      entity_id: "sensor.victron_mk3_ac_output_voltage_l2",
      name: "AC Output Voltage L2",
      domain: "sensor",
    },
    {
      entity_id: "sensor.victron_mk3_ac_output_voltage_l3",
      name: "AC Output Voltage L3",
      domain: "sensor",
    },
    {
      entity_id: "sensor.victron_mk3_ac_output_current",
      name: "AC Output Current",
      domain: "sensor",
    },
    {
      entity_id: "sensor.victron_mk3_ac_output_current_l2",
      name: "AC Output Current L2",
      domain: "sensor",
    },
    {
      entity_id: "sensor.victron_mk3_ac_output_current_l3",
      name: "AC Output Current L3",
      domain: "sensor",
    },
    {
      entity_id: "sensor.victron_mk3_ac_output_power",
      name: "AC Output Power",
      domain: "sensor",
    },
    {
      entity_id: "light.lounge_lamp",
      name: "Lounge Lamp",
      domain: "light",
    },
    {
      entity_id: "light.lounge_strip_lights_left",
      name: "Lounge Strip Lights Left",
      domain: "light",
    },
    {
      entity_id: "light.lounge_strip_lights_right",
      name: "Lounge Strip Lights Right",
      domain: "light",
    },
    {
      entity_id: "light.bar_lamp",
      name: "Bar Lamp",
      domain: "light",
    },
    {
      entity_id: "light.bedroom_strip_light_left",
      name: "Bedroom Strip Light Left",
      domain: "light",
    },
    {
      entity_id: "switch.victron_mk3_battery_monitor",
      name: "Battery Monitor",
      domain: "switch",
    },
    {
      entity_id: "notify.mobile_app_iphone_13",
      name: "Notify Iphone 13",
      domain: "notify",
    },
    {
      entity_id: "automation.electricity_balance_above_ps1",
      name: "Electricity balance ABOVE £1",
      domain: "automation",
    },
  ];
  const issues = harness._collectRepairIssues.call(
    harness,
    prompt,
    `alias: Broken Example
description: Example
triggers:
  - trigger: numeric_state
    entity_id: sensor.victron_mk3_ac_output_voltage
    below: 210
conditions:
  - condition: numeric_state
    entity_id: sensor.victron_mk3_ac_output_power
    above: 100
actions:
  - action: switch.turn_off
    target:
      entity_id: light.lounge_strip_lights_left`,
    { entities }
  );

  assert.ok(
    issues.some((issue) =>
      issue.includes("Use the full resolved Lounge Strip Lights entity family together")
    )
  );
  assert.ok(
    issues.some((issue) =>
      issue.includes("Use the resolved notification target notify.mobile_app_iphone_13.")
    )
  );
  assert.ok(
    issues.some((issue) =>
      issue.includes("Use choose/default branches to implement the requested follow-up outcomes.")
    )
  );
  assert.ok(
    issues.some((issue) =>
      issue.includes("Capture the triggering sensor and its live value in variables")
    )
  );
  assert.ok(
    issues.some((issue) =>
      issue.includes("Use an action service that matches light targets instead of switch.turn_off.")
    )
  );
});

test("Prompt-aware repair issues catch missing time-window and explicit switch guards", () => {
  const harness = buildHarness();
  const issues = harness._collectRepairIssues.call(
    harness,
    lowPowerLightsPrompt,
    `alias: Turn Off Lights on Low AC Power
description: Test
triggers:
  - trigger: numeric_state
    entity_id: sensor.victron_mk3_ac_output_power
    below: 200
conditions: []
actions:
  - action: light.turn_off
    target:
      entity_id:
        - light.lounge_lamp
        - light.lounge_strip_lights_left
        - light.lounge_strip_lights_right
  - delay: "00:05:00"
  - choose:
      - conditions:
          - condition: numeric_state
            entity_id: sensor.victron_mk3_ac_output_power
            below: 200
        sequence:
          - action: light.turn_off
            target:
              entity_id: light.bar_lamp
          - action: notify.mobile_app_iphone_13
            data:
              message: "Shore power is critically low - lights turned off automatically"`,
    { entities: lowPowerLightsEntities }
  );

  assert.ok(
    issues.some((issue) =>
      issue.includes("Preserve the requested time window between 23:00:00 and 06:00:00")
    )
  );
  assert.ok(
    issues.some((issue) =>
      issue.includes(
        "Respect the explicit guard switch.meter_macs_the_architeuthis_electricity_supply_switch"
      )
    )
  );
});

test("Group clause mappings split comma-delimited action branches cleanly", () => {
  const harness = buildHarness();
  const mappings = harness._buildGroupClauseMappings.call(
    harness,
    victronComplexPrompt,
    [
      [
        {
          entity_id: "light.lounge_strip_lights_left",
          name: "Lounge Strip Lights Left",
          domain: "light",
        },
        {
          entity_id: "light.lounge_strip_lights_right",
          name: "Lounge Strip Lights Right",
          domain: "light",
        },
      ],
    ]
  );

  assert.equal(mappings.length, 1);
  assert.equal(
    mappings[0].clause,
    "turn off both lounge strip lights and the bar lamp"
  );
});

test("Deterministic complex builder compiles the Victron prompt into valid YAML", () => {
  const harness = buildHarness();
  const result = harness._buildDeterministicComplexAutomationResult.call(
    harness,
    victronComplexPrompt,
    { entities: victronComplexEntities }
  );

  assert.ok(result);
  assert.equal(result.needs_clarification, false);
  assert.match(result.yaml, /^alias: AC Output Voltage Monitor/m);
  assert.match(result.yaml, /^triggers:/m);
  assert.match(result.yaml, /sensor\.victron_mk3_ac_output_voltage_l2/);
  assert.match(result.yaml, /sensor\.victron_mk3_ac_output_current_l3/);
  assert.match(result.yaml, /condition: numeric_state[\s\S]*sensor\.victron_mk3_ac_output_power[\s\S]*above: 100/);
  assert.match(result.yaml, /condition: not[\s\S]*condition: time[\s\S]*after: "09:00:00"[\s\S]*before: "17:00:00"/);
  assert.match(result.yaml, /state_attr\('automation\.electricity_balance_above_ps1', 'current'\)/);
  assert.match(result.yaml, /repeat:[\s\S]*count: 2/);
  assert.match(result.yaml, /color_name: "red"/);
  assert.match(result.yaml, /brightness_pct: 50/);
  assert.match(result.yaml, /light\.lounge_strip_lights_left/);
  assert.match(result.yaml, /light\.bar_lamp/);
  assert.match(result.yaml, /delay: "00:02:00"/);
  assert.match(result.yaml, /choose:[\s\S]*sensor\.victron_mk3_ac_output_power[\s\S]*above: 100/);
  assert.match(result.yaml, /switch\.victron_mk3_battery_monitor/);
  assert.match(result.yaml, /notify\.mobile_app_iphone_13/);
  assert.equal(
    (result.yaml.match(/action: notify\.mobile_app_iphone_13/g) || []).length,
    1
  );
  assert.match(
    result.yaml,
    /sequence:\n\s+- action: light\.turn_off\n\s+target:\n\s+entity_id: light\.bedroom_strip_light_left\n\s+- action: switch\.turn_off\n\s+target:\n\s+entity_id: switch\.victron_mk3_battery_monitor\n\s+- action: notify\.mobile_app_iphone_13\n\s+data:\n\s+message:/
  );
  assert.match(
    result.yaml,
    /default:\n\s+- action: light\.turn_on\n\s+target:\n\s+entity_id: light\.lounge_lamp\n\s+data:\n\s+color_name: "white"\n\s+brightness_pct: 100/
  );
  assert.match(result.yaml, /Warning: Victron phase imbalance detected - \{\{ triggered_sensor_name \}\} is out of range/);
  assert.match(result.yaml, /triggered_sensor_value/);
  assert.match(result.yaml, /color_name: "white"/);
  assert.match(result.yaml, /brightness_pct: 100/);
});

test("Deterministic complex builder compiles the low-power lights prompt into valid YAML", () => {
  const harness = buildHarness();
  const result = harness._buildDeterministicComplexAutomationResult.call(
    harness,
    lowPowerLightsPrompt,
    { entities: lowPowerLightsEntities }
  );

  assert.ok(result);
  assert.equal(result.needs_clarification, false);
  assert.match(result.yaml, /^alias: AC Output Power Monitor/m);
  assert.match(result.yaml, /^triggers:/m);
  assert.match(
    result.yaml,
    /- trigger: numeric_state[\s\S]*entity_id: sensor\.victron_mk3_ac_output_power[\s\S]*below: 200/
  );
  assert.match(
    result.yaml,
    /condition: time[\s\S]*after: "23:00:00"[\s\S]*before: "06:00:00"/
  );
  assert.match(
    result.yaml,
    /condition: state[\s\S]*entity_id: switch\.meter_macs_the_architeuthis_electricity_supply_switch[\s\S]*state: "on"/
  );
  assert.match(result.yaml, /light\.lounge_lamp/);
  assert.match(result.yaml, /light\.lounge_strip_lights_left/);
  assert.match(result.yaml, /light\.lounge_strip_lights_right/);
  assert.match(result.yaml, /delay: "00:05:00"/);
  assert.match(
    result.yaml,
    /choose:[\s\S]*condition: numeric_state[\s\S]*entity_id: sensor\.victron_mk3_ac_output_power[\s\S]*below: 200/
  );
  assert.match(result.yaml, /light\.bar_lamp/);
  assert.match(result.yaml, /action: notify\.mobile_app_iphone_13/);
  assert.match(
    result.yaml,
    /data:\n\s+message: "Shore power is critically low - lights turned off automatically"/
  );
});

test("Complex repair returns the deterministic fallback for the low-power lights prompt", async () => {
  const harness = buildHarness();
  harness._regenerateAutomationYamlFromScratch = async () => {
    throw new Error("regen should not run when deterministic fallback succeeds");
  };
  harness._rewriteInvalidAutomationYaml = async () => {
    throw new Error("rewrite should not run when deterministic fallback succeeds");
  };
  harness._directChatCompletion = async () => {
    throw new Error("chat repair should not run when deterministic fallback succeeds");
  };

  const result = await harness._repairGeneratedYamlIfNeeded.call(
    harness,
    lowPowerLightsPrompt,
    [{ role: "user", content: lowPowerLightsPrompt }],
    {
      yaml: `alias: Turn Off Lights on Low AC Power
description: Turn off lounge lamp and strip lights when AC output power drops below 200 watts between 11pm and 6am, then check again after 5 minutes.
triggers:
  - trigger: state
    entity_id: sensor.victron_mk3_ac_output_power
    to: "below"
    below: 200
conditions:
  - condition: time
    after: "23:00"
    before: "06:00"
actions:
  - action: light.turn_off
    target:
      entity_id:
        - light.lounge_lamp
        - light.lounge_strip_lights_left
        - light.lounge_strip_lights_right
  - delay: "00:05:00"
  - condition: state
    entity_id: sensor.victron_mk3_ac_output_power
    state: "below"
    below: 200
  - action: light.turn_off
    target:
      entity_id: light.bar_lamp
  - action: notify.mobile_app_iphone_13
    message: "Shore power is critically low - lights turned off automatically"`,
      summary: "Broken draft",
      needs_clarification: false,
      clarifying_questions: [],
    },
    {
      entities: lowPowerLightsEntities,
    }
  );

  assert.match(result.yaml, /^alias: AC Output Power Monitor/m);
  assert.match(result.yaml, /state: "on"/);
  assert.match(result.yaml, /delay: "00:05:00"/);
  assert.match(result.yaml, /action: notify\.mobile_app_iphone_13/);
});

test("Complex repair returns the deterministic fallback before extra model retries", async () => {
  const harness = buildHarness();
  harness._regenerateAutomationYamlFromScratch = async () => {
    throw new Error("regen should not run when deterministic fallback succeeds");
  };
  harness._rewriteInvalidAutomationYaml = async () => {
    throw new Error("rewrite should not run when deterministic fallback succeeds");
  };
  harness._directChatCompletion = async () => {
    throw new Error("chat repair should not run when deterministic fallback succeeds");
  };

  const result = await harness._repairGeneratedYamlIfNeeded.call(
    harness,
    victronComplexPrompt,
    [{ role: "user", content: victronComplexPrompt }],
    {
      yaml: "alias: Broken\ntriggers:\n  - trigger: numeric_state\n    entity_id: sensor.victron_mk3_ac_output_voltage\n    below: 210\nconditions: []\nactions: []",
      summary: "Broken draft",
      needs_clarification: false,
      clarifying_questions: [],
    },
    {
      entities: victronComplexEntities,
    }
  );

  assert.match(result.yaml, /^alias: AC Output Voltage Monitor/m);
  assert.match(result.yaml, /notify\.mobile_app_iphone_13/);
  assert.match(result.yaml, /delay: "00:02:00"/);
});

test("Source does not hardcode a developer-specific Ollama host", () => {
  assert.doesNotMatch(cardSource, /openclaw:11434/);
  assert.doesNotMatch(cardSource, /192\.168\.10\.212:11434/);
});

test("Planning responses are parsed from fenced JSON content", () => {
  const harness = buildHarness();
  const result = harness._parsePlanningResponse.call(harness, {
    choices: [
      {
        message: {
          content:
            "```json\n{\"resolved_request\":\"Test plan\",\"resolved_requirements\":[\"Do the thing\"],\"resolved_entities\":[\"Light -> light.test\"],\"needs_clarification\":false,\"clarifying_questions\":[]}\n```",
        },
      },
    ],
  });

  assert.equal(result.resolved_request, "Test plan");
  assert.deepEqual(result.resolved_requirements, ["Do the thing"]);
  assert.deepEqual(result.resolved_entities, ["Light -> light.test"]);
  assert.equal(result.needs_clarification, false);
});

test("Planner-only JSON on the final pass is downgraded into a recoverable missing-yaml result", () => {
  const harness = buildHarness();
  const result = harness._parseDirectResponse.call(harness, {
    choices: [
      {
        message: {
          content:
            '{"resolved_request":"Watch the phase sensors","resolved_requirements":["Use a numeric trigger"],"resolved_entities":["sensor.victron_mk3_ac_output_voltage"],"needs_clarification":false,"clarifying_questions":[]}',
        },
      },
    ],
  });

  assert.equal(result.needs_clarification, false);
  assert.equal(result.yaml, "");
  assert.equal(result.missing_yaml, true);
  assert.equal(result.planner_only, true);
  assert.match(result.summary, /Watch the phase sensors/);
  assert.match(result.summary, /Resolved entities:/);
});

test("Non-clarifying summaries without YAML are surfaced for the repair pass", () => {
  const harness = buildHarness();
  const result = harness._parseDirectResponse.call(harness, {
    choices: [
      {
        message: {
          content:
            '{"yaml":null,"summary":"The automation is ready and just needs the final YAML block returned.","needs_clarification":false,"clarifying_questions":[]}',
        },
      },
    ],
  });

  assert.equal(result.needs_clarification, false);
  assert.equal(result.yaml, "");
  assert.equal(result.missing_yaml, true);
  assert.match(result.summary, /final YAML block/);
});

test("Direct chat completions request JSON object output from Ollama", () => {
  assert.match(cardSource, /response_format:\s*\{\s*type:\s*"json_object"\s*\}/);
  assert.match(cardSource, /stream:\s*false/);
});

test("Backend generation payload includes the selected service id", () => {
  const harness = buildHarness();
  harness._services = [
    {
      service_id: "primary",
      model: "qwen2.5:14b",
      endpoint_url: "http://localhost:11434",
      is_default: true,
    },
    {
      service_id: "backup",
      model: "gpt-4o-mini",
      endpoint_url: "http://remote:1234",
      is_default: false,
    },
  ];
  harness._selectedServiceId = "backup";

  const payload = harness._buildGenerationRequestPayload.call(
    harness,
    "Turn on the kitchen lights",
    "job-1"
  );

  assert.deepEqual(payload, {
    prompt: "Turn on the kitchen lights",
    service_id: "backup",
    continue_job_id: "job-1",
  });
});

test("Create view source exposes a configured model picker", () => {
  assert.match(cardSource, /class="service-select"/);
  assert.match(cardSource, /automagic\/services/);
  assert.match(cardSource, /service_id/);
});

test("Missing-yaml repair explicitly demands a non-empty yaml string", () => {
  assert.match(cardSource, /did not include the required automation YAML/i);
  assert.match(cardSource, /yaml key must be a non-empty string/i);
  assert.match(cardSource, /Do not leave yaml null or empty/i);
  assert.match(cardSource, /Do not say the automation is ready, complete, or being generated/i);
});

test("System prompt instructs the model to handle follow-up edits and questions", () => {
  assert.match(cardSource, /follow-up change requests/i);
  assert.match(cardSource, /follow-up questions about the current automation/i);
  assert.match(cardSource, /notify\.\* entries/i);
  assert.match(cardSource, /whichever sensor triggered/i);
  assert.match(cardSource, /sibling variants/i);
  assert.match(cardSource, /whole listed set together/i);
  assert.match(cardSource, /current state is "unknown" or "unavailable"/i);
  assert.match(cardSource, /Read the entire request as one combined condition\/action sequence/i);
  assert.match(cardSource, /named automation concept/i);
  assert.match(cardSource, /different threshold or state clauses clearly refer to different entity families/i);
  assert.match(cardSource, /Resolved a grouped-entity clarification automatically/i);
  assert.match(cardSource, /time-window guards or exclusions/i);
  assert.match(cardSource, /boolean logic exactly/i);
});

test("Direct generation source prefers the resolved final pass for very complex prompts", () => {
  assert.match(cardSource, /_shouldPreferResolvedFinalPass\(prompt\)/);
  assert.match(cardSource, /_shouldPreferYamlOnlyResolvedPass\(/);
  assert.match(cardSource, /_isUsefulPlanningResult\(/);
  assert.match(
    cardSource,
    /Resolved the complex prompt into grouped entity mappings before asking the model to generate the final automation\./
  );
  assert.match(cardSource, /resolved_requirements must be ordered natural-language implementation steps/i);
  assert.match(cardSource, /resolved_entities must be human-readable mapping strings/i);
});

test("Planner stays enabled for longer complex prompts instead of bailing out early", () => {
  const harness = buildHarness();
  const prompt =
    "Monitor all three AC output phases from the Victron. If any single phase voltage drops below 210 volts OR any single phase current exceeds 15 amps, AND the total AC output power is above 100 watts, AND it's not between 9am and 5pm on a weekday, turn the lounge lamp red at 50% brightness and flash it twice, then turn off both lounge strip lights and the bar lamp. Wait 2 minutes. If the output power is still above 100 watts, turn off the bedroom strip light and disable the battery monitor switch. Then send a notification to my iPhone saying warning with the actual sensor value included in the message.";

  assert.equal(harness._shouldUsePlanner.call(harness, prompt), true);
});

test("Resolved final messages include planner guidance when available", () => {
  const harness = buildHarness();
  const messages = harness._buildResolvedFinalMessages.call(
    harness,
    "Create a test automation",
    "Resolved grouped entity families:\n- None",
    [
      {
        entity_id: "light.test",
        name: "Test Light",
        domain: "light",
      },
    ],
    {
      resolved_request: "Turn on the light when the sensor trips.",
      resolved_entities: ["Test Light -> light.test"],
      resolved_requirements: ["Use a state trigger", "Return one automation"],
    }
  );

  assert.match(messages[1].content, /Implementation brief:/);
  assert.match(messages[1].content, /Test Light -> light\.test/);
  assert.match(messages[1].content, /Use a state trigger/);
});

test("Plan-to-yaml messages compile from resolved interpretation without planner chat history", () => {
  const harness = buildHarness();
  const messages = harness._buildPlanToYamlMessages.call(
    harness,
    "Monitor all three AC output phases",
    {
      entities: [
        {
          entity_id: "sensor.victron_mk3_ac_output_voltage",
          name: "AC Output Voltage",
          domain: "sensor",
        },
        {
          entity_id: "light.lounge_lamp",
          name: "Lounge Lamp",
          domain: "light",
        },
      ],
      resolvedPrompt:
        "Resolved grouped entity families:\n- AC Output Voltage: sensor.victron_mk3_ac_output_voltage, sensor.victron_mk3_ac_output_voltage_l2",
      plan: {
        resolved_request: "Monitor the Victron AC output phases.",
        resolved_requirements: [
          "Trigger when a phase is out of range",
          "Notify the user with the triggering sensor",
        ],
        resolved_entities: [
          "AC Output Voltage -> sensor.victron_mk3_ac_output_voltage, sensor.victron_mk3_ac_output_voltage_l2",
          "Lounge Lamp -> light.lounge_lamp",
        ],
      },
    }
  );

  assert.equal(messages[0].content, DIRECT_PLAN_TO_YAML_SYSTEM_PROMPT);
  assert.match(messages[1].content, /^Available entities:/);
  assert.match(messages[1].content, /Original request:/);
  assert.match(messages[1].content, /Prompt interpretation:/);
  assert.match(messages[1].content, /Implementation facts:/);
  assert.match(messages[1].content, /Entity mapping: Lounge Lamp -> light\.lounge_lamp/);
  assert.doesNotMatch(messages[1].content, /Implementation brief:/);
});

test("Planner-only compile responses jump straight to YAML regeneration", async () => {
  const harness = buildHarness();
  const calls = [];
  harness._compilePlanToYaml = async (_prompt, context) => {
    calls.push(["compile", context?.plan?.resolved_request || ""]);
    return {
      yaml: "",
      summary: "Planner reply",
      needs_clarification: false,
      clarifying_questions: [],
      missing_yaml: true,
      planner_only: true,
      plan_details: {
        resolved_request: "Compile the final automation",
        resolved_requirements: ["Return YAML"],
        resolved_entities: ["light.test"],
      },
    };
  };
  harness._regenerateAutomationYamlFromScratch = async (_prompt, context, issues) => {
    calls.push([
      "regen",
      context?.plan?.resolved_request || "",
      Array.isArray(issues) ? issues.join(" | ") : "",
    ]);
    return {
      yaml: "alias: Example\ndescription: Example\ntriggers: []\nconditions: []\nactions: []",
      summary: "Compiled",
      needs_clarification: false,
      clarifying_questions: [],
    };
  };
  harness._rewritePlannerResponseToYaml = async () => {
    throw new Error("planner rewrite should not run");
  };
  harness._collectYamlIssues = () => [];

  const result = await harness._repairGeneratedYamlIfNeeded.call(
    harness,
    "Create a complex automation",
    [{ role: "user", content: "Create a complex automation" }],
    {
      yaml: "",
      summary: "Planner reply",
      needs_clarification: false,
      clarifying_questions: [],
      missing_yaml: true,
      planner_only: true,
      plan_details: {
        resolved_request: "Initial plan",
        resolved_requirements: ["Compile the automation"],
        resolved_entities: ["light.test"],
      },
    },
    {
      entities: [
        {
          entity_id: "light.test",
          name: "Test Light",
          domain: "light",
        },
      ],
    }
  );

  assert.equal(calls[0][0], "compile");
  assert.deepEqual(calls[1], [
    "regen",
    "Compile the final automation",
    "The previous response returned planning keys instead of automation YAML.",
  ]);
  assert.match(result.yaml, /^alias: Example/m);
});

test("Complex missing-yaml repairs skip chat JSON retries and go straight to YAML regeneration", async () => {
  const harness = buildHarness();
  harness._isComplexAutomationPrompt = () => true;
  harness._regenerateAutomationYamlFromScratch = async (_prompt, _context, issues) => ({
    yaml: "alias: Complex Example\ndescription: Example\ntriggers: []\nconditions: []\nactions: []",
    summary: Array.isArray(issues) ? issues.join(" ") : "",
    needs_clarification: false,
    clarifying_questions: [],
  });
  harness._directChatCompletion = async () => {
    throw new Error("chat completion should not run for complex missing-yaml repair");
  };
  harness._collectYamlIssues = () => [];

  const result = await harness._repairGeneratedYamlIfNeeded.call(
    harness,
    "If the voltage drops below 210 and power stays above 100 for 2 minutes, do several actions",
    [{ role: "user", content: "complex request" }],
    {
      yaml: "",
      summary: "Missing yaml",
      needs_clarification: false,
      clarifying_questions: [],
      missing_yaml: true,
      planner_only: false,
      plan_details: {
        resolved_request: "Complex request",
        resolved_requirements: ["Return YAML"],
        resolved_entities: ["sensor.test"],
      },
    },
    {
      entities: [
        {
          entity_id: "sensor.test",
          name: "Test Sensor",
          domain: "sensor",
        },
      ],
    }
  );

  assert.match(result.yaml, /^alias: Complex Example/m);
  assert.match(result.summary, /required complete automation YAML/i);
});

test("Source includes a dedicated syntax rewrite fallback for invalid YAML", () => {
  assert.match(cardSource, /_rewriteInvalidAutomationYaml\(prompt, messages, result, issues = \[\]\)/);
  assert.match(cardSource, /_compilePlanToYaml\(prompt, context = \{\}\)/);
  assert.match(cardSource, /_buildPlanToYamlMessages\(prompt, context = \{\}\)/);
  assert.match(cardSource, /_rewritePlannerResponseToYaml\(prompt, context = \{\}\)/);
  assert.match(cardSource, /_directYamlGeneration\(promptText, maxTokens = DIRECT_YAML_ONLY_MAX_TOKENS\)/);
  assert.match(cardSource, /_regenerateAutomationYamlFromScratch\(/);
  assert.match(cardSource, /DIRECT_FINAL_MODEL_PREFERENCES/);
  assert.match(cardSource, /Return ONLY one complete Home Assistant automation in YAML/i);
  assert.match(cardSource, /Do not return JSON, markdown fences, commentary, or explanations/i);
  assert.match(cardSource, /\/api\/generate/);
  assert.match(cardSource, /DIRECT_SYNTAX_REWRITE_SYSTEM_PROMPT/);
  assert.match(cardSource, /DIRECT_PLAN_TO_YAML_SYSTEM_PROMPT/);
  assert.match(cardSource, /rewrite the draft above into one valid Home Assistant automation/i);
  assert.match(cardSource, /Syntax problems to fix:/);
  assert.match(cardSource, /Return one complete Home Assistant automation as JSON now/i);
  assert.match(cardSource, /Do not ask for clarification and do not return planning keys/i);
  assert.match(cardSource, /Your previous reply was invalid because it returned planning keys/i);
  assert.match(cardSource, /exactly four keys: yaml, summary, needs_clarification, clarifying_questions/i);
  assert.match(cardSource, /The previous response returned planning keys instead of automation YAML\./);
  assert.match(cardSource, /For nested outcomes such as 'if still above X after Y, do A, otherwise do B'/i);
  assert.match(cardSource, /The previous response did not include the required complete automation YAML\./);
});
