# AutoMagic - AI Automation Builder for Home Assistant

[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![HA Version](https://img.shields.io/badge/Home%20Assistant-2024.10%2B-blue.svg)](https://www.home-assistant.io)
[![GitHub](https://img.shields.io/badge/GitHub-usersaynoso%2FAutoMagic-blue.svg)](https://github.com/usersaynoso/AutoMagic---AI-Automation-Builder-for-Home-Assistant)

**AutoMagic** is an interactive AI-powered automation builder for Home Assistant. Describe what you want in plain English, preview the result, and install it with one click. No YAML editing required.

## How It Works

1. **Describe** — Type a natural language description of your automation
2. **Generate** — AutoMagic sends your description + your entity list to any OpenAI-compatible LLM
3. **Preview** — Review a visual breakdown of triggers, conditions, and actions
4. **Install** — One click to write the automation and reload HA

## Features

- Works with **any OpenAI-compatible endpoint**: Ollama, LM Studio, OpenAI, Groq, etc.
- **Zero LLM configuration** — AutoMagic owns all prompt construction and response parsing
- **Visual preview** of triggers, conditions, and actions before installing
- **Syntax validation** — enforces HA 2024.10+ automation syntax server-side
- **YAML toggle** — inspect and copy the generated YAML
- **Dark theme aware** — uses HA's CSS variables for consistent styling

## Requirements

- Home Assistant **2024.10** or newer
- A running OpenAI-compatible LLM endpoint (e.g. [Ollama](https://ollama.ai))

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add `https://github.com/usersaynoso/AutoMagic---AI-Automation-Builder-for-Home-Assistant` and select **Integration** as the category
4. Install **AutoMagic - AI Automation Builder**
5. Restart Home Assistant

The Lovelace card is bundled inside the integration and served automatically — no manual file copying needed.

### Manual

1. Copy the `custom_components/automagic` folder to your HA `config/custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **AutoMagic**
3. Enter your LLM endpoint URL (Ollama default: `http://localhost:11434`)
4. Select a model and configure generation parameters
5. Open the **AutoMagic** panel in the sidebar

## Supported LLM Backends

| Backend | Endpoint URL | Notes |
|---------|-------------|-------|
| Ollama | `http://localhost:11434` | Default, recommended for local use |
| LM Studio | `http://localhost:1234` | Local GUI for running models |
| OpenAI | `https://api.openai.com` | Requires API key in URL headers |
| Groq | `https://api.groq.com/openai` | Fast cloud inference |

## Usage

Access AutoMagic from the **sidebar panel** after installation, or add the card to any dashboard:

```yaml
type: custom:automagic-card
title: AutoMagic
show_entity_chips: true
```

### Example Prompts

- "Turn on the porch light at sunset and off at sunrise"
- "Send a notification when the garage door has been open for 10 minutes"
- "Flash the hallway lights red when the front door opens after 10pm"
- "Set the thermostat to 68 when everyone leaves home"

## License

MIT
